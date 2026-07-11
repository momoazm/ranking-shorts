"""Stitch a player's SAME-MATCH goal clips into ONE branded Short (brace / hat-trick recap).

End-of-game feature (Moemen, 2026-07-06): when the live watcher sees a player score 2+ goals
in a match, it re-shows those already-posted goal clips as a single compilation. This is OUR
OWN end-of-match recap of moments we individually posted -- distinct from the banned
behaviour of SOURCING someone else's compilation upload as if it were a single moment
(that _LISTY/title_ok rule is unchanged and doesn't apply to our built cards).

Each input is normalized to the same 1080x1920 blurred-fill spec as every other momoclips
video, hard cuts between goals (no SFX -- audio rule), total capped <58s, one title card +
handle watermark burned over the whole thing.

Usage:
    python tools/build_compilation.py --clip .tmp/wc/goal_a.mp4 --clip .tmp/wc/goal_b.mp4
        --title "BELLINGHAM x2 vs Mexico - ALL GOALS" [--handle @itsmomoclips]
        [--max-total 58] [--out .tmp/final.mp4]

Prints JSON: {"path","duration_sec","byte_size","clips"}
"""
import argparse
import os

from _common import REPO_ROOT, load_env, emit, fail
from _media import run_ffmpeg, probe_duration
import build_ranking_video as brv
from build_clip import build_overlay_ass, clean_title

TMP = REPO_ROOT / ".tmp" / "compile"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", action="append", required=True,
                    help="Source clip path (repeat; order = playback order)")
    ap.add_argument("--title", required=True)
    ap.add_argument("--handle", default="@itsmomoclips")
    ap.add_argument("--max-total", type=float, default=58.0, help="Hard cap (<60s Shorts rule)")
    ap.add_argument("--cta", dest="cta", action="store_true", default=True,
                    help="Follow CTA pop-in over the last --cta-dur seconds (default ON; no SFX).")
    ap.add_argument("--no-cta", dest="cta", action="store_false", help="Disable the follow CTA.")
    ap.add_argument("--cta-dur", type=float, default=2.2, help="CTA pop-in length in seconds.")
    ap.add_argument("--cta-text", default="FOLLOW FOR MORE", help="Follow CTA on-screen text.")
    ap.add_argument("--out", default=".tmp/final.mp4")
    args = ap.parse_args()

    load_env()
    clips = [c for c in args.clip if os.path.isfile(c)]
    if len(clips) < 2:
        fail(f"need >=2 existing clips, got {len(clips)}", given=args.clip)
        return
    TMP.mkdir(parents=True, exist_ok=True)

    # Budget screen time evenly; a goal moment reads fine at >=8s, so drop the longest-tail
    # inputs' excess rather than the clip count.
    per = max(8.0, args.max_total / len(clips) - 0.2)
    parts = []
    for i, src in enumerate(clips):
        dur = probe_duration(src)
        if not dur or dur <= 1:
            continue
        take = min(dur, per)
        # For a long input (a full highlight), the goal usually sits mid-clip; taking the
        # MIDDLE beats taking a build-up-only opening.
        offset = max(0.0, (dur - take) / 2) if dur > per * 1.8 else 0.0
        out = str(TMP / f"part{i}.mp4")
        try:
            brv.normalize(src, offset, take, out)
        except Exception as e:
            fail(f"normalize failed on clip {i}: {e}", clip=src)
            return
        parts.append(out)
    if len(parts) < 2:
        fail("fewer than 2 clips survived normalization")
        return

    total = sum(probe_duration(p) or 0 for p in parts)
    total = min(total, args.max_total)
    ass_name = "compile_overlay.ass"
    build_overlay_ass(clean_title(args.title), args.handle, total, str(TMP / ass_name),
                       args.cta_dur if args.cta else 0.0, args.cta_text)

    out_path = args.out if os.path.isabs(args.out) else str(REPO_ROOT / args.out)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    n = len(parts)
    inputs = []
    for p in parts:
        inputs += ["-i", os.path.abspath(p)]
    concat_in = "".join(f"[{k}:v][{k}:a]" for k in range(n))
    chain = f"{concat_in}concat=n={n}:v=1:a=1[cv][ca];[cv]ass={ass_name}[v]"
    try:
        run_ffmpeg([*inputs, "-filter_complex", chain, "-map", "[v]", "-map", "[ca]",
                    "-t", f"{args.max_total:.3f}", "-r", "30",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
                    os.path.abspath(out_path)], cwd=str(TMP))
    except Exception as e:
        fail(f"concat/burn failed: {e}")
        return

    emit({"path": args.out,
          "duration_sec": round(probe_duration(out_path) or 0, 2),
          "byte_size": os.path.getsize(out_path),
          "clips": len(parts), "title": clean_title(args.title)})


if __name__ == "__main__":
    main()
