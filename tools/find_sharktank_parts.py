"""Split the newest eligible Shark Tank upload into sequential Short-length parts.

The account is switching from streamer clips to full-episode chops: take the channel's
newest video and cut it into consecutive segments that are each just under the 60s Shorts
ceiling, so a ~10 minute pitch becomes ~10 one-minute parts instead of one hand-picked
moment. Parts are emitted in play order and the orchestrator posts the first one that is
not already recorded in the shared clip history (state/used_clips.json -- the same ledger
the streamer pool uses, keyed "<video_id>#<part_index>"), so consecutive scheduled runs
walk through a video part 1 -> part N and then move on to the next newest upload.

Sourcing is a rotation of official pitch-show feeds (Shark Tank US + Dragons' Den UK +
Shark Tank Australia + Dragons' Den Canada by default; override with --channel /
SHARKTANK_CHANNEL[S], cursor in --rotation): runs walk the pool round-robin so the
channel interleaves shows, and every candidate is already the right show, right channel,
and a known slice of one video. Parts stay strictly under 60s (prepare_upload_media
rejects >=60s) and sources needing more than --max-parts are skipped (an hour-long
compilation would otherwise own the channel for months); the video must also have at
least one unposted part left.

Usage:
    python tools/find_sharktank_parts.py [--channel URL] [--scan 8] [--max-parts 12]
        [--max-part-secs 59] [--history state/used_clips.json] [--out .tmp/rank_candidates.json]

Prints JSON: {"source":"youtube","genre":"sharktank","count","video",...,"candidates":[...]}
"""
import argparse
import json
import math
import os

from _common import REPO_ROOT, load_env, emit, fail

# Reuse the proven yt-dlp wrapper (cookies + WARP proxy + bounded playlist read) and the
# duration parser from the existing source pool instead of re-deriving either.
from find_streamer_clips import parse_duration, search

DEFAULT_CHANNEL = "https://www.youtube.com/@SharkTankGlobal/videos"
# Rotation pool: English-language pitch/business shows with full episodes on YouTube. Every
# feed below was probed live on 2026-10-03 (a feed that 404s or has no /videos tab would
# otherwise burn a whole run before the next one is tried). `--channel` / SHARKTANK_CHANNEL[S]
# may override the list; runs walk it round-robin (see --rotation) so the channel interleaves
# shows instead of finishing one show's video before touching the next.
DEFAULT_CHANNELS = [
    "https://www.youtube.com/@SharkTankGlobal/videos",   # Shark Tank US (full episodes)
    "https://www.youtube.com/@DragonsDenGlobal/videos",  # Dragons' Den UK (BBC pitches)
    "https://www.youtube.com/@SharkTankAustralia/videos",  # Shark Tank Australia (English)
    "https://www.youtube.com/@DragonsDenCanada/videos",  # Dragons' Den Canada (CBC pitches)
]
# Every part must land strictly below 60s: prepare_upload_media.py rejects any media with
# `not (0 < duration < 60)`, so an exact-60.0s part (a 600s source split 10 ways) would fail
# the upload step and redden the run. 0.5s of headroom also covers ffmpeg/probe rounding.
MAX_SOURCE_SECS = 59.5


def split_parts(duration, max_part_secs=MAX_SOURCE_SECS, max_parts=12):
    """Cut `duration` seconds into consecutive parts, each strictly under 60s.

    Counts parts by ceiling division so a ~10 minute upload becomes exactly 10 near-1-minute
    parts (587s -> 10 x 58.7s); even (near-)multiples of the ceiling never gain a sliver tail.
    The ceiling is clamped to MAX_SOURCE_SECS no matter what the caller asks for, because an
    exact 60.0s part would be rejected downstream by prepare_upload_media's `< 60` check.
    Returns a list of (start, end) tuples in seconds, or None when the source is unusable
    (no duration, or so long that even the configured part cap cannot cover it).
    """
    try:
        duration = float(duration)
    except (TypeError, ValueError):
        return None
    if duration <= 0:
        return None
    ceiling = min(float(max_part_secs or MAX_SOURCE_SECS), MAX_SOURCE_SECS)
    if ceiling <= 0:
        return None
    if duration <= ceiling:
        return [(0.0, round(duration, 2))]
    count = max(2, int(math.ceil(duration / ceiling - 1e-9)))
    if max_parts and count > int(max_parts):
        return None
    size = duration / count
    return [(round(i * size, 2), round(min(duration, (i + 1) * size), 2))
            for i in range(count)]


def load_used(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return set(json.load(handle).get("used", []))
    except (OSError, json.JSONDecodeError):
        return set()


def load_rotation(path):
    """Round-robin cursor over the feed pool (0 = start at the first feed)."""
    try:
        with open(path, encoding="utf-8") as handle:
            return int(json.load(handle).get("offset") or 0)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return 0


def save_rotation(path, offset):
    """Persist the cursor; a failure here must never fail a posting run."""
    try:
        if os.path.dirname(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"offset": int(offset)}, handle, indent=2)
    except (OSError, TypeError, ValueError):
        pass


def probe_duration(entry):
    """Flat feed entries normally carry `duration`; fall back to a bounded full extract."""
    dur = parse_duration(entry.get("duration"), entry.get("duration_string"))
    if dur:
        return dur
    vid = entry.get("id")
    if not vid:
        return None
    url = entry.get("webpage_url") or f"https://www.youtube.com/watch?v={vid}"
    try:
        from yt_dlp import YoutubeDL
        opts = {"quiet": True, "no_warnings": True, "noprogress": True, "skip_download": True,
                "socket_timeout": 20, "extractor_retries": 1}
        cookie = os.environ.get("YT_COOKIES_FILE") or str(REPO_ROOT / "cookies.txt")
        if os.path.isfile(cookie):
            opts["cookiefile"] = cookie
        proxy = os.environ.get("YTDLP_PROXY")
        if proxy:
            opts["proxy"] = proxy
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False) or {}
        return parse_duration(info.get("duration"), info.get("duration_string"))
    except Exception:
        return None


def build_candidate(entry, parts, index, start, end, feed):
    vid = entry.get("id")
    base = (entry.get("title") or "").strip()
    channel = (entry.get("channel") or entry.get("uploader") or "Shark Tank Global").strip()
    label = f"(Part {index}/{len(parts)})"
    return {
        "id": f"{vid}#{index}",
        "video_id": vid,
        "part_index": index,
        "part_total": len(parts),
        "title": f"{base} {label}",
        "source_title": base,
        "part_label": label,
        "start": start,
        "end": end,
        "duration": round(end - start, 2),
        "url": entry.get("webpage_url") or f"https://www.youtube.com/watch?v={vid}",
        "channel": channel,
        "uploader": channel,
        "handle": "",
        "source": "youtube",
        "source_feed": feed,
        "content_type": "sharktank_part",
        "content_policy": "sharktank-only",
        "rank": None,
    }


def main():
    load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default=os.environ.get("SHARKTANK_CHANNEL",
                    os.environ.get("SHARKTANK_CHANNELS", ",".join(DEFAULT_CHANNELS))),
                    help="Channel /videos feed(s) to take the newest eligible upload from. "
                         "Comma/newline-separated list; runs walk it round-robin (env "
                         "SHARKTANK_CHANNEL or SHARKTANK_CHANNELS).")
    ap.add_argument("--scan", type=int, default=8, help="Newest uploads inspected before giving up")
    ap.add_argument("--max-parts", type=int, default=20,
                    help="Skip sources that would need more parts than this (a 73-minute "
                         "compilation would otherwise own the channel for months)")
    ap.add_argument("--max-part-secs", type=float, default=MAX_SOURCE_SECS,
                    help="Each part must stay strictly under the 60s Shorts ceiling")
    ap.add_argument("--max", type=int, default=12, help="Max parts emitted (orchestrator parity)")
    ap.add_argument("--history", default="state/used_clips.json")
    ap.add_argument("--rotation", default="state/sharktank_rotation.json",
                    help="Round-robin cursor across --channel feeds")
    ap.add_argument("--out", default=".tmp/rank_candidates.json")
    # Accepted for parity with the other finders so the orchestrator can pass them harmlessly.
    ap.add_argument("--genre", default=None)
    ap.add_argument("--angle", default=None)
    ap.add_argument("--search", default=None)
    args = ap.parse_args()

    used = load_used(args.history)
    feeds = [f.strip() for f in str(args.channel).replace("\n", ",").split(",") if f.strip()]
    # Round-robin: start at the cursor so consecutive runs alternate shows. Without this the
    # first feed alone would own the channel until its whole scan window is consumed.
    offset = load_rotation(args.rotation)
    if feeds:
        start = offset % len(feeds)
        feeds = feeds[start:] + feeds[:start]
    else:
        start = 0
    notes = []
    picked = None

    for feed in feeds:
        try:
            entries = [e for e in search(feed, args.scan) if e]
        except Exception as exc:
            notes.append(f"{feed}: feed unavailable ({str(exc)[:80]})")
            continue
        for entry in entries:
            vid = entry.get("id")
            if not vid or not (entry.get("title") or "").strip():
                continue
            duration = probe_duration(entry)
            if not duration:
                notes.append(f"{vid}: no duration")
                continue
            parts = split_parts(duration, args.max_part_secs, args.max_parts)
            if not parts:
                notes.append(f"{vid}: {duration:.0f}s needs more than {args.max_parts} parts")
                continue
            remaining = [i for i in range(1, len(parts) + 1) if f"{vid}#{i}" not in used]
            if not remaining:
                notes.append(f"{vid}: all {len(parts)} parts already posted")
                continue
            picked = (feed, entry, parts, remaining, duration)
            break
        if picked:
            break

    if not picked:
        fail(f"no eligible pitch-show upload with unposted parts in feeds: {feeds}",
             reasons=notes[:6], channel=feeds, content_policy="sharktank-only")
        return

    # Advance the round-robin cursor only when a feed actually produced work, so an
    # unavailable feed does not silently skip a whole show.
    save_rotation(args.rotation, start + 1)
    feed, entry, parts, remaining, duration = picked
    candidates = [build_candidate(entry, parts, i, parts[i - 1][0], parts[i - 1][1], feed)
                  for i in remaining]
    candidates = candidates[: args.max]
    payload = {
        "source": "youtube",
        "genre": "sharktank",
        "content_policy": "sharktank-only",
        "channel": feed,
        "video": {"id": entry.get("id"), "title": (entry.get("title") or "").strip(),
                  "duration_sec": round(duration, 2), "part_total": len(parts),
                  "parts_remaining": len(remaining)},
        "candidates": candidates,
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    emit({**payload, "count": len(candidates), "path": args.out})


if __name__ == "__main__":
    main()
