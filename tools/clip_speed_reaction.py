"""Capture iShowSpeed's LIVE stream around a just-scored World-Cup goal -> branded Short.

Moemen's rule change 2026-07-06 (supersedes the same-day blanket ban): Speed content is BACK,
but ONLY as our own capture of his livestream at goal moments -- the finders still don't
source third-party Speed-clip channel uploads. watch_worldcup.py calls this the moment the
ESPN feed reports a goal.

How it works (and its honest limitation):
  1. Resolve his /live page; if he isn't live -> {"live": false} and exit 0 (a quiet no-op,
     not an error -- most matches he won't be streaming).
  2. Record ~4 min from the live edge via yt-dlp's NATIVE HLS downloader (NOT raw ffmpeg:
     CI egress goes through a SOCKS proxy which ffmpeg can't speak; yt-dlp can). MPEG-TS
     output so a watchdog-truncated file is still readable.
  3. Find the LOUDEST ~40s window (his scream/celebration) by scanning per-second audio RMS.
  4. Fit it 9:16 over a blurred fill + burn the on-brand title card (same look as build_clip).
By the time ESPN reports the goal (~1 min lag) his live reaction is usually still unfolding
(celebration + replays), so the loudest-window cut lands on the reaction in practice; when
the timing misses, the LLM/manual review of the posted clip is the safety net.

Usage:
    python tools/clip_speed_reaction.py --title "SPEED REACTS - MBAPPE GOAL (67')"
        [--channel https://www.youtube.com/@IShowSpeed/live] [--record 240] [--window 42]
        [--check-only] [--out .tmp/speed_final.mp4]

Prints JSON: {"live": bool, "path","duration_sec","byte_size","loud_start_sec", ...}
"""
import argparse
import array
import os
import subprocess
import sys
import time

from _common import REPO_ROOT, load_env, emit, fail
from _media import run_ffmpeg, get_ffmpeg, probe_duration
import build_ranking_video as brv
from build_clip import build_overlay_ass, clean_title, esc  # noqa: F401  (esc used via ass builder)

TMP = REPO_ROOT / ".tmp" / "speed"
DEFAULT_CHANNEL = "https://www.youtube.com/@IShowSpeed/live"


def resolve_live(channel_url):
    """Return (watch_url, title) if the channel is live NOW, else (None, reason)."""
    from yt_dlp import YoutubeDL
    opts = {"quiet": True, "no_warnings": True, "noprogress": True, "skip_download": True,
            "socket_timeout": 30, "extractor_retries": 1}
    proxy = os.environ.get("YTDLP_PROXY")
    if proxy:
        opts["proxy"] = proxy
    cookie = os.environ.get("YT_COOKIES_FILE") or str(REPO_ROOT / "cookies.txt")
    if os.path.isfile(cookie):
        opts["cookiefile"] = cookie
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(channel_url, download=False)
    except Exception as e:
        msg = str(e)
        # yt-dlp raises when a /live page has no ACTIVE stream -- covering both "nothing
        # scheduled" and "stream scheduled but not started" ("This live event will begin in
        # 7 hours", seen 2026-07-07). Both are the normal "not live" outcome, not failures.
        low = msg.lower()
        if ("not currently live" in low or "channel is not live" in low or "no video" in low
                or "will begin in" in low or "premieres in" in low):
            return None, "channel not live"
        return None, f"live check failed: {msg[:160]}"
    if not info or not info.get("is_live"):
        return None, "channel not live"
    return f"https://www.youtube.com/watch?v={info['id']}", info.get("title") or ""


def record_live(watch_url, out_path, seconds):
    """Record ~`seconds` from the live edge with yt-dlp's native HLS downloader.

    yt-dlp has no stop-after-N-seconds flag for live, so a watchdog terminates the process;
    --hls-use-mpegts + --no-part means the truncated .ts is still fully decodable."""
    cmd = [sys.executable, "-m", "yt_dlp", watch_url,
           "-f", "best[height<=720]/best",
           "--hls-use-mpegts", "--no-part", "--quiet", "--no-warnings",
           "-o", str(out_path)]
    proxy = os.environ.get("YTDLP_PROXY")
    if proxy:
        cmd += ["--proxy", proxy]
    cookie = os.environ.get("YT_COOKIES_FILE") or str(REPO_ROOT / "cookies.txt")
    if os.path.isfile(cookie):
        cmd += ["--cookies", cookie]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + seconds
    while time.time() < deadline:
        if proc.poll() is not None:      # died early (stream ended / auth) -- use what we got
            break
        time.sleep(2)
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
    return os.path.isfile(out_path) and os.path.getsize(out_path) > 500_000


def loudest_window(media_path, window_sec):
    """Start second of the loudest `window_sec` stretch, via per-second RMS energy.

    Decodes to 8kHz mono s16 PCM through ffmpeg and slides a window over per-second
    energy sums -- pure stdlib, no numpy on the runner."""
    ff = get_ffmpeg()
    proc = subprocess.run(
        [ff, "-v", "error", "-i", str(media_path), "-map", "a:0?",
         "-ac", "1", "-ar", "8000", "-f", "s16le", "pipe:1"],
        capture_output=True)
    pcm = array.array("h")
    pcm.frombytes(proc.stdout[: len(proc.stdout) // 2 * 2])
    if len(pcm) < 8000 * (window_sec + 5):
        return 0.0                        # too short to scan; take from the start
    per_sec = []
    for i in range(0, len(pcm) - 8000 + 1, 8000):
        s = 0
        for v in pcm[i:i + 8000:8]:       # stride 8 => 1k samples/sec sampled; plenty for RMS
            s += v * v
        per_sec.append(s)
    w = int(window_sec)
    best_i, best_e, cur = 0, -1, sum(per_sec[:w])
    for i in range(len(per_sec) - w):
        if cur > best_e:
            best_e, best_i = cur, i
        cur += per_sec[i + w] - per_sec[i]
    return float(best_i)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True, help="Card title, e.g. 'SPEED REACTS - MBAPPE GOAL'")
    ap.add_argument("--channel", default=DEFAULT_CHANNEL)
    ap.add_argument("--handle", default="@itsmomoclips")
    ap.add_argument("--record", type=float, default=240.0, help="Seconds of live edge to capture")
    ap.add_argument("--window", type=float, default=42.0, help="Length of the loudest cut (<58s)")
    ap.add_argument("--check-only", action="store_true", help="Just report whether he is live")
    ap.add_argument("--out", default=".tmp/speed_final.mp4")
    args = ap.parse_args()

    load_env()
    watch_url, note = resolve_live(args.channel)
    if args.check_only or not watch_url:
        emit({"live": bool(watch_url), "note": note if not watch_url else "live",
              "watch_url": watch_url})
        return

    TMP.mkdir(parents=True, exist_ok=True)
    rec = TMP / "rec.ts"
    try:
        rec.unlink()
    except OSError:
        pass
    if not record_live(watch_url, rec, args.record):
        fail("live recording produced no usable file", live=True, watch_url=watch_url)
        return

    rec_dur = probe_duration(str(rec)) or 0
    start = loudest_window(rec, min(args.window, max(10.0, rec_dur - 2)))
    seg = min(args.window, max(10.0, rec_dur - start - 1))

    # 9:16 blurred-fill fit of the loudest stretch, then the same card burn as build_clip.
    body = str(TMP / "body.mp4")
    try:
        brv.normalize(str(rec), start, seg, body)
    except Exception as e:
        fail(f"normalize failed: {e}")
        return
    body_dur = probe_duration(body) or seg
    ass_name = "speed_overlay.ass"
    build_overlay_ass(clean_title(args.title), args.handle, body_dur, str(TMP / ass_name))
    out_path = args.out if os.path.isabs(args.out) else str(REPO_ROOT / args.out)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    try:
        run_ffmpeg(["-i", os.path.abspath(body), "-vf", f"ass={ass_name}",
                    "-map", "0:v", "-map", "0:a?", "-r", "30",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
                    os.path.abspath(out_path)], cwd=str(TMP))
    except Exception as e:
        fail(f"overlay burn failed: {e}")
        return

    emit({"live": True, "path": args.out,
          "duration_sec": round(probe_duration(out_path) or 0, 2),
          "byte_size": os.path.getsize(out_path),
          "loud_start_sec": round(start, 1), "recorded_sec": round(rec_dur, 1),
          "watch_url": watch_url, "title": clean_title(args.title)})


if __name__ == "__main__":
    main()
