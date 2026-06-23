---
name: cross-post-video
description: Use when Moemen wants to publish one finished video to multiple platforms — posting the same Short to TikTok, Instagram, and YouTube. Posting is irreversible; confirm first.
---

# Cross-Post Video

Publish one finished video (e.g. `.tmp/final.mp4`) to TikTok + Instagram + YouTube in one go.
Tools live in `projects/ranking shorts/`.

## Steps (run from `projects/ranking shorts/`)
1. **Confirm the video is final** — captions in sync, audio clean, background not visibly looping.
2. **Gate (never skip):** show Moemen, per platform, the resolved **account**, title/caption, hashtags, and privacy (**unlisted/draft** by default). Wait for an explicit "go."
3. **Upload** to each platform:
   - `python tools/upload_youtube.py --video .tmp/final.mp4 --story .tmp/story.json --privacy unlisted`
   - `python tools/upload_tiktok.py ...`
   - `python tools/upload_instagram.py ...`
4. **Report** each video ID + URL. If one platform fails, report it and continue the others — don't silently stop.

## Notes
- Keep formats platform-appropriate (vertical, length caps; Shorts ≤60s, hard cap 120s).
- These uploads are the **irreversible** step — same discipline as send-email.
