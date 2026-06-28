"""Render a brand-styled bar chart as a PNG via headless Chromium (Playwright).

Uses HTML->PNG (the project's standard rendering path — no matplotlib/numpy dependency) so
charts match the MOMO brand exactly: gold bars on navy, Cinzel title, Poppins labels. Built for
the weekly-roundup skill (views-per-video, retention-per-video), but generic.

Usage:
    python tools/generate_chart.py --data '{"type":"bar","title":"Views by video","labels":["A","B"],"values":[12,7],"ylabel":"Views"}' --out .tmp/chart1.png

Prints JSON: {"path": "<out path>"}
"""
import argparse
import html as html_lib
import json
import os

from _common import load_theme, emit, fail


def _fmt(v):
    try:
        f = float(v)
        return f"{int(f):,}" if f == int(f) else f"{f:,.1f}"
    except (TypeError, ValueError):
        return str(v)


def build_chart_html(spec, theme):
    colors = theme["colors"]
    disp = theme["fonts"]["display"]["google_font"].replace(" ", "+")
    body = theme["fonts"]["body"]["google_font"].replace(" ", "+")

    labels = spec["labels"]
    values = spec["values"]
    title = spec.get("title", "")
    ylabel = spec.get("ylabel", "")
    maxv = max([v for v in values if isinstance(v, (int, float))] or [1]) or 1

    cols = ""
    for lab, val in zip(labels, values):
        h = max(2, round((val / maxv) * 200)) if isinstance(val, (int, float)) else 2
        cols += (
            f'<div class="col"><div class="barwrap"><div class="val">{_fmt(val)}</div>'
            f'<div class="bar" style="height:{h}px"></div></div>'
            f'<div class="lab">{html_lib.escape(str(lab))}</div></div>'
        )

    ylabel_html = f'<div class="ylabel">{html_lib.escape(ylabel)}</div>' if ylabel else ""

    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>
  @import url('https://fonts.googleapis.com/css2?family={disp}:wght@700&family={body}:wght@400;600&display=swap');
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: {colors['navy']}; font-family: '{theme['fonts']['body']['google_font']}', sans-serif; color: {colors['text_on_dark']}; }}
  .card {{ width: 600px; padding: 22px 24px 18px; }}
  .title {{ font-family: '{theme['fonts']['display']['google_font']}', serif; color: {colors['gold']}; font-size: 20px; margin: 0 0 4px; text-align: center; }}
  .ylabel {{ font-size: 10px; color: {colors['sterling_silver']}; text-transform: uppercase; letter-spacing: 1px; text-align: center; margin-bottom: 12px; }}
  .plot {{ display: flex; align-items: flex-end; gap: 18px; height: 230px; border-bottom: 2px solid {colors['gold_dark']}; padding: 0 6px; }}
  .col {{ flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; height: 100%; }}
  .barwrap {{ display: flex; flex-direction: column; justify-content: flex-end; align-items: center; height: 100%; width: 100%; }}
  .bar {{ width: 62%; max-width: 72px; background: linear-gradient(180deg, {colors['gold_light']}, {colors['gold']}); border-radius: 6px 6px 0 0; }}
  .val {{ font-weight: 700; color: {colors['gold_light']}; font-size: 13px; margin-bottom: 5px; }}
  .lab {{ font-size: 11px; color: {colors['text_on_dark']}; text-align: center; margin-top: 8px; line-height: 1.2; }}
</style></head><body>
  <div class="card">
    <div class="title">{html_lib.escape(title)}</div>
    {ylabel_html}
    <div class="plot">{cols}</div>
  </div>
</body></html>"""


def render(html_str, out_path):
    from playwright.sync_api import sync_playwright

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 600, "height": 400}, device_scale_factor=2)
        page.set_content(html_str)
        page.wait_for_timeout(400)  # let web fonts settle
        el = page.query_selector(".card")
        (el or page).screenshot(path=out_path)
        browser.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True, help="JSON spec: type/title/labels/values/ylabel")
    parser.add_argument("--out", required=True, help="Output PNG path, e.g. .tmp/chart1.png")
    args = parser.parse_args()

    try:
        spec = json.loads(args.data)
    except json.JSONDecodeError as e:
        fail(f"Invalid --data JSON: {e}")
        return

    if not spec.get("labels") or not spec.get("values"):
        fail("Chart spec needs non-empty 'labels' and 'values'.")
        return

    theme = load_theme()

    try:
        render(build_chart_html(spec, theme), args.out)
    except Exception as e:
        fail(f"Chart generation failed: {e}. If 'browser not found', run: playwright install chromium")
        return

    emit({"path": args.out})


if __name__ == "__main__":
    main()
