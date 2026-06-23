---
name: trend-research
description: Use when Moemen wants current trends, topic ideas, or what's hot right now to feed video content — finding viral-worthy subjects, trending sounds, or formats.
---

# Trend Research

Find what's trending and turn it into concrete video ideas.

## Steps
1. **Search** (uses the **research** skill): Firecrawl `firecrawl_search` (try `news`/`web` sources) → Tavily → Exa. Look for current trends, viral formats, and popular topics in MOMO's niche (AI brainrot / Peter & Stewie style Shorts).
2. **Trending sound** (optional, for ranking shorts): `python tools/fetch_trending_music.py ...` from `projects/ranking shorts/`.
3. **Synthesize:** return a short ranked list of **video ideas** — each with a hook angle and why it could pop now.

## Output
- 5–10 ideas, best first. Keep it scannable. Flag anything time-sensitive (a trend that's peaking).
- Hand a chosen idea to the **generate-video** skill.
