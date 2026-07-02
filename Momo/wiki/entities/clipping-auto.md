---
type: entity
tags: [project, youtube, automation, shorts]
created: 2026-06-28
updated: 2026-06-28
sources: [s001]
status: active
---

# clipping-auto (project)

Standalone **daily clipping pipeline** — auto-finds source videos and produces short clips for
upload. Status: **active, deploy pending.** Rules:
[CLAUDE.md](../../projects/clipping-auto/CLAUDE.md).

## What it does
A daily **GitHub Actions** copy of the original `clipping/` flow: auto-finds MrBeast videos,
cuts clips, and uploads them to the "moemen yasser" channel as YouTube **Shorts**. Runs on a
second Instagram account too (reuses the same Meta System User token, different `IG_USER_ID` —
see [[ranking-shorts-instagram]]).

## Clip standard (2026-06-24)
- **35s target / 60s cap** (cut down from 60s/120s). Reason: completion rate is the #1 Shorts
  ranking signal and peaks at 15–60s (OpusClip 2026 analysis of 13.5M+ clips). The earlier ≤2min
  preference was for email-review delivery — a different context.
- **Active-speaker reframing** — `reframe_crop.py` frames the active speaker (lip-motion score +
  hysteresis + segment-aware cuts), not the biggest/nearest face. Fixed "wrong subject framed /
  pans through empty space."
- Upgraded hook prompt in `select_clips.py` (first ~1.5s, curiosity-gap/stakes hooks).

## Quality bar (from memory)
Smooth (zero-phase) reframe + accurate captions; fix lag and ASR. ≤2min historically, now Shorts-
length.

## Triggering (2026-07-01)
Cron schedule removed — now fired **on demand** from the [[momo-website]] "Run my pipelines" badge
(`workflow_dispatch` via `api/runner.py`; local `runner-helper` starts the runner). Badge exposes a
**dry-run** toggle (build clips, no upload). See [[s008-runner-buttons]].

## See also
[[ranking-shorts]] · [[momo-niche]] · [[wat-framework]] · [[competitor-analysis]] (benchmarks this
project's IG account)
