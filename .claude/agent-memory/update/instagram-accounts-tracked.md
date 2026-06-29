---
name: instagram-accounts-tracked
description: Where MOMO's Instagram posting/account config actually lives across projects, for when Phase 1 (IG benchmarking) has real competitor/ data to work with
metadata:
  type: project
---

Confirmed locations (as of 2026-06-29) where Instagram posting config/handles live, per
`[[competitor-folder-state]]`'s note that Phase 1 currently has no `competitor/` folder to compare
against — this is prep for when it does:

- `projects/ranking shorts/tools/upload_instagram.py` — IG Reels publish via Graph API
  (`IG_ACCESS_TOKEN`, `IG_USER_ID` in root `API.env`). Account: `@rank_ingshorts` per prior memory
  (`ranking-shorts-instagram.md` in user-level memory). Publishes are immediately public — no
  draft/unlisted state, unlike YouTube.
- `projects/ranking shorts/tools/upload_zernio.py` — alternate IG posting path via Zernio API
  (per root CLAUDE.md git log: "Switch Instagram posting to Zernio API").
- `projects/clipping-auto/` — a second IG account lives here (same reusable Meta System User
  token, different `IG_USER_ID`), per prior memory.
- `projects/follower-race/state/races.json` — tracks IG follower-growth race state; useful
  context for engagement/growth-rate benchmarking in Phase 1 if it ever runs.

**How to apply:** When Phase 1 actually has competitor data to compare, map any hashtag/cadence/
hook insight to whichever of `upload_instagram.py` / `upload_zernio.py` / clipping-auto's
equivalent is actually live for that account — check root CLAUDE.md git log or ask if unsure which
posting path is current, since it has changed at least once (Zernio switch).
