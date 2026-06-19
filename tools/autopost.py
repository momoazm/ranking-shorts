"""Autonomous orchestrator: build ONE Peter-vs-Stewie dialogue Short end-to-end and
(optionally) publish it to the connected YouTube channel.

This is the cloud entry point run on a schedule (GitHub Actions, every 4h). It owns NO new
pipeline logic — it just subprocess-calls the existing WAT tools in the right order, with the
right cwd, parsing each tool's single-JSON-object stdout and failing loudly on any error.

Forced choices that make it safe + free to run unattended:
  - --engine edge       : Edge-TTS only. Fish Audio is NEVER called -> 0 paid credits touched.
  - --model tiny        : smallest faster-whisper model -> fast caption alignment on a CPU runner.
  - subway_loop.mp4     : the one bundled background (the loop ships a single trimmed clip).
  - title/description/tags come straight from the LLM script (write_story), so each post gets
    a fresh, on-topic, high-CTR title + hashtags with no human in the loop.

Pipeline (each step = one tool, cwd = project root):
  write_story -> generate_voiceover -> align_captions -> build_audio_mix -> assemble_video
  -> upload_youtube (only with real publish; skipped by --no-upload).

Usage:
    python tools/autopost.py [--no-upload] [--privacy public|unlisted|private]
        [--seconds 45] [--model tiny] [--engine edge] [--keep-tmp]

Prints ONE JSON object summarizing the run (and the uploaded URL when published).
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # the project root (cwd for every tool)
TMP = ROOT / ".tmp"
PY = sys.executable

# Bundled assets (relative to ROOT).
BACKGROUND = "assets/backgrounds/subway_loop.mp4"
WHOOSH = "assets/sfx/whoosh.mp3"
BOOM = "assets/sfx/boom.mp3"

# Pipeline artifact paths (under .tmp/).
STORY = ".tmp/story.json"
NARRATION = ".tmp/narration.mp3"
SEGMENTS = ".tmp/segments.json"
CAPTIONS = ".tmp/captions.ass"
MIXED = ".tmp/narration_mixed.mp3"
FINAL = ".tmp/final.mp4"


def run_tool(name, args):
    """Run `python tools/<name> <args>` from ROOT; return its parsed JSON stdout.

    Every WAT tool prints exactly one JSON object and exits 0 on success / 1 with an
    {"error": ...} object on failure. We raise RuntimeError on a bad exit, a non-JSON
    stdout, or an "error" key so the caller (and the CI step) fails fast.
    """
    cmd = [PY, f"tools/{name}", *args]
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    out = (proc.stdout or "").strip()
    # WAT tools emit ONE pretty-printed (multi-line) JSON object. Parse the whole stdout;
    # if stray lines surround it, fall back to the outermost {...} block.
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
        raise RuntimeError(
            f"{name} did not return JSON (exit {proc.returncode}).\n"
            f"stdout:\n{out[-800:]}\nstderr:\n{(proc.stderr or '')[-800:]}"
        )
    if proc.returncode != 0 or "error" in data:
        raise RuntimeError(f"{name} failed: {data.get('error', out[-500:])}")
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-upload", action="store_true",
                        help="Build the video but do NOT publish (local testing).")
    parser.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"])
    parser.add_argument("--characters", default="peter,stewie")
    parser.add_argument("--seconds", type=int, default=55, help="Target script length")
    parser.add_argument("--model", default="tiny", help="faster-whisper model (tiny is fast on CPU)")
    parser.add_argument("--engine", default="edge", choices=["edge", "auto", "fish"],
                        help="TTS engine. Forced edge in the cloud loop (free, no Fish credits).")
    parser.add_argument("--background", default=BACKGROUND)
    parser.add_argument("--keep-tmp", action="store_true", help="Keep .tmp artifacts after the run.")
    args = parser.parse_args()

    TMP.mkdir(exist_ok=True)
    t0 = time.time()
    steps = {}

    # 1) Script (LLM) — also our title/description/tags source.
    steps["write_story"] = run_tool("write_story.py", [
        "--format", "dialogue", "--characters", args.characters,
        "--seconds", str(args.seconds), "--out", STORY,
    ])
    with open(ROOT / STORY, "r", encoding="utf-8") as f:
        story = json.load(f)
    title = story["title"]
    description = story.get("description", "")
    tags = ",".join(story.get("tags", []) or ["shorts"])

    # 2) Multi-voice voiceover (Edge) -> narration.mp3 + segments.json.
    steps["voiceover"] = run_tool("generate_voiceover.py", [
        "--text-from", STORY, "--engine", args.engine,
        "--out", NARRATION, "--segments-out", SEGMENTS,
    ])

    # 3) Word-by-word per-speaker captions.
    steps["captions"] = run_tool("align_captions.py", [
        "--audio", NARRATION, "--segments", SEGMENTS,
        "--model", args.model, "--out", CAPTIONS,
    ])

    # 4) SFX mix: whoosh per line + boom on hook & punchline.
    audio_for_video = NARRATION
    if (ROOT / WHOOSH).is_file() or (ROOT / BOOM).is_file():
        mix_args = ["--audio", NARRATION, "--segments", SEGMENTS,
                    "--boom-on", "both", "--out", MIXED]
        if (ROOT / WHOOSH).is_file():
            mix_args += ["--whoosh", WHOOSH]
        if (ROOT / BOOM).is_file():
            mix_args += ["--boom", BOOM]
        steps["audio_mix"] = run_tool("build_audio_mix.py", mix_args)
        audio_for_video = MIXED

    # 5) Assemble the 1080x1920 short (avatars + active-speaker bounce + burned captions).
    steps["assemble"] = run_tool("assemble_video.py", [
        "--audio", audio_for_video, "--captions", CAPTIONS,
        "--background", args.background, "--story", STORY,
        "--segments", SEGMENTS, "--bounce", "--out", FINAL,
    ])

    result = {
        "status": "built",
        "title": title,
        "final": FINAL,
        "byte_size": steps["assemble"].get("byte_size"),
        "duration_sec": steps["assemble"].get("duration_sec"),
        "elapsed_sec": round(time.time() - t0, 1),
        "uploaded": False,
    }

    # 6) Publish (the only irreversible step).
    if not args.no_upload:
        up = run_tool("upload_youtube.py", [
            "--video", FINAL, "--title", title, "--description", description,
            "--tags", tags, "--privacy", args.privacy, "--confirm",
        ])
        result.update({
            "status": "uploaded",
            "uploaded": True,
            "video_id": up.get("video_id"),
            "url": up.get("url"),
            "privacy": up.get("privacy"),
            "channel_title": up.get("channel_title"),
        })

    if not args.keep_tmp:
        for p in (NARRATION, SEGMENTS, CAPTIONS, MIXED):
            try:
                (ROOT / p).unlink()
            except OSError:
                pass

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
