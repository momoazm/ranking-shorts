"""Render an optional branded vertical cover (1080x1920) for the short: hook text over the
brand navy with the MOMO logo. HTML/CSS -> PNG via headless Chromium (Playwright).

The logo is inlined as a base64 data URI so it loads under set_content() (Chromium blocks
file:// images on an about:blank origin — same constraint generate_pdf.py works around).

Usage:
    python tools/generate_thumbnail.py --story .tmp/story.json [--out .tmp/thumb.png]
    python tools/generate_thumbnail.py --text "BIG HOOK LINE" [--out .tmp/thumb.png]

Prints JSON: {"path": ...}
"""
import argparse
import base64
import json
import os

from _common import load_theme, emit, fail

WIDTH, HEIGHT = 1080, 1920

TEMPLATE = """
<html><head><style>
  @import url('https://fonts.googleapis.com/css2?family={display_font}:wght@700;900&family={body_font}:wght@600&display=swap');
  body {{ margin:0; width:{width}px; height:{height}px; box-sizing:border-box; padding:120px 90px;
          background:radial-gradient(circle at 50% 35%, {navy_light} 0%, {navy} 70%);
          display:flex; flex-direction:column; align-items:center; justify-content:center; gap:60px;
          font-family:'{body_font}', Helvetica, Arial, sans-serif; }}
  .hook {{ font-family:'{display_font}', Georgia, serif; font-weight:900; font-size:120px; line-height:1.1;
           color:{text}; text-align:center; text-shadow:0 6px 24px rgba(0,0,0,0.55); }}
  .accent {{ width:220px; height:12px; background:{gold}; border-radius:6px; }}
  .logo {{ position:absolute; bottom:90px; height:140px; opacity:0.95; }}
</style></head>
<body>
  <div class="hook">{hook}</div>
  <div class="accent"></div>
  <img class="logo" src="data:image/png;base64,{logo_b64}"/>
</body></html>
"""


def render(html, out_path):
    from playwright.sync_api import sync_playwright

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
        page.set_content(html)
        page.wait_for_timeout(400)  # let web fonts settle
        page.screenshot(path=out_path)
        browser.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--story", help="story.json (uses its 'hook' or 'title')")
    parser.add_argument("--text", help="Explicit hook text (overrides --story)")
    parser.add_argument("--out", default=".tmp/thumb.png")
    args = parser.parse_args()

    hook = args.text
    if not hook and args.story:
        try:
            with open(args.story, "r", encoding="utf-8") as f:
                s = json.load(f)
            hook = s.get("hook") or s.get("title")
        except (OSError, json.JSONDecodeError) as e:
            fail(f"Could not read --story: {e}")
            return
    if not hook:
        fail("Provide --text or a --story with a hook/title")
        return

    theme = load_theme()
    colors = theme["colors"]
    logo_path = os.path.join("brand", "logo.png")
    try:
        with open(logo_path, "rb") as f:
            logo_b64 = base64.b64encode(f.read()).decode("ascii")
    except OSError as e:
        fail(f"Could not read brand logo at {logo_path}: {e}")
        return

    html = TEMPLATE.format(
        width=WIDTH, height=HEIGHT,
        navy=colors["navy"], navy_light=colors["navy_light"], gold=colors["gold"], text=colors["text_on_dark"],
        display_font=theme["fonts"]["display"]["google_font"].replace(" ", "+"),
        body_font=theme["fonts"]["body"]["google_font"].replace(" ", "+"),
        hook=hook, logo_b64=logo_b64,
    )

    try:
        render(html, args.out)
    except Exception as e:
        fail(f"Thumbnail render failed: {e}. If 'browser not found', run: playwright install chromium")
        return

    emit({"path": args.out})


if __name__ == "__main__":
    main()
