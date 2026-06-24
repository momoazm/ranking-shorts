"""Autonomous orchestrator for #5->#1 RANKING Shorts built from real YouTube clips.

Pipeline (each step = one tool, cwd = project root):
  rank_topic -> find_ranking_clips -> rank_clips -> build_ranking_video -> build_captions
  -> deliver (email / export / youtube).

Auto-picks a trending topic, pulls candidate clips via yt-dlp (no API quota), the LLM ranks the
best 5 with commentary, then they're trimmed, captioned with a countdown overlay, narrated, and
delivered. Same safety/daily-cap conventions as autopost.py.

Usage:
    python tools/rank_autopost.py [--no-upload] [--niche "..."] [--platforms email,export]
        [--privacy public] [--max-videos 6] [--keep-tmp]
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

ROOT = Path(__file__).resolve().parent.parent
TMP = ROOT / ".tmp"
PY = sys.executable

TOPIC = ".tmp/rank_topic.json"
CANDS = ".tmp/rank_candidates.json"
RANKED = ".tmp/ranked.json"
FINAL = ".tmp/final.mp4"
RANK_STORY = ".tmp/rank_story.json"
CAPMETA = ".tmp/captions_meta.json"
DAILY_COUNT = ".tmp/daily_count.json"


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
        if data.get("reasons"):                       # surface per-item diagnostics (e.g. why clips failed)
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


HISTORY = "state/used_clips.json"


def record_used(ranked_path):
    """Remember the Reddit post ids that went into this video so future runs don't repeat them."""
    ranked = load_json(ranked_path)
    ids = [e.get("id") for e in (ranked or {}).get("entries", []) if e.get("id")]
    if not ids:
        return
    prev = (load_json(HISTORY) or {}).get("used", [])
    merged = list(dict.fromkeys(prev + ids))[-1000:]   # keep the most recent 1000, de-duped
    (ROOT / "state").mkdir(exist_ok=True)
    with open(ROOT / HISTORY, "w", encoding="utf-8") as f:
        json.dump({"used": merged}, f)


def daily_used():
    d = load_json(DAILY_COUNT) or {}
    return d.get("count", 0) if d.get("date") == date.today().isoformat() else 0


def daily_increment():
    with open(ROOT / DAILY_COUNT, "w", encoding="utf-8") as f:
        json.dump({"date": date.today().isoformat(), "count": daily_used() + 1}, f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--niche", default="funny videos / fails / funny moments")
    # TEMPORARY (2026-06-25): forcing World Cup content while the 2026 tournament is live
    # (~through 2026-07-19). Set to None (or pass --force-genre "") to go back to normal rotation.
    ap.add_argument("--force-genre", default="worldcup", choices=["", "fails", "cats", "babies", "dogs", "worldcup"],
                    help="Lock every video to one genre instead of letting the topic model rotate.")
    ap.add_argument("--search", default=None, help="Override the Tenor search query")
    ap.add_argument("--platforms", default="youtube,email")
    ap.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"])
    ap.add_argument("--music", default=None, help="Optional music bed path (default: none -- keep clip audio)")
    ap.add_argument("--music-query", default="trending tiktok background music 2026")
    ap.add_argument("--with-music", action="store_true",
                    help="Add a trending background-music bed under the clips (default: off)")
    ap.add_argument("--per-clip", type=float, default=24.0,
                    help="Max seconds shown per clip; longer clips show their END (the payoff)")
    ap.add_argument("--max-videos", type=int, default=int(os.environ.get("MAX_DAILY_VIDEOS", "6")))
    ap.add_argument("--keep-tmp", action="store_true")
    args = ap.parse_args()

    TMP.mkdir(exist_ok=True)
    platforms = [p.strip().lower() for p in args.platforms.split(",") if p.strip()]
    # Auto-enable Instagram when its credentials are configured. The cloud workflow's --platforms
    # line can't be edited without the 'workflow' OAuth scope, so instead of relying on it we detect
    # IG creds (written to API.env from repo secrets) and add the platform here. Harmless when not
    # publishing -- the instagram delivery branch below is gated on `publishing`.
    load_env()
    if "instagram" not in platforms and os.environ.get("IG_ACCESS_TOKEN") and os.environ.get("IG_USER_ID"):
        platforms.append("instagram")
    t0 = time.time()
    publishing = not args.no_upload
    if publishing:
        if daily_used() >= args.max_videos:
            print(json.dumps({"status": "skipped_daily_cap", "used_today": daily_used(),
                              "max_videos": args.max_videos}, indent=2))
            return
        daily_increment()

    # 1) topic (most-trending genre + title) -> 2) pull short clips from that genre's channels -> 3) rank 5
    topic_args = ["--niche", args.niche, "--out", TOPIC]
    if args.force_genre:
        topic_args += ["--force-genre", args.force_genre]
    topic = run_tool("rank_topic.py", topic_args)
    find_args = ["--out", CANDS]
    if args.search:
        find_args += ["--search", args.search]
    elif topic.get("genre"):
        find_args += ["--genre", topic["genre"]]
    if topic.get("genre") == "worldcup":
        find_args += ["--max", "30"]   # angle lock (fan-only/match-only) rejects most candidates
    _f, ferr = run_tool_safe("find_ranking_clips.py", find_args)
    if ferr and not args.search and topic.get("genre") != "fails":
        # the picked genre didn't have enough clips -> fall back to the reliable one
        run_tool("find_ranking_clips.py", ["--genre", "fails", "--out", CANDS])
    elif ferr:
        raise RuntimeError(ferr)
    run_tool("rank_clips.py", ["--candidates", CANDS, "--topic", TOPIC, "--out", RANKED])

    # 4) background music -> 5) build the video.
    # Default: ALWAYS mix in the committed background bed (assets/music/bg.mp3 -- the
    # user's chosen track, extracted from the reference Short). The per-line whoosh/boom
    # SFX are gone, and the intro swoosh is removed too (user rule, 2026-06-23) -- the bed
    # is now the ONLY non-clip audio. An explicit --music overrides it; --with-music can still
    # pull a trending track instead. (The bed is committed because the cloud runner's IP
    # is blocked from YouTube downloads, so we can't re-extract it at runtime.)
    MUSIC = ".tmp/music.mp3"
    BG_BED = ROOT / "assets" / "music" / "bg.mp3"
    music_path = args.music
    if not music_path and args.with_music:
        _m, merr = run_tool_safe("fetch_trending_music.py", ["--query", args.music_query, "--out", MUSIC])
        music_path = MUSIC if (not merr and (ROOT / MUSIC).is_file()) else None
    if not music_path and BG_BED.is_file():
        music_path = str(BG_BED)

    build_args = ["--ranked", RANKED, "--max-total", "58", "--per-clip", str(args.per_clip),
                  "--title", topic["title"], "--out", FINAL]
    if music_path:
        build_args += ["--music", music_path]
    build = run_tool("build_ranking_video.py", build_args)
    record_used(RANKED)   # mark these clips used so they aren't repeated next run

    # 5) per-platform captions/hashtags (write a tiny story-like file for build_captions)
    title = topic["title"]
    tags = [w for w in "".join(c if c.isalnum() else " " for c in title.lower()).split() if len(w) > 3]
    with open(ROOT / RANK_STORY, "w", encoding="utf-8") as f:
        json.dump({"title": title, "description": topic.get("hook", title),
                   "tags": (tags + ["ranking", "top5", "countdown", "viral"])[:15]}, f)
    run_tool_safe("build_captions.py", ["--story", RANK_STORY, "--out", CAPMETA])
    meta = load_json(CAPMETA) or {}

    result = {"status": "built", "title": title, "final": FINAL,
              "byte_size": build.get("byte_size"), "duration_sec": build.get("duration_sec"),
              "entries": build.get("entries"), "elapsed_sec": round(time.time() - t0, 1),
              "delivery": {}}

    # 6) deliver
    if "email" in platforms:
        m, err = run_tool_safe("email_video.py", ["--video", FINAL, "--captions-meta", CAPMETA,
                                                  "--subject", f"Ranking Short: {title}"])
        result["delivery"]["email"] = {"skipped": err.splitlines()[0][:140]} if err else {"sent_to": m.get("to")}
    if "export" in platforms:
        m, err = run_tool_safe("export_local.py", ["--video", FINAL, "--captions-meta", CAPMETA, "--title", title])
        result["delivery"]["export"] = {"error": err.splitlines()[0][:140]} if err else {"folder": m.get("folder")}
    if publishing and "youtube" in platforms:
        yt = (meta.get("youtube") or {})
        m, err = run_tool_safe("upload_youtube.py", ["--video", FINAL, "--title", yt.get("title", title),
                               "--description", yt.get("description", ""),
                               "--tags", ",".join(yt.get("tags", []) or ["shorts"]),
                               "--privacy", args.privacy, "--confirm"])
        result["delivery"]["youtube"] = {"skipped": err.splitlines()[0][:140]} if err else {"url": m.get("url")}
        result["status"] = "uploaded"
    if publishing and "instagram" in platforms:
        # IG can't take a local file -> host the mp4 at a PUBLIC url, then publish it as a Reel.
        ig = (meta.get("instagram") or {})
        caption = ig.get("caption", title)
        host, herr = run_tool_safe("host_public.py", ["--video", FINAL])
        if herr or not (host or {}).get("url"):
            result["delivery"]["instagram"] = {"skipped": (herr or "host_public returned no url").splitlines()[0][:140]}
        else:
            m, err = run_tool_safe("upload_instagram.py", ["--video-url", host["url"],
                                   "--caption", caption, "--confirm"])
            result["delivery"]["instagram"] = {"skipped": err.splitlines()[0][:140]} if err else {"media_id": m.get("media_id")}
            if not err:
                result["status"] = "uploaded"

    if not args.keep_tmp:
        import shutil
        # Wipe the downloaded source clips + intermediates so disk doesn't fill up run to run.
        shutil.rmtree(ROOT / ".tmp" / "rank", ignore_errors=True)
        for p in (CANDS, RANKED, RANK_STORY, FINAL, CAPMETA, ".tmp/music.mp3", ".tmp/email_small.mp4"):
            try:
                (ROOT / p).unlink()
            except (OSError, IsADirectoryError):
                pass

    emit(result)   # ASCII-safe on Windows cp1252 (titles can contain non-cp1252 chars)


if __name__ == "__main__":
    main()
