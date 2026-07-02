# competitor/ — Instagram benchmark input (gathered 2026-07-01)

Input folder for **Phase 1** of the `competitor-analysis` workflow (the `update` subagent).
Gathered by Claude on 2026-07-01 at Moemen's request, since no `competitor/` folder existed.

## Data-quality caveat (read this first)
Instagram is **heavily login-gated**, so exact per-account follower counts and per-reel metrics
for same-niche faceless "ranking / Top-N" Reel pages are **not reliably scrapable** and are
**not well-indexed by web search** (same finding the YouTube side already logged in
`momo-profile.json`: this specific sub-niche returns generic how-to listicles, not citable
competitor handles with numbers). So this folder is **tactics-first, not metrics-first**:
it captures the *winning patterns and the 2026 Reels ranking model* that same-niche accounts
exploit, all cited, rather than inventing follower numbers. Anything estimated is labeled.

## What's inside
- `reels-algorithm-2026.md` — the 2026 Instagram Reels ranking model (signal weights),
  posting-cadence rules, hashtag reality, and monetization ceilings by niche. **Cited.**
- `competitor-tactics.md` — winning-account tactics for the faceless ranking-Reels niche +
  the specific deltas vs. MOMO's current IG setup.
- `our-accounts.md` — MOMO's two tracked IG accounts (baseline).

## Moemen's tracked IG accounts (the comparison targets)
1. `@rank_ingshorts` — `ranking shorts` project (`IG_USER_ID=17841414896541039`). Brand new.
2. `rankingshorts1` — `clipping-auto` project (`IG_USER_ID=17841479158600540`). Brand new.

Both are pre-launch / near-zero followers, so the benchmark's job is **"copy what winning
accounts do from day one,"** not "compare our numbers."

## Sources
- Kineclip, "12 Best Instagram Reels Niches for 2026 (Ranked)",
  https://kineclip.com/blog/best-niches-instagram-reels-2026/ (scraped 2026-07-01) — ranking
  model, cadence, hashtag reality, monetization ceilings.
- Firecrawl web searches 2026-07-01 for faceless ranking/Top-N Reel accounts — confirmed the
  sub-niche is not indexed with citable handles/metrics (noise, not signal).
