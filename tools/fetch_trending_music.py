"""Fetch a trending background-music track from YouTube (audio only) via yt-dlp.

Searches YouTube for a trending/viral track and downloads its audio to mp3, for use as the music
bed under a ranking video.

COPYRIGHT WARNING: real trending songs are copyrighted — a YouTube upload using one will almost
certainly get a Content ID claim (revenue to the rights holder) or be muted. Pass --query with a
"no copyright"/"royalty free" phrase if you want to avoid that.

Usage:
    python tools/fetch_trending_music.py [--query "..."] [--out .tmp/music.mp3]

Prints JSON: {"path","title","query","id"}
"""
import argparse
import os

from _common import load_env, emit, fail, REPO_ROOT

DEFAULT_QUERY = "trending tiktok background music 2026"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", default=DEFAULT_QUERY)
    ap.add_argument("--out", default=".tmp/music.mp3")
    args = ap.parse_args()

    load_env()
    from _media import get_ffmpeg
    out_base = os.path.splitext(args.out)[0]
    opts = {
        "format": "bestaudio/best",
        "outtmpl": out_base + ".%(ext)s",
        "noplaylist": True, "quiet": True, "no_warnings": True, "noprogress": True,
        "overwrites": True, "ffmpeg_location": os.path.dirname(get_ffmpeg()),
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
    }
    cookie = os.environ.get("YT_COOKIES_FILE") or str(REPO_ROOT / "cookies.txt")
    if os.path.isfile(cookie):
        opts["cookiefile"] = cookie
    proxy = os.environ.get("YTDLP_PROXY")   # datacenter-IP runners: route via WARP/residential proxy
    if proxy:
        opts["proxy"] = proxy

    try:
        from yt_dlp import YoutubeDL
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch1:{args.query}", download=True)
        entry = (info.get("entries") or [info])[0]
    except Exception as e:
        fail(f"Music fetch failed: {e}")
        return

    mp3 = out_base + ".mp3"
    if not os.path.isfile(mp3):
        fail("Music download produced no mp3.")
        return
    emit({"path": mp3, "title": entry.get("title"), "query": args.query, "id": entry.get("id")})


if __name__ == "__main__":
    main()
