---
name: generate-video
description: Use when Moemen wants to make a short-form video — a faceless story Short or the Peter & Stewie dialogue format for the MOMO channel.
---

# Generate Video (short-form)

Build a finished vertical (1080×1920) Short. Lives in `projects/ranking shorts/`.
**Read [ranking-shorts.md](../../../projects/ranking%20shorts/ranking-shorts.md) for exact flags and the full SOP before running.**

## Pipeline (run tools from `projects/ranking shorts/` with the project venv)
1. **Story / script** — `write_story.py` (`--format dialogue --characters peter,stewie` for the duo). ≤120s hard cap.
2. **Voiceover** — `generate_voiceover.py` (Fish Audio → Edge-TTS fallback; `FISH_AUDIO_API_KEY`).
3. **Captions** — `align_captions.py` (word-level, brand-gold highlight).
4. **Background** — `download_background.py` (no-copyright/CC only) → cached clip.
5. **Assemble** — `assemble_video.py` → `.tmp/final.mp4` (+ optional `generate_thumbnail.py`).

## Branding & quality
- Pull captions/thumbnail style from `brand/theme.json`. Aim for a strong hook + viral pacing.

## Gate (never skip)
- Show title, description, tags, privacy (**unlisted**), target channel, duration, size — and have Moemen eyeball `.tmp/final.mp4` — before any upload. Uploading is the **cross-post-video** skill.
