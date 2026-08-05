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
import datetime
import json
import os
import random
import re
import time
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

# After the 2026 tournament, the football account must keep sourcing fresh moments. These are a
# fallback only: targeted live-goal searches stay World-Cup-specific, and the original World Cup
# queries still win whenever they return candidates. Keeping this in the same picker means the
# workflow does not silently become a no-op just because the tournament window has closed.
GENERAL_QUERIES = {
    "goal": [
        "football goal today",
        "soccer goal today",
        "football last minute goal",
        "football insane goal",
    ],
    "streamer": [
        "football fan reaction today",
        "football streamer reaction today",
        "soccer fan reaction viral",
    ],
    "popular": [
        "football viral moment today",
        "football celebration today",
        "football skill today",
        "soccer funny moment today",
    ],
}

# Keep non-association-football sports out of the shared source pool before
# any downstream workflow sees them.  The final semantic gate is stricter,
# but this early block also protects the ranking workflow's World-Cup rescue
# path, which consumes this finder directly.
_NON_SOCCER_SOURCE = re.compile(
    r"\b(?:nfl|nba|mlb|nhl|ncaa|american\s+football|college\s+football|super\s+bowl|"
    r"touchdown|quarterback|running\s+back|wide\s+receiver|linebacker|falcons|patriots|"
    r"chiefs|cowboys|ravens|eagles|packers|49ers|bears|lions|vikings|steelers|jets|"
    r"bills|dolphins|broncos|texans|commanders|saints|buccaneers|raiders|chargers|"
    r"titans|colts|jaguars|panthers|bengals|browns|cardinals|seahawks|giants)\b",
    re.IGNORECASE,
)


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
            "playlistend": n, "socket_timeout": 15, "extractor_retries": 0}
    cookie = os.environ.get("YT_COOKIES_FILE") or str(REPO_ROOT / "cookies.txt")
    if os.path.isfile(cookie):
        opts["cookiefile"] = cookie
    proxy = os.environ.get("YTDLP_PROXY")   # datacenter-IP runners: route via WARP/residential proxy
    if proxy:
        opts["proxy"] = proxy
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return info.get("entries") or []


def parse_duration(value):
    """Normalize yt-dlp's numeric or MM:SS duration fields."""
    if isinstance(value, (int, float)) and value >= 0:
        return float(value)
    if isinstance(value, str) and value.strip():
        bits = value.strip().split(":")
        try:
            total = 0.0
            for bit in bits:
                total = total * 60 + float(bit)
            return total
        except ValueError:
            return None
    return None


def enrich_entry(entry):
    """Fetch full metadata for a flat search result when the search page omitted it.

    YouTube's current results extractor frequently returns title/id but no duration, channel, or
    upload timestamp. The previous picker interpreted that as invalid and discarded every result.
    This probe is intentionally metadata-only (no download) and returns the original entry on a
    transient bot-check failure; the caller can still use a clearly short-looking search result.
    """
    vid = entry.get("id")
    if not vid:
        return entry
    from yt_dlp import YoutubeDL
    opts = {"quiet": True, "no_warnings": True, "noprogress": True, "skip_download": True,
            "socket_timeout": 15, "extractor_retries": 0}
    cookie = os.environ.get("YT_COOKIES_FILE") or str(REPO_ROOT / "cookies.txt")
    if os.path.isfile(cookie):
        opts["cookiefile"] = cookie
    proxy = os.environ.get("YTDLP_PROXY")
    if proxy:
        opts["proxy"] = proxy
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(entry.get("url") or f"https://www.youtube.com/watch?v={vid}",
                                    download=False)
        merged = dict(entry)
        for key in ("title", "duration", "duration_string", "channel", "uploader",
                    "uploader_id", "upload_date", "timestamp"):
            if info.get(key) not in (None, ""):
                merged[key] = info[key]
        return merged
    except Exception:
        return entry


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
    ap.add_argument("--world-cup-only", action="store_true",
                    help="Disable the post-tournament general-football fallback (for targeted live hunts).")
    ap.add_argument("--max-search-seconds", type=float,
                    default=float(os.environ.get("FOOTBALL_PICKER_MAX_SECONDS", "240")),
                    help="Wall-clock budget for metadata searches; return the best candidates found "
                         "before the budget instead of letting a blocked query consume the workflow.")
    ap.add_argument("--history", default="state/used_clips.json",
                    help="JSON of already-posted clip ids, to avoid reposting")
    ap.add_argument("--out", default=".tmp/clip_candidates.json")
    args = ap.parse_args()

    load_env()
    used = load_used(args.history)
    raw_wanted = [c.strip().lower() for c in args.categories.split(",") if c.strip()]
    # `speed` was an old category name from the live-stream experiment. It has no picker queries
    # and iShowSpeed is intentionally blocked; dropping it here prevents an obsolete workflow
    # default from starving the football account after the tournament. Keep the real football
    # categories in the caller's order so a targeted live hunt remains predictable.
    wanted = [c for c in raw_wanted if c in QUERIES or c in GENERAL_QUERIES]
    if not wanted:
        wanted = ["goal", "popular", "streamer"]
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
    search_started = time.monotonic()
    deadline = search_started + max(30.0, args.max_search_seconds)
    deadline_hit = False
    probe_budget = max(24, args.max * 6)
    unknown_duration = 0
    # The general plan is only a fallback. Do not apply it to targeted goal hunts: those must
    # stay scoped to the scorer/team event supplied by the live watcher.
    plans = [plan]
    if not args.query and not args.world_cup_only:
        general_plan = [(q, "football") for cat in wanted for q in GENERAL_QUERIES.get(cat, [])]
        random.shuffle(general_plan)
        plans.append(general_plan)

    for current_plan in plans:
        for q, cat in current_plan:
            if time.monotonic() >= deadline:
                deadline_hit = True
                errors.append("football picker search deadline reached")
                break
            try:
                entries = search_recent(q, args.per_query, sp)
            except Exception as e:
                errors.append(f"{q}: {str(e)[:80]}")
                continue
            for raw_en in entries:
                en = raw_en
                vid = en.get("id")
                duration = parse_duration(en.get("duration") or en.get("duration_string"))
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
                # Flat search results often omit metadata. Probe before rejecting them instead of
                # turning a healthy search into count=0. The budget prevents a bot-walled query
                # from making a 20-minute workflow probe every result on every poll.
                if (duration is None or not (en.get("channel") or en.get("uploader") or
                                              en.get("timestamp") or en.get("upload_date"))) and probe_budget > 0:
                    en = enrich_entry(en)
                    probe_budget -= 1
                    duration = parse_duration(en.get("duration") or en.get("duration_string"))
                    title = (en.get("title") or title).strip()
                if duration is not None and not (args.min_dur <= duration <= args.max_dur):
                    continue
                # If YouTube still withholds duration after the metadata probe, retain the result
                # rather than dropping the whole pool. build_clip enforces its own <60s output
                # cap; the candidate is marked unknown for observability. This is especially
                # important for Shorts results, whose flat extractor omits duration most often.
                duration_unknown = duration is None
                if duration_unknown:
                    unknown_duration += 1
                # Channel screen: an ENGLISH title can still front HINDI commentary from an Indian
                # re-upload channel (user rule 2026-07-08). The title can't reveal that; the channel
                # can. Hard-block bad channels for every category.
                channel = (en.get("channel") or en.get("uploader") or "").strip()
                handle = (en.get("uploader_id") or "").strip()
                if _NON_SOCCER_SOURCE.search(f"{title} {channel} {handle}"):
                    continue
                if not channel_ok(f"{channel} {handle}"):
                    continue
                seen.add(vid)
                stamp = en.get("timestamp")
                if not isinstance(stamp, (int, float)):
                    try:
                        raw_date = str(en.get("upload_date", "") or "")
                        if len(raw_date) == 8 and raw_date.isdigit():
                            stamp = datetime.datetime.strptime(raw_date, "%Y%m%d").replace(
                                tzinfo=datetime.timezone.utc).timestamp()
                        else:
                            stamp = float(stamp or 0)
                    except (TypeError, ValueError):
                        stamp = 0
                ordered.append({"id": vid, "title": title, "duration": duration,
                                "duration_unknown": duration_unknown,
                                "url": f"https://www.youtube.com/watch?v={vid}", "category": cat,
                                "channel": channel, "handle": handle,
                                "timestamp": stamp or 0,
                                "trusted": channel_trusted(channel, handle),
                                "is_tod": is_tod(channel, handle)})
            if len(ordered) >= args.max * 3:     # plenty gathered -> stop hitting the API
                break
        if deadline_hit:
            break
        if len(ordered) >= args.max * 3:
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
    # Sort by content tier first, then true upload timestamp when available. This fixes the old
    # shuffled-query behavior where a stale result from the first random query beat a clip posted
    # minutes ago in a later query.
    ordered.sort(key=lambda c: (tier.get(c.get("category"), 2), -(c.get("timestamp") or 0)))
    cands = ordered[: args.max]
    if not cands:
        # Not an error the run should crash on -- "nothing new happened" is a valid outcome.
        emit({"source": "youtube", "count": 0, "candidates": [], "path": args.out,
              "note": "no fresh unused clips", "errors": errors[:6],
              "unknown_duration_probes": unknown_duration,
              "search_elapsed_sec": round(max(0.0, time.monotonic() - search_started), 1),
              "search_deadline_hit": deadline_hit})
        return

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"source": "youtube", "candidates": cands}, f, indent=2, ensure_ascii=False)
    emit({"source": "youtube", "count": len(cands), "candidates": cands, "path": args.out,
          "unknown_duration_probes": unknown_duration,
          "search_deadline_hit": deadline_hit})


if __name__ == "__main__":
    main()
