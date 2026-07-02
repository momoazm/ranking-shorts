---
type: source
tags: [seed, workspace, momo]
created: 2026-06-28
updated: 2026-06-28
---

# s001 — Claude Code Workspace (seed ingest)

**Source:** Moemen's entire `claude code` repo as of 2026-06-28 — context files, project READMEs,
rules, decision log, and memory. Ingested to seed the brain with a structured picture of who he
is and what he's building. (Reference in place — not copied into `raw/`.)

## Key points
- **Who:** Moemen — student in Cairo, brand **MOMO**, solo, pre-revenue. See [[moemen]].
- **#1 priority:** build as many genuinely useful automations as possible while deepening his
  understanding of AI and Claude Code. See [[goals-and-priorities]].
- **What he makes:** faceless **"ranking" Shorts** (Top-N list videos) for YouTube, expanding to
  TikTok + Instagram. The core engine is [[ranking-shorts]].
- **Active projects:** [[ranking-shorts]], [[clipping-auto]], [[follower-race]], [[website]].
- **How automations are built:** the [[wat-framework]] (Workflows / Agents / Tools) — markdown
  SOPs, deterministic Python tools, the agent orchestrates.
- **Reliability is the bar:** he wants automations "as close to perfect as possible"; the
  standing pain point is making them run flawlessly with less babysitting.
- **Brand is canonical:** master assets in repo-root `brand/`; never re-derive colors/fonts.
  See [[momo-brand]].
- **Key infra:** one `API.env` at repo root with [[api-fallback-chains]]; Gmail + Google
  Workspace via `GWS/`; Firecrawl MCP for web research.

## Notable structure
- `context/` — source of truth about Moemen (me, work, team, priorities, goals).
- `.claude/rules/` — behavioral rules (communication, content, automation practices).
- `decisions/log.md` — append-only decision log.
- Persistent **memory** across sessions (niche, delivery prefs, deploy setup, etc.).

## Touches
[[moemen]] · [[momo-brand]] · [[ranking-shorts]] · [[clipping-auto]] · [[follower-race]] ·
[[website]] · [[wat-framework]] · [[api-fallback-chains]] · [[goals-and-priorities]] ·
[[llm-wiki-method]]
