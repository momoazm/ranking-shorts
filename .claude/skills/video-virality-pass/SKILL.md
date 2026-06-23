---
name: video-virality-pass
description: Use when Moemen wants feedback on a video to make it perform better — reviewing/improving the hook, pacing, title, or thumbnail before (or after) upload to maximize reach.
---

# Video Virality Pass

Review a video (or its script/metadata) and improve it for reach. No uploading here.

## Check, in priority order
1. **Hook (first 1–3s):** Does it stop the scroll? Suggest a sharper opening line/visual.
2. **Pacing:** Cut dead air, tighten transitions, keep it moving. Flag slow spots with timestamps.
3. **Title + caption:** Curiosity/payoff, keyword-aware, on-brand MOMO voice. Offer 2–3 options.
4. **Thumbnail/cover:** Clear focal point, readable text, brand colors from `brand/theme.json`. Suggest or regenerate via the **generate-image** skill.
5. **Audio/captions:** Captions in sync, voices clean, sound bed not overpowering.

## Output
- A short, prioritized punch-list: the few changes most likely to lift performance, biggest-impact first.
- If changes need re-rendering, loop back to the **generate-video** pipeline (re-script or re-assemble).
