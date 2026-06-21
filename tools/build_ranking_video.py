"""Build the final #5->#1 countdown ranking Short from ranked YouTube clips.

Style (per the user's spec):
  * FUNNY clips, shown with their ORIGINAL audio (no AI narrator).
  * the WHOLE frame is shown — fit into 9:16 over a blurred fill, NO crop-zoom.
  * a trending background-music bed is mixed in under the clip audio.
  * each clip is capped so the whole video is <= 3 minutes.
  * a countdown overlay (#N + the video title) sits on each clip.

Resilient: entries whose download/normalize fails are skipped and ranks renumbered (need >=3).

Usage:
    python tools/build_ranking_video.py --ranked .tmp/ranked.json [--music .tmp/music.mp3] \
        [--max-total 180] [--per-clip 35] [--out .tmp/final.mp4]

Prints JSON: {"path","byte_size","duration_sec","entries","title"}
"""
import argparse
import json
import os

from _common import REPO_ROOT, load_env, emit, fail
from _media import run_ffmpeg

OUT_W, OUT_H, FPS = 1080, 1920, 30
TMPDIR = ".tmp/rank"


def ass_time(t):
    h = int(t // 3600); m = int((t % 3600) // 60); s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def esc(text):
    return str(text).replace("\\", " ").replace("{", "(").replace("}", ")").replace("\n", " ").strip()


def _ydl_opts(out_base):
    from _media import get_ffmpeg
    opts = {"format": "bv*[height<=480]+ba/b[height<=480]/b", "merge_output_format": "mp4",
            "outtmpl": out_base + ".%(ext)s", "noplaylist": True, "quiet": True,
            "no_warnings": True, "noprogress": True, "overwrites": True,
            "ffmpeg_location": os.path.dirname(get_ffmpeg()),
            # Fast-fail on slow/bad videos so one hang can't stall the whole run (it gets skipped).
            "socket_timeout": 30, "retries": 2, "fragment_retries": 2, "extractor_retries": 1,
            "concurrent_fragment_downloads": 4}
    cookie = os.environ.get("YT_COOKIES_FILE") or str(REPO_ROOT / "cookies.txt")
    if os.path.isfile(cookie):
        opts["cookiefile"] = cookie
    return opts


def _resolve(out_base):
    for ext in (".mp4", ".mkv", ".webm"):
        if os.path.isfile(out_base + ext):
            return out_base + ext
    return None


def download(url, out_base):
    """Download the WHOLE short clip (Shorts are small -> ~5s each, fast & reliable).

    We deliberately do NOT range-download: cutting a section forces yt-dlp to stream the entire
    source through ffmpeg (>150s on long videos), which is why the old compilation approach was
    unusable. Candidates here come from /shorts tabs, so the whole file is tiny."""
    from yt_dlp import YoutubeDL
    with YoutubeDL(_ydl_opts(out_base)) as ydl:
        ydl.extract_info(url, download=True)
    path = _resolve(out_base)
    if not path:
        raise RuntimeError("download produced no file")
    return path


def normalize(src, offset, dur, out):
    """Whole frame FIT into 9:16 over a blurred fill (no crop-zoom), original audio kept."""
    vf = (f"[0:v]split=2[b][f];"
          f"[b]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,crop={OUT_W}:{OUT_H},"
          f"boxblur=20:1,setsar=1[bg];"
          f"[f]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease,setsar=1[fg];"
          f"[bg][fg]overlay=(W-w)/2:(H-h)/2,fps={FPS},format=yuv420p[v]")
    run_ffmpeg(["-ss", f"{offset:.2f}", "-i", src, "-t", f"{dur:.2f}",
                "-filter_complex", vf, "-map", "[v]", "-map", "0:a",
                "-ar", "44100", "-ac", "2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
                "-c:a", "aac", "-b:a", "160k", out])


def build_overlay_ass(segments):
    head = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 0\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Rank,Arial,210,&H0066D7FF,&H0,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,6,3,8,40,40,70,1\n"
        "Style: Title,Arial,62,&H00FFFFFF,&H0,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,5,2,8,70,70,320,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    rows = []
    for s in segments:
        st, en = ass_time(s["start"]), ass_time(s["end"])
        rows.append(f"Dialogue: 0,{st},{en},Rank,,0,0,0,,#{s['rank']}")
        rows.append(f"Dialogue: 0,{st},{en},Title,,0,0,0,,{esc(s['title'])[:70]}")
    return head + "\n".join(rows) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ranked", default=".tmp/ranked.json")
    ap.add_argument("--music", default=None)
    ap.add_argument("--music-volume", type=float, default=0.18)
    ap.add_argument("--max-total", type=float, default=180.0, help="Hard cap on total length (3 min)")
    ap.add_argument("--per-clip", type=float, default=35.0, help="Max seconds shown per clip")
    ap.add_argument("--out", default=".tmp/final.mp4")
    args = ap.parse_args()

    load_env()
    try:
        data = json.load(open(args.ranked, encoding="utf-8"))
        entries = data["entries"]
    except (OSError, json.JSONDecodeError, KeyError) as e:
        fail(f"Could not read --ranked: {e}")
        return

    os.makedirs(TMPDIR, exist_ok=True)
    # Cap each clip so the whole video stays <= max-total.
    cap = min(args.per_clip, args.max_total / max(1, len(entries)))

    from _media import probe_duration
    clips, segments, cursor = [], [], 0.0
    for i, e in enumerate(entries):
        try:
            src = download(e["url"], os.path.join(TMPDIR, f"src_{i}"))
        except Exception:
            continue
        try:
            dsrc = probe_duration(src)                 # real duration (shorts carry none in search)
        except Exception:
            dsrc = None
        dur = min(cap, dsrc) if dsrc else cap          # show the WHOLE short, capped to keep <=3 min
        if dsrc and dsrc < 2:                          # skip degenerate/blank clips
            continue
        clip = os.path.join(TMPDIR, f"clip_{i}.mp4")
        try:
            normalize(src, 0.0, dur, clip)
        except Exception:
            continue                                   # e.g. clip had no audio track
        clips.append(clip)
        segments.append({"start": cursor, "end": round(cursor + dur, 2), "title": e["title"]})
        cursor = round(cursor + dur, 2)
        if len(clips) >= 5:                            # five is enough for a Top-5
            break

    if len(clips) < 3:
        fail(f"Only {len(clips)} usable clips — need >=3.")
        return

    n = len(clips)
    for p, s in enumerate(segments):
        s["rank"] = n - p                              # first shown = highest number, last = #1
    total = round(min(cursor, args.max_total), 2)

    ass_path = os.path.join(TMPDIR, "overlay.ass")
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(build_overlay_ass(segments))
    ass_rel = os.path.relpath(ass_path, os.getcwd()).replace("\\", "/")

    ff = []
    for c in clips:
        ff += ["-i", c]
    music_idx = None
    if args.music and os.path.isfile(args.music):
        ff += ["-stream_loop", "-1", "-i", args.music]
        music_idx = n

    concat_in = "".join(f"[{k}:v][{k}:a]" for k in range(n))
    chain = f"{concat_in}concat=n={n}:v=1:a=1[cv][ca];[cv]ass={ass_rel}[v]"
    if music_idx is not None:
        chain += (f";[ca]volume=1.0[base];[{music_idx}:a]volume={args.music_volume}[mus];"
                  f"[base][mus]amix=inputs=2:duration=first:dropout_transition=0[a]")
        amap = "[a]"
    else:
        amap = "[ca]"

    ff += ["-filter_complex", chain, "-map", "[v]", "-map", amap, "-t", f"{total:.2f}",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "high", "-preset", "veryfast",
           "-crf", "20", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", args.out]
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    try:
        run_ffmpeg(ff)
    except Exception as e:
        fail(f"Final assembly failed: {e}")
        return

    emit({"path": args.out, "byte_size": os.path.getsize(args.out), "duration_sec": total,
          "entries": [{"rank": s["rank"], "title": s["title"][:50]} for s in segments],
          "title": data.get("title")})


if __name__ == "__main__":
    main()
