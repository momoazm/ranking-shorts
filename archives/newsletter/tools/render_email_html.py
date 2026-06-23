"""Render structured newsletter content into final, email-safe HTML.

Pipeline: Jinja2 fills tools/templates/newsletter.mjml.j2 with content + brand/theme.json
-> mjml compiles that to bulletproof table-based, pre-inlined HTML -> premailer runs as a
defensive second inlining pass in case any style wasn't fully inlined by MJML.

Image references in the content (logo, charts, cards, AI art) must use `image_cid` values
that exactly match the Content-ID names tools/build_email_mime.py will attach later.

Usage:
    python tools/render_email_html.py --data content.json --out .tmp/newsletter.html

content.json shape:
{
  "subject": "...", "preheader": "...",
  "sections": [
    {"heading": "...", "body": "...", "image_cid": "chart1" or null,
     "cta": {"text": "...", "url": "..."} or null}
  ],
  "sources": [{"title": "...", "url": "..."}]
}

Prints JSON: {"path": "<out>", "byte_size": N, "gmail_clip_warning": bool}
"""
import argparse
import json
import os

from _common import load_theme, emit, fail

GMAIL_CLIP_THRESHOLD_BYTES = 100_000  # Gmail clips HTML bodies around ~102KB


def render(content, theme):
    from jinja2 import Environment, FileSystemLoader
    import mjml
    from premailer import transform

    template_dir = os.path.join(os.path.dirname(__file__), "templates")
    env = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template("newsletter.mjml.j2")
    mjml_source = template.render(content=content, theme=theme)

    result = mjml.mjml_to_html(mjml_source)
    if result.errors:
        raise RuntimeError(f"MJML compile errors: {result.errors}")

    html = transform(result.html)  # defensive second inlining pass
    return html


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True, help="Path to a JSON file with the newsletter content")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    try:
        with open(args.data, "r", encoding="utf-8") as f:
            content = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        fail(f"Could not read --data: {e}")
        return

    theme = load_theme()

    try:
        html = render(content, theme)
    except Exception as e:
        fail(f"Render failed: {e}")
        return

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)

    byte_size = len(html.encode("utf-8"))
    emit({
        "path": args.out,
        "byte_size": byte_size,
        "gmail_clip_warning": byte_size > GMAIL_CLIP_THRESHOLD_BYTES,
    })


if __name__ == "__main__":
    main()
