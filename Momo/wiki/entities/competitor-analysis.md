---
type: entity
tags: [project, automation, competitor-research]
created: 2026-06-29
updated: 2026-06-29
sources: [s002, s005]
status: active
---

# competitor-analysis (project)

**Combined competitor-intelligence workflow.** Benchmarks Moemen's Instagram ranking-shorts
accounts vs. IG rivals (+ syncs repos), and MOMO's YouTube channel vs. YouTube rivals. Rules:
[CLAUDE.md](../../projects/competitor-analysis/CLAUDE.md).

## How to run
The `update` subagent — natural language or `@agent-update` — one combined SOP, two phases. No
slash wrapper (the `/improver` skill was removed, see [[s005-improver-skill-removed]]).

## Relationships
- **benchmarks accounts from** [[ranking-shorts]] · [[clipping-auto]]
- **replaces** the old `compare-youtube-channels` skill + `competitor-benchmark-sync` subagent
- **uses** [[wat-framework]] · [[api-fallback-chains]]
- **see** [[ranking-shorts-instagram]]
