"""Mix the dialogue voiceover with sound effects the way the viral channels do: a ducked music
bed under the whole thing, a transition WHOOSH on each new line (speaker change), and a BOOM
impact on the punchline (final line, optionally the hook too).

Kept as a separate, inspectable step (WAT): it consumes narration.mp3 + segments.json and emits
one mixed narration_mixed.mp3 that assemble_video.py then uses as its --audio. Any SFX you don't
pass is simply skipped, so the tool degrades gracefully.

Usage:
    python tools/build_audio_mix.py --audio .tmp/narration.mp3 --segments .tmp/segments.json \\
        --whoosh assets/sfx/whoosh.mp3 --boom assets/sfx/boom.mp3 [--music assets/music/bed.mp3] \\
        [--music-volume 0.10] [--whoosh-volume 0.45] [--boom-volume 0.8] [--boom-on final] \\
        --out .tmp/narration_mixed.mp3

Prints JSON: {"path": ..., "whooshes": N, "booms": N, "music": bool, "duration_sec": F}
"""
import argparse
import json
import os

from _common import emit, fail
from _media import run_ffmpeg, probe_duration


def load_segments(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f).get("segments", [])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", required=True, help="Voiceover mp3")
    parser.add_argument("--segments", required=True, help="Dialogue timeline (for SFX placement)")
    parser.add_argument("--music", help="Background music bed (looped + ducked)")
    parser.add_argument("--whoosh", help="Transition SFX, placed on each new line")
    parser.add_argument("--boom", help="Impact SFX, placed on the punchline")
    parser.add_argument("--music-volume", type=float, default=0.10)
    parser.add_argument("--whoosh-volume", type=float, default=0.45)
    parser.add_argument("--boom-volume", type=float, default=0.8)
    parser.add_argument("--boom-on", choices=["final", "hook", "both", "none"], default="final")
    parser.add_argument("--lead", type=float, default=0.10, help="Seconds a whoosh starts BEFORE the line")
    parser.add_argument("--out", default=".tmp/narration_mixed.mp3")
    args = parser.parse_args()

    for label, p in [("audio", args.audio), ("segments", args.segments)]:
        if not os.path.isfile(p):
            fail(f"{label} not found: {p}")
            return
    for label, p in [("music", args.music), ("whoosh", args.whoosh), ("boom", args.boom)]:
        if p and not os.path.isfile(p):
            fail(f"{label} not found: {p}")
            return

    segs = load_segments(args.segments)
    if not segs:
        fail("No segments to place SFX against.")
        return

    try:
        vo_dur = probe_duration(args.audio)
    except Exception as e:
        fail(f"Could not probe voiceover duration: {e}")
        return

    # WHOOSH on each line change after the first (each turn is a new speaker).
    whoosh_times = [max(0.0, s["start"] - args.lead) for s in segs[1:]] if args.whoosh else []
    # BOOM placement.
    boom_times = []
    if args.boom and args.boom_on != "none":
        if args.boom_on in ("final", "both"):
            boom_times.append(segs[-1]["start"])
        if args.boom_on in ("hook", "both"):
            boom_times.append(segs[0]["start"])

    STEREO = "aformat=sample_rates=44100:channel_layouts=stereo"
    inputs = ["-i", args.audio]                       # 0 = VO
    parts = [f"[0:a]{STEREO},volume=1[vo]"]
    mix = ["[vo]"]
    idx = 1

    if args.music:
        inputs += ["-stream_loop", "-1", "-i", args.music]
        parts.append(f"[{idx}:a]{STEREO},volume={args.music_volume}[mus]")
        mix.append("[mus]")
        idx += 1

    if whoosh_times:
        inputs += ["-i", args.whoosh]
        n = len(whoosh_times)
        splits = "".join(f"[ws{i}]" for i in range(n))
        parts.append(f"[{idx}:a]{STEREO},volume={args.whoosh_volume}[wsrc]")
        parts.append(f"[wsrc]asplit={n}{splits}")
        for i, t in enumerate(whoosh_times):
            ms = max(0, int(round(t * 1000)))
            parts.append(f"[ws{i}]adelay={ms}:all=1[wo{i}]")
            mix.append(f"[wo{i}]")
        idx += 1

    if boom_times:
        inputs += ["-i", args.boom]
        n = len(boom_times)
        splits = "".join(f"[bs{i}]" for i in range(n))
        parts.append(f"[{idx}:a]{STEREO},volume={args.boom_volume}[bsrc]")
        parts.append(f"[bsrc]asplit={n}{splits}")
        for i, t in enumerate(boom_times):
            ms = max(0, int(round(t * 1000)))
            parts.append(f"[bs{i}]adelay={ms}:all=1[bo{i}]")
            mix.append(f"[bo{i}]")
        idx += 1

    # amix anchored to the VO length; normalize=0 keeps levels, alimiter guards against clipping.
    parts.append(
        f"{''.join(mix)}amix=inputs={len(mix)}:duration=first:normalize=0,"
        f"alimiter=level_in=1:level_out=1:limit=0.97[out]"
    )
    filtergraph = ";".join(parts)

    ff = inputs + ["-filter_complex", filtergraph, "-map", "[out]",
                   "-c:a", "libmp3lame", "-q:a", "2", args.out]

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    try:
        run_ffmpeg(ff)
    except Exception as e:
        fail(f"Audio mix failed: {e}")
        return

    try:
        out_dur = probe_duration(args.out)
    except Exception:
        out_dur = round(vo_dur, 2)

    emit({
        "path": args.out,
        "whooshes": len(whoosh_times),
        "booms": len(boom_times),
        "music": bool(args.music),
        "duration_sec": round(out_dur, 2),
    })


if __name__ == "__main__":
    main()
