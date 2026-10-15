"""Build the final #5->#1 countdown ranking Short from ranked YouTube clips.

Style (per the user's spec):
  * FUNNY clips, shown with their ORIGINAL audio (no AI narrator).
  * the WHOLE frame is shown — fit into 9:16 over a blurred fill, NO crop-zoom.
  * an original, rights-safe background bed is mixed in under the clip audio with ducking.
  * each clip is capped so the whole video is <= 3 minutes and long sources are windowed around
    their strongest audible/action beat.
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
import sys
import time

from _common import REPO_ROOT, load_env, emit, fail
from _media import run_ffmpeg, get_ffmpeg

OUT_W, OUT_H, FPS = 1080, 1920, 30
TMPDIR = ".tmp/rank"
SILENCE_DB = -50.0                       # below this mean volume a clip counts as "silent"
DOWNLOAD_DEADLINE_SEC = 150.0            # one bad source must not consume a whole Actions job
DOWNLOAD_ATTEMPT_TIMEOUT_SEC = 25.0      # yt-dlp API calls can outlive socket timeouts
DEFAULT_MUSIC_VOLUME = 0.09
DEFAULT_MUSIC_PITCH = 1.0
DEFAULT_TEASER_TEXT = "WATCH THE #1 PAYOFF"


def ass_time(t):
    h = int(t // 3600); m = int((t % 3600) // 60); s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def esc(text):
    return str(text).replace("\\", " ").replace("{", "(").replace("}", ")").replace("\n", " ").strip()


def _ydl_opts(out_base, fmt, player_client=None, use_proxy=True):
    from _media import get_ffmpeg
    opts = {"format": fmt, "merge_output_format": "mp4",
            # BEST QUALITY: highest resolution first, H.264 only as a same-res tie-break.
            "format_sort": ["res", "vcodec:h264", "acodec:m4a"],
            "outtmpl": out_base + ".%(ext)s", "noplaylist": True, "quiet": True,
            "no_warnings": True, "noprogress": True, "overwrites": True,
            "ffmpeg_location": os.path.dirname(get_ffmpeg()),
            # Fast-fail on slow/bad videos so one hang can't stall the whole run (it gets skipped).
            "socket_timeout": 15, "retries": 0, "fragment_retries": 0, "extractor_retries": 0,
            "concurrent_fragment_downloads": 4}
    if player_client:
        opts["extractor_args"] = {"youtube": {"player_client": player_client}}
    cookie = os.environ.get("YT_COOKIES_FILE") or str(REPO_ROOT / "cookies.txt")
    if os.path.isfile(cookie):
        opts["cookiefile"] = cookie
    # Cloud runners have datacenter IPs that YouTube bot-checks; route yt-dlp (and only
    # yt-dlp) through a proxy when one is provided (e.g. WARP's local SOCKS on the
    # GitHub-hosted runner, or a residential proxy URL). ffmpeg can't speak SOCKS, so
    # never combine this with ffmpeg-side downloading (range/section cuts).
    proxy = os.environ.get("YTDLP_PROXY")
    if proxy and use_proxy:
        opts["proxy"] = proxy
    return opts


# Tried in order: (player_client, format, use_proxy). The first lenient format works for Reddit
# (the default source) and normal YouTube; the youtube player_client is simply ignored by other
# extractors like Reddit.
_DL_ATTEMPTS = [
    # YouTube may challenge the runner egress, the WARP egress, or one specific player-client
    # handshake. Keep both direct and proxied legs for the clients that can use BgUtils POTs;
    # direct/default is important when the current WARP range is flagged. The route order is
    # intentionally the same bounded diversity used by clipping-auto.
    (None, "bv*[height<=2160]+ba/b[height<=2160]", False),
    (None, "bv*[height<=2160]+ba/b[height<=2160]", True),
    (["web_safari"], "bv*[height<=2160]+ba/b[height<=2160]", False),
    (["web_safari"], "bv*[height<=2160]+ba/b[height<=2160]", True),
    (["tv"], "bv*[height<=2160]+ba/b[height<=2160]", False),
    (["tv"], "bv*[height<=2160]+ba/b[height<=2160]", True),
    (["web"], "bv*[height<=2160]+ba/b[height<=2160]", False),
    (["web"], "bv*[height<=2160]+ba/b[height<=2160]", True),
]


def download_deadline_sec():
    """Whole-download wall clock. Callers with LONG sources (a full episode instead of a
    15s Short) raise it through YTDLP_DEADLINE_SEC; the Short defaults stay tight."""
    try:
        override = float(os.environ.get("YTDLP_DEADLINE_SEC") or 0)
    except ValueError:
        override = 0.0
    return override if override > 0 else DOWNLOAD_DEADLINE_SEC


def download_attempt_timeout_sec():
    """Per-route ceiling inside download(). Overridable the same way for long sources."""
    try:
        override = float(os.environ.get("YTDLP_ATTEMPT_TIMEOUT_SEC") or 0)
    except ValueError:
        override = 0.0
    return override if override > 0 else DOWNLOAD_ATTEMPT_TIMEOUT_SEC


def _resolve(out_base):
    for ext in (".mp4", ".mkv", ".webm"):
        if os.path.isfile(out_base + ext):
            return out_base + ext
    return None


# --- Invidious fallback (added 2026-10-15) ---------------------------------------------------
# Sourcing on GitHub's datacenter IPs is bot-walled at the METADATA step ("Sign in to confirm
# you're not a bot"): the request is rejected before any format URL is ever minted, so every
# yt-dlp player_client route in _DL_ATTEMPTS fails regardless of cookies (proven 2026-10-13/15
# across all 12 candidates, 8 routes each).
#
# A public Invidious instance does the hard part from its OWN clean egress: it mints a signed
# googlevideo URL carrying a PO token (the "pot" param). Verified 2026-10-15 that such a URL is
# NOT bound to the requesting IP -- the instance's own IP sits in the signed "ip" param, yet a
# ranged fetch from a DIFFERENT residential IP returned HTTP 206 with the full bytes. So the PO
# token, not the fetcher's IP, gates the media: a datacenter fetcher (this workflow) can pull the
# bytes with no YouTube session cookie at all.
#
# This is a FALLBACK, not a replacement. It runs as a fast path BEFORE the yt-dlp chain; any
# failure is recorded and download() continues through the existing routes untouched. Only public
# data is ever READ -- it never authenticates, posts, or mutates any account. Disable with
# INVIDIOUS_DISABLED=1; point at specific instances with INVIDIOUS_INSTANCES (comma-separated).
_INVIDIOUS_FALLBACKS = (
    # Ordered by observed availability 2026-10-15: f5.si answered HTTP 200 while the others
    # returned 401/403/502 or timed out. Kept as backups in case the first one goes down.
    "https://invidious.f5.si",
    "https://inv.nadeko.net",
    "https://yewtu.be",
    "https://iv.ggtyler.dev",
)
# Common YouTube video itags -> height, used when the API omits an explicit height field.
_ITAG_HEIGHT = {
    160: 144, 597: 144, 605: 144, 278: 144, 394: 144,
    133: 360, 598: 360, 606: 360, 243: 360, 396: 360,
    134: 480, 135: 480, 244: 480, 397: 480,
    136: 720, 599: 720, 607: 720, 247: 720, 398: 720,
    137: 1080, 602: 1080, 608: 1080, 248: 1080, 399: 1080,
    266: 2160, 313: 2160, 401: 2160,
}


def _invidious_instances():
    """Instance base URLs, honouring an INVIDIOUS_INSTANCES override."""
    override = (os.environ.get("INVIDIOUS_INSTANCES") or "").strip()
    if override:
        return [u.strip().rstrip("/") for u in override.split(",") if u.strip()]
    return list(_INVIDIOUS_FALLBACKS)


def youtube_video_id(url):
    """Extract a YouTube video id, or None for anything that isn't a YouTube media link."""
    m = re.search(r"(?:[?&]v=|/shorts/|/embed/|/live/|/v/)([0-9A-Za-z_-]{11})", url or "")
    return m.group(1) if m else None


def _stream_to(path, url, timeout, deadline=None):
    """Fetch a PO-token-signed media URL to disk. Returns bytes written.

    Uses explicit Range requests instead of one long-lived read. Measured 2026-10-15 on this
    source: a plain full-file stream from a third-party IP is throttled to ~0.04 MB/s (an 8 MB
    fetch ran 80s), while ranged requests sustain ~2.9 MB/s -- a 70x difference, and the gap is
    what decides whether a 715s source is downloadable at all. Chunking also bounds how long a
    single stall can hold the download and makes each chunk retryable on its own.

    `deadline` (a time.monotonic() value) is the TOTAL wall-clock budget. urlopen's `timeout`
    only bounds silence between receives, so a server that keeps trickling data can otherwise
    run far past it -- measured: timeout=1 still ran 4.10s of wall time. Every loop here checks
    the deadline so a slow instance can never eat the job's budget before the yt-dlp chain runs.
    """
    import urllib.request
    ua = {"User-Agent": "Mozilla/5.0"}

    def _budget_left():
        return deadline is None or time.monotonic() < deadline

    total = 0
    try:                                   # Content-Range on a 1-byte probe carries the size
        probe = urllib.request.Request(url, headers={**ua, "Range": "bytes=0-0"})
        with urllib.request.urlopen(probe, timeout=20) as resp:
            content_range = resp.headers.get("Content-Range") or ""
            # Read only a slice: the header already carries the total, and an unbounded
            # resp.read() here lets a server that ignores Range stream its entire body past
            # the deadline (measured 16.6s of wall time against a 5.0s budget).
            resp.read(4096)
        if "/" in content_range:
            total = int(content_range.rsplit("/", 1)[-1])
    except Exception:
        total = 0

    written = 0
    chunk_size = 4 * 1024 * 1024
    if total > 0:
        with open(path, "wb") as handle:
            start = 0
            while start < total:
                if not _budget_left():
                    raise RuntimeError(f"download deadline reached at {written} bytes")
                end = min(start + chunk_size, total) - 1
                req = urllib.request.Request(url, headers={**ua, "Range": f"bytes={start}-{end}"})
                last = None
                for attempt in range(3):    # one stalled chunk must not abort the whole file
                    try:
                        with urllib.request.urlopen(req, timeout=timeout) as resp:
                            data = resp.read()
                        break
                    except Exception as exc:
                        last = exc
                        data = b""
                        if attempt == 2:
                            raise RuntimeError(
                                f"chunk {start}-{end} failed after 3 tries: {last}") from last
                if not data:
                    raise RuntimeError(f"chunk {start}-{end} returned no data")
                handle.write(data)
                written += len(data)
                start = end + 1
        return written

    # No usable size reported: fall back to a single plain read. This is the throttled path
    # (~0.04 MB/s measured), so it is bounded by BOTH the total deadline and a minimum
    # sustained rate -- otherwise one instance could sit for ~an hour (150 MB at 0.04 MB/s)
    # while the job's budget drains and the yt-dlp chain never gets its turn.
    req = urllib.request.Request(url, headers=ua)
    started = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(path, "wb") as handle:
        while True:
            if not _budget_left():
                raise RuntimeError(f"download deadline reached at {written} bytes (plain read)")
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            handle.write(chunk)
            written += len(chunk)
            elapsed = time.monotonic() - started
            # 0.25 MB/s is well under the 2.9 MB/s healthy rate but well over the 0.04 MB/s
            # throttle -- past 20s, anything slower is not worth completing.
            if elapsed > 20 and (written / elapsed) < 0.25 * 1024 * 1024:
                raise RuntimeError(
                    f"plain read throttled to {written / 1e6 / elapsed:.2f} MB/s at "
                    f"{written} bytes; aborting rather than draining the download budget")
    return written


def _pick_formats(entry, max_height):
    """Choose the best H.264 video + m4a audio pair from an Invidious /videos payload.

    H.264 + m4a is what the rest of this pipeline already prefers (format_sort vcodec:h264,
    acodec:m4a) and both are MP4, so the merge is a lossless remux with no re-encode. AV1/VP9
    are skipped on purpose: they would need a transcode to combine with m4a.
    """
    def height_of(fmt):
        for key in ("height", "qualityLabel"):
            digits = re.sub(r"\D", "", str(fmt.get(key) or ""))
            if digits:
                return int(digits)
        try:
            return _ITAG_HEIGHT.get(int(fmt.get("itag")), 0)
        except (TypeError, ValueError):
            return 0

    video = None
    audio = None
    for fmt in entry.get("adaptiveFormats") or []:
        mime = str(fmt.get("type") or "")
        media_url = fmt.get("url")
        if not media_url:
            continue
        if mime.startswith("video/"):
            if "avc1" not in mime:
                continue
            height = height_of(fmt)
            if max_height and height > max_height:
                continue
            if video is None or height > video[0]:
                video = (height, media_url)
        elif mime.startswith("audio/"):
            score = 2 if "mp4a" in mime else 1     # m4a keeps the remux all-MP4
            if audio is None or score > audio[0]:
                audio = (score, media_url)
    return (video[1] if video else None, audio[1] if audio else None)


def _download_via_invidious(url, out_base, timeout, deadline=None):
    """Resolve + fetch a YouTube source through a public Invidious instance. Returns a path.

    Raises on any failure so download() can fall through to the yt-dlp chain. `deadline` is a
    time.monotonic() wall-clock budget shared with the rest of download(); it is checked between
    instances so one slow instance cannot consume the budget the yt-dlp chain still needs.
    """
    import urllib.request
    vid = youtube_video_id(url)
    if not vid:
        raise RuntimeError("not a YouTube URL")
    max_height = (os.environ.get("YTDLP_MAX_HEIGHT") or "").strip()
    cap = int(max_height) if max_height.isdigit() else 0
    last = None
    for instance in _invidious_instances():
        if deadline is not None and time.monotonic() >= deadline:
            raise RuntimeError(f"download deadline reached before {instance} (last: {last})")
        api = f"{instance}/api/v1/videos/{vid}"
        try:
            req = urllib.request.Request(api, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as response:
                entry = json.loads(response.read().decode("utf-8", "replace"))
        except Exception as exc:
            last = f"{instance}: {type(exc).__name__}"
            continue
        video_url, audio_url = _pick_formats(entry, cap)
        if not video_url:
            last = f"{instance}: no H.264 video format"
            continue
        if not audio_url:
            # Audio is the payoff for this product. Returning a video-only file here would let
            # the clip publish with substituted silence and no error recorded anywhere, so this
            # instance is skipped and the yt-dlp chain gets its turn instead.
            last = f"{instance}: no audio format"
            continue
        video_tmp, audio_tmp = out_base + ".iv.video", out_base + ".iv.audio"
        try:
            if _stream_to(video_tmp, video_url, timeout, deadline) <= 0:
                raise RuntimeError("empty video stream")
            if _stream_to(audio_tmp, audio_url, timeout, deadline) <= 0:
                raise RuntimeError("empty audio stream")
            out = out_base + ".mp4"
            subprocess.run([get_ffmpeg(), "-y", "-i", video_tmp, "-i", audio_tmp,
                            "-c", "copy", "-movflags", "+faststart", out],
                           check=True, capture_output=True, timeout=timeout)
            return out
        except Exception as exc:
            last = f"{instance}: {type(exc).__name__}: {str(exc)[:120]}"
            continue
        finally:
            for tmp in (video_tmp, audio_tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
    raise RuntimeError(f"Invidious fallback failed: {last or 'no instances configured'}")


def _invidious_enabled():
    return (os.environ.get("INVIDIOUS_DISABLED", "").strip().lower()
            not in ("1", "true", "yes"))


def _download_attempt(url, out_base, player_client, fmt, use_proxy):
    """Run one yt-dlp attempt in a killable child process.

    The Python API can remain inside an extractor call after its socket timeout fires.  A child
    process gives every client/format fallback a real wall-clock ceiling and prevents a blocked
    source from holding the parent video build forever.
    """
    # A landscape source fit into 9:16 never uses more than the output width, so long-source
    # callers can cap the ladder via YTDLP_MAX_HEIGHT instead of pulling a 4K file they
    # will only downscale. Short callers leave it unset and keep the full chain.
    max_height = (os.environ.get("YTDLP_MAX_HEIGHT") or "").strip()
    if max_height.isdigit():
        fmt = re.sub(r"height<=\d+", f"height<={int(max_height)}", fmt)
    cmd = [sys.executable, "-m", "yt_dlp", "--format", fmt,
           "--format-sort", "res,vcodec:h264,acodec:m4a", "--merge-output-format", "mp4",
           "--output", out_base + ".%(ext)s", "--no-playlist", "--quiet", "--no-warnings",
           "--no-progress", "--force-overwrites", "--ffmpeg-location", os.path.dirname(get_ffmpeg()),
           "--socket-timeout", "15", "--retries", "0", "--fragment-retries", "0",
           "--extractor-retries", "0", "--file-access-retries", "0", "--concurrent-fragments", "4"]
    if player_client:
        cmd += ["--extractor-args", "youtube:player_client=" + ",".join(player_client)]
    cookie = os.environ.get("YT_COOKIES_FILE") or str(REPO_ROOT / "cookies.txt")
    if os.path.isfile(cookie):
        cmd += ["--cookies", cookie]
    proxy = os.environ.get("YTDLP_PROXY")
    if proxy and use_proxy:
        cmd += ["--proxy", proxy]
    cmd.append(url)
    attempt_timeout = download_attempt_timeout_sec()
    try:
        proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              timeout=attempt_timeout)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"yt-dlp attempt timed out after {attempt_timeout:.0f}s") from e
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip()[-500:]
        raise RuntimeError(tail or f"yt-dlp exited {proc.returncode}")


def download(url, out_base):
    """Download the WHOLE short clip (Shorts are small -> ~5s each, fast & reliable).

    We deliberately do NOT range-download: cutting a section forces yt-dlp to stream the entire
    source through ffmpeg (>150s on long videos), which is why the old compilation approach was
    unusable. Candidates come from /shorts tabs, so the whole file is tiny.

    Tries the client/format chain in _DL_ATTEMPTS so a bot-checked default client can fall back to
    another that still serves media without cookies."""
    import glob
    # Direct media files (Tenor mp4s) -> just fetch the bytes; no extractor needed.
    if url.lower().split("?")[0].endswith((".mp4", ".webm", ".mov")):
        import urllib.request
        out = out_base + ".mp4"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
        with open(out, "wb") as f:
            f.write(data)
        return out
    last = None
    route_errors = []
    # One wall-clock budget for the WHOLE download() call, claimed BEFORE the fallback so the
    # Invidious attempt is charged against it too. (It was originally computed below the
    # fallback, which left the fallback outside the deadline entirely: a slow instance could
    # burn time the yt-dlp chain then never got, right up to the job's 90-minute kill.)
    deadline = time.monotonic() + download_deadline_sec()
    # Fast path: resolve through a public Invidious instance BEFORE grinding the yt-dlp chain,
    # which is bot-walled on datacenter egress. Any failure is recorded below and the chain
    # still runs untouched, so this can only ever help.
    if _invidious_enabled() and youtube_video_id(url):
        for partial in glob.glob(out_base + ".*"):       # clear partials from a prior attempt
            try:
                os.remove(partial)
            except OSError:
                pass
        if time.monotonic() >= deadline:
            route_errors.append("[invidious] no time left in the download deadline")
        else:
            try:
                path = _download_via_invidious(url, out_base,
                                               download_attempt_timeout_sec(), deadline)
                if path and os.path.isfile(path):
                    return path
            except Exception as e:
                route_errors.append(f"[invidious] {str(e).splitlines()[0][:180]}")
    for player_client, fmt, use_proxy in _DL_ATTEMPTS:
        if time.monotonic() >= deadline:
            break
        for f in glob.glob(out_base + ".*"):           # clear partials from a prior attempt
            try:
                os.remove(f)
            except OSError:
                pass
        try:
            _download_attempt(url, out_base, player_client, fmt, use_proxy)
            path = _resolve(out_base)
            if path:
                return path
        except Exception as e:
            last = e
            route = "+".join(player_client) if player_client else "default"
            route += " via proxy" if use_proxy and os.environ.get("YTDLP_PROXY") else " direct"
            route_errors.append(f"[{route}] {str(e).splitlines()[0][:180]}")
            continue
    if route_errors:
        # A total wall with no authenticated session is almost always the missing-secret
        # case, not a code bug: say so directly (proven 2026-09-20 -- every route, every
        # candidate, both proxy legs, all "sign in to confirm you're not a bot").
        cookie = os.environ.get("YT_COOKIES_FILE") or str(REPO_ROOT / "cookies.txt")
        hint = ("" if os.path.isfile(cookie)
                else " (no cookies.txt in play: anonymous datacenter egress gets bot-walled; "
                     "export a fresh YouTube cookies.txt into the YT_COOKIES repo secret)")
        raise RuntimeError("all YouTube download routes failed" + hint + ": "
                           + " | ".join(route_errors))
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


def _loudness_stats(src, offset, dur):
    """Return (mean_db, max_db) for a candidate window, or None for silent/no-audio media."""
    try:
        p = subprocess.run([get_ffmpeg(), "-hide_banner", "-nostats", "-ss", f"{offset:.2f}",
                            "-t", f"{dur:.2f}", "-i", src, "-map", "0:a:0?",
                            "-af", "volumedetect", "-f", "null", "-"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=20)
    except Exception:
        return None
    mean = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", p.stderr or "")
    peak = re.search(r"max_volume:\s*(-?\d+(?:\.\d+)?) dB", p.stderr or "")
    if not mean:
        return None
    return float(mean.group(1)), float(peak.group(1)) if peak else float(mean.group(1))


def best_moment_offset(src, source_duration, window_duration):
    """Choose a short window around the strongest audible payoff instead of always taking EOF.

    Reddit/YouTube Shorts often already contain one moment, so short sources stay intact. For a
    longer source, a few evenly-spaced windows are scored by average loudness plus the peak. This
    is deliberately deterministic and cheap: it catches the laugh/shout/reaction beat without
    pretending that a title-only model knows the exact frame of the punchline.
    """
    if not source_duration or source_duration <= window_duration + 0.8:
        return 0.0
    slack = max(0.0, source_duration - window_duration)
    starts = sorted({round(slack * f, 2) for f in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)})
    best_start, best_score = starts[-1], None
    for start in starts:
        stats = _loudness_stats(src, start, window_duration)
        if not stats:
            continue
        mean, peak = stats
        score = mean + 0.22 * peak
        if best_score is None or score > best_score:
            best_start, best_score = start, score
    return float(best_start)


def normalize(src, offset, dur, out, loop=0):
    """Whole frame FIT into 9:16 over a blurred fill (no crop-zoom).

    `loop` repeats the source N extra times (for short Tenor gifs) so each rank gets enough screen
    time; the gif is a loop anyway, so this reads naturally.

    Audio (per the user's spec): NO sound effects -- the whoosh/boom/'fahh' SFX were
    removed. Each clip keeps ONLY its ORIGINAL sound when it's audible, or sits on
    silence when it's quiet. The background-music bed is mixed in once over the whole
    video by the final assembly in main() (--music), not per clip."""
    vf = (f"[0:v]split=2[b][f];"
          f"[b]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,crop={OUT_W}:{OUT_H},"
          f"boxblur=20:1,setsar=1[bg];"
          f"[f]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease,setsar=1[fg];"
          f"[bg][fg]overlay=(W-w)/2:(H-h)/2,fps={FPS},format=yuv420p[v]")

    lvl = mean_volume_db(src, offset, dur)
    audible = lvl is not None and lvl > SILENCE_DB

    # inputs: 0=clip; (silent only) 1=silence base. No SFX inputs.
    loop_opt = ["-stream_loop", str(loop)] if loop else []
    inputs = [*loop_opt, "-ss", f"{offset:.2f}", "-i", src]
    if audible:
        a = ["[0:a]aresample=44100,volume=1.0[a]"]
    else:
        inputs += ["-f", "lavfi", "-t", f"{dur:.2f}", "-i", "anullsrc=r=44100:cl=stereo"]
        a = ["[1:a]volume=1.0[a]"]
    chain = vf + ";" + ";".join(a)

    run_ffmpeg([*inputs, "-filter_complex", chain, "-map", "[v]", "-map", "[a]", "-t", f"{dur:.2f}",
                "-ar", "44100", "-ac", "2", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                "-c:a", "aac", "-b:a", "160k", out])


# MOMO theme gold #E6B23A in ASS AABBGGRR (ASS stores colors as BGR, not RGB).
GOLD = "&H003AB2E6&"


def build_overlay_ass(segments, title, total, teaser_dur=0.0, teaser_text="", cta_dur=0.0, cta_text=""):
    head = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 0\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        # Header: the overall video title, pinned top-centre for the whole video.
        "Style: Header,Arial,62,&H00FFFFFF,&H0,&H00000000,&H78000000,1,0,0,0,100,100,0,0,1,5,3,8,50,50,120,1\n"
        # Board: a COMPACT leaderboard down the left side -- top-anchored, fixed slots, #1 on top.
        "Style: Board,Arial,46,&H00FFFFFF,&H0,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,3,2,7,45,40,330,1\n"
        # Teaser: the cold-open hook -- big, centred, gold; only on screen during the teaser flash.
        "Style: Teaser,Arial,90,&H0066D7FF&,&H0,&H00000000,&H78000000,1,0,0,0,100,100,0,0,1,7,4,5,80,80,0,1\n"
        # CTA: a follow call-to-action end-card over the #1 payoff -- bold white, bottom-centre,
        # lifted clear of the phone UI. VISUAL ONLY (no SFX, per the audio rule).
        "Style: CTA,Arial,64,&H00FFFFFF,&H0,&H00000000,&H78000000,1,0,0,0,100,100,0,0,1,6,3,2,60,60,180,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    # rank -> short funny label (e.g. "Aura Lost"); each rank has its own.
    by_rank = {s["rank"]: (s.get("label") or "") for s in segments}
    ranks_asc = sorted(by_rank)                           # 1,2,3,4,5 top-to-bottom (#1 on top)

    # Title is pinned for the whole video EXCEPT the teaser flash, where the cold-open hook owns
    # the screen and promises the #1 payoff up front.
    rows = [f"Dialogue: 0,{ass_time(teaser_dur)},{ass_time(total)},Header,,0,0,0,,{esc(title)[:55]}"]
    if teaser_dur > 0 and teaser_text:
        rows.append(
            f"Dialogue: 0,{ass_time(0)},{ass_time(teaser_dur)},Teaser,,0,0,0,,"
            # fade in/out + a quick scale-down "pop" so the hook punches on the open.
            "{\\fad(90,90)\\fscx118\\fscy118\\t(0,220,\\fscx100\\fscy100)}" + esc(teaser_text)[:24])
    for s in segments:
        cur = s["rank"]
        lines = []
        for k in ranks_asc:
            lbl = esc(by_rank[k])[:16]
            txt = (f"#{k} {lbl}").strip()
            if k == cur:                                  # the rank being revealed now: gold, bold +
                # a kinetic "pop": the active row scales 122%->100% over 220ms as it's revealed.
                lines.append("{\\c" + GOLD + "\\b1\\alpha&H00&\\fscx122\\fscy122"
                             "\\t(0,220,\\fscx100\\fscy100)}" + txt + "{\\r}")
            elif k > cur:                                 # already counted down past -> dimmed
                lines.append("{\\alpha&H85&}" + txt + "{\\r}")
            else:                                         # not revealed yet -> invisible (keeps slot)
                lines.append("{\\alpha&HFF&}" + txt + "{\\r}")
        board = "\\N".join(lines)
        rows.append(f"Dialogue: 0,{ass_time(s['start'] + teaser_dur)},"
                    f"{ass_time(s['end'] + teaser_dur)},Board,,0,0,0,,{board}")
    # Follow CTA end-card: a visual "follow" prompt over the #1 payoff on the final seconds.
    # Clamped to the last (#1) clip so it never bleeds onto #2. Visual only -- no SFX (audio rule).
    if cta_dur > 0 and cta_text and segments:
        last_dur = segments[-1]["end"] - segments[-1]["start"]
        eff = min(cta_dur, last_dur, total)
        cs = max(0.0, total - eff)
        rows.append(
            f"Dialogue: 1,{ass_time(cs)},{ass_time(total)},CTA,,0,0,0,,"
            # fade in + a quick scale-down pop so the follow prompt punches on the payoff.
            "{\\fad(150,0)\\fscx120\\fscy120\\t(0,250,\\fscx100\\fscy100)}" + esc(cta_text)[:26])
    return head + "\n".join(rows) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ranked", default=".tmp/ranked.json")
    ap.add_argument("--title", default=None, help="Overall video title pinned at the top")
    ap.add_argument("--music", default=None)
    ap.add_argument("--music-volume", type=float, default=DEFAULT_MUSIC_VOLUME)
    ap.add_argument("--music-pitch", type=float, default=DEFAULT_MUSIC_PITCH,
                    help="Native pitch only. Non-native pitch shifting is disabled by policy.")
    ap.add_argument("--intro-swoosh", default=None,
                    help="One-shot SFX placed once at t=0. OFF by default (user rule, 2026-06-23 — "
                         "no intro swoosh); only added when an explicit path is passed here.")
    ap.add_argument("--swoosh-volume", type=float, default=0.7,
                    help="Intro swoosh gain. The synthesized swoosh is loud, so it stays audible "
                         "over full-level clip/background audio without ducking.")
    ap.add_argument("--swoosh-duck", type=float, default=0.0,
                    help="Seconds to duck the clip/background audio at the start so the swoosh is "
                         "audible. 0 = no duck (background stays at full level).")
    ap.add_argument("--max-total", type=float, default=58.0, help="Hard cap on total length (under 1 min)")
    ap.add_argument("--per-clip", type=float, default=24.0,
                    help="Max seconds shown per clip; longer clips are scored for their main payoff")
    ap.add_argument("--min-clips", type=int, default=3,
                    help="Minimum number of source clips that must render successfully")
    ap.add_argument("--teaser", dest="teaser", action="store_true", default=True,
                    help="Cold-open hook: flash ~1.2s of the #1 clip before the "
                         "#5 countdown starts (default ON -- biggest retention lever).")
    ap.add_argument("--no-teaser", dest="teaser", action="store_false",
                    help="Disable the cold-open teaser; start straight on #5.")
    ap.add_argument("--teaser-dur", type=float, default=1.2, help="Teaser length in seconds.")
    ap.add_argument("--teaser-text", default=DEFAULT_TEASER_TEXT,
                    help="On-screen hook shown over the teaser flash.")
    ap.add_argument("--cta", dest="cta", action="store_true", default=True,
                    help="Visual follow CTA end-card over the #1 payoff (default ON; no SFX, "
                         "per the audio rule -- purely on-screen text).")
    ap.add_argument("--no-cta", dest="cta", action="store_false",
                    help="Disable the follow CTA end-card.")
    ap.add_argument("--cta-dur", type=float, default=2.5, help="CTA end-card length in seconds.")
    ap.add_argument("--cta-text", default="FOLLOW FOR #1 DAILY", help="Follow CTA on-screen text.")
    ap.add_argument("--out", default=".tmp/final.mp4")
    args = ap.parse_args()

    load_env()
    try:
        data = json.load(open(args.ranked, encoding="utf-8"))
        entries = data["entries"]
    except (OSError, json.JSONDecodeError, KeyError) as e:
        fail(f"Could not read --ranked: {e}")
        return

    if args.min_clips < 1:
        fail("--min-clips must be at least 1")
        return
    if data.get("content_policy") == "streamer-only":
        invalid = [e.get("id") or e.get("title") or "unknown" for e in entries
                   if e.get("content_type") != "streamer_clip"
                   or not e.get("streamer_identity")
                   or e.get("content_policy") != "streamer-only"]
        if invalid:
            fail("Streamer-only ranking contains an unverified entry.",
                 content_policy="streamer-only", invalid_entries=invalid[:10])
            return

    os.makedirs(TMPDIR, exist_ok=True)
    # Reserve room for the cold-open teaser so teaser + clips still fit under max-total.
    teaser_reserve = float(args.teaser_dur) if args.teaser else 0.0
    budget = max(1.0, args.max_total - teaser_reserve)
    # Cap each clip so the whole video stays <= budget.
    cap = min(args.per_clip, budget / max(1, len(entries)))

    from _media import probe_duration
    MIN_SHOW = 3.0                                      # loop short gifs up to this many seconds
    import math
    clips, segments, cursor, errors = [], [], 0.0, []
    for i, e in enumerate(entries):
        try:
            src = download(e["url"], os.path.join(TMPDIR, f"src_{i}"))
        except Exception as ex:
            errors.append(f"download #{e.get('rank', i)}: {str(ex).splitlines()[0][:160]}")
            continue
        try:
            dsrc = probe_duration(src)                 # real duration
        except Exception:
            dsrc = None
        if dsrc and dsrc < 0.8:                         # skip only truly degenerate/blank clips
            errors.append(f"too short #{e.get('rank', i)}: {dsrc:.1f}s")
            continue
        target = min(cap, dsrc or cap)
        if dsrc and dsrc < MIN_SHOW:                   # only loop truly tiny GIF-like sources
            target = min(cap, MIN_SHOW)
            loop, offset, dur = math.ceil(target / dsrc), 0.0, target
        else:
            loop, dur = 0, target
            # Keep a complete Short intact; on longer sources find the main audible/funny beat.
            offset = best_moment_offset(src, dsrc, dur) if dsrc else 0.0
        clip = os.path.join(TMPDIR, f"clip_{i}.mp4")
        try:
            normalize(src, offset, dur, clip, loop)
        except Exception as ex:
            errors.append(f"normalize #{e.get('rank', i)}: {str(ex).splitlines()[0][:160]}")
            continue
        clips.append(clip)
        segments.append({"start": cursor, "end": round(cursor + dur, 2), "title": e["title"],
                         "label": e.get("label") or ""})
        cursor = round(cursor + dur, 2)
        if len(clips) >= 5:                            # five is enough for a Top-5
            break

    if len(clips) < args.min_clips:
        hint = ""
        if any("bot" in e.lower() or "sign in" in e.lower() for e in errors):
            hint = (" -- YouTube is blocking downloads from this IP (bot-check). On GitHub Actions "
                    "set the YT_COOKIES secret to a valid Netscape cookies.txt.")
        fail(f"Only {len(clips)} usable clips — need >={args.min_clips}.{hint}", reasons=errors[:8])
        return

    n = len(clips)
    for p, s in enumerate(segments):
        s["rank"] = n - p                              # first shown = highest number, last = #1
    clip_total = round(min(cursor, budget), 2)

    # Cold-open teaser (user/competitor rule, 2026-06-23): flash ~1.2s of the #1 clip's MAIN ACTION
    # with a concrete payoff hook BEFORE the #5 countdown, so the payoff is promised in frame one --
    # the single biggest retention lever for countdown Shorts. clips[-1] (rank #1) was already
    # normalized to END on the source's payoff moment (see the "show its END" trim above), so the
    # teaser grabs clips[-1]'s OWN selected payoff window rather than the raw source start/end.
    teaser_dur, teaser_clip = 0.0, None
    if args.teaser and clips:
        td = min(float(args.teaser_dur), max(0.5, segments[-1]["end"] - segments[-1]["start"]))
        cand = os.path.join(TMPDIR, "teaser.mp4")
        try:
            last_dur = segments[-1]["end"] - segments[-1]["start"]
            teaser_start = max(0.0, (last_dur - td) * 0.55)
            run_ffmpeg(["-ss", f"{teaser_start:.2f}", "-t", f"{td:.2f}", "-i", clips[-1],
                        "-ar", "44100", "-ac", "2",
                        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                        "-c:a", "aac", "-b:a", "160k", cand])
            teaser_dur, teaser_clip = td, cand
        except Exception as ex:                         # teaser is best-effort: skip, never block
            errors.append(f"teaser: {str(ex).splitlines()[0][:120]}")

    total = round(min(teaser_dur + clip_total, args.max_total), 2)

    title = args.title or data.get("title") or "Ranking"
    ass_path = os.path.join(TMPDIR, "overlay.ass")
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(build_overlay_ass(segments, title, total, teaser_dur,
                                  args.teaser_text if teaser_dur > 0 else "",
                                  args.cta_dur if args.cta else 0.0, args.cta_text))
    ass_rel = os.path.relpath(ass_path, os.getcwd()).replace("\\", "/")

    # Intro swoosh removed (user rule, 2026-06-23): NO intro swoosh by default. It is only
    # added when an explicit --intro-swoosh path is passed; no auto-pickup of assets/sfx/whoosh.mp3.
    intro_swoosh = args.intro_swoosh

    # Concat order: the teaser (if any) plays first, then the #5->#1 clips.
    ff = []
    if teaser_clip:
        ff += ["-i", teaser_clip]
    for c in clips:
        ff += ["-i", c]
    n_v = (1 if teaser_clip else 0) + n                 # number of concat (video+audio) inputs
    idx = n_v
    music_idx = None
    if args.music and os.path.isfile(args.music):
        ff += ["-stream_loop", "-1", "-i", args.music]      # looped bed
        music_idx = idx; idx += 1
    swoosh_idx = None
    if intro_swoosh and os.path.isfile(intro_swoosh):
        ff += ["-i", intro_swoosh]                          # one-shot: NOT looped -> plays once at t=0
        swoosh_idx = idx; idx += 1

    concat_in = "".join(f"[{k}:v][{k}:a]" for k in range(n_v))
    chain = f"{concat_in}concat=n={n_v}:v=1:a=1[cv][ca];[cv]ass={ass_rel}[v]"

    if music_idx is not None and abs(args.music_pitch - 1.0) > 1e-3:
        fail("--music-pitch is disabled; use an original or explicitly rights-cleared bed at native pitch")
        return

    # Audio mix. The clips' ORIGINAL audio stays at full level; the generated bed + optional
    # intro swoosh sit under it. The bed is sidechain-ducked from the clip audio so speech and
    # the actual streamer payoff remain the loudest signal. normalize=0 keeps levels; a final
    # limiter guards the summed signal against clipping.
    # When there's an intro swoosh, briefly duck the clip audio at t=0 so the swoosh punches
    # through (otherwise a full-level clip masks it); ramp back to full over swoosh_duck seconds.
    if music_idx is not None:
        if swoosh_idx is not None and args.swoosh_duck > 0:
            d = args.swoosh_duck
            base_filter = (
                f"[ca]volume='min(1,0.15+0.85*t/{d:.3f})':eval=frame,"
                "asplit=2[base][bed_sidechain]"
            )
        else:
            base_filter = "[ca]volume=1.0,asplit=2[base][bed_sidechain]"
    elif swoosh_idx is not None and args.swoosh_duck > 0:
        d = args.swoosh_duck
        base_filter = f"[ca]volume='min(1,0.15+0.85*t/{d:.3f})':eval=frame[base]"
    else:
        base_filter = "[ca]volume=1.0[base]"
    pre, labels = [base_filter], ["[base]"]
    if music_idx is not None:
        pre.append(
            f"[{music_idx}:a]aresample=44100,highpass=f=70,lowpass=f=9000,"
            f"volume={args.music_volume}[musraw]"
        )
        pre.append(
            "[musraw][bed_sidechain]sidechaincompress=threshold=0.035:ratio=10:"
            "attack=5:release=300[mus]"
        )
        labels.append("[mus]")
    if swoosh_idx is not None:
        pre.append(f"[{swoosh_idx}:a]aresample=44100,volume={args.swoosh_volume}[swh]")
        labels.append("[swh]")
    if len(labels) > 1:
        chain += ";" + ";".join(pre) + ";" + "".join(labels) + (
            f"amix=inputs={len(labels)}:duration=first:normalize=0:dropout_transition=0,"
            f"alimiter=level_in=1:level_out=1:limit=0.97[a]")
        amap = "[a]"
    else:
        amap = "[ca]"

    ff += ["-filter_complex", chain, "-map", "[v]", "-map", amap, "-t", f"{total:.2f}",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "high", "-preset", "medium",
           "-crf", "18", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", args.out]
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    try:
        run_ffmpeg(ff)
    except Exception as e:
        fail(f"Final assembly failed: {e}")
        return

    emit({"path": args.out, "byte_size": os.path.getsize(args.out), "duration_sec": total,
          "entries": [{"rank": s["rank"], "title": s["title"][:50]} for s in segments],
          "title": data.get("title"),
          "audio_profile": "generated_bed_ducked" if music_idx is not None else "original_audio_only",
          "music_volume": round(args.music_volume, 3) if music_idx is not None else 0.0})


if __name__ == "__main__":
    main()
