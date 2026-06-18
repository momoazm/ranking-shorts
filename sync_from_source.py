"""Refresh this deployable copy from the live source projects, so improvements you make in
`ai videos/` (and the uploader in `clipping/`) reach the automation on your next `git push`.

It re-copies ONLY the tracked pipeline tools — never secrets, never the gitignored assets/.
`autopost.py`, the workflow, requirements, and this script are owned by the copy and left alone.

Assumes this copy lives alongside the source projects (the default layout):
    <repo>/ai videos/      <- canonical pipeline tools
    <repo>/clipping/       <- the uploader
    <repo>/ai-videos-auto/ <- this copy

Usage:
    python sync_from_source.py          # copy and report
    python sync_from_source.py --check  # report what WOULD change, copy nothing
"""
import argparse
import filecmp
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT.parent / "ai videos"
CLIP = ROOT.parent / "clipping"

# (source_file, dest_file) pairs.
PIPELINE_TOOLS = [
    "_common.py", "_characters.py", "_llm.py", "_media.py",
    "write_story.py", "generate_voiceover.py", "align_captions.py",
    "build_audio_mix.py", "assemble_video.py",
]
JOBS = [(SRC / "tools" / t, ROOT / "tools" / t) for t in PIPELINE_TOOLS]
JOBS.append((CLIP / "tools" / "upload_youtube.py", ROOT / "tools" / "upload_youtube.py"))
# Brand travels with the tools (theme.json is loaded by align_captions).
JOBS.append((SRC / "brand" / "theme.json", ROOT / "brand" / "theme.json"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="Report changes without copying.")
    args = ap.parse_args()

    missing = [str(s) for s, _ in JOBS if not s.is_file()]
    if missing:
        print("ERROR: source files not found (is this copy alongside 'ai videos/' and 'clipping/'?):")
        for m in missing:
            print("  -", m)
        sys.exit(1)

    changed, same = [], []
    for src, dst in JOBS:
        if dst.is_file() and filecmp.cmp(src, dst, shallow=False):
            same.append(dst.name)
            continue
        changed.append(dst.name)
        if not args.check:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    verb = "would change" if args.check else "synced"
    print(f"{verb}: {len(changed)} file(s); unchanged: {len(same)}")
    for c in changed:
        print(("  ~ " if args.check else "  + ") + c)
    if not args.check and changed:
        print("\nNext: git add -A && git commit -m 'sync tools from source' && git push")


if __name__ == "__main__":
    main()
