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
import random
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
    # Zernio creds (written to API.env from repo secrets) and add the platform here. Harmless when
    # not publishing -- the instagram delivery branch below is gated on `publishing`.
    load_env()
    if "instagram" not in platforms and os.environ.get("ZERNIO_API_KEY") and os.environ.get("ZERNIO_INSTAGRAM_ID"):
        platforms.append("instagram")
    t0 = time.time()
    publishing = not args.no_upload
    if publishing:
        if daily_used() >= args.max_videos:
            print(json.dumps({"status": "skipped_daily_cap", "used_today": daily_used(),
                              "max_videos": args.max_videos}, indent=2))
            return
        daily_increment()

    # 1) figure out the genre (forced, or let the model pick) -> 2) for worldcup, PROBE which angle
    # (fan/match/streamer) is actually sourceable BEFORE committing to a title -- supply per angle
    # varies a lot on Reddit, so locking the angle blind (the old flow) kept silently dropping the
    # World Cup theme because the chosen angle often turned out unsourceable after the fact.
    if args.force_genre == "worldcup":
        topic = {"genre": "worldcup"}   # defer the actual title/angle LLM call until angle is known
    elif args.force_genre:
        topic = run_tool("rank_topic.py", ["--niche", args.niche, "--force-genre", args.force_genre, "--out", TOPIC])
    else:
        topic = run_tool("rank_topic.py", ["--niche", args.niche, "--out", TOPIC])

    requested_genre = topic.get("genre")
    fallback_reason = None

    if topic.get("genre") == "worldcup":
        # Three angles now. fan/match share ONE football source pool; "streamer" (FaZe/
        # Marlon etc. at the World Cup) has its OWN pool -- those clips aren't on the football feeds.
        # Randomize which pool we try first so streamer videos get a fair share across runs instead of
        # the abundant match angle always winning. Each probe leaves CANDS holding its own pool, so on
        # the break CANDS already matches the chosen angle for the ranking step below.
        groups = [("football", ["match", "fan"]), ("streamer", ["streamer"])]
        # On GitHub-hosted (datacenter-IP) runners Reddit's v.redd.it CDN 403-blocks every
        # download path (probed 2026-07-03: plain IP, WARP proxy, direct DASH files -- all
        # blocked; only YouTube works, via YTDLP_PROXY/WARP). NO_REDDIT_SOURCES=1 restricts
        # sourcing to the YouTube streamer pool so cloud runs never pick clips they can't
        # actually download. Unset it (or set a residential YTDLP_PROXY) to restore Reddit.
        no_reddit = os.environ.get("NO_REDDIT_SOURCES") == "1"
        if no_reddit:
            groups = [g for g in groups if g[0] == "streamer"]
        random.shuffle(groups)   # match stays before fan within the football group (more abundant)
        chosen_angle = None
        for pool, cand_angles in groups:
            if pool == "streamer":
                # Streamer clips come from YouTube search (on-theme + well-titled). If YouTube is
                # blocked/empty, fall back to the Reddit streamer subs before giving up on the angle.
                _f, ferr = run_tool_safe("find_streamer_clips.py", ["--max", "30", "--out", CANDS])
                if ferr and not no_reddit:
                    _f, ferr = run_tool_safe("find_ranking_clips.py",
                                             ["--genre", "worldcup", "--angle", "streamer", "--max", "30", "--out", CANDS])
            else:
                _f, ferr = run_tool_safe("find_ranking_clips.py",
                                         ["--genre", "worldcup", "--max", "30", "--out", CANDS])
            if ferr:
                continue   # this pool didn't source -- try the other group
            for cand_angle in cand_angles:
                probe, perr = run_tool_safe("rank_clips.py", ["--candidates", CANDS, "--classify-angle", cand_angle])
                if not perr and probe.get("count", 0) >= 5:
                    chosen_angle = cand_angle
                    break
            if chosen_angle:
                break
        if not chosen_angle and no_reddit:
            # Cloud rescue: the streamer pool starved (it did twice on 2026-07-05 -> 2 failed
            # runs, 2 missed uploads). Reddit is unreachable here, but the single-clip finder's
            # YouTube pool (goals / streamers / viral moments, week window, news+language
            # filtered) downloads fine through WARP -- use it for a "mixed" World Cup countdown.
            _f, ferr = run_tool_safe("find_worldcup_clips.py",
                                     ["--window", "week", "--max", "30", "--max-dur", "240",
                                      "--history", HISTORY, "--out", CANDS])
            if not ferr and (_f or {}).get("count", 0) >= 5:
                chosen_angle = "mixed"
            elif not ferr:
                ferr = f"YouTube mixed rescue pool too thin ({(_f or {}).get('count', 0)} candidates, need >=5)"
        if not chosen_angle and not no_reddit:
            # No pure angle cleared 5 -> stay on-theme with a "mixed" World Cup video (needs only >=5
            # total candidates, which find_ranking_clips guarantees). Re-source the football pool fresh
            # so CANDS definitely holds it for the ranking step, whichever group ran last above.
            _f, ferr = run_tool_safe("find_ranking_clips.py", ["--genre", "worldcup", "--max", "30", "--out", CANDS])
            if not ferr:
                chosen_angle = "mixed"
        if chosen_angle:
            topic = run_tool("rank_topic.py", ["--niche", args.niche, "--force-genre", "worldcup",
                                                "--force-angle", chosen_angle, "--out", TOPIC])
        else:
            fallback_reason = f"worldcup: {ferr or 'no angle could source >=5 clips'}"
    else:
        find_args = ["--out", CANDS]
        if args.search:
            find_args += ["--search", args.search]
        elif topic.get("genre"):
            find_args += ["--genre", topic["genre"]]
        _f, ferr = run_tool_safe("find_ranking_clips.py", find_args)
        if ferr and not args.search and topic.get("genre") != "fails":
            fallback_reason = f"find_ranking_clips({requested_genre}): {ferr}"
        elif ferr:
            raise RuntimeError(ferr)

    # The generic-"fails" rescue pool is Reddit-sourced; under NO_REDDIT_SOURCES those
    # downloads are guaranteed 403s, so fail the run loudly instead of building a dud pool.
    no_reddit_rescue = os.environ.get("NO_REDDIT_SOURCES") == "1"

    if fallback_reason:
        if no_reddit_rescue:
            raise RuntimeError(f"{fallback_reason} (and the Reddit 'fails' rescue pool is "
                               "disabled by NO_REDDIT_SOURCES on this runner)")
        # couldn't source/fit the requested theme -> regenerate a generic "fails" topic to match
        print(f"::warning::{fallback_reason}", file=sys.stderr)
        run_tool("find_ranking_clips.py", ["--genre", "fails", "--out", CANDS])
        topic = run_tool("rank_topic.py", ["--niche", args.niche, "--force-genre", "fails", "--out", TOPIC])

    _r, rerr = run_tool_safe("rank_clips.py", ["--candidates", CANDS, "--topic", TOPIC, "--out", RANKED])
    if rerr and topic.get("genre") != "fails" and not no_reddit_rescue:
        # last-resort safety net (e.g. re-classification flake right after the probe confirmed
        # enough candidates) -- drop the theme for this run rather than crash
        fallback_reason = fallback_reason or f"rank_clips({requested_genre}): {rerr}"
        print(f"::warning::{fallback_reason}", file=sys.stderr)
        run_tool("find_ranking_clips.py", ["--genre", "fails", "--out", CANDS])
        topic = run_tool("rank_topic.py", ["--niche", args.niche, "--force-genre", "fails", "--out", TOPIC])
        run_tool("rank_clips.py", ["--candidates", CANDS, "--topic", TOPIC, "--out", RANKED])
    elif rerr:
        raise RuntimeError(rerr)

    # 3.5) Refine the title based on what clips were actually selected (not the pre-made topic title)
    # This makes the title specific/catchy and ensures the video is cohesive.
    REFINED_TITLE_FILE = ".tmp/refined_title.json"
    refined_title_data, title_err = run_tool_safe("refine_title.py", ["--ranked", RANKED, "--out", REFINED_TITLE_FILE])
    refined_title = None
    if not title_err and refined_title_data:
        refined_title = refined_title_data.get("title", "").strip()
        if refined_title:
            topic["title"] = refined_title
            topic["hook"] = refined_title_data.get("hook", topic.get("hook", refined_title))
    else:
        # Fall back to original topic title if refinement fails
        print(f"::warning::Title refinement failed: {title_err or 'no data'}; using original title", file=sys.stderr)

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
              "requested_genre": requested_genre, "used_genre": topic.get("genre"),
              "fallback_reason": fallback_reason, "delivery": {}}

    # 6) deliver
    if "email" in platforms:
        m, err = run_tool_safe("email_video.py", ["--video", FINAL, "--captions-meta", CAPMETA,
                                                  "--subject", f"Ranking Short: {title}"])
        result["delivery"]["email"] = {"skipped": err.splitlines()[0][:140]} if err else {"sent_to": m.get("to")}
    if "export" in platforms:
        m, err = run_tool_safe("export_local.py", ["--video", FINAL, "--captions-meta", CAPMETA, "--title", title])
        result["delivery"]["export"] = {"error": err.splitlines()[0][:140]} if err else {"folder": m.get("folder")}
    if publishing and "youtube" in platforms:
        # YouTube now publishes via Zernio too (same channel-OAuth-avoidance reasoning as
        # Instagram) -- it also needs a PUBLIC url, not a local path.
        yt = (meta.get("youtube") or {})
        host, herr = run_tool_safe("host_public.py", ["--video", FINAL])
        if herr or not (host or {}).get("url"):
            result["delivery"]["youtube"] = {"skipped": (herr or "host_public returned no url").splitlines()[0][:140]}
        else:
            m, err = run_tool_safe("upload_youtube.py", ["--video-url", host["url"], "--title", yt.get("title", title),
                                   "--description", yt.get("description", ""),
                                   "--tags", ",".join(yt.get("tags", []) or ["shorts"]),
                                   "--privacy", args.privacy, "--confirm"])
            result["delivery"]["youtube"] = {"skipped": err.splitlines()[0][:140]} if err else {"url": m.get("url")}
            if not err:
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
            result["delivery"]["instagram"] = {"skipped": err.splitlines()[0][:140]} if err else {"media_id": m.get("post_id") or m.get("media_id")}
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
