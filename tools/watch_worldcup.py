"""LIVE World-Cup watcher: reacts to real match events instead of blind 20-min polling.

Moemen's spec (2026-07-06): auto-detect when a game starts and a goal is scored -> post the
goal clip within minutes; capture iShowSpeed's livestream reaction to each goal; at full
time, post a star player's performance recap and a compilation of any multi-goal scorer's
goals from this match.

One long-running job (started by .github/workflows/worldcup_live.yml whenever a match is
live or imminent) that polls ESPN's public scoreboard every ~75s and fires per event:

  GOAL      -> targeted YouTube hunt for THAT goal (scorer + teams, upload-date=today,
               title must contain the scorer) -> build_clip -> post. Retries every poll
               until an upload appears (they typically land 3-15 min after the goal).
               (iShowSpeed reactions are handled by the parallel watch_speed.py watcher.)
  FULL TIME -> (a) star recap: if a STAR_PLAYERS name played, targeted hunt for their match
                   footage, card shows box-score line (goals/assists/shots);
               (b) brace/hat-trick compilation: any scorer with 2+ goals this match gets
                   their goal SOURCES (kept pre-watermark) stitched by build_compilation.py;
               (c) TOD highlights (Moemen 2026-07-11): keep hunting for TOD-by-beIN's
                   (@tod_bybein) highlights upload of THIS match and post a Short from it
                   the moment it lands (they typically upload within the hour; hunt expires
                   after HIGHLIGHT_HUNT_MAX_MIN). TOD-only -- other channels' "highlights"
                   are re-upload risk, and TOD is the user's preferred FIFA source.

State (state/worldcup_watch.json, cached across CI runs like used_clips.json) makes goals
and end-of-game posts idempotent -- a crashed/restarted watcher never double-posts.

Usage:
    python tools/watch_worldcup.py [--no-upload] [--privacy public] [--poll 75]
        [--lead-min 25] [--max-minutes 320] [--max-posts 14] [--no-speed] [--once]

Prints one JSON summary at exit.
"""
import argparse
import json
import re
import shutil
import time
from datetime import date
from pathlib import Path

from _common import REPO_ROOT, load_env, emit
from clip_autopost import run_tool_safe, record_used, build_meta
from worldcup_live import get_scoreboard, get_summary, minutes_to_kickoff, norm_name

TMP = REPO_ROOT / ".tmp" / "wc"
STATE_PATH = REPO_ROOT / "state" / "worldcup_watch.json"
FINAL = ".tmp/final.mp4"

# Who counts as a "popular player" for the end-of-game recap. EDIT freely; matched
# accent-insensitively against the box-score roster of players who actually played.
STAR_PLAYERS = [
    "Lionel Messi", "Cristiano Ronaldo", "Kylian Mbappé", "Neymar", "Jude Bellingham",
    "Vinícius Júnior", "Lamine Yamal", "Pedri", "Erling Haaland", "Mohamed Salah",
    "Harry Kane", "Kevin De Bruyne", "Bukayo Saka", "Phil Foden", "Ousmane Dembélé",
    "Achraf Hakimi", "Son Heung-Min", "Antoine Griezmann", "Rodri", "Florian Wirtz",
    "Jamal Musiala", "Christian Pulisic",
]

GOAL_HUNT_MAX_MIN = 50        # stop hunting a goal's upload after this long
HIGHLIGHT_HUNT_MAX_MIN = 180  # stop hunting TOD's post-match highlights upload after this long


def slug(s):
    return re.sub(r"[^0-9A-Za-z]+", "-", str(s)).strip("-").lower()


def last_name(full):
    parts = (full or "").split()
    return parts[-1] if parts else ""


def load_state():
    try:
        return json.load(open(STATE_PATH, encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(st):
    STATE_PATH.parent.mkdir(exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=1)


class Watcher:
    def __init__(self, args):
        self.args = args
        self.st = load_state()
        today = date.today().isoformat()
        if self.st.get("date") != today:      # daily reset (posts cap + per-goal bookkeeping)
            self.st = {"date": today, "goals": {}, "done_matches": [], "posts": 0, "highlights": {}}
        self.st.setdefault("highlights", {})  # state written before 2026-07-11 lacks the key
        self.actions = []                     # run log for the exit summary
        self.was_live = set()                 # match ids seen in-progress THIS run (vs catch-up)
        self.last_zernio_time = 0.0           # for spacing Zernio publishes (YouTube AND Instagram)
        self.platforms = {p.strip().lower() for p in args.platforms.split(",") if p.strip()}
        self.redo_min = [x.strip() for x in (args.redo_min or "").split(",") if x.strip()]
        # --fresh (catch-up backfill): drop the target match's prior goal-state so its goals are
        # re-hunted + re-posted, and point the finder at a throwaway history so already-"used"
        # source clips are findable again (e.g. re-post to YouTube-only after a 429 dropped them).
        self.hist_arg = []
        if args.fresh:
            self.hist_arg = ["--history", ".tmp/wc/fresh_hist.json"]
            (REPO_ROOT / ".tmp" / "wc").mkdir(parents=True, exist_ok=True)
            (REPO_ROOT / ".tmp" / "wc" / "fresh_hist.json").write_text('{"used": []}', encoding="utf-8")
            if args.match:
                self.st["goals"] = {k: g for k, g in self.st["goals"].items()
                                    if g.get("match_id") != args.match}
                self.st["done_matches"] = [m for m in self.st["done_matches"] if m != args.match]
                self.st.get("highlights", {}).pop(args.match, None)

    # ---- posting ------------------------------------------------------------------
    def can_post(self):
        return self.st["posts"] < self.args.max_posts

    def _zernio_upload(self, tool, tool_args):
        """Publish via a Zernio-backed uploader (upload_youtube.py / upload_instagram.py), PACED
        so bursts don't trip Zernio's shared rate limit (both platforms hit the same POST /posts
        -> HTTP 429 on 2026-07-08's Argentina-Egypt run) + Instagram's per-account action-block.
        The tool ALSO retries 429/5xx on the create call itself (_common.zernio_create_post); this
        adds a create-level retry for the Instagram `status=failed` publish outcome (a fresh post
        = fresh IG container). Returns (data, err)."""
        m = err = None
        for attempt in range(self.args.post_retries + 1):
            wait = self.args.post_spacing - (time.time() - self.last_zernio_time)
            if self.last_zernio_time and wait > 0:
                time.sleep(wait)
            m, err = run_tool_safe(tool, tool_args)
            self.last_zernio_time = time.time()
            if not err:
                return m, None
            if attempt < self.args.post_retries:
                time.sleep(30 * (attempt + 1))
        return m, err

    def post(self, final_rel, card, category, what):
        """host_public -> YouTube + Instagram + email, mirroring clip_autopost's delivery."""
        a = {"what": what, "card": card, "delivery": {}}
        self.actions.append(a)
        if self.args.no_upload:
            a["delivery"] = {"skipped": "no-upload mode"}
            return True
        cand = {"title": card, "category": category}
        _, yt_title, description, ig_caption, tags = build_meta(cand, self.args.handle)
        host, herr = run_tool_safe("host_public.py", ["--video", final_rel])
        url = (host or {}).get("url")
        if herr or not url:
            a["delivery"]["error"] = (herr or "host_public returned no url").splitlines()[0][:160]
            return False
        ok = False
        if "youtube" in self.platforms:
            m, err = self._zernio_upload("upload_youtube.py",
                                         ["--video-url", url, "--title", yt_title,
                                          "--description", description, "--tags", ",".join(tags),
                                          "--privacy", self.args.privacy, "--confirm"])
            a["delivery"]["youtube"] = {"skipped": err.splitlines()[0][:160]} if err else {"url": m.get("url")}
            ok = ok or not err
        if "instagram" in self.platforms:
            m, err = self._zernio_upload("upload_instagram.py",
                                         ["--video-url", url, "--caption", ig_caption, "--confirm"])
            if err:
                ig = {"skipped": err.splitlines()[0][:160]}
                # run_tool_safe returns the full parsed JSON on failure -- keep Instagram's own
                # reason (platform_status) so a future failure is diagnosable without re-running.
                detail = (m or {}).get("platform_status")
                if detail:
                    ig["platform_status"] = detail
                a["delivery"]["instagram"] = ig
            else:
                a["delivery"]["instagram"] = {"id": m.get("post_id") or m.get("media_id")}
            ok = ok or not err
        if "email" in self.platforms:
            run_tool_safe("email_video.py", ["--video", final_rel, "--subject", f"momoclips live: {card}"])
        if ok:
            self.st["posts"] += 1
        return ok

    # ---- per-goal -----------------------------------------------------------------
    def on_new_goal(self, match, goal):
        g = {"seen": time.time(), "clip_posted": False, "clip_expired": False,
             "speed_done": False, "src": None,
             "scorer": goal["scorer"], "minute": goal["minute"], "team": goal["team"],
             "own_goal": goal["own_goal"], "match_id": match["id"]}
        self.st["goals"][goal["key"]] = g
        print(f"::notice::GOAL {goal['scorer']} ({goal['minute']}) {match['short']}")
        # iShowSpeed reactions are now owned entirely by the PARALLEL watch_speed.py watcher
        # (2026-07-09) -- capturing them here too would double-post them. This watcher does only
        # broadcast goal clips + end-of-game recaps.

    def opponent_of(self, match, team_name):
        h, aw = match["home"], match["away"]
        if h and h["name"] == team_name:
            return (aw or {}).get("name") or "?"
        return (h or {}).get("name") or "?"

    def hunt_goal_clip(self, match, key):
        g = self.st["goals"][key]
        if g["clip_posted"] or g["clip_expired"] or not self.can_post():
            return
        if (time.time() - g["seen"]) > GOAL_HUNT_MAX_MIN * 60:
            g["clip_expired"] = True
            self.actions.append({"what": "goal_hunt_expired", "goal": key, "scorer": g["scorer"]})
            return
        opp = self.opponent_of(match, g["team"])
        if g["own_goal"]:
            query = f"own goal {match['home']['name']} vs {match['away']['name']} World Cup 2026"
            require = "own goal"
        else:
            query = f"{g['scorer']} goal {g['team']} vs {opp} World Cup 2026"
            require = last_name(g["scorer"])
        cands_path = f".tmp/wc/cands_{slug(key)}.json"
        # Live matches: today-window (freshest). Catch-up over an already-ended match: the
        # uploads may be from "yesterday" in YouTube's day bucketing -> widen to week; the
        # targeted query + --require keep it on this exact goal.
        window = "today" if match["id"] in self.was_live else "week"
        find, ferr = run_tool_safe("find_worldcup_clips.py",
                                   ["--query", query, "--require", require,
                                    "--window", window, "--categories", "goal",
                                    *self.hist_arg, "--out", cands_path])
        cands = (find or {}).get("candidates", []) if not ferr else []
        if not cands:
            return                                    # nothing uploaded yet; retry next poll
        card = (f"OWN GOAL! {match['short']} ({g['minute']})" if g["own_goal"]
                else f"{g['scorer'].upper()} SCORES vs {opp} ({g['minute']})")
        for c in cands[:3]:
            build, berr = run_tool_safe("build_clip.py",
                                        ["--url", c["url"], "--title", card,
                                         "--handle", self.args.handle,
                                         "--source-handle", c.get("handle", ""), "--out", FINAL])
            record_used(c["id"])
            if berr:
                continue
            # Keep the RAW downloaded source (pre-overlay) for the end-of-game compilation --
            # compiling finished Shorts would double-burn title cards.
            src_keep = None
            for p in (REPO_ROOT / ".tmp" / "clip").glob("src.*"):
                src_keep = TMP / f"goalsrc_{slug(key)}{p.suffix}"
                shutil.copy2(p, src_keep)
                break
            g["src"] = str(src_keep) if src_keep else None
            g["clip_posted"] = True
            self.post(FINAL, card, "goal", f"goal_clip:{g['scorer']}")
            return

    # ---- end of game --------------------------------------------------------------
    def goals_of_match(self, mid):
        return {k: g for k, g in self.st["goals"].items() if g["match_id"] == mid}

    def match_settled(self, mid):
        """All this match's goal hunts finished (posted or expired) -> safe to close out."""
        return all(g["clip_posted"] or g["clip_expired"] for g in self.goals_of_match(mid).values())

    def close_out_match(self, match):
        mid = match["id"]
        final_score = f"{match['home']['name']} {match['home']['score']}-{match['away']['score']} {match['away']['name']}"
        print(f"::notice::FULL TIME {final_score} -- running end-of-game features")

        # (a) star-player recap
        if self.can_post():
            try:
                players = get_summary(mid)
            except Exception as e:
                players = []
                self.actions.append({"what": "summary_failed", "match": mid, "error": str(e)[:160]})
            stars = [p for p in players if p.get("played")
                     and any(norm_name(s) in norm_name(p.get("name")) or norm_name(p.get("name")) in norm_name(s)
                             for s in STAR_PLAYERS)]
            if stars:
                star = max(stars, key=lambda p: (p["goals"], p["assists"], p["shots"]))
                opp = self.opponent_of(match, star["team"])
                if star["goals"] or star["assists"]:
                    line = (f"{star['goals']} GOAL{'S' if star['goals'] != 1 else ''} "
                            f"{star['assists']} ASSIST{'S' if star['assists'] != 1 else ''}")
                else:
                    # No goal contribution -> the story is the RESULT. From the R32 on, a loss
                    # means the star is OUT of the World Cup -- that's the viral hook, not shots.
                    side = "home" if match["home"] and match["home"]["name"] == star["team"] else "away"
                    other = "away" if side == "home" else "home"
                    try:
                        lost = int(match[side]["score"]) < int(match[other]["score"])
                    except (TypeError, ValueError, KeyError):
                        lost = False
                    line = "KNOCKED OUT" if lost else f"{star['shots']} SHOTS"
                card = f"{star['name']} vs {opp} - {line}"
                window = "today" if mid in self.was_live else "week"
                find, ferr = run_tool_safe("find_worldcup_clips.py",
                                           ["--query", f"{star['name']} vs {opp} World Cup 2026",
                                            "--query", f"{star['name']} {star['team']} World Cup 2026",
                                            "--require", last_name(star["name"]),
                                            "--window", window, "--categories", "popular",
                                            "--max-dur", "180", *self.hist_arg,
                                            "--out", ".tmp/wc/star_cands.json"])
                posted = False
                for c in ((find or {}).get("candidates") or [])[:3] if not ferr else []:
                    build, berr = run_tool_safe("build_clip.py",
                                                ["--url", c["url"], "--title", card,
                                                 "--handle", self.args.handle, "--out", FINAL])
                    record_used(c["id"])
                    if not berr:
                        self.post(FINAL, card, "popular", f"star_recap:{star['name']}")
                        posted = True
                        break
                if not posted:
                    # Visible in the run summary -- a star recap that finds no footage must not
                    # vanish silently (bit us on a local dry run 2026-07-07).
                    self.actions.append({"what": "star_recap_no_footage", "star": star["name"],
                                         "card": card, "find_error": (ferr or "")[:120]})

        # (b) multi-goal compilation(s)
        by_scorer = {}
        for g in self.goals_of_match(mid).values():
            if not g["own_goal"]:
                by_scorer.setdefault(g["scorer"], []).append(g)
        for scorer, goals in by_scorer.items():
            srcs = [g["src"] for g in goals if g.get("src") and Path(g["src"]).is_file()]
            if len(srcs) < 2 or not self.can_post():
                continue
            opp = self.opponent_of(match, goals[0]["team"])
            card = f"{scorer.upper()} x{len(srcs)} vs {opp} - ALL GOALS"
            args = []
            for s in srcs:
                args += ["--clip", s]
            build, berr = run_tool_safe("build_compilation.py",
                                        [*args, "--title", card, "--handle", self.args.handle,
                                         "--out", FINAL])
            if berr:
                self.actions.append({"what": "compilation_failed", "scorer": scorer,
                                     "error": berr.splitlines()[0][:160]})
                continue
            self.post(FINAL, card, "goal", f"compilation:{scorer} x{len(srcs)}")

        # (c) register the TOD-highlights hunt (Moemen 2026-07-11): TOD by beIN uploads each
        # match's official highlights some time after FT -- keep hunting for it every poll
        # (hunt_tod_highlights) and post a Short from it the moment it lands. Registered with
        # everything the hunt needs so it survives job restarts via state alone.
        self.st["highlights"][mid] = {
            "seen": time.time(), "posted": False, "expired": False,
            "home": (match["home"] or {}).get("name") or "?",
            "away": (match["away"] or {}).get("name") or "?",
            "score": f"{(match['home'] or {}).get('score', '?')}-{(match['away'] or {}).get('score', '?')}",
        }

        # The match is fully closed out -> its kept pre-watermark goal sources have served the
        # compilation and are finally used; delete them so .tmp/wc doesn't accumulate (2026-07-09).
        for g in self.goals_of_match(mid).values():
            if g.get("src"):
                try:
                    Path(g["src"]).unlink()
                except OSError:
                    pass

        self.st["done_matches"].append(mid)

    # ---- TOD post-match highlights ---------------------------------------------------
    def hl_pending(self):
        return any(not (h["posted"] or h["expired"]) for h in self.st["highlights"].values())

    def hunt_tod_highlights(self):
        """Post a Short from TOD-by-beIN's official highlights upload of each finished match.
        Runs every poll until the upload appears or the hunt expires; TOD-ONLY (is_tod flag)
        because generic 'highlights' uploads are exactly the re-upload pool we screen out."""
        for mid, hl in self.st["highlights"].items():
            if hl["posted"] or hl["expired"] or not self.can_post():
                continue
            if (time.time() - hl["seen"]) > HIGHLIGHT_HUNT_MAX_MIN * 60:
                hl["expired"] = True
                self.actions.append({"what": "tod_highlights_expired", "match": mid,
                                     "card": f"{hl['home']} {hl['score']} {hl['away']}"})
                continue
            # A hunt resumed by a later run (this match no longer in was_live) may be chasing
            # an upload from YouTube's "yesterday" bucket -> widen the window like goal hunts.
            window = "today" if mid in self.was_live else "week"
            find, ferr = run_tool_safe(
                "find_worldcup_clips.py",
                ["--query", f"{hl['home']} vs {hl['away']} highlights World Cup 2026",
                 "--query", f"TOD highlights {hl['home']} {hl['away']} World Cup 2026",
                 "--require", "highlight",     # TOD titles its uploads "Highlights | A n-n B | ..."
                 "--window", window, "--categories", "goal",
                 "--max-dur", "1200",          # full TOD highlight reels run ~8-15 min
                 *self.hist_arg, "--out", f".tmp/wc/hl_{slug(mid)}.json"])
            cands = [c for c in (find or {}).get("candidates", []) if c.get("is_tod")] if not ferr else []
            if not cands:
                continue                       # TOD hasn't uploaded yet; retry next poll
            card = f"{hl['home']} {hl['score']} {hl['away']} - HIGHLIGHTS"
            for c in cands[:2]:
                # build_clip takes the FIRST <58s of the source -- TOD reels front-load the
                # early action -- and its --source-handle gate crops TOD's bottom brand bar.
                build, berr = run_tool_safe("build_clip.py",
                                            ["--url", c["url"], "--title", card,
                                             "--handle", self.args.handle,
                                             "--source-handle", c.get("handle", ""),
                                             "--out", FINAL])
                record_used(c["id"])
                if berr:
                    continue
                hl["posted"] = True
                self.post(FINAL, card, "goal", f"tod_highlights:{mid}")
                break

    # ---- main loop ----------------------------------------------------------------
    def run(self):
        deadline = time.time() + self.args.max_minutes * 60
        loops = 0
        while time.time() < deadline:
            loops += 1
            try:
                matches = get_scoreboard(self.args.date)
            except Exception as e:
                self.actions.append({"what": "scoreboard_failed", "error": str(e)[:160]})
                time.sleep(self.args.poll)
                continue
            if self.args.match:               # catch-up/targeted mode: only this event
                matches = [m for m in matches if m["id"] == self.args.match]

            live = [m for m in matches if m["state"] == "in"]
            self.was_live.update(m["id"] for m in live)
            soon = [m for m in matches if m["state"] == "pre"
                    and (minutes_to_kickoff(m) or 1e9) <= self.args.lead_min]
            ended = [m for m in matches if m["state"] == "post"
                     and m["id"] not in self.st["done_matches"]]

            for m in live + ended:
                for goal in m["goals"]:
                    # --redo-min (backfill): process ONLY these goal minutes for the target match,
                    # so re-posting the 4 that a 429 dropped doesn't duplicate the ones that landed.
                    if self.redo_min and any(r in (goal.get("minute") or "") for r in self.redo_min) is False:
                        continue
                    if goal["key"] not in self.st["goals"]:
                        self.on_new_goal(m, goal)
                for key in list(self.goals_of_match(m["id"])):
                    self.hunt_goal_clip(m, key)
            for m in ended:
                if self.match_settled(m["id"]):
                    self.close_out_match(m)
            self.hunt_tod_highlights()

            save_state(self.st)
            hunting = any(not (g["clip_posted"] or g["clip_expired"])
                          for g in self.st["goals"].values())
            if not live and not soon and not ended and not hunting and not self.hl_pending():
                break                                  # nothing to watch -> end the job
            if self.args.once:
                break
            time.sleep(self.args.poll)

        save_state(self.st)
        emit({"status": "done", "loops": loops, "posts_today": self.st["posts"],
              "goals_tracked": len(self.st["goals"]),
              "highlights": {m: ("posted" if h["posted"] else "expired" if h["expired"] else "pending")
                             for m, h in self.st["highlights"].items()},
              "done_matches": self.st["done_matches"], "actions": self.actions})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-upload", action="store_true", help="Build everything, post nothing")
    ap.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"])
    ap.add_argument("--handle", default="@itsmomoclips")
    ap.add_argument("--poll", type=float, default=75.0, help="Seconds between scoreboard polls")
    ap.add_argument("--lead-min", type=float, default=25.0)
    ap.add_argument("--max-minutes", type=float, default=320.0, help="Hard job-length cap")
    ap.add_argument("--max-posts", type=int, default=14, help="Daily cap across ALL live formats")
    ap.add_argument("--no-speed", action="store_true",
                    help="Deprecated no-op (Speed capture moved to watch_speed.py); kept so the "
                         "existing workflow_dispatch input keeps working")
    ap.add_argument("--post-spacing", type=float, default=45.0,
                    help="Min seconds between ANY two Zernio publishes (YouTube+Instagram share "
                         "one rate limit -> burst 429s)")
    ap.add_argument("--post-retries", type=int, default=2,
                    help="Extra publish attempts per platform after the first (30s->60s backoff)")
    ap.add_argument("--once", action="store_true", help="Single poll cycle (testing)")
    ap.add_argument("--date", default=None, help="YYYYMMDD scoreboard date (catch-up on a past day)")
    ap.add_argument("--match", default=None, help="Only process this ESPN event id (targeted catch-up)")
    ap.add_argument("--platforms", default="youtube,instagram,email",
                    help="Where to post (e.g. 'youtube' to backfill ONE platform after a partial run)")
    ap.add_argument("--fresh", action="store_true",
                    help="Re-hunt + re-post the --match's goals, ignoring prior used/posted state "
                         "(backfill a platform that a 429 dropped). Pair with --platforms + --match.")
    ap.add_argument("--redo-min", default=None,
                    help="Backfill only these goal minutes for --match (e.g. '79,83,90'); the "
                         "goals that already landed are left alone. Full-time recap still runs.")
    args = ap.parse_args()

    load_env()
    TMP.mkdir(parents=True, exist_ok=True)
    Watcher(args).run()


if __name__ == "__main__":
    main()
