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
import re
import subprocess

from _common import REPO_ROOT, load_env, emit, fail
from _media import run_ffmpeg, get_ffmpeg

OUT_W, OUT_H, FPS = 1080, 1920, 30
TMPDIR = ".tmp/rank"
SFX_DIR = REPO_ROOT / "assets" / "sfx"
BOOM = str(SFX_DIR / "boom.mp3")        # impact placed on the fail moment
FAIL_SFX = str(SFX_DIR / "fail.mp3")    # comedic "fahh/womp" on the fail
WHOOSH = str(SFX_DIR / "whoosh.mp3")    # trending transition sound at each clip's start
SILENCE_DB = -50.0                       # below this mean volume a clip counts as "silent"


def ass_time(t):
    h = int(t // 3600); m = int((t % 3600) // 60); s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def esc(text):
    return str(text).replace("\\", " ").replace("{", "(").replace("}", ")").replace("\n", " ").strip()


def _ydl_opts(out_base, fmt, player_client=None):
    from _media import get_ffmpeg
    opts = {"format": fmt, "merge_output_format": "mp4",
            "outtmpl": out_base + ".%(ext)s", "noplaylist": True, "quiet": True,
            "no_warnings": True, "noprogress": True, "overwrites": True,
            "ffmpeg_location": os.path.dirname(get_ffmpeg()),
            # Fast-fail on slow/bad videos so one hang can't stall the whole run (it gets skipped).
            "socket_timeout": 30, "retries": 2, "fragment_retries": 2, "extractor_retries": 1,
            "concurrent_fragment_downloads": 4}
    if player_client:
        opts["extractor_args"] = {"youtube": {"player_client": player_client}}
    cookie = os.environ.get("YT_COOKIES_FILE") or str(REPO_ROOT / "cookies.txt")
    if os.path.isfile(cookie):
        opts["cookiefile"] = cookie
    return opts


# Tried in order. Default web client gives the best quality and works on normal IPs; the android
# client is the fallback that still serves media on some blocked/datacenter IPs (GitHub Actions).
# When YouTube hard bot-checks the IP, none of these work without the YT_COOKIES secret.
_DL_ATTEMPTS = [
    (None, "bv*[height<=480]+ba/b[height<=480]/b"),
    (["android"], "best"),
    (["web_safari"], "best[height<=720]/best"),
]


def _resolve(out_base):
    for ext in (".mp4", ".mkv", ".webm"):
        if os.path.isfile(out_base + ext):
            return out_base + ext
    return None


def download(url, out_base):
    """Download the WHOLE short clip (Shorts are small -> ~5s each, fast & reliable).

    We deliberately do NOT range-download: cutting a section forces yt-dlp to stream the entire
    source through ffmpeg (>150s on long videos), which is why the old compilation approach was
    unusable. Candidates come from /shorts tabs, so the whole file is tiny.

    Tries the client/format chain in _DL_ATTEMPTS so a bot-checked default client can fall back to
    another that still serves media without cookies."""
    import glob
    from yt_dlp import YoutubeDL
    last = None
    for player_client, fmt in _DL_ATTEMPTS:
        for f in glob.glob(out_base + ".*"):           # clear partials from a prior attempt
            try:
                os.remove(f)
            except OSError:
                pass
        try:
            with YoutubeDL(_ydl_opts(out_base, fmt, player_client)) as ydl:
                ydl.extract_info(url, download=True)
            path = _resolve(out_base)
            if path:
                return path
        except Exception as e:
            last = e
            continue
    raise last or RuntimeError("download produced no file")


def mean_volume_db(src, offset, dur):
    """Mean loudness (dB) of the shown window, or None if the clip has no audio at all."""
    try:
        p = subprocess.run([get_ffmpeg(), "-hide_banner", "-nostats", "-ss", f"{offset:.2f}",
                            "-t", f"{dur:.2f}", "-i", src, "-map", "0:a:0?", "-af", "volumedetect",
                            "-f", "null", "-"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    except Exception:
        return None
    m = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", p.stderr or "")
    return float(m.group(1)) if m else None


def normalize(src, offset, dur, out):
    """Whole frame FIT into 9:16 over a blurred fill (no crop-zoom).

    Audio layering (the user's spec) on EVERY clip:
      * keep the clip's ORIGINAL sound when it's audible; if it's silent, sit it on silence;
      * a trending WHOOSH transition at the clip's start;
      * a 'fahh' (womp) + BOOM impact landing together on the FAIL moment (the clip's end, since we
        end-weight the window so the payoff is what's shown)."""
    vf = (f"[0:v]split=2[b][f];"
          f"[b]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,crop={OUT_W}:{OUT_H},"
          f"boxblur=20:1,setsar=1[bg];"
          f"[f]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease,setsar=1[fg];"
          f"[bg][fg]overlay=(W-w)/2:(H-h)/2,fps={FPS},format=yuv420p[v]")

    lvl = mean_volume_db(src, offset, dur)
    audible = lvl is not None and lvl > SILENCE_DB
    boom_ms = int(max(0.0, dur - 0.6) * 1000)    # impact right on the payoff
    fahh_ms = int(max(0.0, dur - 0.95) * 1000)   # 'fahh' leads into the impact

    # inputs: 0=clip, 1=boom, 2=fahh, 3=whoosh; (silent only) 4=silence base
    a = [f"[3:a]atrim=0:0.9,volume=0.5[wh]",                                  # trending transition
         f"[1:a]atrim=0:1.2,adelay={boom_ms}|{boom_ms},volume=0.7[bm]",       # boom on fail
         f"[2:a]adelay={fahh_ms}|{fahh_ms},volume=0.6[fa]"]                   # fahh on fail
    inputs = ["-ss", f"{offset:.2f}", "-i", src, "-i", BOOM, "-i", FAIL_SFX, "-i", WHOOSH]
    if audible:
        a.append("[0:a]aresample=44100,volume=1.0[base]")
    else:
        inputs += ["-f", "lavfi", "-t", f"{dur:.2f}", "-i", "anullsrc=r=44100:cl=stereo"]
        a.append("[4:a]volume=1.0[base]")
    a.append("[base][wh][bm][fa]amix=inputs=4:duration=first:normalize=0[a]")
    chain = vf + ";" + ";".join(a)

    run_ffmpeg([*inputs, "-filter_complex", chain, "-map", "[v]", "-map", "[a]", "-t", f"{dur:.2f}",
                "-ar", "44100", "-ac", "2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
                "-c:a", "aac", "-b:a", "160k", out])


GOLD = "&H0066D7FF&"   # ASS AABBGGRR -> bright gold (the active rank)


def build_overlay_ass(segments, title, total):
    head = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 0\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        # Header: the overall video title, pinned top-centre for the whole video.
        "Style: Header,Arial,62,&H00FFFFFF,&H0,&H00000000,&H78000000,1,0,0,0,100,100,0,0,1,5,3,8,50,50,120,1\n"
        # Board: a COMPACT leaderboard down the left side -- top-anchored, fixed slots, #1 on top.
        "Style: Board,Arial,46,&H00FFFFFF,&H0,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,3,2,7,45,40,330,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    # rank -> short funny label (e.g. "Aura Lost"); each rank has its own.
    by_rank = {s["rank"]: (s.get("label") or "") for s in segments}
    ranks_asc = sorted(by_rank)                           # 1,2,3,4,5 top-to-bottom (#1 on top)

    rows = [f"Dialogue: 0,{ass_time(0)},{ass_time(total)},Header,,0,0,0,,{esc(title)[:55]}"]
    for s in segments:
        cur = s["rank"]
        lines = []
        for k in ranks_asc:
            lbl = esc(by_rank[k])[:16]
            txt = (f"#{k} {lbl}").strip()
            if k == cur:                                  # the rank being revealed now: gold, bold
                lines.append("{\\c" + GOLD + "\\b1\\alpha&H00&}" + txt + "{\\r}")
            elif k > cur:                                 # already counted down past -> dimmed
                lines.append("{\\alpha&H85&}" + txt + "{\\r}")
            else:                                         # not revealed yet -> invisible (keeps slot)
                lines.append("{\\alpha&HFF&}" + txt + "{\\r}")
        board = "\\N".join(lines)
        rows.append(f"Dialogue: 0,{ass_time(s['start'])},{ass_time(s['end'])},Board,,0,0,0,,{board}")
    return head + "\n".join(rows) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ranked", default=".tmp/ranked.json")
    ap.add_argument("--title", default=None, help="Overall video title pinned at the top")
    ap.add_argument("--music", default=None)
    ap.add_argument("--music-volume", type=float, default=0.18)
    ap.add_argument("--max-total", type=float, default=120.0, help="Hard cap on total length (2 min)")
    ap.add_argument("--per-clip", type=float, default=24.0,
                    help="Max seconds shown per clip; longer clips show their END (the payoff)")
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
    clips, segments, cursor, errors = [], [], 0.0, []
    for i, e in enumerate(entries):
        try:
            src = download(e["url"], os.path.join(TMPDIR, f"src_{i}"))
        except Exception as ex:
            errors.append(f"download #{e.get('rank', i)}: {str(ex).splitlines()[0][:160]}")
            continue
        try:
            dsrc = probe_duration(src)                 # real duration (shorts carry none in search)
        except Exception:
            dsrc = None
        if dsrc and dsrc < 2:                          # skip degenerate/blank clips
            continue
        dur = min(cap, dsrc) if dsrc else cap
        # The funny PAYOFF (the fail itself) is almost always at the END of the clip. If the short is
        # longer than our per-clip budget, show its TAIL, not its intro -- otherwise we'd cut off the
        # actual fail (the bug the user hit). Short clips that fit are shown whole.
        offset = max(0.0, dsrc - dur) if (dsrc and dsrc > dur) else 0.0
        clip = os.path.join(TMPDIR, f"clip_{i}.mp4")
        try:
            normalize(src, offset, dur, clip)
        except Exception as ex:
            errors.append(f"normalize #{e.get('rank', i)}: {str(ex).splitlines()[0][:160]}")
            continue
        clips.append(clip)
        segments.append({"start": cursor, "end": round(cursor + dur, 2), "title": e["title"],
                         "label": e.get("label") or ""})
        cursor = round(cursor + dur, 2)
        if len(clips) >= 5:                            # five is enough for a Top-5
            break

    if len(clips) < 3:
        hint = ""
        if any("bot" in e.lower() or "sign in" in e.lower() for e in errors):
            hint = (" -- YouTube is blocking downloads from this IP (bot-check). On GitHub Actions "
                    "set the YT_COOKIES secret to a valid Netscape cookies.txt.")
        fail(f"Only {len(clips)} usable clips — need >=3.{hint}", reasons=errors[:8])
        return

    n = len(clips)
    for p, s in enumerate(segments):
        s["rank"] = n - p                              # first shown = highest number, last = #1
    total = round(min(cursor, args.max_total), 2)

    title = args.title or data.get("title") or "Ranking"
    ass_path = os.path.join(TMPDIR, "overlay.ass")
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(build_overlay_ass(segments, title, total))
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
