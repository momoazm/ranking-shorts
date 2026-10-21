"""Download one full source video to a stable path, once, for sequential chopping.

Why this exists: a Shark Tank episode is chopped into 6-12 parts and each part is rendered
by build_clip.py with a different --start. Passing the same YouTube URL to every part would
download the (100-300 MB) episode once per part. The batch orchestrator therefore downloads
the whole source ONCE with this tool, then hands the local file to every part via
`build_clip.py --source-file`.

It is a thin, env-configured wrapper around build_ranking_video.download() -- the exact
downloader (Invidious fast path, WARP proxy, PO-token clients, cookies) the rest of the
pipeline already trusts -- so the download ladder never drifts between tools.

Usage:
    python tools/fetch_source.py --url https://www.youtube.com/watch?v=... \
        --out .tmp/sharktank/source.mp4 --max-height 1440 --download-deadline 900

Prints JSON: {"path": "...", "byte_size": 123, "duration_sec": 587.2}
"""
import argparse
import os

from _common import REPO_ROOT, load_env, emit, fail
from _media import probe_duration

# Reuse the proven downloader (same module build_clip.py imports).
import build_ranking_video as brv


def fetch(url, out_path, max_height=0, deadline=0.0, attempt_timeout=0.0):
    """Download `url` to `out_path` (an .mp4 path) and return the real file path.

    `out_path` may be relative to the repo root. The downloader appends its own extension
    to an extension-less base, so the `.mp4` suffix is stripped before the call; the
    returned path is whatever yt-dlp actually produced.
    """
    if deadline and deadline > 0:
        os.environ["YTDLP_DEADLINE_SEC"] = f"{deadline:.0f}"
    if attempt_timeout and attempt_timeout > 0:
        os.environ["YTDLP_ATTEMPT_TIMEOUT_SEC"] = f"{attempt_timeout:.0f}"
    if max_height and max_height > 0:
        os.environ["YTDLP_MAX_HEIGHT"] = str(int(max_height))

    target = out_path if os.path.isabs(out_path) else str(REPO_ROOT / out_path)
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    # yt-dlp writes "<base>.<ext>"; drop a known media suffix so we don't get "source.mp4.mp4".
    base = target
    for ext in (".mp4", ".webm", ".mkv", ".mov"):
        if base.lower().endswith(ext):
            base = base[: -len(ext)]
            break
    # Remove leftovers from a previous run so a stale file is never mistaken for this one.
    for suffix in (".mp4", ".webm", ".mkv", ".mov", ".part"):
        try:
            os.remove(base + suffix)
        except OSError:
            pass
    path = brv.download(url, base)
    if not path or not os.path.isfile(path):
        raise RuntimeError("downloader produced no file")
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--out", default=".tmp/sharktank/source.mp4")
    parser.add_argument("--max-height", type=int, default=0,
                        help="Cap the download ladder (0 = the downloader's own default).")
    parser.add_argument("--download-deadline", type=float, default=0.0,
                        help="Wall-clock budget for the whole download in seconds.")
    parser.add_argument("--download-attempt-timeout", type=float, default=0.0,
                        help="Per-route ceiling for one yt-dlp attempt.")
    args = parser.parse_args()

    load_env()
    try:
        path = fetch(args.url, args.out, args.max_height,
                     args.download_deadline, args.download_attempt_timeout)
        duration = probe_duration(path)
    except Exception as exc:
        fail(f"source download failed: {exc}", url=args.url)
        return
    emit({"path": path, "byte_size": os.path.getsize(path),
          "duration_sec": round(duration, 2) if duration else None,
          "source_url": args.url})


if __name__ == "__main__":
    main()
