"""Shared ffmpeg helpers. Prefer a system ffmpeg on PATH (guaranteed to ship libass for the
`ass=` caption filter — the cloud runner's apt build does); otherwise fall back to the binary
bundled by imageio-ffmpeg so no system install is required on Windows (the same binary yt-dlp
is pointed at for post-processing). The imageio build may lack libass, so PATH wins when present.
"""
import re
import shutil
import subprocess


def get_ffmpeg():
    system = shutil.which("ffmpeg")
    if system:
        return system
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def run_ffmpeg(args, **kwargs):
    """Run `ffmpeg <args>`; raise RuntimeError with a stderr tail on non-zero exit."""
    cmd = [get_ffmpeg(), "-hide_banner", "-y", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kwargs)
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").strip().splitlines()[-15:])
        raise RuntimeError(f"ffmpeg failed (exit {proc.returncode}):\n{tail}")
    return proc


def probe_duration(path):
    """Return media duration in seconds by parsing ffmpeg's header (imageio-ffmpeg has no ffprobe)."""
    proc = subprocess.run(
        [get_ffmpeg(), "-hide_banner", "-i", path],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    # `ffmpeg -i` with no output exits non-zero but still prints "Duration: HH:MM:SS.ss" to stderr.
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", proc.stderr or "")
    if not m:
        raise RuntimeError(f"Could not determine duration of {path}")
    h, mnt, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return h * 3600 + mnt * 60 + s
