"""Render newsletter content directly to a paginated PDF via headless Chromium (Playwright).

Uses a print-optimized template (tools/templates/newsletter_print.html.j2), not the
email-safe MJML one -- print layout isn't constrained by email-client table stacking, so
each section's image sits inline beside its text instead of full-width above/below it.

Usage:
    python tools/generate_pdf.py --data .tmp/content.json \\
        --images '[{"cid":"logo","path":"brand/logo.png"},{"cid":"chart1","path":".tmp/chart1.png"}]' \\
        --out .tmp/newsletter.pdf

Prints JSON: {"path": "<out>", "byte_size": N}
"""
import argparse
import json
import os
from pathlib import Path

from _common import load_theme, emit, fail


def render_html(content, theme, image_uris):
    from jinja2 import Environment, FileSystemLoader

    template_dir = os.path.join(os.path.dirname(__file__), "templates")
    env = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template("newsletter_print.html.j2")
    return template.render(content=content, theme=theme, images=image_uris)


def render_pdf(html, out_path):
    from playwright.sync_api import sync_playwright

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    # Chromium blocks file:// resources referenced from a page loaded via
    # set_content() (opaque/about:blank origin) -- the page itself must be
    # loaded via a file:// URL (same-origin) for local <img> sources to resolve.
    tmp_html_path = Path(out_path).with_suffix(".tmp.html")
    tmp_html_path.write_text(html, encoding="utf-8")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(tmp_html_path.resolve().as_uri(), wait_until="networkidle")
            page.pdf(
                path=out_path, print_background=True, width="640px",
                margin={"top": "0px", "bottom": "0px", "left": "0px", "right": "0px"},
            )
            browser.close()
    finally:
        tmp_html_path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True, help="Path to the newsletter content JSON")
    parser.add_argument("--images", default="[]", help='JSON list of {"cid": "...", "path": "..."}')
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    try:
        with open(args.data, "r", encoding="utf-8") as f:
            content = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        fail(f"Could not read --data: {e}")
        return

    try:
        images = json.loads(args.images)
    except json.JSONDecodeError as e:
        fail(f"Invalid --images JSON: {e}")
        return

    image_uris = {}
    for image in images:
        if not os.path.isfile(image["path"]):
            fail(f"Image file not found: {image['path']} (cid: {image['cid']})")
            return
        image_uris[image["cid"]] = Path(image["path"]).resolve().as_uri()

    theme = load_theme()

    try:
        html = render_html(content, theme, image_uris)
        render_pdf(html, args.out)
    except Exception as e:
        fail(f"PDF rendering failed: {e}. If this is a 'browser not found' error, run: playwright install chromium")
        return

    emit({"path": args.out, "byte_size": os.path.getsize(args.out)})


if __name__ == "__main__":
    main()
