"""Find candidate funny clips for a ranking video from Tenor (Google's GIF platform).

Why Tenor: YouTube and Reddit block downloads from datacenter IPs (GitHub Actions) -- YouTube wants
cookies, Reddit's API/CDN return "auth required" / "403 Blocked". Tenor's media CDN is built for
embedding, so it serves clips to servers without any auth or IP-blocking, and it needs no secret
(a public demo key works; override with TENOR_API_KEY). Clips are short GIF-style loops, usually
silent -- build_ranking_video's SFX layer (whoosh/boom/fahh) supplies the sound.

Usage:
    python tools/find_ranking_clips.py [--genre fails] [--search "funny fails"]
        [--max 20] [--history state/used_clips.json] [--out .tmp/rank_candidates.json]

Prints JSON: {"count","query","candidates":[{"id","title","duration","url"}, ...]}
"""
import argparse
import json
import os
import random
import urllib.parse
import urllib.request

from _common import load_env, emit, fail

# Tenor's well-known public demo key; fine for low volume. Override with TENOR_API_KEY in API.env.
DEMO_KEY = "LIVDSRZULELA"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0"

# Each genre maps to a few search queries; one is picked per run for variety.
GENRE_QUERIES = {
    "fails":  ["funny fails", "epic fail", "fail compilation", "instant regret"],
    "cats":   ["funny cats", "cat fail", "funny kitten"],
    "babies": ["funny babies", "baby fail", "funny kids"],
    "dogs":   ["funny dogs", "dog fail", "funny puppy"],
}
DEFAULT_QUERIES = ["funny fails", "funny animals", "funny cats", "epic fail"]


def load_used(path):
    """Set of Tenor ids already used in past videos (so we never repeat a clip)."""
    try:
        with open(path, encoding="utf-8") as f:
            return set(json.load(f).get("used", []))
    except (OSError, json.JSONDecodeError):
        return set()


def tenor_search(query, key, limit):
    """Return Tenor results (v1 API) as candidate dicts with a direct .mp4 url."""
    q = urllib.parse.quote(query)
    url = (f"https://g.tenor.com/v1/search?q={q}&key={key}&limit={limit}"
           f"&media_filter=minimal&contentfilter=medium&ar_range=all")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    data = json.load(urllib.request.urlopen(req, timeout=30))
    items = []
    for r in data.get("results", []):
        mp4 = None
        for m in (r.get("media") or []):
            if "mp4" in m:
                mp4 = m["mp4"]
                break
        if not mp4 or not mp4.get("url"):
            continue
        items.append({"id": str(r.get("id")), "title": (r.get("content_description") or "").strip(),
                      "duration": mp4.get("duration"), "url": mp4["url"]})
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--genre", default=None, choices=list(GENRE_QUERIES),
                    help="Pick search queries for this genre (fails/cats/babies/dogs)")
    ap.add_argument("--search", default=None, help="Explicit Tenor search query (overrides --genre)")
    ap.add_argument("--limit", type=int, default=40, help="Tenor results to request")
    ap.add_argument("--max", type=int, default=20, help="Max candidates to return")
    ap.add_argument("--history", default="state/used_clips.json",
                    help="JSON of already-used clip ids, to avoid repeating run to run")
    # accepted for backward-compat with the orchestrator; ignored.
    ap.add_argument("--query", default=None)
    ap.add_argument("--out", default=".tmp/rank_candidates.json")
    args = ap.parse_args()

    load_env()
    key = os.environ.get("TENOR_API_KEY") or DEMO_KEY
    if args.search:
        queries = [args.search]
    elif args.genre:
        queries = list(GENRE_QUERIES[args.genre])
    else:
        queries = list(DEFAULT_QUERIES)
    random.shuffle(queries)
    used = load_used(args.history)

    seen, errors, chosen_q = {}, [], None
    for q in queries:                          # one query usually returns plenty; accumulate if thin
        try:
            for it in tenor_search(q, key, args.limit):
                seen.setdefault(it["id"], it)
        except Exception as e:
            errors.append(f"{q}: {str(e)[:80]}")
            continue
        chosen_q = q if chosen_q is None else "mixed"
        if len([i for i in seen.values() if i["id"] not in used]) >= 10:
            break

    fresh = [i for i in seen.values() if i["id"] not in used]
    if len(fresh) < 5:                         # only allow repeats if we've genuinely drained fresh
        fresh = list(seen.values())
    if len(fresh) < 5:
        fail(f"Only {len(fresh)} Tenor candidates -- need >=5.", reasons=errors[:6])
        return

    random.shuffle(fresh)
    cands = fresh[: args.max]
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"query": chosen_q, "candidates": cands}, f, indent=2, ensure_ascii=False)
    emit({"count": len(cands), "query": chosen_q, "candidates": cands, "path": args.out})


if __name__ == "__main__":
    main()
