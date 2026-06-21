"""Autonomous orchestrator: build ONE brainrot dialogue Short end-to-end and (optionally) publish
it to YouTube + TikTok + Instagram.

This is the cloud entry point run on a schedule (GitHub Actions, every 4h). It owns NO new
pipeline logic — it subprocess-calls the existing WAT tools in the right order, parses each tool's
single-JSON-object stdout, and fails loudly on a core error while DEGRADING GRACEFULLY on optional
ones (research, AI visuals, a platform whose API isn't approved yet).

Key behaviors:
  - VISUALS: default --visual-mode aigen builds the whole video from Nano Banana scene images
    (generate_scene_images.py). If that can't run (free quota exhausted, key unset, safety block),
    it auto-downgrades to the reliable gameplay-background mode for that one video.
  - HASHTAGS: build_playbook (cached ~daily) feeds trending hooks/hashtags into write_story, and
    build_captions emits per-platform caption/hashtag blocks so every upload is well-tagged.
  - VOLUME: a date-stamped daily counter enforces --max-videos (default 6) so retries / manual
    re-runs / overlapping jobs can't blow past the cross-post target.
  - 3 PLATFORMS: posts one video to each of --platforms; a platform that isn't configured/approved
    is skipped with a clear status instead of failing the run. YouTube upload is the irreversible
    step that's always gated by --confirm inside upload_youtube.py.

Usage:
    python tools/autopost.py [--no-upload] [--visual-mode aigen|gameplay]
        [--platforms youtube,tiktok,instagram] [--privacy public|unlisted|private]
        [--max-videos 6] [--seconds 45] [--keep-tmp]
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

from _common import emit

ROOT = Path(__file__).resolve().parent.parent
TMP = ROOT / ".tmp"
PY = sys.executable

BACKGROUND = "assets/backgrounds/subway_loop.mp4"
WHOOSH = "assets/sfx/whoosh.mp3"
BOOM = "assets/sfx/boom.mp3"

STORY = ".tmp/story.json"
NARRATION = ".tmp/narration.mp3"
SEGMENTS = ".tmp/segments.json"
CAPTIONS = ".tmp/captions.ass"
MIXED = ".tmp/narration_mixed.mp3"
FINAL = ".tmp/final.mp4"
PLAYBOOK = ".tmp/playbook.json"
SCENES = ".tmp/scenes.json"
SCENES_DIR = ".tmp/scenes"
CAPMETA = ".tmp/captions_meta.json"
DAILY_COUNT = ".tmp/daily_count.json"


def run_tool(name, args):
    """Run `python tools/<name> <args>` from ROOT; return its parsed JSON stdout, raising on error."""
    data, err = run_tool_safe(name, args)
    if err:
        raise RuntimeError(err)
    return data


def run_tool_safe(name, args):
    """Like run_tool but returns (data, error_message) instead of raising — for optional steps."""
    cmd = [PY, f"tools/{name}", *args]
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
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
        return None, (f"{name} did not return JSON (exit {proc.returncode}).\n"
                      f"stdout:\n{out[-600:]}\nstderr:\n{(proc.stderr or '')[-600:]}")
    if proc.returncode != 0 or "error" in data:
        return data, f"{name} failed: {data.get('error', out[-400:])}"
    return data, None


def load_json(path):
    try:
        with open(ROOT / path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


# ----------------------------- daily volume cap -----------------------------
def daily_used():
    data = load_json(DAILY_COUNT) or {}
    return data.get("count", 0) if data.get("date") == date.today().isoformat() else 0


def daily_increment():
    used = daily_used()
    with open(ROOT / DAILY_COUNT, "w", encoding="utf-8") as f:
        json.dump({"date": date.today().isoformat(), "count": used + 1}, f)


# ----------------------------- playbook (cached ~daily) -----------------------------
def ensure_playbook():
    """Best-effort: (re)build the playbook at most once/day. Never fatal — write_story works without."""
    pb = load_json(PLAYBOOK)
    if pb and pb.get("generated_at") == date.today().isoformat():
        return "cached"
    _data, err = run_tool_safe("build_playbook.py", ["--out", PLAYBOOK])
    return "built" if not err else f"skipped ({err.splitlines()[0][:120]})"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-upload", action="store_true")
    parser.add_argument("--visual-mode", default="aigen", choices=["aigen", "composite", "gameplay"],
                        help="aigen = cinematic short-movie scenes with characters drawn in & changing "
                             "settings (default); composite = real character PNGs over AI backgrounds; "
                             "gameplay = old background loop")
    parser.add_argument("--allow-gameplay-fallback", action="store_true",
                        help="If Nano Banana scene generation fails, fall back to the gameplay "
                             "background instead of failing. OFF by default (stay fully AI-generated).")
    parser.add_argument("--platforms", default="youtube,email",
                        help="Targets: youtube,tiktok,instagram (auto-post); 'email' (Gmail the "
                             "video+captions to yourself); 'export' (save to exports/ folder)")
    parser.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"])
    parser.add_argument("--characters", default="tung,tralalero",
                        help="Brainrot duo (registry keys). Default: the Italian-brainrot meme duo.")
    parser.add_argument("--seconds", type=int, default=60, help="Target script length (longer story)")
    parser.add_argument("--rate", default="+30%", help="Edge-TTS speaking rate (faster talking)")
    parser.add_argument("--model", default="base", help="faster-whisper model")
    parser.add_argument("--engine", default="edge", choices=["edge", "auto", "fish"])
    parser.add_argument("--background", default=BACKGROUND)
    parser.add_argument("--max-videos", type=int, default=int(os.environ.get("MAX_DAILY_VIDEOS", "6")),
                        help="Hard daily cap across runs (default 6 = YouTube's free upload ceiling)")
    parser.add_argument("--max-images", type=int, default=30,
                        help="Cap on images per video; more = more pictures per story section (free FLUX)")
    parser.add_argument("--keep-tmp", action="store_true")
    args = parser.parse_args()

    TMP.mkdir(exist_ok=True)
    platforms = [p.strip().lower() for p in args.platforms.split(",") if p.strip()]
    t0 = time.time()

    # Daily cap: reserve a slot up front so double/overlapping runs can't exceed it.
    publishing = not args.no_upload
    if publishing:
        used = daily_used()
        if used >= args.max_videos:
            emit({"status": "skipped_daily_cap", "used_today": used, "max_videos": args.max_videos})
            return
        daily_increment()

    steps = {}

    # 0) Research playbook (cached daily; best-effort).
    steps["playbook"] = ensure_playbook()

    # 1) Script (LLM), shaped by the playbook — also the title/hashtags source.
    run_tool("write_story.py", [
        "--format", "dialogue", "--characters", args.characters,
        "--seconds", str(args.seconds), "--playbook", PLAYBOOK, "--out", STORY,
    ])
    story = load_json(STORY)
    title = story["title"]

    # 2) Multi-voice voiceover (Edge) -> narration.mp3 + segments.json.
    steps["voiceover"] = run_tool("generate_voiceover.py", [
        "--text-from", STORY, "--engine", args.engine, "--rate", args.rate,
        "--out", NARRATION, "--segments-out", SEGMENTS,
    ])

    # 3) Word-by-word per-speaker captions.
    steps["captions"] = run_tool("align_captions.py", [
        "--audio", NARRATION, "--segments", SEGMENTS, "--model", args.model, "--out", CAPTIONS,
    ])

    # 4) SFX mix: whoosh per line + boom on hook & punchline.
    audio_for_video = NARRATION
    if (ROOT / WHOOSH).is_file() or (ROOT / BOOM).is_file():
        mix_args = ["--audio", NARRATION, "--segments", SEGMENTS, "--boom-on", "both", "--out", MIXED]
        if (ROOT / WHOOSH).is_file():
            mix_args += ["--whoosh", WHOOSH]
        if (ROOT / BOOM).is_file():
            mix_args += ["--boom", BOOM]
        steps["audio_mix"] = run_tool("build_audio_mix.py", mix_args)
        audio_for_video = MIXED

    # 5) VISUALS: build the WHOLE video from Nano Banana scenes (no gameplay background).
    #    By default there is NO subway/gameplay fallback — if scene generation fails the run fails,
    #    so we never ship a gameplay-background video. Opt into a fallback with --allow-gameplay-fallback.
    visual_mode = args.visual_mode
    scenes_arg = []
    if visual_mode in ("aigen", "composite"):
        scene_args = [
            "--story", STORY, "--segments", SEGMENTS, "--audio", audio_for_video,
            "--out-dir", SCENES_DIR, "--manifest", SCENES, "--max-images", str(args.max_images),
        ]
        if visual_mode == "composite":
            # Empty 3D backgrounds — the real character PNGs get composited on top at assembly.
            scene_args += ["--scene-content", "background"]
        _data, err = run_tool_safe("generate_scene_images.py", scene_args)
        if err:
            if args.allow_gameplay_fallback:
                visual_mode = "gameplay"
                steps["scenes"] = f"downgraded to gameplay ({err.splitlines()[0][:140]})"
            else:
                raise RuntimeError(
                    "Nano Banana scene generation failed and gameplay fallback is OFF "
                    f"(fully-AI mode). Fix the cause or pass --allow-gameplay-fallback. Error: {err}")
        else:
            scenes_arg = ["--scenes", SCENES]
            steps["scenes"] = _data

    # 6) Assemble the 1080x1920 short.
    assemble_args = ["--audio", audio_for_video, "--captions", CAPTIONS, "--story", STORY,
                     "--segments", SEGMENTS, "--out", FINAL]
    if scenes_arg:
        assemble_args += scenes_arg
        if visual_mode == "composite":
            # Overlay the real character renders on the AI backgrounds, active-speaker highlight + bounce.
            assemble_args += ["--overlay-characters", "--bounce"]
    else:
        assemble_args += ["--background", args.background, "--bounce"]
    steps["assemble"] = run_tool("assemble_video.py", assemble_args)

    # 7) Per-platform captions/hashtags (deterministic; falls back to story fields on failure).
    cap, cap_err = run_tool_safe("build_captions.py", ["--story", STORY, "--playbook", PLAYBOOK, "--out", CAPMETA])
    meta = load_json(CAPMETA) or {}
    yt = meta.get("youtube", {})
    yt_title = yt.get("title") or title
    yt_desc = yt.get("description") or story.get("description", "")
    yt_tags = ",".join(yt.get("tags") or story.get("tags", []) or ["shorts"])

    result = {
        "status": "built",
        "title": title,
        "visual_mode": visual_mode,
        "final": FINAL,
        "byte_size": steps["assemble"].get("byte_size"),
        "duration_sec": steps["assemble"].get("duration_sec"),
        "playbook": steps.get("playbook"),
        "scenes": steps.get("scenes") if isinstance(steps.get("scenes"), str) else (steps.get("scenes") or {}).get("count"),
        "elapsed_sec": round(time.time() - t0, 1),
        "uploads": {},
    }

    # 7b) Semi-manual delivery (no IG/TikTok API needed): email the video to yourself and/or
    #     save it to the exports/ folder, both with ready-to-paste captions.
    if "email" in platforms:
        mdata, merr = run_tool_safe("email_video.py", [
            "--video", FINAL, "--captions-meta", CAPMETA,
            "--subject", f"New brainrot Short: {title}",
        ])
        result["email"] = {"skipped": merr.splitlines()[0][:160]} if merr else {
            "sent_to": mdata.get("to"), "message_id": mdata.get("message_id")}

    if "export" in platforms:
        edata, eerr = run_tool_safe("export_local.py", [
            "--video", FINAL, "--captions-meta", CAPMETA, "--title", title,
        ])
        result["export"] = {"error": eerr.splitlines()[0][:160]} if eerr else {"folder": edata.get("folder")}

    # 8) Publish to each platform (graceful per-platform degradation).
    if publishing:
        uploads = {}

        if "youtube" in platforms:
            ydata, yerr = run_tool_safe("upload_youtube.py", [
                "--video", FINAL, "--title", yt_title, "--description", yt_desc,
                "--tags", yt_tags, "--privacy", args.privacy, "--confirm",
            ])
            uploads["youtube"] = {"skipped": yerr.splitlines()[0][:160]} if yerr else {
                "video_id": ydata.get("video_id"), "url": ydata.get("url"), "privacy": ydata.get("privacy")}

        if "tiktok" in platforms:
            tcap = (meta.get("tiktok", {}) or {}).get("caption") or yt_title
            tdata, terr = run_tool_safe("upload_tiktok.py", ["--video", FINAL, "--title", tcap, "--confirm"])
            uploads["tiktok"] = {"skipped": terr.splitlines()[0][:160]} if terr else {
                "publish_id": tdata.get("publish_id"), "status": tdata.get("status")}

        if "instagram" in platforms:
            uploads["instagram"] = post_instagram(meta.get("instagram", {}), yt_desc)

        result["uploads"] = uploads
        result["status"] = "uploaded"

    if not args.keep_tmp:
        for p in (NARRATION, SEGMENTS, CAPTIONS, MIXED):
            try:
                (ROOT / p).unlink()
            except OSError:
                pass

    emit(result)


def post_instagram(ig_meta, fallback_caption):
    """IG needs a public URL first (host_public.py), then the Graph API two-step publish."""
    hdata, herr = run_tool_safe("host_public.py", ["--video", FINAL])
    if herr:
        return {"skipped": f"host_public failed: {herr.splitlines()[0][:140]}"}
    url = hdata.get("url")
    caption = (ig_meta or {}).get("caption") or fallback_caption
    idata, ierr = run_tool_safe("upload_instagram.py", ["--video-url", url, "--caption", caption, "--confirm"])
    if ierr:
        return {"skipped": ierr.splitlines()[0][:160], "public_url": url}
    return {"media_id": idata.get("media_id"), "status": idata.get("status")}


if __name__ == "__main__":
    main()
