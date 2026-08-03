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
import math
import os
import random
import re
import subprocess
import sys
import time
import urllib.request

from _common import channel_ok, load_env, emit, fail, title_ok, REPO_ROOT

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# Funny / wholesome video subreddits per genre. One is picked per run (RSS is rate-limited), with
# the rest as fallbacks if the first is empty/blocked. Override with --subreddits.
GENRE_SUBS = {
    "fails":  ["Whatcouldgowrong", "instantkarma", "instant_regret", "IdiotsInCars", "funny"],
    "cats":   ["cats", "catsstandingup", "Catloaf", "IllegallySmolCats", "CatsBeingCats"],
    "babies": ["KidsAreFuckingStupid", "ContagiousLaughter", "funny"],
    "dogs":   ["WhatsWrongWithYourDog", "Zoomies", "dogswithjobs", "AnimalsBeingDerps"],
    # World Cup funny moments + fan/crowd reactions (forced on while the 2026 tournament is live).
    # r/soccer deliberately excluded: its "top" feed mixes in tragedy/tribute/political posts
    # alongside funny clips, which the rank_clips.py safety instruction can't reliably screen out.
    "worldcup": ["WorldCup", "footballhighlights", "footy"],
}

# The worldcup "streamer" angle (FaZe / Marlon etc. -- NO iShowSpeed, user rule 2026-07-06) is NOT on the
# football feeds -- those clips live on livestream-clip subs. Sourced only when
# `--genre worldcup --angle streamer` is passed. r/LivestreamFail leads (huge, reliably v.redd.it-
# hosted, covers every big streamer's WC moments); the creator subs are supply fallbacks.
WORLDCUP_STREAMER_SUBS = ["LivestreamFail", "livestreamfails", "FaZeClan"]  # no iShowSpeed (user rule 2026-07-06)
DEFAULT_SUBS = ["Whatcouldgowrong", "instantkarma", "IdiotsInCars", "KidsAreFuckingStupid", "cats"]

# GitHub-hosted runners cannot reliably fetch Reddit media.  YouTube Shorts are the cloud-safe
# funny-source path: the search result itself is usually the finished moment, while yt-dlp still
# gives us a real source URL and view/length metadata for ranking and quality checks.
YOUTUBE_QUERIES = {
    "fails": [
        "funny fails shorts",
        "instant karma funny shorts",
        "funny moments caught on camera shorts",
        "best funny fail moments shorts",
    ],
    "cats": ["funny cat moments shorts", "cats being funny shorts", "cat fails shorts"],
    "babies": ["funny baby moments shorts", "kids funny moments shorts"],
    "dogs": ["funny dog moments shorts", "dogs being funny shorts", "dog fails shorts"],
    "worldcup": ["funny football moments shorts", "funny World Cup moments shorts"],
}
_YOUTUBE_BAD = re.compile(
    r"\b(full\s+episode|podcast|trailer|music\s+video|official\s+audio|lyrics|news|analysis|"
    r"reaction\s+compilation|compilation|montage|top\s*\d+|best\s+of\s+\d{4})\b",
    re.IGNORECASE,
)


def _youtube_search(query, limit):
    """Run yt-dlp search in a killable child so a bot-wall cannot hold the workflow."""
    cmd = [sys.executable, "-m", "yt_dlp", "--flat-playlist", "--dump-single-json",
           "--skip-download", "--no-playlist", "--quiet", "--no-warnings", "--no-progress",
           "--socket-timeout", "15", "--retries", "0", "--extractor-retries", "0",
           "--playlist-end", str(limit)]
    cookie = os.environ.get("YT_COOKIES_FILE") or str(REPO_ROOT / "cookies.txt")
    if os.path.isfile(cookie):
        cmd += ["--cookies", cookie]
    proxy = os.environ.get("YTDLP_PROXY")
    if proxy:
        cmd += ["--proxy", proxy]
    cmd.append(f"ytsearch{limit}:{query}")
    try:
        proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=70)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"YouTube search timed out for {query!r}") from e
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip()[-400:]
        raise RuntimeError(tail or f"yt-dlp search exited {proc.returncode}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"yt-dlp search returned invalid JSON: {e}") from e
    return data.get("entries") or []


def _youtube_candidates(genre, limit, query_override=None):
    queries = [query_override] if query_override else list(YOUTUBE_QUERIES.get(genre, YOUTUBE_QUERIES["fails"]))
    random.shuffle(queries)
    by_id, errors = {}, []
    for query in queries:
        try:
            entries = _youtube_search(query, max(12, min(30, limit)))
        except Exception as e:
            errors.append(f"{query}: {str(e)[:120]}")
            continue
        for item in entries:
            vid = item.get("id")
            title = html.unescape(str(item.get("title") or "").strip())
            channel = str(item.get("channel") or item.get("uploader") or "").strip()
            if not vid or vid in by_id or not title or not title_ok(title):
                continue
            if _YOUTUBE_BAD.search(title) or not channel_ok(channel):
                continue
            try:
                duration = float(item.get("duration") or 0)
            except (TypeError, ValueError):
                duration = 0.0
            # Prefer self-contained Shorts/moments. Long-form uploads and two-second teasers do
            # not make a useful countdown segment, and a hard upper bound prevents the builder
            # from downloading an entire compilation by accident.
            if not duration or not (3.0 <= duration <= 90.0):
                continue
            by_id[vid] = {
                "id": vid,
                "title": title,
                "duration": round(duration, 2) if duration else None,
                "url": item.get("webpage_url") or f"https://www.youtube.com/watch?v={vid}",
                "channel": channel,
                "uploader": item.get("uploader") or channel,
                "view_count": item.get("view_count"),
                "like_count": item.get("like_count"),
                "upload_date": item.get("upload_date"),
                "source": "youtube",
                "search_query": query,
            }
    if len(by_id) < 5:
        fail(f"Only {len(by_id)} usable YouTube funny candidates -- need >=5.", reasons=errors[:6])
        return []

    def score(c):
        views = max(0, int(c.get("view_count") or 0))
        likes = max(0, int(c.get("like_count") or 0))
        dur = c.get("duration") or 45
        # Views/likes are supporting signals only; the LLM still chooses the actual clips. Keep
        # short, self-contained moments ahead of long search noise and add tiny jitter for variety.
        quality = math.log10(views + 1) + 0.35 * math.log10(likes + 1)
        length = 1.0 if 6 <= dur <= 55 else 0.4
        return quality + length + random.random() * 0.15

    # Keep at most two results per channel so one repost farm cannot fill the whole countdown.
    picked, per_channel = [], {}
    for candidate in sorted(by_id.values(), key=score, reverse=True):
        key = candidate["channel"].lower() or candidate["id"]
        if per_channel.get(key, 0) >= 2:
            continue
        per_channel[key] = per_channel.get(key, 0) + 1
        picked.append(candidate)
        if len(picked) >= limit:
            break
    return picked


def fetch_rss(subreddit, period, attempts=4):
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
                backoff = 10 * (2 ** i)  # exponential: 10s, 20s, 40s
                time.sleep(backoff)
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
    """Pull VIDEO posts (id, title, v.redd.it URL) out of the RSS entries.

    Two reasons we key on v.redd.it: (1) top feeds are mostly images/text and only Reddit-hosted
    videos are downloadable; (2) we hand yt-dlp the v.redd.it CDN URL directly instead of the
    reddit.com permalink -- the permalink hits Reddit's API, which 'requires authentication' from
    datacenter IPs (GitHub Actions), while the CDN/DASH manifest serves the media without auth."""
    items, seen = [], set()
    for block in rss.split("<entry>")[1:]:
        vm = re.search(r"(https?://v\.redd\.it/[A-Za-z0-9]+)", block)
        if not vm:                                    # keep only Reddit-hosted videos
            continue
        m = re.search(r'href="https://www\.reddit\.com/r/[^"]+/comments/([^/"]+)/[^"]*"', block)
        vid = m.group(1) if m else vm.group(1).rsplit("/", 1)[-1]
        if vid in seen:
            continue
        seen.add(vid)
        tm = re.search(r"<title>(.*?)</title>", block, re.S)
        title = html.unescape((tm.group(1) if tm else "").strip())
        items.append({"id": vid, "title": title, "duration": None, "url": vm.group(1)})
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--genre", default=None, choices=list(GENRE_SUBS),
                    help="Pick subreddits for this genre (fails/cats/babies/dogs)")
    ap.add_argument("--subreddits", default=None, help="Comma-separated subreddits (overrides --genre)")
    ap.add_argument("--angle", default=None,
                    help="For --genre worldcup: 'streamer' pulls from livestream-clip subs "
                         "(FaZe/livestream fails; no iShowSpeed) instead of the football feeds. "
                         "fan/match/mixed/unset all use the football feeds.")
    ap.add_argument("--source", choices=["auto", "reddit", "youtube"], default="auto",
                    help="Candidate source. auto selects YouTube when NO_REDDIT_SOURCES=1.")
    ap.add_argument("--period", default=None, choices=["day", "week", "month", "year", "all"],
                    help="Reddit top period (default: random week/month/year for variety)")
    ap.add_argument("--max", type=int, default=20, help="Max candidates to return")
    ap.add_argument("--history", default="state/used_clips.json",
                    help="JSON of already-used post ids, to avoid repeating clips run to run")
    # accepted for backward-compat with the orchestrator; ignored (we pull Reddit feeds,
    # not free-text search). --search lets the orchestrator pass a topic without crashing.
    ap.add_argument("--query", default=None)
    ap.add_argument("--search", default=None)
    ap.add_argument("--out", default=".tmp/rank_candidates.json")
    args = ap.parse_args()

    load_env()
    source = args.source
    if source == "auto":
        source = "youtube" if os.environ.get("NO_REDDIT_SOURCES") == "1" else "reddit"

    if source == "youtube":
        cands = _youtube_candidates(args.genre or "fails", args.max, args.search or args.query)
        if not cands:
            return
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"source": "youtube", "genre": args.genre or "fails",
                       "candidates": cands}, f, indent=2, ensure_ascii=False)
        emit({"count": len(cands), "source": "youtube", "genre": args.genre or "fails",
              "candidates": cands, "path": args.out})
        return

    if args.subreddits:
        subs = [s.strip() for s in args.subreddits.split(",") if s.strip()]
    elif args.genre == "worldcup" and args.angle == "streamer":
        subs = list(WORLDCUP_STREAMER_SUBS)
    elif args.genre:
        subs = list(GENRE_SUBS[args.genre])
    else:
        subs = list(DEFAULT_SUBS)
    random.shuffle(subs)                                    # vary the source run to run
    period = args.period or random.choice(["week", "month", "year"])   # vary the time window too
    used = load_used(args.history)

    seen, errors, hit_subs = {}, [], []   # seen = id->video post (deduped across feeds)
    for sub in subs:                       # accumulate VIDEOS across feeds until we have plenty
        try:
            posts = parse_posts(fetch_rss(sub, period))
        except Exception as e:
            errors.append(f"{sub}: {str(e)[:80]}")
            continue
        new = 0
        for p in posts:
            if p["id"] not in seen:
                seen[p["id"]] = p
                new += 1
        if new:
            hit_subs.append(sub)
        fresh_now = [p for p in seen.values() if p["id"] not in used]
        if len(fresh_now) >= args.max:     # enough unused videos; stop hitting RSS (rate limits)
            break

    fresh = [p for p in seen.values() if p["id"] not in used]
    chosen_sub = hit_subs[0] if len(hit_subs) == 1 else "mixed"
    if len(fresh) < 5:                      # only if we've genuinely drained the fresh pool, allow repeats
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
