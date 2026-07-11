"""Build ONE branded vertical Short from a single source clip (momoclips pipeline).

Distinct from build_ranking_video.py (which stitches a #5->#1 countdown): this takes ONE
World-Cup moment -- a goal, a fan/streamer reaction, a viral clip -- and turns it into a
finished 1080x1920 Short: the whole frame fit into 9:16 over a blurred fill (no crop-zoom),
original clip audio kept (the commentary/crowd IS the appeal -- no SFX, per the project's
audio rule), with a compact on-brand title card and an @momoclips watermark burned on.

Reuses the proven download() + normalize() from build_ranking_video (same 9:16 blurred-fill
fit, same "keep original audio / silence when quiet" behaviour, same yt-dlp WARP-proxy path).

Usage:
    python tools/build_clip.py --url <youtube_url> --title "RONALDO GOAL" \
        [--handle @momoclips] [--max-secs 58] [--music path.mp3] [--out .tmp/final.mp4]

Prints JSON: {"path","duration_sec","byte_size","title","source_url","width","height"}
"""
import argparse
import json
import os
import re
import sys

from _common import REPO_ROOT, load_env, emit, fail, is_tod, TOD_CROP_FRAC
from _media import run_ffmpeg, get_ffmpeg, probe_duration

# Reuse the ranking pipeline's downloader + 9:16 normaliser (same module, sibling import).
import build_ranking_video as brv

OUT_W, OUT_H = brv.OUT_W, brv.OUT_H
CLIP_TMP = ".tmp/clip"


def esc(text):
    """ASS-safe: strip braces/backslashes/newlines that would break the filter."""
    return (str(text).replace("\\", " ").replace("{", "(").replace("}", ")")
            .replace("\n", " ").strip())


def clean_title(raw):
    """Turn a noisy source title into a short, punchy card.

    'Cristiano Ronaldo Goal | Portugal 2-1 Croatia | FIFA World Cup 2026(TM)'
      -> 'Cristiano Ronaldo Goal - Portugal 2-1 Croatia'
    'Lionel Messi Goal vs Cape Verde During Argentina vs Cape Verde Fifa World Cup 2026 Match'
      -> 'Lionel Messi Goal vs Cape Verde'
    """
    t = raw.replace("™", " ").replace("®", " ")
    # Case-insensitive removal of FIFA/World-Cup boilerplate + junk phrases.
    for pat in (r"fifa\s+world\s+cup\s*20\d\d", r"world\s+cup\s*20\d\d", r"fifa\s+world\s+cup",
                r"full\s+match", r"highlights?", r"#\w+", r"\(\s*4k\s*\)", r"\b4k\b", r"\bhd\b"):
        t = re.sub(pat, " ", t, flags=re.IGNORECASE)
    # Split on separators; also break on a padded "During"/"vs ... vs" duplication so a repeated
    # "X vs Y During X vs Y" collapses to its first, most descriptive segment.
    t = re.sub(r"\s+during\s+", " | ", t, flags=re.IGNORECASE)
    parts = [re.sub(r"\s+", " ", p).strip(" -–—") for p in re.split(r"[|–—]|\s-\s", t)]
    # Removing boilerplate can leave its trailing separator dangling at the FRONT of a part
    # ("FIFA World Cup 2026: Messi..." -> ": Messi..." -- posted with a leading colon on
    # 2026-07-05). Titles must start with a letter or digit.
    parts = [re.sub(r"^[^0-9A-Za-z]+", "", p).strip() for p in parts]
    parts = [p for p in parts if p]
    # Prefer the first segment; add a second only if the first is short and the second adds a score.
    out = parts[0] if parts else re.sub(r"\s+", " ", t).strip()
    if parts and len(out) < 32 and len(parts) > 1 and re.search(r"\d", parts[1]):
        out = f"{out} - {parts[1]}"
    # Strip trailing filler words left dangling by the removals.
    out = re.sub(r"\b(match|game|video|clip|moment)\s*$", "", out, flags=re.IGNORECASE).strip(" -")
    # Word-boundary truncation so we never cut mid-word.
    if len(out) > 62:
        out = out[:62].rsplit(" ", 1)[0]
    # Belt-and-suspenders: never return a title that opens with punctuation/symbols.
    return re.sub(r"^[^0-9A-Za-z]+", "", out).strip(" -–—:;|.,!?")


def build_overlay_ass(title, handle, total, out_path, cta_dur=0.0, cta_text=""):
    """A compact title card: bold title pinned top for the whole clip + a small handle
    watermark bottom-centre. Colours/anchoring mirror build_ranking_video's Header style so
    the two formats look like one channel. Gold accent = brand.

    Optional follow CTA (mirrors build_ranking_video's end-card): a bold pop-in over the
    LAST cta_dur seconds of footage that's already playing -- no dead time appended, no SFX
    (audio rule). Research on short-form CTAs backs this over a bolt-on end screen: baked
    into the video reads as natural, a separate end card kills momentum/rewatch."""
    def ass_time(t):
        h = int(t // 3600); m = int((t % 3600) // 60); s = t % 60
        return f"{h}:{m:02d}:{s:05.2f}"

    head = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 0\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        # Title: bold white, gold-adjacent shadow box, pinned top-centre the whole clip.
        "Style: Title,Arial,64,&H00FFFFFF,&H0,&H00000000,&H78000000,1,0,0,0,100,100,0,0,1,5,3,8,60,60,120,1\n"
        # Handle: small gold watermark, bottom-centre, lifted clear of the phone UI.
        "Style: Handle,Arial,44,&H0066D7FF&,&H0,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,3,2,2,60,60,150,1\n"
        # CTA: bold gold follow prompt, sits above the handle watermark so they never collide.
        "Style: CTA,Arial,58,&H0066D7FF&,&H0,&H00000000,&H78000000,1,0,0,0,100,100,0,0,1,6,3,2,60,60,260,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    rows = [
        # Title pops in with a quick scale-down so it punches on the open, then holds.
        f"Dialogue: 0,{ass_time(0)},{ass_time(total)},Title,,0,0,0,,"
        "{\\fad(120,0)\\fscx112\\fscy112\\t(0,240,\\fscx100\\fscy100)}" + esc(title),
        f"Dialogue: 0,{ass_time(0)},{ass_time(total)},Handle,,0,0,0,,{esc(handle)}",
    ]
    if cta_dur > 0 and cta_text:
        eff = min(cta_dur, total)
        cs = max(0.0, total - eff)
        rows.append(
            f"Dialogue: 1,{ass_time(cs)},{ass_time(total)},CTA,,0,0,0,,"
            "{\\fad(150,0)\\fscx120\\fscy120\\t(0,250,\\fscx100\\fscy100)}" + esc(cta_text)[:26])
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(head + "\n".join(rows) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="Source YouTube (or direct media) URL")
    ap.add_argument("--title", required=True, help="Overlay/card title (already punchy)")
    ap.add_argument("--handle", default="@itsmomoclips", help="Watermark handle")
    ap.add_argument("--max-secs", type=float, default=58.0, help="Hard cap (<60s Shorts length)")
    ap.add_argument("--music", default=None, help="Optional music bed path (default: keep original audio only)")
    ap.add_argument("--music-volume", type=float, default=0.12)
    ap.add_argument("--source-handle", default="",
                    help="Uploader @handle of the source. TOD-by-beIN clips get their bottom "
                         "branding bar cropped off before the 9:16 fit; every other source is untouched.")
    ap.add_argument("--cta", dest="cta", action="store_true", default=True,
                    help="Follow CTA pop-in over the last --cta-dur seconds (default ON; no SFX, "
                         "per the audio rule -- purely on-screen text, same pattern as build_ranking_video).")
    ap.add_argument("--no-cta", dest="cta", action="store_false", help="Disable the follow CTA.")
    ap.add_argument("--cta-dur", type=float, default=2.2, help="CTA pop-in length in seconds.")
    ap.add_argument("--cta-text", default="FOLLOW FOR MORE", help="Follow CTA on-screen text.")
    ap.add_argument("--out", default=".tmp/final.mp4")
    args = ap.parse_args()

    load_env()
    # Always tidy the card title (strip trademark junk / FIFA boilerplate, cap length) so any
    # caller can hand us a raw source title and still get a clean, legible card.
    args.title = clean_title(args.title)
    tmpdir = REPO_ROOT / CLIP_TMP
    tmpdir.mkdir(parents=True, exist_ok=True)
    src_base = str(tmpdir / "src")

    # 1) download the whole (short) source clip -- yt-dlp routes via WARP on cloud runners.
    try:
        src = brv.download(args.url, src_base)
    except Exception as e:
        fail(f"download failed: {e}", url=args.url)
        return
    if not src or not os.path.isfile(src):
        fail("download produced no file", url=args.url)
        return

    dur = probe_duration(src)
    if not dur or dur <= 0:
        fail("could not read source duration", src=src)
        return
    seg = min(dur, args.max_secs)   # single-moment uploads are already short; cap at <60s from the start

    # 1b) TOD-by-beIN clips carry a bottom branding bar; crop it off BEFORE the 9:16 fit so it's
    #     gone from both the sharp foreground and the blurred fill. TOD-only (is_tod gate) --
    #     every other source is left untouched. A crop failure falls back to the uncropped source.
    if is_tod("", args.source_handle) and TOD_CROP_FRAC > 0:
        cropped = str(tmpdir / "src_crop.mp4")
        keep_h = f"trunc(ih*{1.0 - TOD_CROP_FRAC:.4f}/2)*2"   # even height; y=0 keeps the top, drops the bottom bar
        try:
            run_ffmpeg(["-i", os.path.abspath(src), "-vf", f"crop=iw:{keep_h}:0:0",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                        "-c:a", "aac", "-b:a", "192k", os.path.abspath(cropped)])
            if os.path.isfile(cropped):
                src = cropped
        except Exception as e:
            print(f"::warning::TOD bottom-crop failed ({str(e)[:120]}); using uncropped source", file=sys.stderr)

    # 2) fit to 9:16 over a blurred fill, keep original audio (or silence if the clip is quiet).
    body = str(tmpdir / "body.mp4")
    try:
        brv.normalize(src, 0.0, seg, body)
    except Exception as e:
        fail(f"normalize failed: {e}", src=src)
        return

    # 3) burn the title card + handle watermark. Bare filename + cwd=.tmp/clip so ffmpeg's
    #    filtergraph parser never sees the repo path's drive-colon/space (same rule as the
    #    ranking/clipping ass burns).
    body_dur = probe_duration(body) or seg
    ass_name = "clip_overlay.ass"
    build_overlay_ass(args.title, args.handle, body_dur, str(tmpdir / ass_name),
                       args.cta_dur if args.cta else 0.0, args.cta_text)

    out_path = args.out if os.path.isabs(args.out) else str(REPO_ROOT / args.out)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    vf = f"ass={ass_name}"
    inputs = ["-i", os.path.abspath(body)]
    amap = ["-map", "0:a?"]
    achain = None
    music = args.music
    if music and os.path.isfile(music):
        # Mix a quiet bed UNDER the original audio; ducking so commentary/crowd stays on top.
        inputs += ["-stream_loop", "-1", "-i", os.path.abspath(music)]
        achain = (f"[1:a]volume={args.music_volume}[m];"
                  f"[0:a][m]sidechaincompress=threshold=0.03:ratio=8:attack=5:release=250[duck];"
                  f"[0:a][duck]amix=inputs=2:duration=first:dropout_transition=0[a]")
        amap = ["-map", "[a]"]

    cmd = [*inputs]
    if achain:
        cmd += ["-filter_complex", f"[0:v]{vf}[v];{achain}", "-map", "[v]", *amap]
    else:
        cmd += ["-vf", vf, "-map", "0:v", *amap]
    cmd += ["-t", f"{args.max_secs:.3f}", "-r", "30",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", os.path.abspath(out_path)]
    try:
        run_ffmpeg(cmd, cwd=str(tmpdir))
    except Exception as e:
        fail(f"overlay burn failed: {e}")
        return

    out_dur = probe_duration(out_path)
    emit({
        "path": args.out,
        "duration_sec": round(out_dur, 2) if out_dur else None,
        "byte_size": os.path.getsize(out_path),
        "title": args.title,
        "source_url": args.url,
        "width": OUT_W, "height": OUT_H,
        "music": os.path.basename(music) if (music and os.path.isfile(music)) else None,
    })


if __name__ == "__main__":
    main()
