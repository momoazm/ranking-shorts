"""Download a character image into assets/characters/<key>.png for the dialogue overlay.

Point it at a transparent PNG (ideally cut-out, alpha background) for one of the registry
characters. The file is saved under the exact name the registry expects so assemble_video.py
finds it. Re-runs are cached (skips if already present unless --force).

COPYRIGHT: famous cartoon characters are copyrighted; this tool just downloads what you point
it at and does NOT vet rights. Use sources you're entitled to use, or original/CC art.

Usage:
    python tools/fetch_character.py --key peter --url "https://.../peter.png"
    python tools/fetch_character.py --key stewie --url "https://.../stewie.png" --force

Prints JSON: {"path": ..., "key": ..., "bytes": N, "has_alpha": bool, "cached": bool}
"""
import argparse
import os

from _common import REPO_ROOT, emit, fail
from _characters import CHARACTERS
from _media import run_ffmpeg, get_ffmpeg


def has_alpha(path):
    """True if ffmpeg reports an alpha channel in the image's pixel format."""
    import subprocess
    proc = subprocess.run(
        [get_ffmpeg(), "-hide_banner", "-i", path],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    out = proc.stderr or ""
    return any(tok in out for tok in ("yuva", "rgba", "bgra", "argb", "pal8", "ya8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--key", required=True, help=f"Registry key, one of: {', '.join(CHARACTERS)}")
    parser.add_argument("--url", help="Direct image URL (PNG/WEBP with transparency preferred)")
    parser.add_argument("--file", help="Local image file to import instead of --url")
    parser.add_argument("--force", action="store_true", help="Re-download even if cached")
    args = parser.parse_args()

    key = args.key.strip().lower()
    if key not in CHARACTERS:
        fail(f"Unknown character key '{args.key}'. Known: {', '.join(CHARACTERS)}")
        return
    if not args.url and not args.file:
        fail("Provide --url or --file")
        return

    dest_rel = CHARACTERS[key]["image"]            # e.g. assets/characters/peter.png
    dest = REPO_ROOT / dest_rel
    os.makedirs(dest.parent, exist_ok=True)

    if dest.is_file() and not args.force:
        emit({"path": dest_rel, "key": key, "bytes": dest.stat().st_size,
              "has_alpha": has_alpha(str(dest)), "cached": True})
        return

    tmp = str(dest) + ".download"
    try:
        if args.file:
            import shutil
            shutil.copyfile(args.file, tmp)
        else:
            import httpx
            headers = {"User-Agent": "Mozilla/5.0 (compatible; ai-videos/1.0)"}
            with httpx.Client(follow_redirects=True, timeout=60, headers=headers) as client:
                r = client.get(args.url)
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    f.write(r.content)
    except Exception as e:
        if os.path.isfile(tmp):
            os.remove(tmp)
        fail(f"Download/import failed: {e}")
        return

    # Normalize to PNG (preserving any alpha). Non-alpha sources (jpg) become opaque PNGs —
    # they'll overlay as a rectangle; prefer a cut-out PNG/WEBP for a clean look.
    try:
        run_ffmpeg(["-i", tmp, str(dest)])
    except Exception as e:
        if os.path.isfile(tmp):
            os.remove(tmp)
        fail(f"Could not convert image to PNG: {e}")
        return
    finally:
        if os.path.isfile(tmp):
            os.remove(tmp)

    alpha = has_alpha(str(dest))
    emit({
        "path": dest_rel, "key": key, "bytes": dest.stat().st_size,
        "has_alpha": alpha, "cached": False,
        "note": None if alpha else "No alpha channel — overlay will be a rectangle. Use a cut-out PNG/WEBP.",
    })


if __name__ == "__main__":
    main()
