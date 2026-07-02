---
type: source
tags: [momo, instagram, monetization, follower-race, competitor-analysis]
updated: 2026-07-02
---
# s018 — Follower-race posts autonomously + improver goes monetization-first, all channels (2026-07-02)

Moemen's go: [[follower-race]] runs were "succeeding" but stopping at `awaiting_review` (manual
gate) — gate cleared (`manual_gate_cleared: true`), so every cloud run now **builds AND posts**
to Instagram via Zernio. Caption upgraded: follow-loop CTA ("FOLLOW and you're in the next
race") + 5 niche hashtags. Detail → [decisions/log.md](../../../decisions/log.md).

## Relationships
- **supersedes** the review-email gate flow in [[s013-follower-race-instagram-playwright]]
- [[competitor-analysis]] (the improver / [[update]] agent) **expanded to** all 5 surfaces:
  MOMO Shorts + "moemen yasser" (YouTube), @rank_ingshorts + clipping 2nd acct +
  @the_followers_racer (IG) — was 2 of 5
- SOP gains a **Monetization lens**: YPP bar (1K subs + 10M Shorts views/90d) + retention
  levers (hook 0–2s, pattern breaks, loop ending, ≤5 hashtags, follow CTA) mapped to the exact
  pipeline file per project — **builds on** [[s011-monetization-reach-fixes]]
- `momo-profile.json` **gains** `owned_channels` (incl. [[clipping-auto]]'s channel)
