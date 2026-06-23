---
name: infographics
description: Use when Moemen wants a standalone, on-brand infographic made from a finished video's key points — a shareable recap/summary visual. Runs inline; generates the image via the AI-image fallback chain using the MOMO brand assets.
argument-hint: [key points, or path to .tmp/story.json]
---

## What This Skill Does

Turn a finished video's key points into a **standalone, on-brand MOMO infographic** (PNG), generated
by AI image using the brand assets (`brand/theme.json` palette + `brand/logo.png`). Inline — uses the
current flow's context (the video we just built).

## Steps (run from `projects/ranking shorts/`)

1. **Get the key points.** Prefer the current flow's video: read `.tmp/story.json` and distil its
   `title` + `hook` + `narration` into **3–6 short labels**. If `$ARGUMENTS` is given, use that
   (raw points or a `story.json` path). If nothing's available, ask Moemen for the points.
2. **Load the brand.** Read `brand/theme.json` for the palette/fonts and build a `--style` string
   from its actual values, e.g.:
   `MOMO brand: deep navy #0B1622 background, gold #C9A96C accents, cream #F2E9D8 text, monumental
   Cinzel serif headings, clean Poppins labels, thin gold line icons, premium minimal infographic,
   high contrast`
3. **Generate** — prefer Gemini so the real logo art guides the look:
   ```
   python tools/generate_ai_image.py --provider gemini --refs brand/logo.png \
     --style "<brand style from step 2>" \
     --prompt "Clean vertical infographic titled '<title>' summarizing: <3–6 short labels>. \
               Organized panels, one thin-line icon per point, strong hierarchy, MOMO branding." \
     --out .tmp/infographic.png
   ```
   If Gemini is unavailable/errors, drop `--provider gemini --refs ...` to use the full fallback
   chain (Cloudflare → HF → Pollinations → Gemini) with the **same** `--style` and prompt.
4. **(Optional) Stamp the logo** for a guaranteed brand mark: overlay `brand/logo.png` in a corner,
   respecting ~25% clearspace (`theme.json` `logo.clearspace_ratio`). If we want this every time,
   add a tiny reusable overlay tool.
5. **Show Moemen** `.tmp/infographic.png` and the points used; offer a re-roll with a tweaked prompt.

## Output
- `.tmp/infographic.png` — a standalone branded infographic.

## Notes
- **Brand assets are not optional:** colors/fonts come from `brand/theme.json`; the actual
  `brand/logo.png` is fed to Gemini via `--refs` (and/or overlaid). Never re-derive brand colors.
- **Keep text short** — AI image text garbles easily; use the title + 3–6 short labels, not sentences.
- **Cost:** AI image gen may use paid credits (Cloudflare/HF). One render is fine; ask before batch re-rolls.
- **Not irreversible/public** — no send gate (it's a local file). Posting it later → `/cross-post-video`.
