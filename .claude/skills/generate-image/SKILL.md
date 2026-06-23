---
name: generate-image
description: Use when Moemen needs an image generated — an AI illustration, a thumbnail, a stat/quote card, or a chart for a video, newsletter, or post.
---

# Generate Image

Create an image, best provider first, fall back on limit/error.

## Pick the tool
- **AI illustration:** `python tools/generate_ai_image.py --prompt "..."` (run from `projects/<name>/`).
- **Stat/quote card:** `python tools/generate_card_image.py ...`
- **Data chart (real numbers):** `python tools/generate_chart.py ...`

## AI image provider order (inside generate_ai_image.py)
1. **Cloudflare** (`CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID`)
2. **Hugging Face** (`HF_API_TOKEN`)
3. **Pollinations** (no key)
4. **Gemini** (`GEMINI_API_KEY`) when the above are exhausted

## Notes
- Output goes to `.tmp/`. Keep each visual's `cid` name identical across generate → render → build steps.
- Always apply branding from the root `brand/` (and the project's `brand/theme.json`). Never re-derive colors/fonts.
- Use AI images sparingly; prefer real charts/cards where the content is data or a quote.
