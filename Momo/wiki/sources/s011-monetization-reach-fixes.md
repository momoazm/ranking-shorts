---
type: source
tags: [momo]
updated: 2026-07-01
---
# s011 — Monetization reach fixes (ranking-shorts)
2026-07-01 monetization pass: benchmarked YouTube (via [[update]] Phase 2) + Instagram, then shipped
3 reach fixes to [[ranking-shorts]] (commit `db366cd`, `momoazm/ranking-shorts` main). Detail → [decisions/log.md](../../../decisions/log.md).

## Key points
- **Hook:** `rank_clips` opens the countdown on the most gripping clip (#5/first-shown), not the weakest.
- **Hashtags:** `build_captions` dropped stale Family Guy/"brainrot" tags (wrong niche → misclassified reach); niche-first; Instagram capped to 5.
- **Follow CTA:** `build_ranking_video` adds a visual follow end-card over #1 (no SFX, per the audio rule) — a follow *sound* was declined.
- IG upload cadence left manual (Moemen fires it from the MOMO site).

## Relationships
- **produces** fixes to [[ranking-shorts]] · **part of** [[competitor-analysis]] · **driven by** [[update]]
- **see** [[momo-actual-niche]] — the brainrot tags contradicted the current niche
