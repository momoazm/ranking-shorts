---
type: source
tags: [momo, instagram, playwright, follower-race]
updated: 2026-07-01
---
# s013 — Follower-race → Instagram, race polish, site button, follower auto-sync (2026-07-01)

[[follower-race]] connected to Instagram end to end. **Zernio posts the Reel from the cloud
runner**; **comment-replies + follower-list sync run locally** via [[playwright-cli]] using a
one-time saved IG session (`tools/ig_login.py` → `state/ig_session.json`, gitignored — IG has no
reply/followers API and challenges cloud IPs).

## Relationships
- [[follower-race]] **posts to** Instagram **via** Zernio (cloud); **replies via** [[playwright-cli]] (local)
- new tools **reply_placements.py** (comment→finish-place replies, `--confirm` gated) &
  **sync_followers.py** (scrapes followers modal → usernames+pfps → `known_followers.json`, which
  **drives the racer count**) — both **use** [[playwright-cli]] + the saved session
- race.html **produces** viral polish: leaderboard HUD, finish zoom + photo-finish flash, winner
  banner, snappier podium (ease-out-back + pulsing halo); determinism (Pass A==B) held
- [[momo-website]] **gained** a "Run follower race" button (reuses `/api/runner` → workflow_dispatch)
- archived old Zernio-comment path (`watch_race_comments.py`, `zernio_webhook.py`)
- **see** [[s010-playwright-cli]] · gated by confirm-before-irreversible
- **superseded by** [[s014-follower-race-toplevel-mention-reply]] (reply is now a top-level @mention, not threaded)
