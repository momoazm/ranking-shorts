"""Render a 'flow diagram' infographic: an AI-generated hero scene (e.g. a glowing
circular node diagram) with CRISP text labels overlaid via HTML/Playwright — so the
art looks AI-generated but every label is legible. Brand colors from theme.json.

Usage:
  python tools/build_flow_infographic.py --scene .tmp/flow-scene.png --title "CLAUDE CODE SKILLS" \
      --labels '[{"text":"COMMAND PROMPT","sub":"slash trigger","x":0.16,"y":0.14}, ...]' \
      [--out .tmp/flow.png] [--size 1024]

Each label: {text, sub(optional), x, y} where x,y are FRACTIONS (0..1) of the image,
the center point of the label box. Prints JSON: {"path":..., "labels":N}
"""
import argparse
import base64
import html
import json
import os

from _common import load_theme, emit, fail

LABEL = """
  <div class="lbl" style="left:{x}%; top:{y}%;">
    <div class="lt">{text}</div>{sub}
  </div>"""
SUB = '<div class="ls">{t}</div>'

TEMPLATE = """
<html><head><style>
  @import url('https://fonts.googleapis.com/css2?family={display_font}:wght@700;900&family={body_font}:wght@600;700&display=swap');
  * {{ box-sizing:border-box; margin:0; }}
  body {{ width:{size}px; height:{size}px; position:relative; background:{navy};
          font-family:'{body_font}', Helvetica, Arial, sans-serif; }}
  .scene {{ position:absolute; inset:0; width:100%; height:100%; object-fit:cover; }}
  .title {{ position:absolute; top:2.4%; left:50%; transform:translateX(-50%);
            font-family:'{display_font}', Georgia, serif; font-weight:900; font-size:48px;
            color:{gold}; letter-spacing:2px; text-align:center; white-space:nowrap;
            padding:6px 26px; border-radius:14px; background:rgba(4,8,16,0.58);
            box-shadow:0 0 22px rgba(230,178,58,0.35);
            text-shadow:0 0 18px rgba(230,178,58,0.65), 0 3px 10px rgba(0,0,0,0.9); }}
  .lbl {{ position:absolute; transform:translate(-50%,-50%); text-align:center; width:250px;
          padding:9px 13px; border-radius:13px;
          background:rgba(4,8,16,0.66); backdrop-filter:blur(2px);
          box-shadow:0 0 16px rgba(45,124,140,0.3); }}
  .lt {{ color:{cyan}; font-weight:800; font-size:29px; line-height:1.1; letter-spacing:0.5px;
         text-shadow:0 0 10px rgba(90,210,235,0.6), 0 2px 6px rgba(0,0,0,0.95); }}
  .ls {{ color:{text}; font-weight:600; font-size:18px; margin-top:3px; opacity:0.95;
         text-shadow:0 2px 6px rgba(0,0,0,0.95); }}
</style></head>
<body>
  <img class="scene" src="data:image/png;base64,{scene_b64}"/>
  <div class="title">{title}</div>
  {labels}
</body></html>
"""


def render(html_str, out_path, size):
    from playwright.sync_api import sync_playwright
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": size, "height": size})
        page.set_content(html_str)
        page.wait_for_timeout(500)
        page.screenshot(path=out_path)
        b.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", required=True, help="Background hero image path")
    ap.add_argument("--title", required=True)
    ap.add_argument("--labels", required=True, help="JSON list of {text, sub?, x, y}")
    ap.add_argument("--out", default=".tmp/flow.png")
    ap.add_argument("--size", type=int, default=1024)
    args = ap.parse_args()

    try:
        labels = json.loads(args.labels)
    except json.JSONDecodeError as e:
        fail(f"--labels is not valid JSON: {e}")
        return
    try:
        with open(args.scene, "rb") as f:
            scene_b64 = base64.b64encode(f.read()).decode("ascii")
    except OSError as e:
        fail(f"Could not read --scene {args.scene}: {e}")
        return

    theme = load_theme()
    c = theme["colors"]
    lbl_html = "".join(
        LABEL.format(
            x=round(float(l["x"]) * 100, 2), y=round(float(l["y"]) * 100, 2),
            text=html.escape(l.get("text", "")),
            sub=SUB.format(t=html.escape(l["sub"])) if l.get("sub") else "",
        )
        for l in labels
    )
    html_str = TEMPLATE.format(
        size=args.size, navy=c["navy"], gold=c["gold"], cyan=c["nile_teal"],
        text=c["text_on_dark"],
        display_font=theme["fonts"]["display"]["google_font"].replace(" ", "+"),
        body_font=theme["fonts"]["body"]["google_font"].replace(" ", "+"),
        scene_b64=scene_b64, title=html.escape(args.title), labels=lbl_html,
    )
    try:
        render(html_str, args.out, args.size)
    except Exception as e:
        fail(f"Flow render failed: {e}. If 'browser not found', run: playwright install chromium")
        return
    emit({"path": args.out, "labels": len(labels)})


if __name__ == "__main__":
    main()
