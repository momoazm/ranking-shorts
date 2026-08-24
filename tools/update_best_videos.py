"""Track the MOST SUCCESSFUL video per platform workflow (YouTube + Instagram)
for this project's accounts (@itsmomoclip YT / @itsmomoclips IG).

Pulls Zernio analytics (same publish path as upload_youtube.py /
upload_instagram.py), picks each platform's most successful video
(views -> engagement_rate -> recency tie-break), and stores it -- with a
metrics-backed explanation of WHY it won -- in `state/best_videos.json`.
rank_autopost.py refreshes it at the end of every real run; standalone works too.
Complements ig_fetch_analytics.py / yt_fetch_analytics.py (which dig deeper into
a single known post/channel but don't rank across all posts).

Account ids resolve in order: $ZERNIO_YOUTUBE_ID / $ZERNIO_INSTAGRAM_ID when set
(the CI secrets), else auto-discovered via GET /v1/accounts using $ZERNIO_API_KEY
-- so local runs work without any id configured.

Usage:
    python tools/update_best_videos.py [--limit 100] [--out state/best_videos.json]

Prints JSON on success; {"error": ...} + exit 1 on failure.
"""
import argparse
import datetime
import json
import os
import re

from _common import REPO_ROOT, load_env, emit, fail

ZERNIO_API = "https://zernio.com/api/v1"
PLATFORMS = ("youtube", "instagram")
HEX24 = re.compile(r"^[0-9a-f]{24}$")

HOOK_PATTERNS = [
    ("specific_number", re.compile(r"\d")),
    ("curiosity_gap", re.compile(r"\b(what|why|how|who|which|secret|nobody|until)\b", re.I)),
    ("big_stakes", re.compile(r"\$?\d[\d,.]*\s*(k|000)|\$1,000,000|\$250", re.I)),
    ("transformation_tease", re.compile(r"\b(until this happened|then this|you won'?t believe|turns? into)\b", re.I)),
    ("conflict_or_challenge", re.compile(r"\b(fight|vs\.?|versus|attack|survive|last to|battle|challenge)\b", re.I)),
    ("shock_reaction", re.compile(r"\b(how did|wtf|insane|crazy|shocking|screams?|no way)\b", re.I)),
]


def _get(api_key, path, params=None):
    import httpx

    r = httpx.get(f"{ZERNIO_API}{path}", params=params or {},
                  headers={"Authorization": f"Bearer {api_key}"}, timeout=60)
    if r.status_code == 402:
        fail("Zernio Analytics add-on required -- enable it in the dashboard.",
             code="analytics_addon_required")
    r.raise_for_status()
    return r.json()


def _as_list(d, *keys):
    if isinstance(d, list):
        return d
    if isinstance(d, dict):
        for key in keys:
            if isinstance(d.get(key), list):
                return d[key]
    return []


def resolve_account_ids(api_key):
    """env var first (when valid), else discover this key's accounts via /accounts."""
    by_platform = {}
    for acc in _as_list(_get(api_key, "/accounts") or {}, "accounts", "data"):
        plat, aid = acc.get("platform"), acc.get("_id") or acc.get("id")
        if plat in PLATFORMS and aid and HEX24.match(str(aid)):
            by_platform[plat] = str(aid)
    out = {}
    for plat, env_name in (("youtube", "ZERNIO_YOUTUBE_ID"),
                           ("instagram", "ZERNIO_INSTAGRAM_ID")):
        val = (os.environ.get(env_name) or "").strip()
        out[plat] = val if HEX24.match(val) else by_platform.get(plat)
    return out


def fetch_posts(api_key, platform, account_id, limit):
    posts = []
    for page in range(0, 10):  # first request must NOT pass page=1 (some accounts return empty)
        params = {"platform": platform, "accountId": account_id, "limit": 100,
                  "sortBy": "date", "order": "desc"}
        if page:
            params["page"] = page
        batch = _as_list(_get(api_key, "/analytics", params), "posts", "data")
        posts.extend(batch)
        if len(batch) < 100:
            break
    return posts[:limit]


def normalize(post):
    plat0 = (post.get("platforms") or [{}])[0]
    a = plat0.get("analytics") or post.get("analytics") or {}
    dur_s = a.get("videoDurationSeconds") or 0
    avg_watch_ms = a.get("igReelsAvgWatchTime") or 0
    content = (post.get("content") or "").strip()
    return {
        "id": post.get("_id"),
        "url": post.get("platformPostUrl") or plat0.get("platformPostUrl"),
        "title": content.split("\n")[0][:120],
        "published_at": post.get("publishedAt"),
        "views": a.get("views", 0) or 0,
        "likes": a.get("likes", 0) or 0,
        "comments": a.get("comments", 0) or 0,
        "shares": a.get("shares", 0) or 0,
        "saves": a.get("saves", 0) or 0,
        "engagement_rate": a.get("engagementRate", 0) or 0,
        "duration_seconds": dur_s,
        "avg_watch_time_ms": avg_watch_ms,
        "retention_ratio": round(avg_watch_ms / 1000.0 / dur_s, 3) if dur_s else None,
    }


def medians_of(rows):
    if not rows:
        return {"views": 0, "engagement_rate": 0}
    def med(vals):
        v = sorted(vals)
        n = len(v)
        return v[n // 2] if n % 2 else round((v[n // 2 - 1] + v[n // 2]) / 2, 2)
    return {"views": med([r["views"] for r in rows]),
            "engagement_rate": med([r["engagement_rate"] for r in rows])}


def explain_why(winner, meds):
    why = []
    if meds["views"]:
        why.append(f"views {winner['views']} = {winner['views'] / meds['views']:.1f}x the "
                   f"account median ({meds['views']})")
    elif winner["views"] > 0:
        why.append(f"top views of all account posts ({winner['views']}; median is 0)")
    if winner["retention_ratio"] is not None:
        why.append(f"average watch time covers ~{winner['retention_ratio'] * 100:.0f}% of the clip "
                   "-- strong retention, the main distribution signal")
    if winner["engagement_rate"] > 0 and winner["engagement_rate"] >= meds["engagement_rate"]:
        why.append(f"engagement rate {winner['engagement_rate']}% vs median "
                   f"{meds['engagement_rate']}%")
    hooks = [n for n, rx in HOOK_PATTERNS if rx.search(winner["title"])]
    if hooks:
        why.append("hook/title pattern(s): " + ", ".join(hooks))
    interactions = winner["likes"] + winner["comments"] + winner["shares"] + winner["saves"]
    if interactions:
        why.append(f"{interactions} interactions ({winner['likes']} likes, {winner['comments']} "
                   f"comments) signal quality to the algorithm")
    return why


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--out", default="state/best_videos.json")
    args = parser.parse_args()

    load_env()
    # This project's own Zernio key first (shared env keeps per-project suffixed copies);
    # fall back to the generic name for self-contained layouts.
    api_key = next((os.environ[k].strip() for k in
                    ("ZERNIO_API_KEY_RANKING_SHORTS", "ZERNIO_API_KEY")
                    if os.environ.get(k, "").strip()), "")
    if not api_key:
        fail("ZERNIO_API_KEY(_RANKING_SHORTS) not set.")

    ids = resolve_account_ids(api_key)
    missing = [p for p in PLATFORMS if not ids.get(p)]
    if missing:
        fail(f"No valid Zernio account id resolvable for: {', '.join(missing)}.")

    store_path = REPO_ROOT / args.out
    try:
        with open(store_path, "r", encoding="utf-8") as f:
            store = json.load(f)
    except (OSError, json.JSONDecodeError):
        store = {}

    result_platforms, errors = {}, []
    for plat in PLATFORMS:
        try:
            rows = [normalize(p) for p in fetch_posts(api_key, plat, ids[plat], args.limit)]
        except Exception as e:
            errors.append({"platform": plat, "error": str(e)})
            continue
        ranked = sorted(rows, key=lambda r: (r["views"], r["engagement_rate"],
                                             r["published_at"] or ""), reverse=True)
        meds = medians_of(rows)
        entry = {
            "account_id": ids[plat],
            "posts_analyzed": len(rows),
            "median_views": meds["views"],
            "most_successful_video": None,
            "runner_up_url": ranked[1]["url"] if len(ranked) > 1 else None,
        }
        if ranked:
            w = ranked[0]
            entry["most_successful_video"] = {
                **{k: w[k] for k in ("id", "url", "title", "published_at", "views",
                                     "likes", "comments", "shares", "saves",
                                     "engagement_rate", "duration_seconds",
                                     "avg_watch_time_ms", "retention_ratio")},
                "why_most_successful": explain_why(w, meds),
            }
        result_platforms[plat] = entry

    if not result_platforms:
        fail("Could not fetch analytics for any platform.", details=errors)

    store.update({
        "_note": "Most successful video per platform workflow (YouTube / Instagram), "
                 "refreshed by tools/update_best_videos.py after each real rank_autopost "
                 "run. 'why_most_successful' is computed from metrics vs account medians.",
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "ranking_rule": "views desc, then engagement_rate desc, then recency",
        "platforms": {**store.get("platforms", {}), **result_platforms},
    })
    if errors:
        store["last_errors"] = errors

    store_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(store_path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2, ensure_ascii=False)
    os.replace(tmp, store_path)

    emit({
        "status": "ok",
        "out": args.out,
        "platforms": {p: {
            "most_successful": (result_platforms[p]["most_successful_video"] or {}).get("url"),
            "views": (result_platforms[p]["most_successful_video"] or {}).get("views"),
        } for p in result_platforms},
        "errors": errors,
    })


if __name__ == "__main__":
    main()
