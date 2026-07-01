---
type: entity
tags: [skill, web, ai]
created: 2026-07-01
updated: 2026-07-01
sources: [s012]
status: active
---

# website-selftest (skill)

Inline skill that tests the MOMO site's **backends** end to end: a full [[cs-rag]] round-trip
(ingest a throwaway passphrase doc → query → assert top match → delete only those vectors) and,
with `--url`, the live `/api/{health,ask,gcal,runner}` endpoints. Self-cleaning (never
`delete_all`). Rules → [SKILL.md](../../../projects/website/skills/website-selftest/SKILL.md).

## Relationships
- **tests** [[cs-rag]] + [[momo-website]] · **is part of** [[website]] · **created by** [[s012]]
- **complements** serve+screenshot frontend check (see [[website]])
