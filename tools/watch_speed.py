"""PARALLEL iShowSpeed livestream watcher -> auto-posts his World-Cup reactions to Instagram.

Moemen's spec (2026-07-09): continuously check if iShowSpeed is live on YouTube AND streaming
a World-Cup match (e.g. the next Morocco vs France). While he is, capture a clip of him at every
big moment -- a goal, a penalty, a celebration, a chant, or a TikTok/collab with another creator
-- and post it straight to the football Instagram account. Runs IN PARALLEL with the broadcast
goal-clip watcher (watch_worldcup.py), which now owns NO Speed capture (this tool owns all of it,
so his reactions are never double-posted).

The honest detection problem: no sports feed reports "he started a chant" or "he's filming a
TikTok". Only two things can. So this watcher fuses two triggers on his OWN recorded stream:
  1. MATCH EVENTS (ESPN scoreboard) -- a fresh goal tells us a big moment just happened, so the
     current chunk almost certainly holds his reaction; used to bias the title ("SPEED REACTS TO
     <SCORER> GOAL").
  2. AUDIO-ENERGY PEAKS (top_peaks) -- his screams, chants, celebrations and loud collabs all
     spike the audio well above the stream's own baseline; that peak IS the clippable moment,
     whatever its label. Calm stretches produce no peak, so nothing gets posted.
Each candidate window is then LABELLED by a Gemini vision pass over a few frames: it writes a
punchy title and filters out false positives (ads, loading screens, calm talking). If vision is
unavailable we degrade safely -- post a goal-driven peak with a generic title, but DROP a pure
audio peak (never risk posting a boring moment unlabelled).

State (state/speed_watch.json, cached across CI runs) keeps the daily post cap and reacted-goal
bookkeeping idempotent so a restarted watcher never re-posts.

Usage:
    python tools/watch_speed.py [--no-upload] [--platforms instagram] [--once]
        [--poll 60] [--chunk 210] [--window 42] [--max-posts 8] [--peak-ratio 1.6]
        [--any-live] [--channel URL] [--max-minutes 320] [--idle-exit-min 60]

Prints one JSON summary at exit.
"""
import argparse
import time
from datetime import date

from _common import REPO_ROOT, load_env, emit
from _media import probe_duration
from clip_autopost import run_tool_safe, build_meta
from clip_speed_reaction import (DEFAULT_CHANNEL, resolve_live, record_live,
                                 per_second_energy, top_peaks, loudest_window,
                                 extract_frames, render_short)
from worldcup_live import get_scoreboard, norm_name
from _llm import vision_complete, parse_json

TMP = REPO_ROOT / ".tmp" / "speed"
STATE_PATH = REPO_ROOT / "state" / "speed_watch.json"

VISION_SYS = ("You label frames from streamer iShowSpeed's live stream while he watches a World "
              "Cup match, for a viral football clips account. Reply with strict JSON only.")


def load_state():
    import json
    try:
        return json.load(open(STATE_PATH, encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(st):
    import json
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=1)


def match_wc_stream(title, matches):
    """Return the WC match this live title is about, or None. Matches a competing team name
    (accent-insensitive) or a generic 'world cup'/'fifa' keyword in Speed's stream title."""
    t = norm_name(title)
    if not t:
        return None
    for m in matches:
        for side in (m.get("home"), m.get("away")):
            name = (side or {}).get("name")
            if name and norm_name(name) in t:
                return m
    if "world cup" in t or "fifa" in t or "worldcup" in t:
        # He's clearly on a WC watchalong but named no team -> attach to a live match if one exists.
        live = [m for m in matches if m["state"] == "in"]
        return live[0] if live else (matches[0] if matches else {"id": "?", "short": "World Cup"})
    return None


class SpeedWatcher:
    def __init__(self, args):
        self.args = args
        self.st = load_state()
        today = date.today().isoformat()
        if self.st.get("date") != today:
            self.st = {"date": today, "posts": 0, "reacted_goals": [], "clip_no": 0}
        self.st.setdefault("reacted_goals", [])
        self.st.setdefault("clip_no", 0)
        self.actions = []
        self.platforms = {p.strip().lower() for p in args.platforms.split(",") if p.strip()}
        self.last_zernio_time = 0.0
        self.not_live_note_shown = False

    def can_post(self):
        return self.st["posts"] < self.args.max_posts

    # ---- vision labelling ---------------------------------------------------------
    def label_window(self, chunk_path, start, seg, goal_hint):
        """Gemini-vision label for a candidate window. Returns (keep, title) or (None, None) on
        a vision failure so the caller can apply the safe-degrade policy."""
        frames = extract_frames(chunk_path, start, seg, 3, str(TMP / "frames"))
        if not frames:
            return None, None
        hint = (f" A goal was just scored by {goal_hint}." if goal_hint else "")
        prompt = (
            "Frames are ~evenly spaced across one short window of iShowSpeed's live stream."
            + hint +
            ' Return ONE JSON object: {"keep": true|false, '
            '"kind": "goal-celebration"|"chant"|"creator-collab"|"big-reaction"|"talking"|"ad"|"boring", '
            '"title": "<=6-word ALL-CAPS punchy title, NO emoji, no quotes>"}. '
            "keep=true ONLY if he is visibly hyped: celebrating, screaming, chanting, dancing, or "
            "interacting/filming with another person -- something a football fan would clip and "
            "share. keep=false for calm talking to camera, ads, menus/loading screens, or nothing "
            "happening. JSON only.")
        try:
            out = vision_complete(frames, prompt, system=VISION_SYS, json_mode=True)
            data = parse_json(out["text"])
        except Exception as e:
            self.actions.append({"what": "vision_failed", "error": str(e)[:140]})
            return None, None
        keep = bool(data.get("keep"))
        title = (data.get("title") or "").strip().strip('"')[:60] or None
        return keep, title

    # ---- posting ------------------------------------------------------------------
    def _zernio_upload(self, tool, tool_args):
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

    def post(self, final_rel, card, what):
        a = {"what": what, "card": card, "delivery": {}}
        self.actions.append(a)
        if self.args.no_upload:
            a["delivery"] = {"skipped": "no-upload mode"}
            self.st["posts"] += 1        # count toward cap so a dry run mirrors real pacing
            return True
        cand = {"title": card, "category": "streamer"}
        _, yt_title, description, ig_caption, tags = build_meta(cand, self.args.handle)
        host, herr = run_tool_safe("host_public.py", ["--video", final_rel])
        url = (host or {}).get("url")
        if herr or not url:
            a["delivery"]["error"] = (herr or "host_public returned no url").splitlines()[0][:160]
            return False
        ok = False
        if "instagram" in self.platforms:
            m, err = self._zernio_upload("upload_instagram.py",
                                         ["--video-url", url, "--caption", ig_caption, "--confirm"])
            if err:
                ig = {"skipped": err.splitlines()[0][:160]}
                detail = (m or {}).get("platform_status")
                if detail:
                    ig["platform_status"] = detail
                a["delivery"]["instagram"] = ig
            else:
                a["delivery"]["instagram"] = {"id": m.get("post_id") or m.get("media_id")}
            ok = ok or not err
        if "youtube" in self.platforms:
            m, err = self._zernio_upload("upload_youtube.py",
                                         ["--video-url", url, "--title", yt_title,
                                          "--description", description, "--tags", ",".join(tags),
                                          "--privacy", self.args.privacy, "--confirm"])
            a["delivery"]["youtube"] = {"skipped": err.splitlines()[0][:160]} if err else {"url": m.get("url")}
            ok = ok or not err
        if ok:
            self.st["posts"] += 1
        return ok

    # ---- one recorded chunk -------------------------------------------------------
    def new_goal_hint(self, match):
        """First not-yet-reacted goal in this match; marks it reacted. Used to title a reaction."""
        for g in (match.get("goals") or []):
            if g["key"] not in self.st["reacted_goals"]:
                self.st["reacted_goals"].append(g["key"])
                if not g.get("own_goal"):
                    return g.get("scorer") or None
                return "an own goal"
        return None

    def process_chunk(self, chunk_path, match):
        goal_hint = self.new_goal_hint(match) if match else None
        per_sec = per_second_energy(chunk_path)
        peaks = top_peaks(chunk_path, self.args.window, max_peaks=self.args.max_per_chunk,
                          ratio=self.args.peak_ratio, per_sec=per_sec)
        # A goal just happened but the audio didn't clear the bar (e.g. he muted / crowd only) ->
        # still take the loudest window: a goal reaction is worth posting regardless.
        if goal_hint and not peaks:
            peaks = [(loudest_window(chunk_path, self.args.window, per_sec=per_sec), 0.0)]
        rec_dur = probe_duration(chunk_path) or 0
        for i, (start, energy) in enumerate(peaks):
            if not self.can_post():
                break
            seg = min(self.args.window, max(10.0, rec_dur - start - 1))
            keep, title = self.label_window(chunk_path, start, seg, goal_hint if i == 0 else None)
            if keep is None:                       # vision unavailable -> safe degrade
                if not (goal_hint and i == 0):
                    self.actions.append({"what": "dropped_unlabelled_peak", "energy": energy})
                    continue
                title = f"SPEED REACTS TO {goal_hint.upper()} GOAL"
            elif not keep:
                self.actions.append({"what": "peak_rejected_by_vision", "energy": energy})
                continue
            if goal_hint and i == 0 and (not title or "SPEED" not in title.upper()):
                title = f"SPEED REACTS TO {goal_hint.upper()} GOAL"
            title = title or "SPEED GOES CRAZY"
            self.st["clip_no"] += 1
            out_rel = f".tmp/speed/clip_{self.st['clip_no']}.mp4"
            try:
                render_short(chunk_path, start, seg, title, self.args.handle, out_rel)
            except Exception as e:
                self.actions.append({"what": "render_failed", "title": title, "error": str(e)[:140]})
                continue
            self.post(out_rel, title, f"speed_clip:{title}")
            # The clip is finally used (hosted+posted) -> delete it so .tmp/speed doesn't grow
            # (2026-07-09). In --no-upload mode keep it: CI uploads it as an inspection artifact.
            if not self.args.no_upload:
                try:
                    (REPO_ROOT / out_rel).unlink()
                except OSError:
                    pass

    # ---- main loop ----------------------------------------------------------------
    def run(self):
        TMP.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + self.args.max_minutes * 60
        last_live = time.time()
        chunks = 0
        while time.time() < deadline and self.can_post():
            watch_url, note = resolve_live(self.args.channel)
            if not watch_url:
                if not self.not_live_note_shown:
                    print(f"::notice::Speed not live ({note}) -- watching")
                    self.not_live_note_shown = True
                if time.time() - last_live > self.args.idle_exit_min * 60:
                    self.actions.append({"what": "idle_exit", "note": note})
                    break
                if self.args.once:
                    break
                time.sleep(self.args.not_live_poll)
                continue

            last_live = time.time()
            self.not_live_note_shown = False
            try:
                matches = get_scoreboard()
            except Exception:
                matches = []
            match = match_wc_stream(note, matches)
            if not match and not self.args.any_live:
                self.actions.append({"what": "live_but_not_wc", "title": note[:100]})
                if self.args.once:
                    break
                time.sleep(self.args.not_live_poll)
                continue

            chunks += 1
            print(f"::notice::Speed LIVE on {(match or {}).get('short', '?')} -- recording chunk {chunks}")
            chunk = TMP / "chunk.ts"
            try:
                chunk.unlink()
            except OSError:
                pass
            if not record_live(watch_url, chunk, self.args.chunk):
                self.actions.append({"what": "chunk_record_failed", "watch_url": watch_url})
                time.sleep(self.args.poll)
                continue
            self.process_chunk(str(chunk), match)
            save_state(self.st)
            if self.args.once:
                break
            time.sleep(self.args.poll)

        # Drop the last recorded chunk + extracted frames (raw source, finally used).
        import shutil
        try:
            (TMP / "chunk.ts").unlink()
        except OSError:
            pass
        shutil.rmtree(TMP / "frames", ignore_errors=True)

        save_state(self.st)
        emit({"status": "done", "chunks": chunks, "posts_today": self.st["posts"],
              "reacted_goals": len(self.st["reacted_goals"]), "actions": self.actions})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-upload", action="store_true", help="Build everything, post nothing")
    ap.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"])
    ap.add_argument("--handle", default="@itsmomoclips")
    ap.add_argument("--channel", default=DEFAULT_CHANNEL)
    ap.add_argument("--platforms", default="instagram",
                    help="Where to post his reactions (football account = instagram)")
    ap.add_argument("--poll", type=float, default=60.0, help="Seconds between chunks while live")
    ap.add_argument("--not-live-poll", type=float, default=120.0,
                    help="Seconds between live-checks while he is offline")
    ap.add_argument("--chunk", type=float, default=210.0, help="Seconds of live edge per chunk")
    ap.add_argument("--window", type=float, default=42.0, help="Length of each posted cut (<58s)")
    ap.add_argument("--peak-ratio", type=float, default=1.6,
                    help="A window is a candidate only if its energy >= ratio * the chunk median")
    ap.add_argument("--max-per-chunk", type=int, default=2, help="Max clips taken from one chunk")
    ap.add_argument("--max-posts", type=int, default=8, help="Daily cap on Speed clips")
    ap.add_argument("--any-live", action="store_true",
                    help="Capture even if the stream title is not clearly a World Cup match")
    ap.add_argument("--max-minutes", type=float, default=320.0, help="Hard job-length cap")
    ap.add_argument("--idle-exit-min", type=float, default=60.0,
                    help="Exit if he hasn't been live for this many minutes (saves CI on quiet days)")
    ap.add_argument("--post-spacing", type=float, default=45.0,
                    help="Min seconds between Zernio publishes (shared rate limit -> burst 429s)")
    ap.add_argument("--post-retries", type=int, default=2)
    ap.add_argument("--once", action="store_true", help="Single cycle (testing)")
    args = ap.parse_args()

    load_env()
    SpeedWatcher(args).run()


if __name__ == "__main__":
    main()
