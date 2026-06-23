---
name: infographics
description: Use when Moemen wants a standalone, on-brand infographic made from a finished video's key points — a shareable recap/summary visual with legible text. Runs inline; renders HTML→PNG using the MOMO brand assets.
argument-hint: [key points, or path to .tmp/story.json]
---

## What This Skill Does

Turn a title + key points into a standalone, on-brand **MOMO infographic** (PNG) with **crisp,
legible text** and the real brand assets (`brand/theme.json` colors/fonts + `brand/logo.png`).
Renders **HTML → PNG via Playwright** (`build_infographic.py`) — not AI image generation, so the
text is always readable. Inline — uses the current flow's context (the video we just built).

## Steps (run from `projects/ranking shorts/`)

1. **Gather title + key points.** Prefer the current flow's video: read `.tmp/story.json` (use its
   `title`; distil `hook` + `narration` into **3–6 short labels**, one phrase each). If `$ARGUMENTS`
   is given, use that. If nothing's available, ask Moemen for the title + points.
2. **Render the infographic:**
   ```
   python tools/build_infographic.py --title "<TITLE>" \
     --points "<point 1|point 2|point 3|...>" --out .tmp/infographic.png
   ```
   - Points are separated by `|`. Keep to **≤7**, each a short phrase that fits one line.
   - Brand colors/fonts/logo are applied **automatically** from `brand/theme.json` + `brand/logo.png`.
   - Default 1080×1920 (vertical). For another ratio add `--width/--height` (e.g. `--width 1080
     --height 1350` for 4:5).
3. **Show Moemen** `.tmp/infographic.png`. Tweak wording and re-render freely — it's local and free.
4. *(Optional, only if asked)* For a decorative AI background instead of the flat navy, generate one
   with `generate_ai_image.py` (brand `--style`, Gemini `--refs brand/logo.png`) and composite.

## Output
- `.tmp/infographic.png` — a legible, on-brand infographic.

## Notes
- **Brand assets are not optional** and are applied automatically by the tool (navy/gold/cream,
  Cinzel/Poppins, MOMO logo). Never re-derive brand colors.
- **Keep each point short** (a phrase, not a sentence) so it fits one line; ≤7 points.
- Rendering is **local and free** (no API call) — re-roll wording as much as you like.
- **Not irreversible/public** — no send gate. Posting it later → `/cross-post-video`.
