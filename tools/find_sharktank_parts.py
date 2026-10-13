"""Split the newest eligible Shark Tank upload into sequential Short-length parts.

The account is switching from streamer clips to full-episode chops: take the channel's
newest video and cut it into consecutive segments that are each just under the 60s Shorts
ceiling, so a ~10 minute pitch becomes ~10 one-minute parts instead of one hand-picked
moment. Parts are emitted in play order and the orchestrator posts the first one that is
not already recorded in the shared clip history (state/used_clips.json -- the same ledger
the streamer pool uses, keyed "<video_id>#<part_index>"), so consecutive scheduled runs
walk through a video part 1 -> part N and then move on to the next newest upload. An
unfinished chop is finished first: an upload with some parts already posted outranks a
brand-new one (closest to done first), because the orchestrator posts exactly one part per
run and the newest-first feed walk alone used to abandon every chop after its first part.
The pool also carries the first part(s) of the next --max-videos distinct uploads, so a
bot-walled upload fails over to a different video_id instead of burning the slot.

Sourcing is a rotation of official pitch-show feeds (Shark Tank US + Dragons' Den UK +
Shark Tank Australia + Dragons' Den Canada by default; override with --channel /
SHARKTANK_CHANNEL[S], cursor in --rotation): runs walk the pool round-robin so the
channel interleaves shows, and every candidate is already the right show, right channel,
and a known slice of one video. Parts stay strictly under 60s (prepare_upload_media
rejects >=60s) and sources needing more than --max-parts are skipped (an hour-long
compilation would otherwise own the channel for months); the video must also have at
least one unposted part left.

Usage:
    python tools/find_sharktank_parts.py [--channel URL] [--scan 8] [--max-parts 20]
        [--max-part-secs 59.5] [--history state/used_clips.json] [--out .tmp/rank_candidates.json]
        [--inprogress state/sharktank_inprogress.json] [--rotation state/sharktank_rotation.json]

--inprogress is the durable queue, ROOT-anchored by default so it cannot be sharded from
the download-failure strikes by running the tool from another directory. It holds two
maps: the uploads whose parts are not all posted (any chop with a part already posted,
plus this run's whole candidate pool, so a fallback post is remembered too), and the
download-failure strikes that demote an upload which keeps failing to download. An
unfinished chop is therefore still offered after it scrolls out of the feeds' --scan
window, and the file is written atomically (temp file + rename) so a killed run cannot
wipe it.

Prints JSON: {"source":"youtube","genre":"sharktank","count","video",...,"candidates":[...]}
"""
import argparse
import json
import math
import os
import sys
import time

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


# Durable in-progress queue ----------------------------------------------------------
# A chop is a SEQUENTIAL playlist: parts 1..N of one upload, and the orchestrator posts
# exactly one part per run. The finder used to always offer the NEWEST upload of whichever
# feed the round-robin landed on, so every new episode displaced an unfinished video and
# its remaining parts were never offered again -- measured over 2026-10-03..05, only 7 of
# 59 parts ever reached the channel. In-progress videos are therefore remembered here,
# outside the feeds' --scan window, so finishing one no longer depends on it still being
# among the 8 newest uploads of its own feed.
INPROGRESS_STATE = "state/sharktank_inprogress.json"
FAILURE_WINDOW_SEC = 7 * 24 * 3600   # a recorded download failure demotes the video for a week
DEAD_STRIKES = 2                      # ... but only once it has failed that many times
_SLIM_FIELDS = ("id", "title", "channel", "uploader", "webpage_url")


def slim_entry(entry):
    """Exactly the fields build_candidate() reads, so a part can be rebuilt from state after
    its upload scrolls out of the feed's scan window."""
    return {field: (entry or {}).get(field) for field in _SLIM_FIELDS}


def load_progress(path):
    """Return (videos, failures). A missing or corrupt file is an empty queue, never a crash."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    videos = data.get("videos")
    failures = data.get("failures")
    return (videos if isinstance(videos, dict) else {},
            failures if isinstance(failures, dict) else {})


def save_progress(path, videos, failures):
    """Best-effort ATOMIC write: losing the queue must never fail the posting run that hit
    it, and a partial write must never destroy it either -- load_progress treats a corrupt
    file as empty, so a truncate-write that got killed mid-dump (the finder runs under a
    hard child timeout) would silently delete every in-progress video and every strike."""
    try:
        if os.path.dirname(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
        temp = f"{path}.tmp"
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump({"videos": videos, "failures": failures}, handle,
                      indent=2, ensure_ascii=False)
        os.replace(temp, path)          # atomic on POSIX and on Windows
    except (OSError, TypeError, ValueError):
        try:
            os.remove(f"{path}.tmp")
        except OSError:
            pass


def _failure_count(failures, video_id, now=None):
    """Strikes for `video_id` still inside the demotion window (0 when healthy or expired)."""
    entry = (failures or {}).get(video_id)
    if not isinstance(entry, dict):
        return 0
    try:
        count = int(entry.get("count") or 0)
        last = float(entry.get("last_at") or 0)
    except (TypeError, ValueError):
        return 0
    if (now if now is not None else time.time()) - last > FAILURE_WINDOW_SEC:
        return 0
    return count


def record_download_failure(video_id, path=None):
    """Called by rank_autopost when a chop's source download fails.

    The per-run blacklist already skips the rest of that video's parts for THIS run;
    persisting the failure lets the NEXT run demote an upload that keeps failing instead of
    forcing it back to the front of the queue. Never raises.

    `path` defaults to the repo's own queue file, ROOT-anchored rather than cwd-relative,
    so launching the orchestrator from another directory cannot silently lose the strike.
    """
    if not video_id:
        return
    target = path or str(REPO_ROOT / INPROGRESS_STATE)
    try:
        videos, failures = load_progress(target)
        now = time.time()
        current = failures.get(video_id)
        current = current if isinstance(current, dict) else {}
        try:
            previous = int(current.get("count") or 0)
            last = float(current.get("last_at") or 0)
        except (TypeError, ValueError):
            previous, last = 0, 0.0
        if now - last > FAILURE_WINDOW_SEC:
            previous = 0            # a fresh window starts a fresh count
        failures[video_id] = {"count": previous + 1, "last_at": now}
        save_progress(target, videos, failures)
    except Exception as exc:        # pragma: no cover - defensive
        print(f"::warning::could not record shark tank download failure: {exc}", file=sys.stderr)


def pick_priority(pick, failures=None):
    """Sort key: finish what has already started, and demote a chop that keeps failing.

    0 = in-progress and healthy -> finish it (closest to done first)
    1 = brand-new upload -> the caller's rotated, newest-first order decides among these
    2 = in-progress but currently failing -> come back to it once the others are clear

    The strike only demotes an IN-PROGRESS chop. An upload that has never posted a part is
    already handled one level up, by the orchestrator's per-run video_id blacklist, so
    demoting it here would just hide it from the download-failure fallback pool.
    """
    _feed, entry, parts, remaining, _duration = pick
    if len(parts) - len(remaining) <= 0:
        return (1, 0)
    if _failure_count(failures, (entry or {}).get("id") or "") >= DEAD_STRIKES:
        return (2, 0)
    return (0, len(remaining))


def order_picks(picks, failures=None):
    """Stable sort, so ties keep the feed-rotation / newest-first order the caller built."""
    return sorted(picks, key=lambda pick: pick_priority(pick, failures))


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
    ap.add_argument("--max-videos", type=int, default=3,
                    help="Distinct uploads to emit (newest first). Part 1 of every extra "
                         "video is a download-failure fallback for the orchestrator.")
    ap.add_argument("--history", default="state/used_clips.json")
    ap.add_argument("--rotation", default="state/sharktank_rotation.json",
                    help="Round-robin cursor across --channel feeds")
    ap.add_argument("--inprogress", default=str(REPO_ROOT / INPROGRESS_STATE),
                    help="Durable queue of uploads whose parts are not all posted yet, so an "
                         "unfinished chop keeps being offered even after it scrolls out of "
                         "the feeds' --scan window")
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
    picks = []
    stored_videos, failures = load_progress(args.inprogress)

    # Every feed is walked -- NOT just until --max-videos picks. A video that is already
    # part-posted must be found wherever it lives, otherwise finishing one depends on the
    # round-robin landing on its feed while it is still inside the scan window. Flat feed
    # entries carry their duration, so the extra walks cost no per-entry network probe in
    # the normal case.
    max_videos = max(1, min(args.max_videos, args.max))
    seen_ids = set()      # this upload already produced a pick
    finished = set()      # every part posted -- the only way an upload is pruned
    for feed in feeds:
        try:
            entries = [e for e in search(feed, args.scan) if e]
        except Exception as exc:
            notes.append(f"{feed}: feed unavailable ({str(exc)[:80]})")
            continue
        for entry in entries:
            vid = entry.get("id")
            if not vid or vid in seen_ids or not (entry.get("title") or "").strip():
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
            seen_ids.add(vid)
            if not remaining:
                finished.add(vid)
                notes.append(f"{vid}: all {len(parts)} parts already posted")
                continue
            picks.append((feed, entry, parts, remaining, duration))

    # Re-attach in-progress uploads the feeds no longer show (scrolled past --scan, or the
    # feed was unavailable this run). They need no network: the queue keeps the duration and
    # exactly the fields build_candidate() reads.
    for vid, info in stored_videos.items():
        if vid in seen_ids or not isinstance(info, dict):
            continue
        if info.get("id") != vid:
            # A record whose id does not match its key would emit candidates carrying a
            # None or foreign video_id, which would collide in the shared
            # "<video_id>#<part>" ledger. This writer always stores the id, so only a
            # hand-edited or corrupt queue can produce one: skip offering it, but leave it
            # in the queue below rather than destroy something we cannot interpret.
            notes.append(f"{vid}: queue record id does not match its key; not offered")
            continue
        duration = info.get("duration")
        parts = split_parts(duration, args.max_part_secs, args.max_parts) if duration else None
        if not parts:
            notes.append(f"{vid}: kept in the queue, not re-evaluable this run")
            continue
        remaining = [i for i in range(1, len(parts) + 1) if f"{vid}#{i}" not in used]
        if not remaining:
            finished.add(vid)
            continue
        picks.append((info.get("feed") or "", dict(info), parts, remaining, duration))

    if not picks:
        fail(f"no eligible pitch-show upload with unposted parts in feeds: {feeds}",
             reasons=notes[:6], channel=feeds, content_policy="sharktank-only")
        return

    # Finish what has already started before opening a new upload (see INPROGRESS_STATE):
    # the newest-first feed walk alone abandoned every chop after its first part or two.
    ordered = order_picks(picks, failures)
    pool = ordered[:max_videos]

    # Persist what is still in progress. EVERY upload whose part could be posted from this
    # run's pool is remembered, not just the front pick: the orchestrator falls through to a
    # distinct fallback video when the front pick's download fails, and if that upload then
    # scrolls out of the scan window its parts 2..N would never be offered again -- the very
    # loss this queue exists to prevent. The pool is exactly the set of videos the
    # orchestrator is about to see as candidates.
    pool_ids = {(p[1] or {}).get("id") for p in pool}
    live = {}
    for pick in ordered:
        _feed, entry, parts, remaining, duration = pick
        vid = (entry or {}).get("id")
        if not vid:
            continue
        if len(parts) - len(remaining) > 0 or vid in pool_ids:
            live[vid] = {**slim_entry(entry), "duration": duration,
                         "part_total": len(parts), "feed": _feed}
    # A known upload leaves the queue ONLY once every part is posted. Everything else -- a
    # feed that was down, a duration that no longer resolves, a lowered --max-parts, or a
    # pool candidate that has not been posted yet -- is carried through untouched.
    #
    # Deliberately NOT pruned on the inference "the ledger shows no part posted, so this
    # upload never started". state/ (the ledger AND this queue) exists only in the GitHub
    # Actions cache, whose post step is success()-gated, so a run that posts a part and then
    # goes red -- an Instagram-required failure after the YouTube post, a timeout, or a
    # cancelled no_upload dispatch -- rolls BOTH files back to the previous snapshot. The
    # next run would then see a chop that really does have a live posted part as
    # "unstarted", and pruning on that inference would delete it permanently, in a green
    # run. Pruning on positive evidence of completion is safe; pruning on a ledger that can
    # lag reality is not. The accepted cost is that a pool candidate which never gets posted
    # is retained until it eventually does, so the queue grows slowly on a busy feed (a few
    # hundred bytes per entry, re-attached in memory with no network call).
    for vid, info in stored_videos.items():
        if vid not in live and vid not in finished and isinstance(info, dict):
            live[vid] = info
    # Aged-out strikes are dropped so the map cannot grow without bound; a strike that
    # expires is already worth zero, so this cannot change this run's ordering.
    failures = {vid: record for vid, record in failures.items()
                if isinstance(record, dict) and _failure_count(failures, vid) > 0}
    save_progress(args.inprogress, live, failures)

    picks = pool

    # Advance the round-robin cursor whenever this run produced a non-empty pool, so the next
    # run starts at the next feed. A run with an empty pool exits above via fail() BEFORE
    # reaching this line, leaving the cursor untouched. Note that a run whose feeds were all
    # unavailable but whose durable queue still had a chop to offer does advance it -- that
    # run's work came from the queue rather than a feed, so no show loses a turn to it.
    save_rotation(args.rotation, start + 1)
    candidates = []
    for index, (feed, entry, parts, remaining, duration) in enumerate(picks):
        # Reserve one slot for every not-yet-emitted video so the fallback video's first
        # part always fits inside --max (earlier videos may take the rest).
        budget = args.max - len(candidates) - (len(picks) - index - 1)
        for i in remaining[: max(1, budget)]:
            candidates.append(
                build_candidate(entry, parts, i, parts[i - 1][0], parts[i - 1][1], feed))
    feed, entry, parts, remaining, duration = picks[0]
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
