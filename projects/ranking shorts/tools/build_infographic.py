"""Render a branded, legible infographic (default 1080x1920) from a title + key points.
HTML/CSS -> PNG via headless Chromium (Playwright). Unlike AI image generation, text is
rendered crisply and the real MOMO brand assets (theme.json colors/fonts + logo.png) are used.

The logo is inlined as a base64 data URI so it loads under set_content() (Chromium blocks
file:// images on an about:blank origin — same constraint generate_thumbnail.py works around).

Usage:
    python tools/build_infographic.py --title "CLAUDE CODE" \
        --points "Agentic coding in your terminal|Reads, writes & edits your codebase|Runs commands, tests & git" \
        [--out .tmp/infographic.png] [--width 1080 --height 1920]

Points are separated by '|'. Prints JSON: {"path": ..., "points": N}
"""
import argparse
import base64
import html
import os

from _common import load_theme, emit, fail

CARD = """
    <div class="card">
      <div class="num">{n}</div>{icon}
      <div class="ptext">{text}</div>
    </div>"""

ICON = '<img class="icon" src="data:image/png;base64,{b64}"/>'

TEMPLATE = """
<html><head><style>
  @import url('https://fonts.googleapis.com/css2?family={display_font}:wght@700;900&family={body_font}:wght@500;600&display=swap');
  * {{ box-sizing:border-box; }}
  body {{ margin:0; width:{width}px; height:{height}px; padding:96px 80px;
          background:radial-gradient(circle at 50% 22%, {navy_light} 0%, {navy} 72%);
          font-family:'{body_font}', Helvetica, Arial, sans-serif;
          display:flex; flex-direction:column; align-items:center; }}
  .title {{ font-family:'{display_font}', Georgia, serif; font-weight:900;
            font-size:{title_size}px; line-height:1.05; color:{gold}; text-align:center;
            letter-spacing:1px; text-shadow:0 4px 20px rgba(0,0,0,0.5); }}
  .accent {{ width:200px; height:10px; background:{gold}; border-radius:5px; margin:34px 0 56px; }}
  .cards {{ display:flex; flex-direction:column; gap:{gap}px; width:100%; }}
  .card {{ display:flex; align-items:center; gap:36px; padding:34px 40px;
           background:{navy_light}; border-left:10px solid {gold}; border-radius:22px;
           box-shadow:0 10px 30px rgba(0,0,0,0.35); }}
  .num {{ flex:0 0 auto; width:{num}px; height:{num}px; border-radius:50%;
          background:{gold}; color:{text_on_gold}; font-family:'{display_font}', Georgia, serif;
          font-weight:900; font-size:{num_font}px; display:flex; align-items:center; justify-content:center; }}
  .icon {{ flex:0 0 auto; width:{icon}px; height:{icon}px; border-radius:14px; object-fit:cover;
           border:3px solid {gold}; background:{navy}; }}
  .ptext {{ color:{text}; font-size:{ptext_size}px; font-weight:500; line-height:1.28; }}
  .logo {{ margin-top:auto; padding-top:48px; height:120px; opacity:0.95; }}
</style></head>
<body>
  <div class="title">{title}</div>
  <div class="accent"></div>
  <div class="cards">{cards}</div>
  <img class="logo" src="data:image/png;base64,{logo_b64}"/>
</body></html>
"""


def render(html_str, out_path, width, height):
    from playwright.sync_api import sync_playwright

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        page.set_content(html_str)
        page.wait_for_timeout(500)  # let web fonts settle
        page.screenshot(path=out_path)
        browser.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    parser.add_argument("--points", required=True, help="Key points separated by '|'")
    parser.add_argument("--icons", default="", help="Optional icon image paths separated by '|', "
                        "one per point (composited into each card)")
    parser.add_argument("--out", default=".tmp/infographic.png")
    parser.add_argument("--width", type=int, default=1080)
    parser.add_argument("--height", type=int, default=1920)
    args = parser.parse_args()

    points = [p.strip() for p in args.points.split("|") if p.strip()]
    if not points:
        fail("No points parsed from --points (separate items with '|')")
        return
    if len(points) > 7:
        fail(f"Too many points ({len(points)}); keep it to 7 or fewer for legibility")
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

    # Scale a few sizes down as the point count grows so it always fits.
    n = len(points)
    ptext_size = 50 if n <= 4 else (44 if n <= 5 else 38)
    gap = 30 if n <= 4 else (24 if n <= 5 else 18)

    icon_paths = [p.strip() for p in args.icons.split("|") if p.strip()] if args.icons else []
    if icon_paths and len(icon_paths) != n:
        fail(f"--icons count ({len(icon_paths)}) must match points count ({n})")
        return
    icons_b64 = []
    for ip in icon_paths:
        try:
            with open(ip, "rb") as f:
                icons_b64.append(base64.b64encode(f.read()).decode("ascii"))
        except OSError as e:
            fail(f"Could not read icon {ip}: {e}")
            return

    cards = "".join(
        CARD.format(
            n=i + 1,
            text=html.escape(p),
            icon=ICON.format(b64=icons_b64[i]) if icons_b64 else "",
        )
        for i, p in enumerate(points)
    )
    html_str = TEMPLATE.format(
        width=args.width, height=args.height,
        navy=colors["navy"], navy_light=colors["navy_light"], gold=colors["gold"],
        text=colors["text_on_dark"], text_on_gold=colors["text_on_gold"],
        display_font=theme["fonts"]["display"]["google_font"].replace(" ", "+"),
        body_font=theme["fonts"]["body"]["google_font"].replace(" ", "+"),
        title=html.escape(args.title), title_size=96, num=84, num_font=44,
        icon=96, ptext_size=ptext_size, gap=gap, cards=cards, logo_b64=logo_b64,
    )

    try:
        render(html_str, args.out, args.width, args.height)
    except Exception as e:
        fail(f"Infographic render failed: {e}. If 'browser not found', run: playwright install chromium")
        return

    emit({"path": args.out, "points": n})


if __name__ == "__main__":
    main()
