"""Find ONE fresh World-Cup clip to post, from YouTube, newest-first.

This powers the SINGLE-CLIP momoclips pipeline (distinct from the #5->#1 ranking
compilation). Every ~20 min the orchestrator asks this tool "did something new happen?"
-- so the whole job is: search the target moments sorted by upload date, drop anything
we've already posted, keep only short/downloadable clips, and hand back the freshest
unused candidates (the orchestrator posts the top one). If nothing new/valid is found it
returns count=0 and the run posts nothing -- that's the "only trigger when something
happened" behaviour.

Why YouTube (not Reddit): Reddit's v.redd.it CDN 403-blocks GitHub's datacenter IPs on
every path (probed 2026-07-03), while YouTube works through the WARP SOCKS proxy
(YTDLP_PROXY). So YouTube is the only cloud-viable source. `ytsearchdate` returns results
sorted newest-first, which is what makes fresh goals/clips surface within minutes.

Categories (each candidate is tagged so the title/caption can match its vibe):
  goal      -- Messi / Ronaldo / big-nation goals (official footage; copyright risk accepted)
  streamer  -- iShowSpeed & other creators at / reacting to the World Cup
  popular   -- viral / best-moment World-Cup clips

Usage:
    python tools/find_worldcup_clips.py [--max 8] [--min-dur 5] [--max-dur 180]
        [--history state/used_clips.json] [--out .tmp/clip_candidates.json]

Prints JSON: {"source":"youtube","count","candidates":[{"id","title","duration","url","category"}...]}
"""
import argparse
import json
import os
import random
import urllib.parse

from _common import REPO_ROOT, load_env, emit, fail

# YouTube search "sp" filter tokens (URL-encoded). "Upload date: Today" is what surfaces
# just-happened content -- probed 2026-07-04: it returned same-day match uploads where a
# plain/relevance search only returned evergreen "best goals" compilations. Fallbacks widen
# the window if a category comes back empty early in the day.
SP_TODAY = "EgIIAg%3D%3D"
SP_WEEK = "EgIIAw%3D%3D"

# category -> search queries. EDIT to retarget who/what we clip. Kept tightly World-Cup-scoped
# so titles are descriptive (helps the safety/relevance read) and results stay on-theme.
QUERIES = {
    "goal": [
        "Messi goal World Cup 2026",
        "Ronaldo goal World Cup 2026",
        "World Cup 2026 goal today",
        "Argentina goal World Cup 2026",
        "Brazil goal World Cup 2026",
        "France goal World Cup 2026",
        "England goal World Cup 2026",
        "Portugal goal World Cup 2026",
    ],
    "streamer": [
        "iShowSpeed World Cup 2026",
        "iShowSpeed World Cup reaction",
        "streamer reacts World Cup 2026 goal",
    ],
    "popular": [
        "World Cup 2026 viral moment",
        "World Cup 2026 best moment today",
    ],
}


def load_used(path):
    """Set of clip ids already posted (so we never repeat one)."""
    try:
        with open(path, encoding="utf-8") as f:
            return set(json.load(f).get("used", []))
    except (OSError, json.JSONDecodeError):
        return set()


def search_recent(query, n, sp):
    """Flat YouTube search FILTERED to a recent upload window -> list of entry dicts.

    Uses the YouTube results URL with an `sp` upload-date filter (Today / This week) rather
    than `ytsearch:` -- `ytsearch` is relevance-ranked and re-surfaces the same evergreen
    compilations, while the date filter is what makes a just-uploaded goal appear on the next
    poll. (`ytsearchdate` isn't supported by the installed yt-dlp build.)
    """
    from yt_dlp import YoutubeDL
    url = f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(query)}&sp={sp}"
    opts = {"quiet": True, "no_warnings": True, "noprogress": True,
            "extract_flat": "in_playlist", "skip_download": True,
            "playlistend": n, "socket_timeout": 30, "extractor_retries": 1}
    cookie = os.environ.get("YT_COOKIES_FILE") or str(REPO_ROOT / "cookies.txt")
    if os.path.isfile(cookie):
        opts["cookiefile"] = cookie
    proxy = os.environ.get("YTDLP_PROXY")   # datacenter-IP runners: route via WARP/residential proxy
    if proxy:
        opts["proxy"] = proxy
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return info.get("entries") or []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-query", type=int, default=8, help="Results fetched per query (newest first)")
    ap.add_argument("--min-dur", type=float, default=5.0, help="Skip clips shorter than this (blank/degenerate)")
    ap.add_argument("--max-dur", type=float, default=75.0,
                    help="Skip clips longer than this -- the whole file is downloaded and a Short is "
                         "<60s, so bias toward true single-moment clips (goals/reactions) over "
                         "multi-minute highlights reels.")
    ap.add_argument("--max", type=int, default=8, help="Max candidates to return (orchestrator posts the top one)")
    ap.add_argument("--categories", default="goal,streamer,popular",
                    help="Comma list restricting which categories to search (e.g. 'streamer,popular').")
    ap.add_argument("--window", default="today", choices=["today", "week"],
                    help="Upload-date window: 'today' (freshest, default) or 'week' (wider supply).")
    ap.add_argument("--history", default="state/used_clips.json",
                    help="JSON of already-posted clip ids, to avoid reposting")
    ap.add_argument("--out", default=".tmp/clip_candidates.json")
    args = ap.parse_args()

    load_env()
    used = load_used(args.history)
    wanted = [c.strip() for c in args.categories.split(",") if c.strip()]
    sp = SP_TODAY if args.window == "today" else SP_WEEK

    # Build a flat, shuffled (query, category) list so no single category monopolises supply and
    # the same query doesn't always lead. Categories stay balanced across runs.
    plan = [(q, cat) for cat in wanted for q in QUERIES.get(cat, [])]
    random.shuffle(plan)

    ordered, seen, errors = [], set(), []   # ordered = freshest-first candidates, deduped
    for q, cat in plan:
        try:
            entries = search_recent(q, args.per_query, sp)
        except Exception as e:
            errors.append(f"{q}: {str(e)[:80]}")
            continue
        for en in entries:
            vid = en.get("id")
            dur = en.get("duration")
            title = (en.get("title") or "").strip()
            if not vid or not title or vid in seen or vid in used:
                continue
            # Require a KNOWN, short duration: unknown usually means a live stream, and a long
            # VOD would download the whole file. Both must be excluded before the build step.
            if not isinstance(dur, (int, float)) or not (args.min_dur <= dur <= args.max_dur):
                continue
            seen.add(vid)
            ordered.append({"id": vid, "title": title, "duration": float(dur),
                            "url": f"https://www.youtube.com/watch?v={vid}", "category": cat})
        if len(ordered) >= args.max * 3:     # plenty gathered -> stop hitting the API
            break

    # `ytsearchdate` already returns newest-first per query; interleaving queries roughly preserves
    # freshness. Keep the first --max as the candidates to try.
    cands = ordered[: args.max]
    if not cands:
        # Not an error the run should crash on -- "nothing new happened" is a valid outcome.
        emit({"source": "youtube", "count": 0, "candidates": [], "path": args.out,
              "note": "no fresh unused clips", "errors": errors[:6]})
        return

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"source": "youtube", "candidates": cands}, f, indent=2, ensure_ascii=False)
    emit({"source": "youtube", "count": len(cands), "candidates": cands, "path": args.out})


if __name__ == "__main__":
    main()
