"""Live World-Cup match data from ESPN's public scoreboard JSON (no key, no scraping).

This is the EVENT SOURCE for the live watcher (watch_worldcup.py): instead of blindly
polling YouTube every 20 min, the watcher polls this feed every ~75s during matches and
reacts to real events -- kickoff, each goal (scorer + minute), final whistle, box-score
stats. Endpoint probed 2026-07-06: goals appear in competitions[].details with
athletesInvolved (scorer displayName), clock, team id, penalty/own-goal flags.

STDLIB ONLY (urllib) on purpose: the workflow's cheap "gate" step runs this before any
pip/ffmpeg/WARP setup, so a no-match day costs ~30s of CI, not 5 min.

Usage:
    python tools/worldcup_live.py --mode scoreboard [--date YYYYMMDD]
    python tools/worldcup_live.py --mode summary --event 760505
    python tools/worldcup_live.py --mode gate [--lead-min 25] [--chain]

Prints one JSON object (matches / player stats / {"watch": bool, ...}).

--chain (the workflow's scheduled/relayed path) turns the gate into a RELAY PLANNER:
GitHub silently drops most high-frequency cron ticks on this account (*/15 delivered ~3
runs/day twice in a row -> EGY-ARG and MAR-FRA were missed), so instead of hoping a tick
lands inside a kickoff window, ANY delivered run carries coverage forward itself:
  - match live/imminent            -> {"action": "watch"}   (run the watcher now)
  - kickoff <= --nap-min away      -> sleep right here, then {"action": "watch"}
  - kickoff later today            -> sleep --hop-min, then {"action": "relay"}
                                      (the workflow re-dispatches itself; dispatch events
                                      are delivered reliably, unlike cron)
  - nothing left today             -> {"action": "exit"}
"""
import argparse
import json
import time
import unicodedata
import urllib.request
from datetime import datetime, timezone

from _common import emit, fail

BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def fetch_json(url, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.load(r)
        except Exception as e:          # network blips are routine on CI; retry with backoff
            last = e
            time.sleep(3 * (i + 1))
    raise RuntimeError(f"ESPN fetch failed after {tries} tries: {last}")


def norm_name(s):
    """Accent-insensitive lowercase for name matching (Vinícius == Vinicius)."""
    return "".join(c for c in unicodedata.normalize("NFKD", s or "")
                   if not unicodedata.combining(c)).lower().strip()


def parse_match(event):
    comp = event["competitions"][0]
    status = comp.get("status", {})
    stype = status.get("type", {})
    teams = {}
    home = away = None
    for c in comp.get("competitors", []):
        t = {"id": c.get("team", {}).get("id"),
             "name": c.get("team", {}).get("displayName"),
             "abbrev": c.get("team", {}).get("abbreviation"),
             "score": c.get("score"),
             "homeAway": c.get("homeAway")}
        teams[t["id"]] = t
        if t["homeAway"] == "home":
            home = t
        else:
            away = t
    goals = []
    for det in comp.get("details", []):
        if not det.get("scoringPlay") or det.get("shootout"):
            continue
        ath = (det.get("athletesInvolved") or [{}])[0]
        clock = det.get("clock", {})
        team_id = det.get("team", {}).get("id")
        # Stable per-goal key: match + clock-second + scorer id. Used for cross-run dedup.
        key = f"{event['id']}:{int(clock.get('value') or 0)}:{ath.get('id') or 'x'}"
        goals.append({
            "key": key,
            "scorer": ath.get("displayName") or "Unknown",
            "scorer_short": ath.get("shortName") or "",
            "minute": clock.get("displayValue") or "",
            "team": (teams.get(team_id) or {}).get("name"),
            "penalty": bool(det.get("penaltyKick")),
            "own_goal": bool(det.get("ownGoal")),
        })
    return {
        "id": event["id"],
        "name": event.get("name"),
        "short": event.get("shortName"),
        "kickoff": comp.get("date") or event.get("date"),
        "state": stype.get("state"),                     # pre | in | post
        "status": stype.get("name"),                     # STATUS_SCHEDULED / IN / FULL_TIME...
        "completed": bool(stype.get("completed")),
        "clock": status.get("displayClock"),
        "home": home, "away": away,
        "goals": goals,
    }


def get_scoreboard(date=None):
    url = f"{BASE}/scoreboard" + (f"?dates={date}" if date else "")
    data = fetch_json(url)
    return [parse_match(e) for e in data.get("events", [])]


def minutes_to_kickoff(match, now=None):
    now = now or datetime.now(timezone.utc)
    try:
        ko = datetime.strptime(match["kickoff"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None
    return (ko - now).total_seconds() / 60.0


# Box-score stat names we surface for the star-player recap (ESPN rosters[].roster[].stats).
_KEY_STATS = {"goals": "totalGoals", "assists": "goalAssists", "shots": "totalShots",
              "shots_on_target": "shotsOnTarget", "saves": "saves"}


def get_summary(event_id):
    data = fetch_json(f"{BASE}/summary?event={event_id}")
    players = []
    for side in data.get("rosters", []):
        team = side.get("team", {}).get("displayName")
        for p in side.get("roster", []):
            ath = p.get("athlete", {})
            stats = {s.get("name"): s.get("value") for s in (p.get("stats") or [])}
            row = {"name": ath.get("displayName"), "team": team,
                   "position": (p.get("position") or {}).get("abbreviation"),
                   "starter": bool(p.get("starter")),
                   "played": bool(p.get("starter")) or bool(p.get("subbedIn"))}
            for label, espn in _KEY_STATS.items():
                v = stats.get(espn)
                row[label] = int(v) if isinstance(v, (int, float)) else 0
            players.append(row)
    return players


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="scoreboard", choices=["scoreboard", "summary", "gate"])
    ap.add_argument("--date", default=None, help="YYYYMMDD (scoreboard; default: today UTC)")
    ap.add_argument("--event", default=None, help="ESPN event id (summary mode)")
    ap.add_argument("--lead-min", type=float, default=25.0,
                    help="gate: watch if a match is live or kicks off within this many minutes")
    ap.add_argument("--chain", action="store_true",
                    help="gate: nap-or-relay toward the next kickoff instead of just answering")
    ap.add_argument("--nap-min", type=float, default=30.0,
                    help="chain: kickoff at most this many min past the lead window -> sleep "
                         "here and watch in THIS run (keeps the job under the 6h cap)")
    ap.add_argument("--hop-min", type=float, default=50.0,
                    help="chain: sleep this long before relaying (short hops release the "
                         "concurrency slot so manual dispatches never queue for hours)")
    args = ap.parse_args()

    try:
        if args.mode == "summary":
            if not args.event:
                fail("--event required in summary mode")
                return
            emit({"event": args.event, "players": get_summary(args.event)})
            return

        matches = get_scoreboard(args.date)
        if args.mode == "gate":
            live = [m for m in matches if m["state"] == "in"]
            soon = [m for m in matches if m["state"] == "pre"
                    and (minutes_to_kickoff(m) is not None)
                    and minutes_to_kickoff(m) <= args.lead_min]
            # Earliest FUTURE kickoff beyond the lead window -> how long a chained run
            # must carry coverage forward before the watcher is worth starting.
            upcoming = sorted((minutes_to_kickoff(m), m["short"]) for m in matches
                              if m["state"] == "pre" and minutes_to_kickoff(m) is not None
                              and minutes_to_kickoff(m) > args.lead_min)
            next_wait_min = round(upcoming[0][0] - args.lead_min, 1) if upcoming else None
            # SAFETY NET: a match that ended recently (kickoff < ~5h ago). If the chain died
            # mid-day (Actions outage, dropped seed), the ended match never opens a live/soon
            # gate and its goals+recap are lost -- that's exactly how the 07-09 22:48 tick
            # walked past the already-finished MAR-FRA. A catch-up watch is a cheap no-op when
            # state says everything already posted. Deliberately NOT counted in `watch`: the
            # relay-forward step keys off watch/next_wait_min, and counting recent_post there
            # would relay in a loop until the window expired.
            recent_post = [m["short"] for m in matches if m["state"] == "post"
                           and (minutes_to_kickoff(m) or -1e9) > -300]
            out = {"watch": bool(live or soon),
                   "live": [m["short"] for m in live],
                   "soon": [m["short"] for m in soon],
                   "recent_post": recent_post,
                   "next_wait_min": next_wait_min,
                   "next_kickoff": upcoming[0][1] if upcoming else None,
                   "today": [f"{m['short']} [{m['state']}]" for m in matches]}
            if args.chain:
                if out["watch"] or recent_post:
                    out["action"] = "watch"
                elif next_wait_min is None:
                    out["action"] = "exit"
                elif next_wait_min <= args.nap_min:
                    time.sleep(next_wait_min * 60 + 30)   # +30s so the re-check lands inside lead
                    out["action"] = "watch"
                else:
                    time.sleep(args.hop_min * 60)
                    out["action"] = "relay"
            emit(out)
            return
        emit({"count": len(matches), "matches": matches})
    except Exception as e:
        fail(str(e)[:300])


if __name__ == "__main__":
    main()
