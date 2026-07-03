"""Find candidate WORLD-CUP STREAMER clips (iShowSpeed / FaZe / Marlon etc.) via YouTube search.

Why YouTube instead of Reddit for this angle: the streamer subs (r/LivestreamFail ...) are
drama-heavy and mostly NOT World-Cup related, and their post titles are too vague for the ranker's
title-based relevance/safety filter to work. A YouTube search ("iShowSpeed World Cup") returns
clips that are actually on-theme AND descriptively titled, so rank_clips.py's `streamer` classifier
can reliably confirm World-Cup relevance and screen out anything off-topic/unsafe.

This only works because the ranking pipeline now runs on a SELF-HOSTED runner (Moemen's home IP) --
GitHub's cloud IPs are bot-checked by YouTube, which is why the default Reddit source exists. On a
blocked IP this tool will return few/no candidates and the orchestrator falls back to fan/match.

We keep only SHORT videos (a known duration within [--min-dur, --max-dur]); build_ranking_video.py
downloads the WHOLE file per clip, so an hours-long watchalong VOD must never slip through.

Usage:
    python tools/find_streamer_clips.py [--queries "a;b"] [--min-dur 3] [--max-dur 240]
        [--max 30] [--out .tmp/rank_candidates.json]

Prints JSON: {"source":"youtube","count","candidates":[{"id","title","duration","url"}, ...]}
"""
import argparse
import json
import os
import random

from _common import REPO_ROOT, load_env, emit, fail

# WC-streamer search queries. EDIT THIS LIST to change who we target. Kept World-Cup-scoped so
# results stay on-theme and descriptively titled (the ranker filters by title). The generic last
# query covers streamers not named here so a thin roster never starves supply.
STREAMER_QUERIES = [
    "iShowSpeed World Cup football",
    "iShowSpeed World Cup reaction",
    "FaZe World Cup football reaction",
    "Marlon streamer World Cup watchalong",
    "streamer reacts World Cup goal",
    "streamers watch World Cup live football",
]


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
    ap.add_argument("--per-query", type=int, default=15, help="Results fetched per query")
    ap.add_argument("--min-dur", type=float, default=3.0, help="Skip clips shorter than this (blank/degenerate)")
    ap.add_argument("--max-dur", type=float, default=240.0,
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
    queries = ([q.strip() for q in args.queries.split(";") if q.strip()]
               if args.queries else list(STREAMER_QUERIES))
    random.shuffle(queries)                                 # vary which roster names lead run to run
    used = load_used(args.history)

    seen, errors = {}, []       # seen = id -> candidate (deduped across queries)
    for q in queries:
        try:
            entries = search(q, args.per_query)
        except Exception as e:
            errors.append(f"{q}: {str(e)[:80]}")
            continue
        for en in entries:
            vid = en.get("id")
            dur = en.get("duration")
            title = (en.get("title") or "").strip()
            if not vid or not title or vid in seen or vid in used:
                continue
            # Require a KNOWN, short duration: unknown usually means a live stream, and a long VOD
            # would download the whole file. Both must be excluded before the build step.
            if not isinstance(dur, (int, float)) or not (args.min_dur <= dur <= args.max_dur):
                continue
            seen[vid] = {"id": vid, "title": title, "duration": float(dur),
                         "url": f"https://www.youtube.com/watch?v={vid}"}
        if len(seen) >= args.max:                           # enough on-theme short clips -> stop
            break

    cands = list(seen.values())
    if len(cands) < 5:
        fail(f"Only {len(cands)} World-Cup streamer clips from YouTube -- need >=5.", reasons=errors[:6])
        return

    random.shuffle(cands)                                   # vary which clips reach the ranker
    cands = cands[: args.max]
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"source": "youtube", "candidates": cands}, f, indent=2, ensure_ascii=False)
    emit({"source": "youtube", "count": len(cands), "candidates": cands, "path": args.out})


if __name__ == "__main__":
    main()
