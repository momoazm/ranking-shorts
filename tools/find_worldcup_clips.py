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
Priority (user 2026-07-08, iShowSpeed removed 2026-07-12): the GAME itself first, then other
events -- the finder emits candidates in that tier order, and the orchestrator posts the first
that builds.
  goal      -- (tier 1) Messi/Ronaldo/big-nation goals; TOD-by-beIN preferred (copyright risk accepted)
  streamer  -- (tier 2) other creators reacting to the World Cup (NOT iShowSpeed -- see channel_ok)
  popular   -- (tier 2) viral / best-moment clips + trending OFF-pitch moments (celebrations,
               fan scenes, drama/controversy) -- "the trending stuff other than the game itself"

`speed` (iShowSpeed) is REMOVED (user 2026-07-12, reverses the 2026-07-08 un-block): no query
searches for it, and channel_ok() screens out his handle/name from every other category too.

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

from _common import REPO_ROOT, load_env, emit, fail, title_ok, channel_ok, channel_trusted, is_tod

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
        # TOD by beIN (@tod_bybein) is the preferred FIFA-highlights source (user 2026-07-08).
        "TOD beIN World Cup 2026 goal",
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
        "streamer reacts World Cup 2026 goal",
        "fan reaction World Cup 2026 goal",
    ],
    "popular": [
        # The match PLUS the most-trending off-pitch moments (user 2026-07-08): celebrations,
        # fan scenes, drama/controversy, rivalries, and viral non-goal moments -- "the trending
        # stuff other than the game itself".
        "World Cup 2026 viral moment",
        "World Cup 2026 best moment today",
        "World Cup 2026 celebration",
        "World Cup 2026 fans go crazy",
        "World Cup 2026 red card controversy",
        "World Cup 2026 trending moment today",
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
    ap.add_argument("--query", action="append", default=None,
                    help="TARGETED mode (repeatable): search exactly these queries instead of the "
                         "category presets -- used by watch_worldcup.py to hunt one specific goal "
                         "('<scorer> goal <home> vs <away>') the moment the live feed reports it.")
    ap.add_argument("--require", default=None,
                    help="Targeted mode: comma list of words; a candidate title must contain ALL "
                         "of them (case/accent-insensitive), e.g. the scorer's last name + 'goal'. "
                         "Keeps a targeted search from drifting to unrelated fresh uploads.")
    ap.add_argument("--window", default="today", choices=["today", "week"],
                    help="Upload-date window: 'today' (freshest, default) or 'week' (wider supply).")
    ap.add_argument("--no-trusted-pref", action="store_true",
                    help="Don't prefer official/major broadcasters (Indian-channel block still applies).")
    ap.add_argument("--history", default="state/used_clips.json",
                    help="JSON of already-posted clip ids, to avoid reposting")
    ap.add_argument("--out", default=".tmp/clip_candidates.json")
    args = ap.parse_args()

    load_env()
    used = load_used(args.history)
    wanted = [c.strip() for c in args.categories.split(",") if c.strip()]
    sp = SP_TODAY if args.window == "today" else SP_WEEK

    if args.query:
        # Targeted mode: the caller knows exactly what happened (live-feed goal event) and wants
        # the freshest upload of THAT moment. Tag results with the first wanted category.
        plan = [(q, wanted[0] if wanted else "goal") for q in args.query]
    else:
        # Build a flat, shuffled (query, category) list so no single category monopolises supply
        # and the same query doesn't always lead. Categories stay balanced across runs.
        plan = [(q, cat) for cat in wanted for q in QUERIES.get(cat, [])]
        random.shuffle(plan)

    def _fold(s):
        import unicodedata
        return "".join(c for c in unicodedata.normalize("NFKD", s)
                       if not unicodedata.combining(c)).lower()
    require = [_fold(w.strip()) for w in (args.require or "").split(",") if w.strip()]

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
            # English-audience screen: drop non-Latin-script titles and news/analysis/talk
            # markers (a Hindi Zee News studio segment got posted on 2026-07-05 -- its title
            # carried English keywords, so keyword search alone can't be trusted).
            if not title_ok(title):
                continue
            # Targeted mode: every required word must appear (accent-insensitive) so a search
            # for "Bellingham goal England vs Mexico" can't return some other fresh upload.
            if require and any(w not in _fold(title) for w in require):
                continue
            # Require a KNOWN, short duration: unknown usually means a live stream, and a long
            # VOD would download the whole file. Both must be excluded before the build step.
            if not isinstance(dur, (int, float)) or not (args.min_dur <= dur <= args.max_dur):
                continue
            # Channel screen: an ENGLISH title can still front HINDI commentary from an Indian
            # re-upload channel (user rule 2026-07-08). The title can't reveal that; the channel
            # can. Hard-block bad channels for every category.
            channel = (en.get("channel") or en.get("uploader") or "").strip()
            handle = (en.get("uploader_id") or "").strip()
            if not channel_ok(f"{channel} {handle}"):
                continue
            seen.add(vid)
            ordered.append({"id": vid, "title": title, "duration": float(dur),
                            "url": f"https://www.youtube.com/watch?v={vid}", "category": cat,
                            "channel": channel, "handle": handle,
                            "trusted": channel_trusted(channel, handle),
                            "is_tod": is_tod(channel, handle)})
        if len(ordered) >= args.max * 3:     # plenty gathered -> stop hitting the API
            break

    # PRIORITY TIERS (user 2026-07-08, iShowSpeed tier removed 2026-07-12): the GAME itself
    # first, then other events (fan/streamer/popular). Within the goal tier, prefer
    # official/major broadcasters (TOD/beIN, FIFA, FOX, CBS, ESPN...) for clean commentary --
    # if any trusted goal was found, drop the untrusted goals (Hindi/re-upload risk); events
    # aren't broadcaster content, so the trusted screen only gates goals and they stay as
    # lower-tier fallback.
    trusted_goals = [c for c in ordered if c.get("category") == "goal" and c.get("trusted")]
    if trusted_goals and not args.no_trusted_pref:
        ordered = [c for c in ordered if c.get("category") != "goal" or c.get("trusted")]
    tier = {"goal": 0}
    # Stable sort keeps each query's newest-first (freshness) order WITHIN a tier.
    ordered.sort(key=lambda c: tier.get(c.get("category"), 2))
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
