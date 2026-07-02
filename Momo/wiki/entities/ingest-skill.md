---
type: entity
tags: [skill]
created: 2026-07-02
updated: 2026-07-02
sources: [s015]
status: active
---

# ingest (skill)

Inline skill `/ingest`: executes this brain's **Ingest op** consistently — tiny `sNNN` source
node, typed edges on touched nodes, `index.md` + `log.md` updates. Backs the standing
"ingest same turn" rule in root `CLAUDE.md`. Detail →
[SKILL.md](../../.claude/skills/ingest/SKILL.md).

## Relationships
- **implements** [[llm-wiki-method]] · **is part of** [[wrap-skill]] (step 3 of session close-out)
