"""Fetch a sound effect or music track into assets/sfx (or assets/music) for the dialogue mix.

Handles a direct audio URL (httpx) OR a YouTube/page URL (yt-dlp bestaudio). Normalizes to a
trimmed, mono->stereo mp3 with the bundled ffmpeg so the mix tool gets clean, predictable clips.

COPYRIGHT: point this at genuinely no-copyright / royalty-free sources you may use; it does NOT
vet rights.

Usage:
    python tools/fetch_audio.py --url "<url>" --name whoosh --dir assets/sfx --duration 1.2
    python tools/fetch_audio.py --url "<youtube>" --name boom --dir assets/sfx --start 0.1 --duration 1.5

Prints JSON: {"path": ..., "name": ..., "duration_sec": F, "source": "http|ytdlp"}
"""
import argparse
import os

from _common import emit, fail
from _media import get_ffmpeg, run_ffmpeg, probe_duration

AUDIO_EXTS = (".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac", ".opus")


def download_http(url, tmp):
    import httpx
    headers = {"User-Agent": "Mozilla/5.0 (compatible; ai-videos/1.0)"}
    with httpx.Client(follow_redirects=True, timeout=90, headers=headers) as c:
        r = c.get(url)
        r.raise_for_status()
        with open(tmp, "wb") as f:
            f.write(r.content)


def download_ytdlp(url, tmp_base):
    import yt_dlp
    opts = {
        "outtmpl": tmp_base + ".%(ext)s",
        "format": "bestaudio/best",
        "ffmpeg_location": get_ffmpeg(),
        "noplaylist": True, "quiet": True, "no_warnings": True, "overwrites": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        req = info.get("requested_downloads")
        return req[0]["filepath"] if req else ydl.prepare_filename(info)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--name", required=True, help="e.g. whoosh, boom, bed")
    parser.add_argument("--dir", default="assets/sfx", help="assets/sfx or assets/music")
    parser.add_argument("--start", type=float, default=0.0, help="Trim start seconds")
    parser.add_argument("--duration", type=float, default=0.0, help="Trim length seconds (0 = keep all)")
    parser.add_argument("--gain-db", type=float, default=0.0, help="Volume gain in dB")
    parser.add_argument("--via", choices=["auto", "http", "ytdlp"], default="auto")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    safe = "".join(c for c in args.name if c.isalnum() or c in ("-", "_")).strip("_") or "audio"
    os.makedirs(args.dir, exist_ok=True)
    dest = os.path.join(args.dir, f"{safe}.mp3")
    if os.path.isfile(dest) and not args.force:
        try:
            dur = probe_duration(dest)
        except Exception:
            dur = None
        emit({"path": dest, "name": safe, "duration_sec": dur, "source": "cached"})
        return

    via = args.via
    if via == "auto":
        path = args.url.split("?")[0].lower()
        via = "http" if path.endswith(AUDIO_EXTS) else "ytdlp"

    tmp_base = os.path.join(args.dir, f".{safe}.raw")
    raw = tmp_base + ".bin"
    try:
        if via == "http":
            download_http(args.url, raw)
        else:
            raw = download_ytdlp(args.url, tmp_base)
    except Exception as e:
        fail(f"Audio download failed ({via}): {e}")
        return

    # Normalize: optional trim + gain, force stereo 44.1k mp3.
    af = ["aformat=sample_rates=44100:channel_layouts=stereo"]
    if args.gain_db:
        af.append(f"volume={args.gain_db}dB")
    ff = []
    if args.start > 0:
        ff += ["-ss", str(args.start)]
    ff += ["-i", raw]
    if args.duration > 0:
        ff += ["-t", str(args.duration)]
    ff += ["-af", ",".join(af), "-c:a", "libmp3lame", "-q:a", "2", dest]
    try:
        run_ffmpeg(ff)
    except Exception as e:
        fail(f"ffmpeg normalize failed: {e}")
        return
    finally:
        if os.path.isfile(raw):
            os.remove(raw)

    try:
        dur = probe_duration(dest)
    except Exception:
        dur = None
    emit({"path": dest, "name": safe, "duration_sec": dur, "source": via})


if __name__ == "__main__":
    main()
