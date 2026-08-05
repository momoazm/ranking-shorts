"""Find candidate streamer/creator clips via YouTube search.

The main ranking workflow uses this as a dedicated source pool for funny live-stream moments,
reactions, meltdowns, and chat interactions. `_common.title_ok` supplies the deterministic
English/safety screen, including the repository's current iShowSpeed block.

Why YouTube instead of Reddit: streamer subs are drama-heavy and their post titles are often too
vague for the ranker's relevance/safety filter. YouTube search returns short, descriptively titled
creator moments that can be ranked for an obvious funny payoff.

The GitHub workflow supplies a WARP proxy and a BgUtils proof-of-origin token provider so this
YouTube source remains usable on cloud runners. If YouTube is blocked or the pool is too thin, the
streamer-mode orchestrator fails clearly instead of falling back to football or generic fails.

We keep only SHORT videos (a known duration within [--min-dur, --max-dur]); build_ranking_video.py
downloads the WHOLE file per clip, so an hours-long watchalong VOD must never slip through.

Usage:
    python tools/find_streamer_clips.py [--queries "a;b"] [--min-dur 3] [--max-dur 180]
        [--max 30] [--out .tmp/rank_candidates.json]

Prints JSON: {"source":"youtube","count","candidates":[{"id","title","duration","url"}, ...]}
"""
import argparse
import json
import os
import random
import re

from _common import REPO_ROOT, load_env, emit, fail, title_ok

# Streamer search queries. Keep these focused on standalone creator moments rather than full VODs,
# podcasts, or compilations. The generic queries ensure the pool does not depend on one creator.
STREAMER_QUERIES = [
    "Kai Cenat funny moments shorts",
    "Jynxzi funny moments shorts",
    "CaseOh funny moments shorts",
    "xQc funny moments shorts",
    "Adin Ross funny streamer clips",
    "Twitch streamer funniest reaction shorts",
    "streamer rage funny clip shorts",
    "streamer chat interaction funny clip",
]

# A second-pass roster used only when the creator-specific pass produces fewer than the five
# clips needed for a #5 -> #1 video. These queries still describe streamer content, but their
# results often omit a creator name from the title or channel metadata, which is why they are not
# part of the strict first pass.
STREAMER_FALLBACK_QUERIES = [
    "funny Twitch streamer moments shorts",
    "viral streamer reaction clips shorts",
    "streamer rage moments shorts",
    "live streamer funniest clips shorts",
    "Kai Cenat reaction clips shorts",
    "Jynxzi rage moments shorts",
    "CaseOh funniest clips shorts",
    "xQc reaction clips shorts",
]

STREAMER_HINTS = (
    "streamer", "twitch", "kai cenat", "kaicenat", "jynxzi", "caseoh", "xqc", "adin ross", "adinross",
    "pokimane", "ludwig", "hasan", "tarik", "nmplol", "sodapoppin", "faze",
)

_NON_STREAMER_SPORT = re.compile(
    r"\b(?:nfl|nba|mlb|nhl|ncaa|baseball|basketball|american\s+football|soccer|football|"
    r"hockey|cricket|pitcher|pitching|home\s+run|touchdown|quarterback|premier\s+league|"
    r"champions\s+league|world\s+cup)\b",
    re.IGNORECASE,
)
_PROMO_TITLE = re.compile(r"^\s*(?:follow|subscribe|join|watch\s+me|link\s+in\s+bio)\b", re.IGNORECASE)
_NON_CLIP_TITLE = re.compile(r"\b(?:official\s+music\s+video|music\s+video|diss\s+track|lyrics?|album|song)\b", re.IGNORECASE)

def streamer_signal(title, channel, handle=""):
    text = f"{title} {channel} {handle}".lower()
    known_creator = any(hint in text for hint in STREAMER_HINTS
                        if hint not in {"streamer", "twitch"})
    if known_creator or "streamer" in text:
        return True
    # A bare "Twitch" in a title is not evidence (athlete compilations use it too). When
    # that is the only signal, require uploader metadata itself to look like a creator
    # channel so a generic sports channel cannot pass on query context alone.
    meta = f"{channel} {handle}".lower()
    return "twitch" in text and any(marker in meta for marker in ("clips", "live", "stream", "twitch"))


def load_used(path):
    """Set of clip ids already used in past videos (so we never repeat a clip)."""
    try:
        with open(path, encoding="utf-8") as f:
            return set(json.load(f).get("used", []))
    except (OSError, json.JSONDecodeError):
        return set()


def search(query, n):
    """Flat YouTube search -> list of {id,title,duration} dicts (no download, fast)."""
    from yt_dlp import YoutubeDL
    opts = {"quiet": True, "no_warnings": True, "noprogress": True,
            "extract_flat": "in_playlist", "skip_download": True,
            "socket_timeout": 30, "extractor_retries": 1}
    cookie = os.environ.get("YT_COOKIES_FILE") or str(REPO_ROOT / "cookies.txt")
    if os.path.isfile(cookie):
        opts["cookiefile"] = cookie
    proxy = os.environ.get("YTDLP_PROXY")   # datacenter-IP runners: route via WARP/residential proxy
    if proxy:
        opts["proxy"] = proxy
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{n}:{query}", download=False)
    return info.get("entries") or []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", default=None,
                    help="Semicolon-separated search queries (overrides the built-in roster).")
    ap.add_argument("--per-query", type=int, default=20, help="Results fetched per query")
    ap.add_argument("--min-dur", type=float, default=3.0, help="Skip clips shorter than this (blank/degenerate)")
    ap.add_argument("--max-dur", type=float, default=180.0,
                    help="Skip clips longer than this -- the whole file is downloaded per clip, so "
                         "long VODs/watchalongs must be excluded.")
    ap.add_argument("--max", type=int, default=30, help="Max candidates to return")
    ap.add_argument("--history", default="state/used_clips.json",
                    help="JSON of already-used clip ids, to avoid repeating clips run to run")
    # accepted for parity with find_ranking_clips.py so the orchestrator can pass them harmlessly
    ap.add_argument("--genre", default=None)
    ap.add_argument("--angle", default=None)
    ap.add_argument("--out", default=".tmp/rank_candidates.json")
    args = ap.parse_args()

    load_env()
    custom_queries = args.queries is not None
    queries = ([q.strip() for q in args.queries.split(";") if q.strip()]
               if custom_queries else list(STREAMER_QUERIES))
    random.shuffle(queries)                                 # vary which roster names lead run to run
    used = load_used(args.history)

    seen, errors = {}, []       # seen = id -> candidate (deduped across queries)

    def add_entries(entries):
        """Add safe, known-duration candidates from one streamer-focused search."""
        for en in entries:
            vid = en.get("id")
            dur = en.get("duration")
            title = (en.get("title") or "").strip()
            channel = (en.get("channel") or en.get("uploader") or "").strip()
            handle = (en.get("uploader_id") or en.get("channel_id") or "").strip()
            if not vid or not title or vid in seen or vid in used:
                continue
            # English-audience screen: drop non-Latin-script, news/analysis/talk, list, and
            # blocked-creator markers before they ever reach the ranker.
            if not title_ok(title):
                continue
            if (_NON_STREAMER_SPORT.search(f"{title} {channel} {handle}")
                    or _PROMO_TITLE.search(title) or _NON_CLIP_TITLE.search(title)):
                continue
            # Every result must carry an explicit creator/streamer signal in its title or channel.
            # Search-query context is not evidence: the previous broad fallback admitted an NFL
            # Falcons fan reaction simply because the word "reaction" appeared in its title.
            # If YouTube omits both signals, skip it and keep the workflow fail-closed.
            if not streamer_signal(title, channel, handle):
                continue
            # Require a KNOWN, short duration: unknown usually means a live stream, and a long VOD
            # would download the whole file. Both must be excluded before the build step.
            if not isinstance(dur, (int, float)) or not (args.min_dur <= dur <= args.max_dur):
                continue
            seen[vid] = {"id": vid, "title": title, "duration": float(dur),
                         "url": f"https://www.youtube.com/watch?v={vid}",
                         "channel": channel, "uploader": en.get("uploader") or channel,
                         "handle": handle,
                         "source": "youtube"}

    for q in queries:
        try:
            entries = search(q, args.per_query)
        except Exception as e:
            errors.append(f"{q}: {str(e)[:80]}")
            continue
        add_entries(entries)
        if len(seen) >= args.max:                           # enough on-theme short clips -> stop
            break

    # YouTube often omits the channel name from flat search results. If the strict creator pool
    # is too thin, widen discovery with streamer-only queries while retaining the English/title,
    # known-duration, dedupe, and short-video safety gates above. Custom query callers keep the
    # strict semantics they requested.
    if len(seen) < 5 and not custom_queries:
        fallback_queries = list(STREAMER_FALLBACK_QUERIES)
        random.shuffle(fallback_queries)
        for q in fallback_queries:
            try:
                entries = search(q, args.per_query)
            except Exception as e:
                errors.append(f"{q}: {str(e)[:80]}")
                continue
            add_entries(entries)
            if len(seen) >= args.max:
                break

    cands = list(seen.values())
    if len(cands) < 5:
        fail(f"Only {len(cands)} usable streamer clips from YouTube -- need >=5.", reasons=errors[:6])
        return

    random.shuffle(cands)                                   # vary which clips reach the ranker
    cands = cands[: args.max]
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"source": "youtube", "candidates": cands}, f, indent=2, ensure_ascii=False)
    emit({"source": "youtube", "count": len(cands), "candidates": cands, "path": args.out})


if __name__ == "__main__":
    main()
