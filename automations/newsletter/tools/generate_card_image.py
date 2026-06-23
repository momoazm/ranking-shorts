"""Render a styled HTML/CSS stat or quote card to a PNG via headless Chromium (Playwright).

Usage:
    python tools/generate_card_image.py --type stat --data '{"value":"42%","label":"of readers said X"}' --out .tmp/card1.png
    python tools/generate_card_image.py --type quote --data '{"quote":"...","author":"..."}' --out .tmp/card2.png

Prints JSON: {"path": "<out path>"}
"""
import argparse
import json
import os

from _common import load_theme, emit, fail

WIDTH = 600
HEIGHT = 400

STAT_TEMPLATE = """
<html><head><style>
  @import url('https://fonts.googleapis.com/css2?family={display_font}:wght@700&family={body_font}:wght@400;600&display=swap');
  body {{ margin:0; width:{width}px; height:{height}px; background:{navy};
          display:flex; flex-direction:column; align-items:center; justify-content:center;
          font-family:'{body_font}', Helvetica, Arial, sans-serif; }}
  .value {{ font-family:'{display_font}', Georgia, serif; font-size:96px; font-weight:700; color:{gold}; margin:0; }}
  .label {{ font-size:24px; color:{text}; text-align:center; max-width:80%; margin-top:12px; }}
  .accent {{ width:80px; height:6px; background:{red}; margin-top:18px; border-radius:3px; }}
</style></head>
<body>
  <p class="value">{value}</p>
  <div class="accent"></div>
  <p class="label">{label}</p>
</body></html>
"""

QUOTE_TEMPLATE = """
<html><head><style>
  @import url('https://fonts.googleapis.com/css2?family={display_font}:wght@700&family={body_font}:wght@400;600&display=swap');
  body {{ margin:0; width:{width}px; height:{height}px; background:{navy};
          display:flex; flex-direction:column; align-items:center; justify-content:center;
          font-family:'{body_font}', Helvetica, Arial, sans-serif; padding:0 40px; box-sizing:border-box; }}
  .quote {{ font-family:'{display_font}', Georgia, serif; font-size:32px; color:{text}; text-align:center;
            line-height:1.4; }}
  .quote::before, .quote::after {{ color:{gold}; font-size:40px; }}
  .author {{ font-size:18px; color:{gold}; margin-top:20px; letter-spacing:1px; text-transform:uppercase; }}
</style></head>
<body>
  <p class="quote">&ldquo;{quote}&rdquo;</p>
  <p class="author">&mdash; {author}</p>
</body></html>
"""


def render(html, out_path):
    from playwright.sync_api import sync_playwright

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
        page.set_content(html)
        page.wait_for_timeout(300)  # let web fonts settle if network is available
        page.screenshot(path=out_path)
        browser.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", required=True, choices=["stat", "quote"])
    parser.add_argument("--data", required=True, help="JSON: stat->{value,label}, quote->{quote,author}")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    try:
        data = json.loads(args.data)
    except json.JSONDecodeError as e:
        fail(f"Invalid --data JSON: {e}")
        return

    theme = load_theme()
    colors = theme["colors"]
    fonts = {
        "display_font": theme["fonts"]["display"]["google_font"].replace(" ", "+"),
        "body_font": theme["fonts"]["body"]["google_font"].replace(" ", "+"),
    }

    if args.type == "stat":
        html = STAT_TEMPLATE.format(
            width=WIDTH, height=HEIGHT,
            navy=colors["navy"], gold=colors["gold"], red=colors["scarab_red"], text=colors["text_on_dark"],
            value=data["value"], label=data["label"], **fonts,
        )
    else:
        html = QUOTE_TEMPLATE.format(
            width=WIDTH, height=HEIGHT,
            navy=colors["navy"], gold=colors["gold"], text=colors["text_on_dark"],
            quote=data["quote"], author=data["author"], **fonts,
        )

    try:
        render(html, args.out)
    except Exception as e:
        fail(
            f"Card rendering failed: {e}. If this is a 'browser not found' error, run: playwright install chromium",
        )
        return

    emit({"path": args.out})


if __name__ == "__main__":
    main()
