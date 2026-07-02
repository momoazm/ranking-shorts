---
type: entity
tags: [project, instagram, automation]
created: 2026-06-28
updated: 2026-07-01
sources: [s001, s013]
status: active
---

# Followers Race (project)

Instagram automation: **physics marble races** where every marble is one of
**@the_followers_racer's** real followers (real username + photo when fetchable), racing down a
winding obstacle track to a podium finale showing the top 3.
Rules: [README.md](../../projects/follower-race/README.md).

## Build
- **WWE-style intro/outro voiceover**, royalty-free music bed.
- Physics via **Matter.js**, rendered headlessly through **Playwright**, composited with
  **ffmpeg**.

A newer/standalone format distinct from the ranking-Shorts engine — interactive, follower-driven
engagement content for Instagram.

## Live on Instagram (2026-07-01, [[s013]])
- **posts to** IG **via** Zernio from the cloud runner; **replies to commenters** with their
  finish place **via** [[playwright-cli]] locally (saved IG session — no reply API exists).
- **follower list auto-synced** (`sync_followers.py`) from the logged-in followers modal → its
  length **is** the racer count; pfps cached for real-photo marbles.
- viral polish: leaderboard HUD, finish zoom + flash, winner banner, snappier podium.
- **run on demand from** [[momo-website]] (a "Run follower race" button).

## See also
[[ranking-shorts]] · [[momo-brand]] · [[wat-framework]] · [[playwright-cli]] · [[momo-website]]
