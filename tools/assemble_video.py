"""Compose the final vertical (1080x1920) short with ffmpeg: a random window of the gameplay
background, scaled/cropped to cover, with the voiceover (optional ducked music bed) and the
word-by-word .ass captions burned in.

DIALOGUE MODE: when --story is a dialogue script whose characters have images on disk, the two
avatars are overlaid (A bottom-left, B bottom-right). Each is dimmed by default and "lights up"
(full opacity, slightly larger) only while that character is speaking, driven by the --segments
timeline. Captions sit mid-screen above them.

Uses the libx264 + libass-enabled ffmpeg bundled by imageio-ffmpeg.

Usage:
    python tools/assemble_video.py --audio .tmp/narration.mp3 --captions .tmp/captions.ass \\
        --background assets/backgrounds/minecraft_parkour.mp4 [--music assets/music/bed.mp3] \\
        [--story .tmp/story.json] [--segments .tmp/segments.json] [--out .tmp/final.mp4]

Prints JSON: {"path": ..., "byte_size": N, "duration_sec": F, "background_start": F, "characters": [...]}
"""
import argparse
import json
import os
import random

from _common import REPO_ROOT, emit, fail
from _media import run_ffmpeg, probe_duration

OUT_W, OUT_H, FPS = 1080, 1920, 30
DIM_H, ACT_H = 500, 580       # avatar height when idle vs. actively speaking (grows = "leans in")
DIM_ALPHA = 0.5               # idle avatar opacity
SIDE_MARGIN, BOTTOM_MARGIN = 24, 30


def ass_filter_path(path):
    """ffmpeg's ass filter treats ':' and '\\' specially — pass a cwd-relative, forward-slash path."""
    rel = os.path.relpath(path, os.getcwd())
    return rel.replace("\\", "/")


def load_json(path):
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def enable_expr(name, segments):
    """ffmpeg enable= expression that's true while `name` is the active speaker."""
    spans = [f"between(t,{s['start']},{s['end']})" for s in segments
             if str(s.get("speaker", "")).lower() == name.lower()]
    return "+".join(spans) if spans else "0"


def bounce_expr(name, segments, amp, dur):
    """Upward 'hop' pixels: a half-sine bump for ~dur seconds at the start of each of this
    speaker's lines, so the active avatar bounces when it starts talking. 0 otherwise."""
    starts = [s["start"] for s in segments if str(s.get("speaker", "")).lower() == name.lower()]
    if not starts:
        return None
    terms = "+".join(f"(between(t,{s},{round(s + dur, 3)})*sin(PI*(t-{s})/{dur}))" for s in starts)
    return f"{amp}*({terms})"


def overlay_chars(cast, segments, img_base_idx, bounce_px=0, bounce_dur=0.3):
    """Build the filter sub-graph that overlays the avatars onto [bg0], returns (graph, last_label).

    Each character gets a dim always-on copy plus a full-opacity copy enabled during its turns
    (if a segments timeline is available). With --bounce, the active copy hops at each line start.
    """
    graph = []
    last = "bg0"
    for slot, c in enumerate(cast):
        idx = img_base_idx + slot
        left = (slot == 0)
        x = f"{SIDE_MARGIN}" if left else f"main_w-overlay_w-{SIDE_MARGIN}"
        y = f"main_h-overlay_h-{BOTTOM_MARGIN}"

        if segments:
            graph.append(f"[{idx}:v]split=2[c{idx}x][c{idx}y]")
            graph.append(f"[c{idx}x]scale=-1:{DIM_H},format=rgba,colorchannelmixer=aa={DIM_ALPHA}[dim{idx}]")
            graph.append(f"[c{idx}y]scale=-1:{ACT_H},format=rgba[act{idx}]")
            graph.append(f"[{last}][dim{idx}]overlay=x={x}:y={y}[o{idx}d]")
            expr = enable_expr(c["name"], segments)
            y_act = y
            if bounce_px > 0:
                be = bounce_expr(c["name"], segments, bounce_px, bounce_dur)
                if be:
                    y_act = f"main_h-overlay_h-{BOTTOM_MARGIN}-({be})"
            # y/enable are single-quoted so the commas inside between()/sin() aren't parsed as
            # filtergraph separators.
            graph.append(f"[o{idx}d][act{idx}]overlay=x={x}:y='{y_act}':enable='{expr}'[o{idx}a]")
            last = f"o{idx}a"
        else:
            graph.append(f"[{idx}:v]scale=-1:{ACT_H},format=rgba[act{idx}]")
            graph.append(f"[{last}][act{idx}]overlay=x={x}:y={y}[o{idx}a]")
            last = f"o{idx}a"
    return graph, last


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", required=True, help="Voiceover mp3")
    parser.add_argument("--captions", required=True, help=".ass subtitle file")
    parser.add_argument("--background", required=True, help="Gameplay background mp4")
    parser.add_argument("--story", help="story.json (dialogue → overlay its characters)")
    parser.add_argument("--segments", default=".tmp/segments.json", help="Dialogue timeline for active-speaker highlight")
    parser.add_argument("--music", help="Optional background music bed (ducked under the VO)")
    parser.add_argument("--music-volume", type=float, default=0.12)
    parser.add_argument("--bounce", action="store_true", help="Active speaker hops when its line starts")
    parser.add_argument("--bounce-px", type=int, default=36, help="Bounce height in pixels")
    parser.add_argument("--tail", type=float, default=0.6, help="Seconds of silence/background after VO ends")
    parser.add_argument("--out", default=".tmp/final.mp4")
    args = parser.parse_args()

    for label, p in [("audio", args.audio), ("captions", args.captions), ("background", args.background)]:
        if not os.path.isfile(p):
            fail(f"{label} not found: {p}")
            return
    if args.music and not os.path.isfile(args.music):
        fail(f"music not found: {args.music}")
        return

    # Decide whether to overlay characters (dialogue story + at least one image present).
    cast = []
    story = load_json(args.story)
    if story and story.get("format") == "dialogue":
        for c in story.get("characters", []):
            img = c.get("image")
            if img and os.path.isfile(REPO_ROOT / img):
                cast.append({"name": c.get("name"), "image": img})
    segments = (load_json(args.segments) or {}).get("segments") if cast else None

    try:
        vo_dur = probe_duration(args.audio)
        bg_dur = probe_duration(args.background)
    except Exception as e:
        fail(f"Could not probe input durations: {e}")
        return

    total = round(vo_dur + args.tail, 2)
    loop_bg = bg_dur < total + 0.3
    bg_start = 0.0 if loop_bg else round(random.uniform(0, max(0.0, bg_dur - total - 0.2)), 2)

    ass = ass_filter_path(args.captions)

    # Inputs: background(0), audio(1), [music], then one image per overlaid character.
    ff = []
    if loop_bg:
        ff += ["-stream_loop", "-1"]
    ff += ["-ss", str(bg_start), "-i", args.background]   # 0
    ff += ["-i", args.audio]                              # 1
    next_idx = 2
    if args.music:
        ff += ["-stream_loop", "-1", "-i", args.music]    # 2
        next_idx = 3
    img_base_idx = next_idx
    for c in cast:
        ff += ["-loop", "1", "-i", str(REPO_ROOT / c["image"])]

    # Video graph: cover-scale the background, overlay avatars, then burn captions.
    vchain = [f"[0:v]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
              f"crop={OUT_W}:{OUT_H},setsar=1,fps={FPS}[bg0]"]
    if cast:
        ov, last = overlay_chars(cast, segments, img_base_idx,
                                 bounce_px=(args.bounce_px if args.bounce else 0))
        vchain += ov
        vchain.append(f"[{last}]ass={ass}[v]")
    else:
        vchain.append(f"[bg0]ass={ass}[v]")
    vfilter = ";".join(vchain)

    if args.music:
        afilter = (
            f";[1:a]volume=1.0[vo];[2:a]volume={args.music_volume}[bg];"
            f"[vo][bg]amix=inputs=2:duration=first:dropout_transition=0[a]"
        )
        amap = "[a]"
    else:
        afilter = ""
        amap = "1:a"

    ff += [
        "-filter_complex", vfilter + afilter,
        "-map", "[v]", "-map", amap,
        "-t", str(total),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "high", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        args.out,
    ]

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    try:
        run_ffmpeg(ff)
    except Exception as e:
        fail(f"Video assembly failed: {e}")
        return

    emit({
        "path": args.out,
        "byte_size": os.path.getsize(args.out),
        "duration_sec": total,
        "background_start": bg_start,
        "looped_background": loop_bg,
        "characters": [c["name"] for c in cast],
        "active_highlight": bool(cast and segments),
    })


if __name__ == "__main__":
    main()
