---
name: cross-post-video
description: Publish one finished video to TikTok + Instagram + YouTube as a step in the current flow — e.g. posting the Short just rendered at the end of an automation. Runs INLINE (keeps the flow's context). Posting is irreversible — confirm first.
---

# Cross-Post Video — inline

Publish one finished video (e.g. the `.tmp/final.mp4` from the current flow) to TikTok + Instagram +
YouTube, using the context already built (title, tags, story.json). Tools live in
`projects/ranking shorts/`.

## Steps (run from `projects/ranking shorts/`)
1. **Confirm the video is final** — captions in sync, audio clean, background not visibly looping.
2. **Gate (never skip):** show Moemen, per platform, the resolved **account**, title/caption,
   hashtags, and privacy (**unlisted/draft** by default). Wait for an explicit "go." Without
   confirmation, stop — do not post.
3. **Upload** to each platform:
   - `python tools/upload_youtube.py --video .tmp/final.mp4 --story .tmp/story.json --privacy unlisted`
   - `python tools/upload_tiktok.py ...`
   - `python tools/upload_instagram.py ...`
4. **Report** each video ID + URL. If one platform fails, report it and continue the others.

## Notes
- Keep formats platform-appropriate (vertical; Shorts ≤60s, hard cap 120s).
- These uploads are **irreversible** — same discipline as send-email.
