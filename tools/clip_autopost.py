"""Autonomous orchestrator for the SINGLE-CLIP momoclips pipeline.

Every ~20 min (via .github/workflows/worldcup_clips.yml) this asks "did a fresh World-Cup
moment get uploaded?" and, if so, turns the top one into a finished branded Short and posts
it to YouTube + Instagram (@momoclips). If nothing new is found it posts nothing -- that's
the "only trigger when something happened" behaviour.

Pipeline (each step = one tool, cwd = project root):
  find_worldcup_clips -> build_clip -> host_public -> upload_youtube / upload_instagram
  -> record used id.

Dedup (state/used_clips.json) guarantees the same clip is never posted twice across polls; a
daily cap stops a busy match day from flooding the channel.

Usage:
    python tools/clip_autopost.py [--no-upload] [--platforms youtube,instagram,email]
        [--privacy unlisted|public] [--max-videos 8] [--window today|week]
        [--categories goal,streamer,popular] [--keep-tmp]

Copyright note: official goal footage is heavily Content-ID-claimed; posting it is Moemen's
explicit, accepted risk (decision log 2026-07-04). Nothing here vets rights.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

from _common import emit, load_env
from _llm import llm_complete, parse_json
from build_clip import clean_title   # shared title tidy so card + posted text match

ROOT = Path(__file__).resolve().parent.parent
TMP = ROOT / ".tmp"
PY = sys.executable

CANDS = ".tmp/clip_candidates.json"
FINAL = ".tmp/final.mp4"
DAILY_COUNT = ".tmp/clip_daily_count.json"
HISTORY = "state/used_clips.json"


def run_tool_safe(name, args):
    proc = subprocess.run([PY, f"tools/{name}", *args], cwd=str(ROOT), capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    out = (proc.stdout or "").strip()
    data = None
    if out:
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            i, j = out.find("{"), out.rfind("}")
            if i != -1 and j > i:
                try:
                    data = json.loads(out[i:j + 1])
                except json.JSONDecodeError:
                    data = None
    if data is None:
        return None, f"{name} did not return JSON (exit {proc.returncode}). stderr:\n{(proc.stderr or '')[-500:]}"
    if proc.returncode != 0 or "error" in data:
        msg = data.get("error", out[-300:])
        if data.get("reasons"):
            msg += " | reasons: " + "; ".join(str(r) for r in data["reasons"][:5])
        return data, f"{name} failed: {msg}"
    return data, None


def run_tool(name, args):
    data, err = run_tool_safe(name, args)
    if err:
        raise RuntimeError(err)
    return data


def load_json(path):
    try:
        return json.load(open(ROOT / path, encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def record_used(vid):
    if not vid:
        return
    prev = (load_json(HISTORY) or {}).get("used", [])
    merged = list(dict.fromkeys(prev + [vid]))[-1000:]
    (ROOT / "state").mkdir(exist_ok=True)
    with open(ROOT / HISTORY, "w", encoding="utf-8") as f:
        json.dump({"used": merged}, f)


def daily_used():
    d = load_json(DAILY_COUNT) or {}
    return d.get("count", 0) if d.get("date") == date.today().isoformat() else 0


def daily_increment():
    with open(ROOT / DAILY_COUNT, "w", encoding="utf-8") as f:
        json.dump({"date": date.today().isoformat(), "count": daily_used() + 1}, f)


# category -> (metadata-title suffix with emoji, base hashtags). Emoji live in the POSTED text
# only, never in the burned card (libass/Arial can't render colour emoji).
CATEGORY_META = {
    "goal":     ("\U0001F6A8⚽\U0001F525", ["WorldCup2026", "football", "goal", "shorts"]),
    "streamer": ("\U0001F62E\U0001F525",       ["streamer", "WorldCup2026", "shorts"]),
    "popular":  ("\U0001F525",                 ["WorldCup2026", "viral", "football", "shorts"]),
}


def screen_candidates(cands):
    """LLM relevance gate: keep only candidates whose title clearly describes ACTUAL World-Cup
    footage in English. The finder's keyword search can't tell a real goal clip from a news
    studio talking about goals (a Hindi Zee News record-discussion segment got posted on
    2026-07-05) -- this is the semantic check the deterministic title filter can't do.
    On a whole-chain LLM failure returns cands unchanged (the deterministic filter already ran;
    better to post a probably-fine clip than to silently stop posting)."""
    listing = "\n".join(f"[{i}] {c['title']}" for i, c in enumerate(cands))
    prompt = (
        f"CANDIDATES:\n{listing}\n\n"
        'Return ONE JSON object: {"matches": [<int indices>]}\n'
        "Return the indices of every candidate whose title clearly describes ACTUAL FOOTAGE of "
        "ONE SINGLE specific World Cup moment: a goal, save, skill, celebration, streamer/fan "
        "reaction, or viral on-the-ground moment. EXCLUDE: ranked lists and Top-N countdowns, "
        "'most/best X in history' or all-time stat/record pieces, player-vs-player comparisons, "
        "compilations and montages, news reports and news-channel segments, studio "
        "discussion/analysis, previews, predictions, interviews, press conferences, podcasts, "
        "anything featuring the streamer iShowSpeed, and anything whose title is not primarily "
        "in English. Output JSON only.")
    try:
        out = llm_complete(prompt, system="You screen clip titles for a strict content filter. Strict JSON.",
                           json_mode=True, temperature=0.2)
        idxs = sorted({i for i in parse_json(out["text"]).get("matches", [])
                       if isinstance(i, int) and 0 <= i < len(cands)})
    except Exception as e:
        print(f"::warning::candidate screen failed ({str(e)[:120]}); using unscreened candidates",
              file=sys.stderr)
        return cands
    return [cands[i] for i in idxs]


def build_meta(cand, handle):
    """Make the burned card title + the YouTube/IG posted text from a candidate."""
    raw = cand.get("title", "").strip()
    cat = cand.get("category", "popular")
    emoji, base_tags = CATEGORY_META.get(cat, CATEGORY_META["popular"])
    card = clean_title(raw)   # same tidy build_clip burns, so card + posted text agree
    # Posted title: short, emoji, a couple of hashtags. Keep well under YouTube's 100-char limit.
    yt_title = f"{card} {emoji} #Shorts".strip()
    tags = base_tags + [w for w in
                        "".join(c if c.isalnum() else " " for c in raw.lower()).split()
                        if len(w) > 3][:6]
    hashtags = " ".join(f"#{t}" for t in dict.fromkeys(tags))
    description = f"{card}\n\n{hashtags}\n\nFollow {handle} for daily World Cup clips."
    ig_caption = f"{card} {emoji}\n\nFollow {handle} for daily World Cup clips ⚽\U0001F525\n\n{hashtags}"
    return card, yt_title, description, ig_caption, tags


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-upload", action="store_true", help="Build only; post nothing")
    ap.add_argument("--platforms", default="youtube,instagram,email")
    ap.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"],
                    help="YouTube privacy (default public -- Moemen's go-ahead 2026-07-05)")
    ap.add_argument("--handle", default="@itsmomoclips")
    ap.add_argument("--max-videos", type=int, default=int(os.environ.get("MAX_DAILY_CLIPS", "8")),
                    help="Daily post cap so a busy match day doesn't flood the channel")
    ap.add_argument("--window", default="today", choices=["today", "week"])
    ap.add_argument("--categories", default="goal,streamer,popular")
    ap.add_argument("--music", default=None, help="Optional music bed (default: keep original clip audio)")
    ap.add_argument("--keep-tmp", action="store_true")
    args = ap.parse_args()

    load_env()
    TMP.mkdir(exist_ok=True)
    platforms = [p.strip().lower() for p in args.platforms.split(",") if p.strip()]
    # Auto-enable Instagram when Zernio creds are present (workflow can't edit --platforms without
    # the 'workflow' OAuth scope) -- mirrors rank_autopost.
    if "instagram" not in platforms and os.environ.get("ZERNIO_API_KEY") and os.environ.get("ZERNIO_INSTAGRAM_ID"):
        platforms.append("instagram")
    publishing = not args.no_upload
    t0 = time.time()

    if publishing and daily_used() >= args.max_videos:
        emit({"status": "skipped_daily_cap", "used_today": daily_used(), "max_videos": args.max_videos})
        return

    # 1) find a fresh, unused, short clip. count==0 => nothing new happened -> post nothing.
    find, ferr = run_tool_safe("find_worldcup_clips.py",
                               ["--window", args.window, "--categories", args.categories, "--out", CANDS])
    if ferr:
        emit({"status": "find_failed", "error": ferr.splitlines()[0][:200]})
        return
    cands = (find or {}).get("candidates", [])
    if not cands:
        # Surface the finder's per-query errors so a proxy/bot-check failure is distinguishable
        # from a genuinely empty window.
        emit({"status": "nothing_new", "note": (find or {}).get("note", "no fresh clips"),
              "search_errors": (find or {}).get("errors", []),
              "elapsed_sec": round(time.time() - t0, 1)})
        return

    # 1.5) semantic relevance screen -- footage only, English only. "None survived" is a valid
    # quiet-poll outcome, same as an empty search window.
    found_n = len(cands)
    cands = screen_candidates(cands)
    if not cands:
        emit({"status": "nothing_new", "note": f"all {found_n} candidates rejected by relevance screen",
              "elapsed_sec": round(time.time() - t0, 1)})
        return

    # 2) build the branded Short. Try candidates in order until one builds: an individual clip
    # can 403 on its video data (geo/format-locked streams on some uploads) even though search
    # + WARP work, so a single bad clip must not waste the whole poll. Each attempted source is
    # marked used (pass or fail) so it's never retried on the next poll.
    cand = card = yt_title = description = ig_caption = tags = build = None
    attempts = []
    for c in cands[: max(1, min(5, len(cands)))]:
        _card, _yt, _desc, _cap, _tags = build_meta(c, args.handle)
        build_args = ["--url", c["url"], "--title", _card, "--handle", args.handle, "--out", FINAL]
        if args.music:
            build_args += ["--music", args.music]
        b, berr = run_tool_safe("build_clip.py", build_args)
        record_used(c["id"])
        if not berr:
            cand, card, yt_title, description, ig_caption, tags, build = c, _card, _yt, _desc, _cap, _tags, b
            break
        attempts.append({"id": c["id"], "error": berr.splitlines()[0][:160]})
        print(f"::warning::build_clip failed for {c['id']}: {berr.splitlines()[0][:160]}", file=sys.stderr)

    if build is None:
        emit({"status": "all_builds_failed", "tried": len(attempts), "attempts": attempts,
              "elapsed_sec": round(time.time() - t0, 1)})
        return

    result = {"status": "built", "candidate": cand, "title": yt_title, "card": card,
              "final": FINAL, "byte_size": build.get("byte_size"),
              "duration_sec": build.get("duration_sec"), "privacy": args.privacy,
              "elapsed_sec": None, "delivery": {}}

    # 3) deliver. host_public gives the public URL that Zernio-based uploaders need.
    published = False
    if publishing and ("youtube" in platforms or "instagram" in platforms):
        host, herr = run_tool_safe("host_public.py", ["--video", FINAL])
        url = (host or {}).get("url")
        if herr or not url:
            skip = (herr or "host_public returned no url").splitlines()[0][:160]
            if "youtube" in platforms:
                result["delivery"]["youtube"] = {"skipped": skip}
            if "instagram" in platforms:
                result["delivery"]["instagram"] = {"skipped": skip}
        else:
            if "youtube" in platforms:
                m, err = run_tool_safe("upload_youtube.py",
                                       ["--video-url", url, "--title", yt_title,
                                        "--description", description, "--tags", ",".join(tags),
                                        "--privacy", args.privacy, "--confirm"])
                result["delivery"]["youtube"] = {"skipped": err.splitlines()[0][:160]} if err else {"url": m.get("url")}
                published = published or not err
            if "instagram" in platforms:
                m, err = run_tool_safe("upload_instagram.py",
                                       ["--video-url", url, "--caption", ig_caption, "--confirm"])
                result["delivery"]["instagram"] = {"skipped": err.splitlines()[0][:160]} if err else {"media_id": m.get("post_id") or m.get("media_id")}
                published = published or not err

    if publishing and "email" in platforms:
        m, err = run_tool_safe("email_video.py", ["--video", FINAL, "--subject", f"momoclips: {card}"])
        result["delivery"]["email"] = {"skipped": err.splitlines()[0][:160]} if err else {"sent_to": m.get("to")}

    if published:
        result["status"] = "uploaded"
        daily_increment()

    result["elapsed_sec"] = round(time.time() - t0, 1)

    if not args.keep_tmp:
        import shutil
        shutil.rmtree(ROOT / ".tmp" / "clip", ignore_errors=True)
        for p in (CANDS, FINAL):
            try:
                (ROOT / p).unlink()
            except OSError:
                pass

    emit(result)


if __name__ == "__main__":
    main()
