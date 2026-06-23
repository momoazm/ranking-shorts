"""Screenshot the CS landing page from a running localhost server.

Mirrors the role of the project's screenshot.mjs, but in Python on top of the
Playwright + Chromium that's already installed (no Node required).

Usage (run from the `website/` folder):
    python screenshot.py                      # shoots http://localhost:3000
    python screenshot.py http://localhost:3000
    python screenshot.py http://localhost:3000 hero   # adds a -hero label

Each run captures TWO full-page PNGs into ./temporary screenshots/ :
    screenshot-<N>-desktop[-label].png   (1440px wide)
    screenshot-<N>-mobile[-label].png    (390px wide)
N auto-increments and never overwrites. Read the PNGs back with the Read tool
to eyeball them, fix mismatches, and re-run — that's the loop.
"""
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT_DIR = Path(__file__).parent / "temporary screenshots"
VIEWPORTS = {
    "desktop": {"width": 1440, "height": 900},
    "mobile": {"width": 390, "height": 844, "is_mobile": True},
}


def next_index() -> int:
    """Highest screenshot-N-* number on disk, + 1 (so files are never clobbered)."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    nums = [
        int(m.group(1))
        for f in OUT_DIR.glob("screenshot-*.png")
        if (m := re.match(r"screenshot-(\d+)", f.name))
    ]
    return (max(nums) + 1) if nums else 1


def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:3000"
    label = f"-{sys.argv[2]}" if len(sys.argv) > 2 else ""
    n = next_index()

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name, vp in VIEWPORTS.items():
            ctx = browser.new_context(
                viewport={"width": vp["width"], "height": vp["height"]},
                is_mobile=vp.get("is_mobile", False),
                device_scale_factor=2,
            )
            page = ctx.new_page()
            page.goto(url, wait_until="networkidle", timeout=30000)
            # Reveal-on-scroll sections start at opacity:0 and only show once the
            # IntersectionObserver fires — which is unreliable in a one-shot
            # full-page capture. Force every .reveal section visible so the whole
            # page renders deterministically.
            page.evaluate(
                "document.querySelectorAll('.reveal').forEach(e => e.classList.add('in'))"
            )
            page.wait_for_timeout(900)  # let fonts + reveal transitions settle
            out = OUT_DIR / f"screenshot-{n}-{name}{label}.png"
            page.screenshot(path=str(out), full_page=True)
            print(f"saved {out.relative_to(Path(__file__).parent)}")
            ctx.close()
        browser.close()


if __name__ == "__main__":
    main()
