---
name: compare-youtube-channels
description: Use when Moemen wants to compare YouTube channels — by default MOMO's ranking-Shorts channel against its top competitors in the niche — to find where rivals win and exactly how to match then exceed them. Runs INLINE and returns a decision-ready comparison in chat (no email/PDF). Triggers like "compare me to my competitors", "run a competitor analysis", "how do I stack up on YouTube".
argument-hint: optional focus or rival names (e.g. "focus on hooks", "vs MrBeast-style list channels")
---

## Context

Compares **YouTube channels** and returns the answer **in the conversation** — no PDF, no email.
Default mode is **MOMO vs its competitors**: research the top channels in MOMO's niche, find the
specific points where they out-perform MOMO, and give concrete, do-this-next ways to match then
**exceed** them. If Moemen names specific channels to compare, compare those instead.

MOMO's baseline lives in `momo-profile.json` (next to this file). MOMO's niche is the canonical one
from `context/work.md`: **faceless "ranking" (Top-N ranked-list) Shorts** — bias every insight
toward making those Shorts more viral, not generic business metrics.

`$ARGUMENTS` (optional) = a focus for this run (a specific rival, a platform, "focus on hooks/
thumbnails", or explicit channel names to compare head-to-head).

**Web research uses the project fallback chain, best-first:** Firecrawl (MCP `firecrawl_search`) →
`TAVILY_API_KEY` → `EXA_API_KEY`. For pulling a strong source's full text, delegate to the
`extract-article` subagent. Surface only **whole-chain** failures — don't loop on a metered API.

## Steps

1. **Load the baseline.** Read `momo-profile.json`. Resolve niche, handle, known metrics, stated
   goals, and any `named_competitors`. If `$ARGUMENTS` names specific channels, treat those as the
   comparison set and skip discovery (step 2).

2. **Discover competitors** (skip if channels were named). Search for the top channels in MOMO's
   niche, e.g.:
   - `"best faceless ranking Shorts channels YouTube"`
   - `"top Top-10 list Shorts creators 2026"`
   - `"fastest growing list/ranking YouTube Shorts <sub-topic>"`
   Merge results with `named_competitors` from the profile, dedup, and settle on a working set of
   **~3–6 channels**.

3. **Research each channel.** Per channel, search for subscribers, avg views, posting cadence,
   video length, hook style, thumbnail/title patterns, and what their most-viewed Shorts do. Use
   `extract-article` on the 1–3 strongest sources when a snippet isn't enough. **Keep every URL** —
   it becomes a cited source in the output.
   - **YouTube stat reality (learned):** channel pages are JS-rendered, so subs/views usually can't
     be scraped directly. Use Social Blade / vidIQ-style sources or search snippets, and **mark
     numbers as cited vs. estimated.** Never fabricate a metric to fill a table.

4. **Gap analysis** (your own reasoning — this is the deliverable). For each channel vs MOMO, score
   the dimensions that actually drive ranking-Short performance:
   - **Hook (first 1–2s)** — how they open; pattern interrupt; promise of the payoff.
   - **List structure & pacing** — count-up vs count-down, reveal cadence, cut speed, dead air.
   - **On-screen text / captions** — readability, rank labels, kinetic text.
   - **Thumbnail & title** — curiosity, numbers, contrast (matters even for Shorts feed/click).
   - **Audio** — trending sounds vs. music bed, SFX use, voiceover quality.
   - **Topic selection** — how viral/shareable their list *topics* are vs MOMO's.
   - **Cadence & consistency** — posting frequency, series/format repeatability.
   For every dimension a rival leads, record three things: the **gap**, the **evidence (source)**,
   and a **concrete move for MOMO to match then exceed it.**

5. **Write the comparison in chat** using the Output Format below. Lead with the answer.

## Output Format

Return directly in the conversation (Markdown), in this order:

1. **Bottom line** — the 2–3 biggest opportunities for MOMO, stated as actions.
2. **The competitor set** — a table: `Channel | Subs (cited/est.) | Avg views | Cadence | Why they win`.
3. **Where they beat MOMO** — grouped by the dimensions in step 4; each row = gap → evidence.
4. **Action plan to exceed** — a prioritized, numbered list of concrete changes to MOMO's Shorts
   (hooks, list pacing, topics, thumbnails, audio, cadence). Specific and do-this-next.
5. **Sources** — every URL used, titled. Flag which metrics are estimates vs. cited.

## Notes

- **No publishing, no email, no files.** This skill only researches and writes back to chat. (If
  Moemen later wants it emailed as a branded PDF, that's the `send-email` skill + newsletter tools —
  a separate, gated step.)
- **Don't fabricate metrics.** Thin sourcing for a small niche is expected — say so and compare
  qualitatively (hooks, pacing, topics) rather than inventing numbers. Be honest about estimates.
- **Keep the profile current.** If you confirm a real competitor, metric, or handle this run, offer
  to update `momo-profile.json` (especially `named_competitors`) so the next run starts smarter.
- **Focus arg wins.** If `$ARGUMENTS` says "focus on hooks" or names a rival, weight the analysis
  there instead of covering every dimension evenly.
