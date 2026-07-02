---
type: entity
tags: [project, youtube, automation]
created: 2026-06-28
updated: 2026-06-28
sources: [s001, s009]
status: active
---

# ranking shorts (project)

**The core MOMO content engine.** Faceless vertical YouTube Shorts pipeline producing "ranking"
/ Top-N list videos. Status: **active, primary focus.** Rules:
[ranking-shorts.md](../../projects/ranking%20shorts/ranking-shorts.md).

## What it does
Generates ranked-list Shorts end to end and auto-posts them. Built on the [[wat-framework]]
(deterministic Python in `tools/`, SOPs, agent orchestrates). Houses the shared **Gmail email
infra** (moved here when `newsletter` was archived) and **Instagram** posting.

## Virality hardening (2026-06-23)
Driven by a competitor comparison vs FailArmy/AFV/format-twins, which found MOMO's gaps were:
no upfront payoff promise, static reveals, flat topic framing. Fixes:
- **1-min hard cap** (was 2 min); intro swoosh removed.
- **Cold-open teaser** — flashes the #1 clip with "WAIT FOR #1" before #5 (on by default).
- **Kinetic rank reveals** — active leaderboard row pops 122%→100% on each reveal.
- **Curiosity-gap topic titles** (`rank_topic.py`).

## World Cup angles (2026-07-01)
While the 2026 tournament is live the pipeline is forced to a `worldcup` genre with **three
rotating angles**: `fan` (stands), `match` (on-pitch), and `streamer` (iShowSpeed/FaZe/Marlon/xQc
at the WC). Streamer clips are **YouTube-sourced** (`find_streamer_clips.py`), the others Reddit.
See [[s009-worldcup-streamer-angle]].

## Distribution
- **YouTube** — MOMO Shorts channel (primary).
- **Instagram** — @rank_ingshorts, via the Zernio API (switched from direct Meta Graph posting,
  commit b2edc5f). See [[ranking-shorts-instagram]].
- Goal: auto-post one finished video to **YouTube + TikTok + Instagram** in a single run.

## Deployed copy
Mirrored to GitHub `momoazm/ranking-shorts`. ⚠ Its `sync_from_source.py` points at a stale
"ai videos/" layout — **edit the deployed repo directly** rather than relying on sync.

## Triggering (2026-07-01)
Cron schedule removed — now fired **on demand** from the [[momo-website]] "Run my pipelines" badge
(`workflow_dispatch` via `api/runner.py`; local `runner-helper` starts the runner). See
[[s008-runner-buttons]].

## See also
[[clipping-auto]] · [[momo-niche]] · [[momo-brand]] · [[api-fallback-chains]] · [[wat-framework]] ·
[[competitor-analysis]] (benchmarks this project's IG account)
