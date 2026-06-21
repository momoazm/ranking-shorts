"""Find candidate funny clips for a ranking video from Reddit (CI-friendly, no cookies/bot-check).

Why Reddit instead of YouTube: YouTube bot-checks downloads from datacenter IPs (GitHub Actions),
so it needs fragile, expiring cookies. Reddit's video posts download fine from cloud IPs with no
auth, and funny subreddits (r/Whatcouldgowrong, r/IdiotsInCars, r/cats ...) are full of short clips.

Listing uses Reddit's RSS feed (the .json endpoint 403s for bots; .rss works). RSS rate-limits one
IP hard, so we make ONE feed request per run -- a single subreddit's top feed returns ~25 posts,
far more than the 5 we need -- with backoff retry on 429. yt-dlp then downloads each post.

Usage:
    python tools/find_ranking_clips.py [--genre fails] [--subreddits a,b] [--period month]
        [--max 20] [--out .tmp/rank_candidates.json]

Prints JSON: {"count","subreddit","candidates":[{"id","title","duration","url"}, ...]}
"""
import argparse
import html
import json
import os
import random
import re
import time
import urllib.request

from _common import load_env, emit, fail

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# Funny / wholesome video subreddits per genre. One is picked per run (RSS is rate-limited), with
# the rest as fallbacks if the first is empty/blocked. Override with --subreddits.
GENRE_SUBS = {
    "fails":  ["Whatcouldgowrong", "instantkarma", "instant_regret", "IdiotsInCars", "funny"],
    "cats":   ["cats", "catsstandingup", "Catloaf", "IllegallySmolCats", "CatsBeingCats"],
    "babies": ["KidsAreFuckingStupid", "ContagiousLaughter", "funny"],
    "dogs":   ["WhatsWrongWithYourDog", "dogswithjobs", "Zoomies", "rarepuppers"],
}
DEFAULT_SUBS = ["Whatcouldgowrong", "instantkarma", "IdiotsInCars", "KidsAreFuckingStupid", "cats"]


def fetch_rss(subreddit, period, attempts=3):
    """Return the raw RSS for a subreddit's top feed, retrying with backoff on 429."""
    url = f"https://www.reddit.com/r/{subreddit}/top/.rss?t={period}"
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
        except Exception as e:
            last = e
            if "429" in str(e) and i < attempts - 1:
                time.sleep(6 * (i + 1))   # back off and retry
                continue
            raise last


def load_used(path):
    """Set of Reddit post ids already used in past videos (so we never repeat a clip)."""
    try:
        with open(path, encoding="utf-8") as f:
            return set(json.load(f).get("used", []))
    except (OSError, json.JSONDecodeError):
        return set()


def parse_posts(rss):
    """Pull (id, title, permalink) out of the RSS entries (skip the feed header entry)."""
    items, seen = [], set()
    for block in rss.split("<entry>")[1:]:
        m = re.search(r'href="(https://www\.reddit\.com/r/[^"]+/comments/([^/"]+)/[^"]*)"', block)
        if not m:
            continue
        url, vid = m.group(1), m.group(2)
        if vid in seen:
            continue
        seen.add(vid)
        tm = re.search(r"<title>(.*?)</title>", block, re.S)
        title = html.unescape((tm.group(1) if tm else "").strip())
        items.append({"id": vid, "title": title, "duration": None, "url": url})
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--genre", default=None, choices=list(GENRE_SUBS),
                    help="Pick subreddits for this genre (fails/cats/babies/dogs)")
    ap.add_argument("--subreddits", default=None, help="Comma-separated subreddits (overrides --genre)")
    ap.add_argument("--period", default=None, choices=["day", "week", "month", "year", "all"],
                    help="Reddit top period (default: random week/month/year for variety)")
    ap.add_argument("--max", type=int, default=20, help="Max candidates to return")
    ap.add_argument("--history", default="state/used_clips.json",
                    help="JSON of already-used post ids, to avoid repeating clips run to run")
    # accepted for backward-compat with the orchestrator; ignored (we pull Reddit, not search).
    ap.add_argument("--query", default=None)
    ap.add_argument("--out", default=".tmp/rank_candidates.json")
    args = ap.parse_args()

    load_env()
    if args.subreddits:
        subs = [s.strip() for s in args.subreddits.split(",") if s.strip()]
    elif args.genre:
        subs = list(GENRE_SUBS[args.genre])
    else:
        subs = list(DEFAULT_SUBS)
    random.shuffle(subs)                                    # vary the source run to run
    period = args.period or random.choice(["week", "month", "year"])   # vary the time window too
    used = load_used(args.history)

    seen, fresh, errors = {}, [], []   # seen = id->post (all), fresh = not-yet-used
    chosen_sub = None
    for sub in subs:                   # ONE feed is usually enough; stop once we have 5 fresh posts
        try:
            posts = parse_posts(fetch_rss(sub, period))
        except Exception as e:
            errors.append(f"{sub}: {str(e)[:80]}")
            continue
        for p in posts:
            seen.setdefault(p["id"], p)
        sub_fresh = [p for p in posts if p["id"] not in used]
        if len(sub_fresh) >= 5:
            fresh, chosen_sub = sub_fresh, sub
            break

    if not fresh:                      # no single feed had 5 unused -> pool fresh across feeds...
        fresh = [p for p in seen.values() if p["id"] not in used]
        chosen_sub = "mixed"
    if len(fresh) < 5:                 # ...and only if we've genuinely drained them, allow repeats
        fresh = list(seen.values())

    if len(fresh) < 5:
        fail(f"Only {len(fresh)} candidate posts from Reddit -- need >=5.", reasons=errors[:6])
        return

    random.shuffle(fresh)              # vary which clips reach the ranker
    cands = fresh[: args.max]
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"subreddit": chosen_sub, "period": period, "candidates": cands},
                  f, indent=2, ensure_ascii=False)
    emit({"count": len(cands), "subreddit": chosen_sub, "period": period,
          "candidates": cands, "path": args.out})


if __name__ == "__main__":
    main()
