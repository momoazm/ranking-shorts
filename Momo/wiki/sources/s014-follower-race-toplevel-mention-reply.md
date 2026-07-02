---
type: source
tags: [momo, instagram, playwright, follower-race]
updated: 2026-07-02
---
# s014 — Follower-race reply = top-level @mention, not threaded (2026-07-02)

[[follower-race]]'s Playwright comment-reply now posts a **top-level @mention** comment
(`@username You finished 2nd place! 🥈`) in the reel's main composer — NOT a per-comment threaded
"Reply". `post_reply()` in `reply_placements.py` rewritten; dropped the `_click_reply_for` path.

## Relationships
- **supersedes** the threaded-reply approach in [[s013-follower-race-instagram-playwright]]
- **uses** [[playwright-cli]] + the saved IG session; reads stay dialog-scoped (no adjacent-reel leak)
- **why:** headless IG threaded-reply silently dropped posts / landed top-level anyway, and
  throttled `the_followers_racer` after repeated tries — a top-level @mention still notifies + is
  clearly addressed, so it hits the reliability bar
- [[follower-race]] pushed (f9fd4cc); still `--confirm`-gated, live post awaits Moemen's go
- [[momo-website]] "Run follower race" button verified live (pipelines.html + runner.py `followers`,
  workflow on default branch) — only open item: GH_DISPATCH_TOKEN Actions:read+write scope
