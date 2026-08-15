"""Autonomous orchestrator for #5->#1 RANKING Shorts built from real YouTube clips.

Pipeline (each step = one tool, cwd = project root):
  rank_topic -> find_ranking_clips -> rank_clips -> build_ranking_video -> build_captions
  -> deliver (email / export / youtube).

Auto-picks a trending topic, pulls candidate clips via yt-dlp (no API quota), the LLM ranks the
best 5 with commentary, then they're trimmed, captioned with a countdown overlay, narrated, and
delivered. Same safety/daily-cap conventions as autopost.py.

Usage:
    python tools/rank_autopost.py [--no-upload] [--niche "..."] [--platforms youtube,instagram,tiktok,email]
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

from _common import emit, load_env, log_ig_post

ROOT = Path(__file__).resolve().parent.parent
TMP = ROOT / ".tmp"
PY = sys.executable

TOPIC = ".tmp/rank_topic.json"
CANDS = ".tmp/rank_candidates.json"
RANKED = ".tmp/ranked.json"
FINAL = ".tmp/final.mp4"
REVIEW_MANIFEST = ".tmp/review_manifest.json"
RANK_STORY = ".tmp/rank_story.json"
CAPMETA = ".tmp/captions_meta.json"
DAILY_COUNT = ".tmp/daily_count.json"
FORMAT_STATE = "state/format_experiment.json"

# Every network- or media-heavy child must have a bounded wall-clock budget.  Without this,
# yt-dlp or a public host can leave the Actions job "in progress" until the workflow's much
# larger job timeout, which looks like a silent upload stall and blocks the next scheduled run.
TOOL_TIMEOUTS = {
    "rank_topic.py": 120,
    "find_streamer_clips.py": 240,
    "find_ranking_clips.py": 240,
    "find_worldcup_clips.py": 240,
    "rank_clips.py": 180,
    "refine_title.py": 120,
    "fetch_trending_music.py": 180,
    "build_ranking_video.py": 900,
    "build_clip.py": 900,
    "prepare_upload_media.py": 240,
    "build_captions.py": 180,
    "host_public.py": 240,
    "upload_youtube.py": 360,
    "upload_instagram.py": 360,
    "upload_tiktok.py": 360,
    "email_video.py": 300,
    "export_local.py": 180,
}


def run_tool_safe(name, args):
    timeout = TOOL_TIMEOUTS.get(name, 300)
    try:
        proc = subprocess.run([PY, f"tools/{name}", *args], cwd=str(ROOT), capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, f"{name} timed out after {timeout}s"
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
        with open(ROOT / path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def _is_streamer_source_starvation(error):
    """Recognize a failed build caused by too few downloadable streamer clips."""
    text = str(error or "").lower()
    return "usable clips" in text and "need >=5" in text


def _is_streamer_clip_download_failure(error):
    """Recognize a standalone source fetch failure without masking render/config errors."""
    text = str(error or "").lower()
    return "build_clip.py failed: download failed" in text or "yt-dlp" in text and "download" in text


def _streamer_no_source_payload(source, requested_genre, detail, candidate_count=None):
    payload = {"status": "no_source", "content_policy": "streamer-only",
               "source_mode": source, "requested_genre": requested_genre,
               "detail": str(detail)}
    if candidate_count is not None:
        payload["candidate_count"] = int(candidate_count)
    return payload


HISTORY = "state/used_clips.json"


def record_used(ranked_path, selected_format="ranking"):
    """Remember only sources that actually went into this format's video."""
    ranked = load_json(ranked_path)
    entries = (ranked or {}).get("entries", [])
    if selected_format == "standalone":
        entries = [e for e in entries if e.get("rank") == 1][:1]
    ids = [e.get("id") for e in entries if e.get("id")]
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


def choose_format(requested, no_upload=False):
    """Choose the streamer presentation while preserving a small ranked control cohort.

    Public competitor evidence favors standalone clips for discovery, but the existing account's
    countdown has a valid retention hypothesis.  Auto mode therefore runs standalone by default
    and reserves every fifth *real* post for ranking until measured analytics are written into the
    state ledger.  A future winner field can switch the auto cohort without changing the workflow.
    Dry runs never advance the cohort counter.
    """
    requested = (requested or "auto").strip().lower()
    if requested not in {"auto", "standalone", "ranking"}:
        raise ValueError(f"unknown format: {requested}")
    state = load_json(FORMAT_STATE) or {"run_index": 0, "winner": None, "runs": []}
    if not isinstance(state, dict):
        state = {"run_index": 0, "winner": None, "runs": []}
    winner = state.get("winner") if state.get("winner") in {"standalone", "ranking"} else None
    if requested != "auto":
        selected = requested
    elif winner:
        selected = winner
    else:
        try:
            run_index = max(0, int(state.get("run_index", 0)))
        except (TypeError, ValueError):
            run_index = 0
        selected = "ranking" if run_index % 5 == 4 else "standalone"
    if not no_upload:
        try:
            prior_index = max(0, int(state.get("run_index", 0) or 0))
        except (TypeError, ValueError):
            prior_index = 0
        state["run_index"] = prior_index + 1
        state.setdefault("runs", []).append({"index": prior_index,
                                               "requested": requested,
                                               "selected": selected,
                                               "status": "selected"})
        state["runs"] = state["runs"][-40:]
    return selected, state


def save_format_state(state, selected, status="built"):
    state = dict(state or {})
    runs = list(state.get("runs") or [])
    if runs:
        runs[-1] = {**runs[-1], "selected": selected, "status": status}
    state["runs"] = runs[-40:]
    path = ROOT / FORMAT_STATE
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, ensure_ascii=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--format", choices=["auto", "standalone", "ranking"], default="auto",
                    help="Streamer presentation. Auto defaults to standalone and keeps a 1-in-5 ranked control.")
    ap.add_argument("--niche", default="funny videos / fails / funny moments")
    # The main workflow forces the dedicated streamer genre; football has its own isolated
    # workflows and MrBeast sourcing belongs to clipping-auto.
    ap.add_argument("--force-genre", default="fails", choices=["", "fails", "cats", "babies", "dogs", "streamer", "worldcup"],
                    help="Lock every video to one genre instead of letting the topic model rotate.")
    ap.add_argument("--search", default=None, help="Override the Tenor search query")
    ap.add_argument("--platforms", default="youtube,instagram,tiktok,email")
    ap.add_argument("--required-platforms",
                    default=os.environ.get("REQUIRED_PLATFORMS", "youtube,instagram"),
                    help="Comma-separated destinations that must publish or the run fails. "
                         "Email and TikTok stay optional until their credentials are configured.")
    ap.add_argument("--tiktok-privacy", default=None,
                    choices=["SELF_ONLY", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR",
                             "PUBLIC_TO_EVERYONE"],
                    help="TikTok privacy (defaults to PUBLIC_TO_EVERYONE for public runs, "
                         "SELF_ONLY otherwise).")
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
    required_platforms = {p.strip().lower() for p in args.required_platforms.split(",") if p.strip()}
    # Auto-enable Instagram when its credentials are configured. The cloud workflow's --platforms
    # line can't be edited without the 'workflow' OAuth scope, so instead of relying on it we detect
    # Zernio creds (written to API.env from repo secrets) and add the platform here. Harmless when
    # not publishing -- the instagram delivery branch below is gated on `publishing`.
    load_env()
    selected_format, format_state = choose_format(args.format, no_upload=args.no_upload)
    source = os.environ.get("RANKING_SOURCE", "").strip().lower()
    if source not in {"reddit", "youtube", "streamer"}:
        source = "youtube" if os.environ.get("NO_REDDIT_SOURCES") == "1" else "reddit"
    if "instagram" not in platforms and os.environ.get("ZERNIO_API_KEY") and os.environ.get("ZERNIO_INSTAGRAM_ID"):
        platforms.append("instagram")
    t0 = time.time()
    publishing = not args.no_upload
    if publishing:
        if daily_used() >= args.max_videos:
            print(json.dumps({"status": "skipped_daily_cap", "used_today": daily_used(),
                              "max_videos": args.max_videos}, indent=2))
            return

    # 1) figure out the genre (forced, or let the model pick) -> 2) for worldcup, PROBE which angle
    # (fan/match/streamer) is actually sourceable BEFORE committing to a title -- supply per angle
    # varies a lot on Reddit, so locking the angle blind (the old flow) kept silently dropping the
    # World Cup theme because the chosen angle often turned out unsourceable after the fact.
    if args.force_genre == "worldcup":
        topic = {"genre": "worldcup"}   # defer the actual title/angle LLM call until angle is known
    elif args.force_genre == "streamer" or source == "streamer":
        # Streamer mode is a dedicated source pool. Do not let the generic funny/fails finder or
        # its fallback rescue turn this account back into a mixed ranking feed.
        topic = run_tool("rank_topic.py", ["--niche", args.niche,
                                            "--force-genre", "streamer", "--out", TOPIC])
    elif args.force_genre:
        topic = run_tool("rank_topic.py", ["--niche", args.niche, "--force-genre", args.force_genre, "--out", TOPIC])
    else:
        topic = run_tool("rank_topic.py", ["--niche", args.niche, "--out", TOPIC])

    requested_genre = topic.get("genre")
    fallback_reason = None
    account_streamer_only = source == "streamer" or args.force_genre == "streamer"
    if account_streamer_only and requested_genre != "streamer":
        raise RuntimeError("Streamer-only account received a non-streamer topic; refusing to publish.")

    if topic.get("genre") == "streamer":
        _f, ferr = run_tool_safe("find_streamer_clips.py",
                                 ["--max", "30", "--history", HISTORY, "--out", CANDS])
        if ferr:
            # A scheduled slot with no source is an honest no-op: do not turn a temporary
            # YouTube search shortage into a red Actions run, and never rescue it with generic
            # fails/football clips because this account is streamer-only.
            if os.environ.get("NO_SOURCE_OK") == "1":
                payload = {"status": "no_source", "content_policy": "streamer-only",
                           "source_mode": source, "requested_genre": requested_genre,
                           "detail": ferr}
                if _f and isinstance(_f, dict) and _f.get("count") is not None:
                    payload["candidate_count"] = _f["count"]
                emit(payload)
                return
            raise RuntimeError(f"streamer source failed: {ferr}")
    elif topic.get("genre") == "worldcup":
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
        find_args = ["--out", CANDS, "--source", source]
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
        run_tool("find_ranking_clips.py", ["--genre", "fails", "--source", source, "--out", CANDS])
        topic = run_tool("rank_topic.py", ["--niche", args.niche, "--force-genre", "fails", "--out", TOPIC])

    _r, rerr = run_tool_safe("rank_clips.py", ["--candidates", CANDS, "--topic", TOPIC, "--out", RANKED])
    if rerr and topic.get("genre") != "fails" and not no_reddit_rescue:
        # last-resort safety net (e.g. re-classification flake right after the probe confirmed
        # enough candidates) -- drop the theme for this run rather than crash
        fallback_reason = fallback_reason or f"rank_clips({requested_genre}): {rerr}"
        print(f"::warning::{fallback_reason}", file=sys.stderr)
        run_tool("find_ranking_clips.py", ["--genre", "fails", "--source", source, "--out", CANDS])
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

    # 4) background music -> 5) build the video.  Standalone streamer clips keep original audio
    # and use a single source moment; ranked controls keep the existing #5->#1 countdown and
    # branded bed.  Both paths use the same strict streamer candidate/ranking gate above.
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
    if selected_format == "ranking" and not music_path and BG_BED.is_file():
        music_path = str(BG_BED)

    if selected_format == "standalone":
        ranked_data = load_json(RANKED) or {}
        ranked_entries = ranked_data.get("entries") or []
        best = next((entry for entry in ranked_entries if entry.get("rank") == 1), None)
        if not best:
            raise RuntimeError("Standalone streamer mode could not identify the ranked #1 source")
        if (best.get("content_type") != "streamer_clip"
                or best.get("content_policy") != "streamer-only"
                or not best.get("streamer_identity")):
            raise RuntimeError("Standalone streamer mode received an unverified source entry")
        build_args = ["--url", best["url"], "--title", best["title"],
                      "--handle", "@itsmomoclips", "--badge", "MOMOCLIPS / STREAMER CLIP",
                      "--source-handle", best.get("streamer_identity") or best.get("channel") or "",
                      # The live winners hold attention for roughly 20-24 seconds on average;
                      # a standalone control should finish the payoff before the 58s countdown
                      # ceiling. Ranking controls keep their separate 58s budget below.
                      "--max-secs", "45", "--cta-text", "FOLLOW FOR MORE STREAMER MOMENTS",
                      "--out", FINAL]
        # Standalone mode intentionally keeps source audio as the creative signal. An explicitly
        # requested --music still works for controlled tests, but auto mode does not add a bed.
        if args.music:
            build_args += ["--music", args.music]
        build, build_err = run_tool_safe("build_clip.py", build_args)
    else:
        build_args = ["--ranked", RANKED, "--max-total", "58", "--per-clip", str(args.per_clip),
                      "--title", topic["title"], "--out", FINAL]
        if topic.get("genre") == "streamer":
            # A streamer ranking is always a real #5 -> #1 countdown, never a silently shortened
            # Top-3/Top-4 after a download or normalization failure.
            build_args += ["--min-clips", "5"]
        if music_path:
            build_args += ["--music", music_path]
        build, build_err = run_tool_safe("build_ranking_video.py", build_args)
    if build_err:
        # The source finder can return valid streamer metadata while YouTube blocks every
        # media download route a few seconds later. Scheduled/no-upload diagnostics should
        # report that as an honest no-post, not a red Actions failure. Never use this escape
        # hatch for a real non-streamer build or for unrelated renderer bugs.
        if (os.environ.get("NO_SOURCE_OK") == "1"
                and topic.get("genre") == "streamer"
                and (_is_streamer_source_starvation(build_err)
                     or (selected_format == "standalone" and _is_streamer_clip_download_failure(build_err)))):
            candidate_data = load_json(CANDS)
            payload = _streamer_no_source_payload(
                source, requested_genre, build_err,
                len(candidate_data.get("candidates", [])) if isinstance(candidate_data, dict) else None,
            )
            payload["format"] = selected_format
            emit(payload)
            return
        raise RuntimeError(build_err)
    if not isinstance(build, dict):
        raise RuntimeError("build_ranking_video.py returned no build result")

    # Instagram rejected the two latest ranking posts with an explicit "re-export as MP4
    # (H.264 video, AAC audio)" error. Do one final, in-place delivery encode after the creative
    # renderer and before hosting so every platform receives the same verified artifact.
    media, media_err = run_tool_safe(
        "prepare_upload_media.py", ["--input", FINAL, "--output", FINAL])
    if media_err:
        raise RuntimeError(media_err)
    if not media or not (media.get("contract") or {}).get("valid"):
        raise RuntimeError("prepare_upload_media.py returned no valid media contract")

    # 5) per-platform captions/hashtags (write a tiny story-like file for build_captions)
    title = (build.get("title") or topic["title"]) if selected_format == "standalone" else topic["title"]
    if selected_format == "standalone":
        standalone_entry = next((entry for entry in (load_json(RANKED) or {}).get("entries", [])
                                 if entry.get("rank") == 1), {})
        description = standalone_entry.get("title") or title
        tag_seed = ["streamer", "streamerclips", "liveclip", "shorts"]
    else:
        description = topic.get("hook", title)
        tag_seed = ["ranking", "top5", "countdown", "shorts"]
    tags = [w for w in "".join(c if c.isalnum() else " " for c in title.lower()).split() if len(w) > 3]
    with open(ROOT / RANK_STORY, "w", encoding="utf-8") as f:
        json.dump({"title": title, "description": description,
                   "tags": (tags + tag_seed + ["viral"])[:15]}, f)
    run_tool_safe("build_captions.py", ["--story", RANK_STORY, "--out", CAPMETA])
    meta = load_json(CAPMETA) or {}

    source_entry = None
    if selected_format == "standalone":
        source_entry = next((entry for entry in (load_json(RANKED) or {}).get("entries", [])
                             if entry.get("rank") == 1), None)
    result = {"status": "built", "title": title, "final": FINAL,
              "byte_size": build.get("byte_size"), "duration_sec": build.get("duration_sec"),
              "media_contract": media.get("contract"),
              "entries": build.get("entries"), "elapsed_sec": round(time.time() - t0, 1),
              "format": selected_format,
              "format_requested": args.format,
              "format_experiment": {"default": "standalone", "ranked_control_every": 5},
              "source_entry": source_entry,
              "source_mode": source,
              "requested_genre": requested_genre, "used_genre": topic.get("genre"),
              "content_policy": "streamer-only" if topic.get("genre") == "streamer" else None,
              "fallback_reason": fallback_reason, "delivery": {}}

    with open(ROOT / REVIEW_MANIFEST, "w", encoding="utf-8") as handle:
        json.dump({
            "status": "built", "account": "@itsmomoclips", "format": selected_format,
            "content_policy": result["content_policy"], "title": title,
            "duration_sec": result["duration_sec"], "byte_size": result["byte_size"],
            "source_entry": source_entry,
            "quality_contract": {"vertical": "1080x1920", "max_duration_sec": 59,
                                 "audio_required": True, "video_codec": "h264",
                                 "audio_codec": "aac", "pixel_format": "yuv420p",
                                 "faststart": True, "streamer_only": True},
            "delivery_contract": {"required": sorted(required_platforms),
                                   "retry_is_provider_side": True,
                                   "no_delete_without_analytics": True},
        }, handle, indent=2, ensure_ascii=True)

    # 6) deliver. Host the finished MP4 once for the public-url platforms, then use the local
    # file for TikTok's FILE_UPLOAD API. The old flow hosted separately for YouTube and Instagram,
    # which doubled the number of failure points and could leave one platform silently skipped.
    published = False
    host_url = None
    host_error = None
    needs_public_url = publishing and any(p in platforms for p in ("youtube", "instagram"))
    if needs_public_url:
        host, herr = run_tool_safe("host_public.py", ["--video", FINAL])
        host_url = (host or {}).get("url")
        host_error = herr or (None if host_url else "host_public returned no url")

    if publishing and "youtube" in platforms:
        yt = (meta.get("youtube") or {})
        if host_error:
            result["delivery"]["youtube"] = {"skipped": host_error.splitlines()[0][:140]}
        else:
            m, err = run_tool_safe("upload_youtube.py", ["--video-url", host_url,
                                       "--title", yt.get("title", title),
                                       "--description", yt.get("description", ""),
                                       "--tags", ",".join(yt.get("tags", []) or ["shorts"]),
                                       "--privacy", args.privacy, "--confirm"])
            ok = not err and (m or {}).get("status") in {"uploaded", "already_published"}
            result["delivery"]["youtube"] = ({"skipped": err.splitlines()[0][:140],
                                                 "diagnostics": {k: m.get(k) for k in
                                                                 ("post_id", "retry_attempted", "ambiguous", "platform_status", "poll_error")
                                                                 if (m or {}).get(k) not in (None, "", {})}}
                                                if err else {"url": m.get("url")})
            published = published or ok

    if publishing and "instagram" in platforms:
        ig = (meta.get("instagram") or {})
        if host_error:
            result["delivery"]["instagram"] = {"skipped": host_error.splitlines()[0][:140]}
        else:
            m, err = run_tool_safe("upload_instagram.py", ["--video-url", host_url,
                                       "--caption", ig.get("caption", title), "--confirm"])
            ok = not err and (m or {}).get("status") in {"uploaded", "already_published"}
            result["delivery"]["instagram"] = ({"skipped": err.splitlines()[0][:140],
                                                   "diagnostics": {k: m.get(k) for k in
                                                                   ("post_id", "retry_attempted", "ambiguous", "platform_status", "poll_error")
                                                                   if (m or {}).get(k) not in (None, "", {})}}
                                                  if err else {"media_id": m.get("post_id") or m.get("media_id")})
            published = published or ok
            if ok and m:
                post_id = m.get("post_id") or m.get("media_id")
                if post_id:
                    log_ig_post(
                        post_id,
                        style=f"streamer-{selected_format}",
                        experiment=(args.format == "auto" and selected_format == "ranking"),
                        context={"format": selected_format, "source": "rank_autopost",
                                 "content_policy": "streamer-only",
                                 "title_signal_score": (source_entry or {}).get("signal_score"),
                                 "duration_sec": (media.get("contract") or {}).get("duration_sec")},
                    )

    if publishing and "tiktok" in platforms:
        tt = (meta.get("tiktok") or {})
        tiktok_privacy = args.tiktok_privacy or (
            "PUBLIC_TO_EVERYONE" if args.privacy == "public" else "SELF_ONLY")
        m, err = run_tool_safe("upload_tiktok.py", ["--video", FINAL,
                                    "--title", tt.get("caption", title),
                                    "--privacy", tiktok_privacy, "--confirm"])
        ok = not err and (m or {}).get("status") in {"uploaded", "already_published"}
        result["delivery"]["tiktok"] = ({"skipped": err.splitlines()[0][:140]}
                                          if err else {"publish_id": m.get("publish_id")})
        published = published or ok

    if publishing and "email" in platforms:
        m, err = run_tool_safe("email_video.py", ["--video", FINAL, "--captions-meta", CAPMETA,
                                                  "--subject", f"Ranking Short: {title}"])
        result["delivery"]["email"] = {"skipped": err.splitlines()[0][:140]} if err else {"sent_to": m.get("to")}
    if "export" in platforms:
        m, err = run_tool_safe("export_local.py", ["--video", FINAL, "--captions-meta", CAPMETA, "--title", title])
        result["delivery"]["export"] = {"error": err.splitlines()[0][:140]} if err else {"folder": m.get("folder")}

    # A workflow must never look green when one of its promised destinations failed.  Keep the
    # required set separate from the full platform list so optional integrations (currently
    # TikTok/email when their secrets are absent) can be reported without blocking YouTube and
    # Instagram.  If one platform did publish, consume the source once to avoid a duplicate on
    # the next poll; the non-zero exit still makes the partial delivery visible to Actions.
    required_failures = []
    if publishing:
        for platform in sorted(required_platforms & set(platforms)):
            delivery = result["delivery"].get(platform) or {}
            if delivery.get("skipped") or delivery.get("error"):
                required_failures.append({
                    "platform": platform,
                    "detail": delivery.get("skipped") or delivery.get("error"),
                })
        if required_failures:
            result["required_delivery_failures"] = required_failures

    # A failed build/upload must be retryable. The old code incremented the daily cap before
    # building and marked source clips used before delivery, so one transient LLM, host, or API
    # failure could make later scheduled runs appear to have "stopped" permanently.
    if published:
        result["status"] = "partial_upload" if required_failures else "uploaded"
        daily_increment()
        record_used(RANKED, selected_format)
    elif required_failures:
        result["status"] = "delivery_failed"

    if publishing:
        save_format_state(format_state, selected_format, status=result.get("status", "built"))

    # No-upload runs are the workflow's media-QA mode: keep the finished MP4 until the
    # upload-artifact step can collect it. Real publishing runs may still clean scratch files.
    if not args.keep_tmp and publishing:
        import shutil
        # Wipe the downloaded source clips + intermediates so disk doesn't fill up run to run.
        shutil.rmtree(ROOT / ".tmp" / "rank", ignore_errors=True)
        for p in (CANDS, RANKED, RANK_STORY, FINAL, CAPMETA, ".tmp/music.mp3", ".tmp/email_small.mp4"):
            try:
                (ROOT / p).unlink()
            except (OSError, IsADirectoryError):
                pass

    emit(result)   # ASCII-safe on Windows cp1252 (titles can contain non-cp1252 chars)
    if required_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
