"""Save a finished video + ready-to-paste captions into a dated folder for MANUAL posting.

The semi-manual workflow: the pipeline builds the brainrot Short and its per-platform
caption/hashtag blocks, this drops them into `exports/<date-time>-<title>/` so you can grab the
mp4 and copy the caption straight onto Instagram / TikTok from your phone — no API approval needed.

Writes:
  video.mp4        the finished 1080x1920 Short
  instagram.txt    caption + hashtags for the IG Reel
  tiktok.txt       caption + hashtags for TikTok
  youtube.txt      title, description, and tags (if you also post YT by hand)
  POST_ME.txt      a tiny checklist tying it together

Usage:
    python tools/export_local.py --video .tmp/final.mp4 --captions-meta .tmp/captions_meta.json \
        [--title "..."] [--out-dir exports]

Prints JSON: {"folder": "exports/...", "files": [...]}
"""
import argparse
import json
import os
import re
import shutil
from datetime import datetime

from _common import emit, fail


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def slug(text, n=40):
    s = re.sub(r"[^0-9a-z]+", "-", (text or "video").lower()).strip("-")
    return (s[:n].rstrip("-")) or "video"


def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--captions-meta", default=".tmp/captions_meta.json")
    parser.add_argument("--title", default="")
    parser.add_argument("--out-dir", default="exports")
    args = parser.parse_args()

    if not os.path.isfile(args.video):
        fail(f"Video not found: {args.video}")
        return
    meta = load_json(args.captions_meta) or {}
    title = args.title or meta.get("title") or "brainrot-short"

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    folder = os.path.join(args.out_dir, f"{stamp}-{slug(title)}")
    os.makedirs(folder, exist_ok=True)

    shutil.copy2(args.video, os.path.join(folder, "video.mp4"))

    ig = (meta.get("instagram", {}) or {}).get("caption", "") or title
    tt = (meta.get("tiktok", {}) or {}).get("caption", "") or title
    yt = meta.get("youtube", {}) or {}
    yt_txt = (f"TITLE:\n{yt.get('title', title)}\n\n"
              f"DESCRIPTION:\n{yt.get('description', '')}\n\n"
              f"TAGS:\n{', '.join(yt.get('tags', []))}\n")

    write(os.path.join(folder, "instagram.txt"), ig)
    write(os.path.join(folder, "tiktok.txt"), tt)
    write(os.path.join(folder, "youtube.txt"), yt_txt)
    write(os.path.join(folder, "POST_ME.txt"),
          "MANUAL POST CHECKLIST\n"
          "=====================\n"
          f"Title: {title}\n\n"
          "1. INSTAGRAM (Reel): upload video.mp4, paste instagram.txt as the caption.\n"
          "2. TIKTOK: upload video.mp4, paste tiktok.txt as the caption.\n"
          "3. (optional) YOUTUBE: upload video.mp4, use youtube.txt for title/description/tags.\n\n"
          "The video is 1080x1920, <60s — Shorts/Reels/TikTok ready.\n")

    files = ["video.mp4", "instagram.txt", "tiktok.txt", "youtube.txt", "POST_ME.txt"]
    emit({"folder": folder, "files": files, "title": title})


if __name__ == "__main__":
    main()
