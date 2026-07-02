# Momo Brain — Relationship-First Wiki

Moemen's second brain: a **graph of small linked nodes** in this Obsidian vault. Value = the
**links between things**, not long prose. Moemen asks; you do the linking. Rules here override
generic behavior inside `Momo/`.

## Principles
1. **Relationships over prose.** Capture facts as **edges** between nodes, not paragraphs.
2. **Token-frugal.** Tiny nodes. Read `index.md` to navigate — don't open files blindly. Don't
   re-read sources you've summarized. Link to detail, never duplicate it.
3. **Use Obsidian, not the web.** Navigate via `index.md` + `[[links]]` (graph view is the map).
   Only search the web when Moemen explicitly asks.

## Layout
- `raw/` — dropped-in sources. Read, never edit. Repo files count as sources — link in place.
- `wiki/` — the node graph: `entities/`, `concepts/`, `sources/`, `comparisons/`.
- `index.md` — the map. `log.md` — the timeline.

## Node format (keep small, ≤~12 lines)
```markdown
---
type: entity | concept | source | comparison
tags: [momo]
updated: 2026-06-28
---
# Node Name
One sentence: what it is. Link detail, don't restate → [file](../../path.md)

## Relationships
- **uses** [[tool]] · **is part of** [[parent]] · **see** [[related]]
```
- **Typed edges** (a verb per link): *uses, is part of, produces, posts to, competes with,
  supersedes, contradicts, see.*
- Link freely — a `[[link]]` with no page yet is a valid TODO, not an error.
- Filenames: lowercase-kebab-case, unique across the vault.

## Operations
- **Ingest:** read source once → tiny `sNNN-slug.md` in `sources/` (key points as links) → add
  edges to the nodes it touches → update `index.md` → append `ingest` to `log.md`.
- **Query:** read `index.md`, follow links, answer with `[[sNNN]]` citations, add any new edge.
- **Lint:** report orphans, missing edges, contradictions, stale claims. Keep it short.

## Defaults
- Absolute dates (Cairo). Next source id = next free `sNNN`.
- `log.md` entries: `## [YYYY-MM-DD] <op> | <title>`.
- **This brain is the whole workspace's map, not just a side vault.** Root `CLAUDE.md` makes two
  standing rules: (1) Claude Code **consults `index.md` + `[[links]]` first** to find relations and
  save tokens before scanning the repo; (2) **every meaningful addition** to the workspace (new
  project, skill, subagent, feature, site, integration, or decision) gets **ingested same-turn** —
  not just decisions. Keep nodes tiny; link, don't duplicate.
- Add useful conventions here so future sessions inherit them.
