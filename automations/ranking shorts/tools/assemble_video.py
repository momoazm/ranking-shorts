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
# Avatar heights (idle vs. active). Kept modest so SQUARE character art (e.g. 1024x1024 brainrot
# renders) doesn't end up ~580px wide and overlap/cover the other character in the middle.
DIM_H, ACT_H = 430, 500
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


def overlay_chars(cast, segments, img_base_idx, bounce_px=0, bounce_dur=0.3, base_label="bg0"):
    """Build the filter sub-graph that overlays the avatars onto [base_label], returns (graph, last).

    Each character gets a dim always-on copy plus a full-opacity copy enabled during its turns
    (if a segments timeline is available). With --bounce, the active copy hops at each line start.
    """
    graph = []
    last = base_label
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


def assemble_aigen(args, manifest, total):
    """AIGEN MODE: build the video from a sequence of Nano Banana scene images (one per dialogue
    beat), each Ken-Burns zoomed and cut on the beat, with the .ass captions burned on top and the
    voiceover (optional ducked music) as audio. Hard cuts intentionally land on speaker changes,
    where the whoosh SFX already sits."""
    scenes = sorted(manifest.get("scenes", []), key=lambda s: s.get("index", 0))
    paths = [s["path"] for s in scenes if os.path.isfile(s["path"])]
    if len(paths) != len(scenes) or not scenes:
        raise RuntimeError("scenes manifest references missing image files")

    # Contiguous durations from each beat's start (no gaps); last beat fills the tail.
    starts = [float(s.get("start", 0)) for s in scenes]
    durs = []
    for i, st in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else total
        durs.append(max(0.4, round(end - st, 3)))

    ass = ass_filter_path(args.captions)
    ff = ["-i", args.audio]                       # 0 = voiceover
    music_idx = None
    if args.music:
        ff += ["-stream_loop", "-1", "-i", args.music]
        music_idx = 1
    img_base = (music_idx + 1) if music_idx is not None else 1
    for p, d in zip(paths, durs):
        ff += ["-loop", "1", "-t", str(d), "-i", p]

    # COMPOSITE: optionally overlay the REAL character PNGs on top of the AI 3D backgrounds, with the
    # active speaker lit up + bounce (driven by the dialogue segments) — exact character likeness.
    cast, segs = [], None
    if getattr(args, "overlay_characters", False):
        story = load_json(args.story)
        if story and story.get("format") == "dialogue":
            for c in story.get("characters", []):
                img = c.get("image")
                if img and os.path.isfile(REPO_ROOT / img):
                    cast.append({"name": c.get("name"), "image": img})
        segs = (load_json(args.segments) or {}).get("segments") if cast else None
    char_base = img_base + len(paths)
    for c in cast:
        ff += ["-loop", "1", "-i", str(REPO_ROOT / c["image"])]

    # Camera PAN per scene (not zoom): oversample 2x, hold a fixed slight overscan and slide the
    # crop window across the image. Direction alternates per shot (L->R, R->L, top->bottom, bottom->top)
    # so consecutive scenes feel dynamic and distinct.
    Z = 1.18
    vchain = []
    labels = []
    for k, d in enumerate(durs):
        idx = img_base + k
        frames = max(1, round(d * FPS))
        denom = max(frames - 1, 1)
        cx, cy = "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"
        direction = k % 4
        if direction == 0:      # pan left -> right
            xx, yy = f"(iw-iw/zoom)*on/{denom}", cy
        elif direction == 1:    # pan right -> left
            xx, yy = f"(iw-iw/zoom)*(1-on/{denom})", cy
        elif direction == 2:    # pan top -> bottom
            xx, yy = cx, f"(ih-ih/zoom)*on/{denom}"
        else:                   # pan bottom -> top
            xx, yy = cx, f"(ih-ih/zoom)*(1-on/{denom})"
        lab = f"v{k}"
        vchain.append(
            f"[{idx}:v]scale={OUT_W*2}:{OUT_H*2}:force_original_aspect_ratio=increase,"
            f"crop={OUT_W*2}:{OUT_H*2},"
            f"zoompan=z={Z}:d={frames}:x='{xx}':y='{yy}':s={OUT_W}x{OUT_H}:fps={FPS},"
            f"setsar=1[{lab}]"
        )
        labels.append(f"[{lab}]")
    vchain.append(f"{''.join(labels)}concat=n={len(labels)}:v=1:a=0[vcat]")
    if cast:
        ov, last = overlay_chars(cast, segs, char_base,
                                 bounce_px=(args.bounce_px if args.bounce else 0), base_label="vcat")
        vchain += ov
        vchain.append(f"[{last}]ass={ass}[v]")
    else:
        vchain.append(f"[vcat]ass={ass}[v]")
    vfilter = ";".join(vchain)

    if args.music:
        afilter = (f";[0:a]volume=1.0[vo];[{music_idx}:a]volume={args.music_volume}[bg];"
                   f"[vo][bg]amix=inputs=2:duration=first:dropout_transition=0[a]")
        amap = "[a]"
    else:
        afilter = ""
        amap = "0:a"

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
    run_ffmpeg(ff)
    emit({
        "path": args.out,
        "byte_size": os.path.getsize(args.out),
        "duration_sec": total,
        "visual_mode": "composite" if cast else "aigen",
        "scenes": len(paths),
        "characters": [c["name"] for c in cast],
    })


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", required=True, help="Voiceover mp3")
    parser.add_argument("--captions", required=True, help=".ass subtitle file")
    parser.add_argument("--background", help="Gameplay background mp4 (gameplay mode)")
    parser.add_argument("--scenes", help="scenes.json manifest (aigen mode: build from AI images)")
    parser.add_argument("--overlay-characters", action="store_true",
                        help="Composite the real character PNGs over the AI scene backgrounds")
    parser.add_argument("--story", help="story.json (dialogue → overlay its characters)")
    parser.add_argument("--segments", default=".tmp/segments.json", help="Dialogue timeline for active-speaker highlight")
    parser.add_argument("--music", help="Optional background music bed (ducked under the VO)")
    parser.add_argument("--music-volume", type=float, default=0.12)
    parser.add_argument("--bounce", action="store_true", help="Active speaker hops when its line starts")
    parser.add_argument("--bounce-px", type=int, default=36, help="Bounce height in pixels")
    parser.add_argument("--tail", type=float, default=0.6, help="Seconds of silence/background after VO ends")
    parser.add_argument("--out", default=".tmp/final.mp4")
    args = parser.parse_args()

    for label, p in [("audio", args.audio), ("captions", args.captions)]:
        if not os.path.isfile(p):
            fail(f"{label} not found: {p}")
            return
    if args.music and not os.path.isfile(args.music):
        fail(f"music not found: {args.music}")
        return

    # AIGEN MODE: a scenes manifest takes precedence — build the whole video from AI images.
    if args.scenes and os.path.isfile(args.scenes):
        manifest = load_json(args.scenes)
        if not manifest or not manifest.get("scenes"):
            fail(f"scenes manifest empty/unreadable: {args.scenes}")
            return
        try:
            total = round(probe_duration(args.audio) + args.tail, 2)
            assemble_aigen(args, manifest, total)
        except Exception as e:
            fail(f"AIGEN video assembly failed: {e}")
        return

    # GAMEPLAY MODE (fallback): needs a background clip.
    if not args.background or not os.path.isfile(args.background):
        fail(f"background not found: {args.background}")
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
