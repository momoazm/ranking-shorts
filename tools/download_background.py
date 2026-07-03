"""Download a long looping gameplay background (Minecraft parkour, Subway Surfers, etc.) once
and cache it under assets/backgrounds/<name>.mp4 for reuse across many videos.

Point --url at a NO-COPYRIGHT / Creative-Commons gameplay source you have the right to use —
this tool downloads and caches; it does NOT vet rights. Uses yt-dlp with the ffmpeg binary
bundled by imageio-ffmpeg (no system install needed).

Usage:
    python tools/download_background.py --url "https://..." --name minecraft_parkour [--max-height 1080] [--force]

Prints JSON: {"path": ..., "name": ..., "cached": bool, "duration_sec": F}
"""
import argparse
import os
from pathlib import Path

from _common import emit, fail
from _media import get_ffmpeg, probe_duration

BACKGROUNDS_DIR = Path("assets/backgrounds")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--name", required=True, help="Stable cache name, e.g. minecraft_parkour")
    parser.add_argument("--max-height", type=int, default=1080)
    parser.add_argument("--force", action="store_true", help="Re-download even if cached")
    args = parser.parse_args()

    safe_name = "".join(c for c in args.name if c.isalnum() or c in ("-", "_")).strip("_") or "background"
    BACKGROUNDS_DIR.mkdir(parents=True, exist_ok=True)
    target = BACKGROUNDS_DIR / f"{safe_name}.mp4"

    if target.is_file() and not args.force:
        try:
            duration = probe_duration(str(target))
        except Exception:
            duration = None
        emit({"path": str(target), "name": safe_name, "cached": True, "duration_sec": duration})
        return

    try:
        import yt_dlp
    except ImportError as e:
        fail(f"yt-dlp not installed: {e}. Install requirements.txt into the project venv.")
        return

    opts = {
        "outtmpl": str(BACKGROUNDS_DIR / f"{safe_name}.%(ext)s"),
        "format": f"bv*[ext=mp4][height<={args.max_height}]+ba[ext=m4a]/b[ext=mp4]/b",
        "merge_output_format": "mp4",
        "ffmpeg_location": get_ffmpeg(),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "overwrites": True,
    }
    proxy = os.environ.get("YTDLP_PROXY")   # datacenter-IP runners: route via WARP/residential proxy
    if proxy:
        opts["proxy"] = proxy

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(args.url, download=True)
            requested = info.get("requested_downloads")
            final_path = requested[0]["filepath"] if requested else ydl.prepare_filename(info)
    except Exception as e:
        fail(f"yt-dlp download failed: {e}. Check the URL is reachable and downloadable.")
        return

    final_path = Path(final_path)
    if final_path.resolve() != target.resolve():
        try:
            if target.exists():
                target.unlink()
            final_path.rename(target)
        except OSError:
            target = final_path  # report whatever was actually produced

    try:
        duration = probe_duration(str(target))
    except Exception:
        duration = None

    emit({"path": str(target), "name": safe_name, "cached": False, "duration_sec": duration})


if __name__ == "__main__":
    main()
