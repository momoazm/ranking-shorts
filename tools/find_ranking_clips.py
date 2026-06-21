"""Find candidate SHORT YouTube clips for a ranking video from curated funny-Shorts channels.

YouTube's open search (what yt-dlp can reach) returns almost only long compilations, and cutting a
moment out of a 12-50 min compilation streams the whole video (>150s each) -- too slow for cloud
automation. Real Shorts download whole in ~5s. So instead of searching, we pull recent clips from a
curated list of funny-Shorts channels' /shorts tabs (each is guaranteed a short, standalone clip).
The LLM (rank_clips.py) then picks and orders the funniest 5.

Usage:
    python tools/find_ranking_clips.py [--channels "@FailArmy,@AFV"] [--per-channel 8]
        [--max 14] [--out .tmp/rank_candidates.json]

Prints JSON: {"count","candidates":[{"id","title","duration","url","channel"}, ...]}
"""
import argparse
import json
import os
import random

from _common import load_env, emit, fail, REPO_ROOT

# Curated Shorts channels per genre (each verified to expose a /shorts tab). These license or own
# their footage, the most defensible source for reused clips. Pick a genre with --genre, or override
# the channel list directly with --channels.
GENRES = {
    "fails":  ["@FailArmy", "@AFV", "@viralhog", "@JukinMedia"],
    "cats":   ["@TheDodo", "@PetCollective", "@TheCatReviewer"],
    "babies": ["@AFV", "@CuteBabyClub"],
    "dogs":   ["@TheDodo", "@FunnyDogs"],
}
# Default (no genre given) = a broad funny mix.
DEFAULT_CHANNELS = ["@FailArmy", "@AFV", "@TheDodo", "@PetCollective",
                    "@viralhog", "@JukinMedia", "@dailydoseofinternet"]


def _ydl_search_opts(per_channel):
    opts = {"quiet": True, "no_warnings": True, "noprogress": True,
            "extract_flat": "in_playlist", "skip_download": True,
            "playlistend": per_channel, "socket_timeout": 30, "extractor_retries": 1,
            # datacenter IPs get bot-challenged on the web client; mobile/tv clients usually don't.
            "extractor_args": {"youtube": {"player_client": ["tv", "ios", "mweb", "web"]}}}
    cookie = os.environ.get("YT_COOKIES_FILE") or str(REPO_ROOT / "cookies.txt")
    if os.path.isfile(cookie):
        opts["cookiefile"] = cookie
    return opts


def pull_channel(handle, per_channel):
    from yt_dlp import YoutubeDL
    h = handle.strip()
    if not h.startswith("@") and "youtube.com" not in h:
        h = "@" + h
    url = h if "youtube.com" in h else f"https://www.youtube.com/{h}/shorts"
    items = []
    with YoutubeDL(_ydl_search_opts(per_channel)) as ydl:
        info = ydl.extract_info(url, download=False)
    for e in (info.get("entries") or []):
        vid = e.get("id")
        if not vid:
            continue
        items.append({"id": vid, "title": e.get("title") or "",
                      # /shorts tab entries carry no duration in flat mode; they're Shorts (<=~60s),
                      # and build_ranking_video probes + caps each one, so None is fine.
                      "duration": e.get("duration"),
                      "url": e.get("url") or f"https://www.youtube.com/shorts/{vid}",
                      "channel": h})
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--genre", default=None, choices=list(GENRES),
                    help="Pull from this genre's curated channels (fails/cats/babies/dogs)")
    ap.add_argument("--channels", default=None,
                    help="Comma-separated channel handles/URLs (overrides --genre)")
    ap.add_argument("--per-channel", type=int, default=12, help="Recent Shorts to pull per channel")
    ap.add_argument("--max", type=int, default=20, help="Total candidates to return")
    # accepted for backward-compat with the orchestrator; ignored (we pull channels, not search).
    ap.add_argument("--query", default=None)
    ap.add_argument("--out", default=".tmp/rank_candidates.json")
    args = ap.parse_args()

    load_env()
    if args.channels:
        channels = [c.strip() for c in args.channels.split(",") if c.strip()]
    elif args.genre:
        channels = list(GENRES[args.genre])
    else:
        channels = list(DEFAULT_CHANNELS)
    random.shuffle(channels)   # vary the mix run to run

    cands, seen, errors = [], set(), []
    for ch in channels:
        try:
            for it in pull_channel(ch, args.per_channel):
                if it["id"] in seen:
                    continue
                seen.add(it["id"])
                cands.append(it)
        except Exception as e:
            errors.append(f"{ch}: {str(e)[:80]}")
            continue

    if len(cands) < 5:
        fail(f"Only {len(cands)} usable Shorts from channels -- need >=5.",
             candidates=cands, channel_errors=errors)
        return

    random.shuffle(cands)
    cands = cands[: args.max]

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"candidates": cands}, f, indent=2, ensure_ascii=False)
    emit({"count": len(cands), "candidates": cands, "channel_errors": errors, "path": args.out})


if __name__ == "__main__":
    main()
