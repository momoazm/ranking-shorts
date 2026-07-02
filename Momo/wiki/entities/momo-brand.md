---
type: entity
tags: [brand, momo]
created: 2026-06-28
updated: 2026-06-28
sources: [s001]
status: active
---

# MOMO (brand)

Moemen's content brand. **Branding is not optional** — load assets, never re-derive
colors/fonts.

## Canonical assets
- **Master lives in repo-root `brand/`** (`logo.png`, `theme.json`, `brandguidelines.png`) — the
  source of truth.
- Each project keeps its own `brand/` copy because deterministic tools load `brand/theme.json`
  relative to the project folder. Project copies **mirror the root master**; if the brand
  changes, update root `brand/` then re-sync the copies.

## Current look (per decision log)
- **Gold:** richer metallic `#E6B23A` (refined from earlier brighter `#FFD23F`; original
  `#C9A96C`) — tuned to be less lemon-yellow.
- **Navy:** very dark `#040810` (from `#0B1622`).
- Logo background made **transparent** (the old dark box showed as a black rectangle on dark
  backgrounds). Originals archived in `archives/brand-old/`.

> Older docs reference the master brand under `projects/newsletter/brand/` — that project was
> **archived** (2026-06-24); the canonical location is now **repo-root `brand/`**. ⚠ contradiction
> resolved in favor of the newer decision-log entry.

## Voice
Energetic, fast, punchy ranked-list ("Top N") entertainment. Strong hook in the first seconds,
tight pacing, clear payoff — optimized for retention and shareability.

## See also
[[moemen]] · [[ranking-shorts]] · [[momo-niche]]
