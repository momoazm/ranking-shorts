---
type: entity
tags: [skill]
created: 2026-07-02
updated: 2026-07-02
sources: [s015]
status: active
---

# wrap (skill)

Inline skill `/wrap`: session close-out — append new decisions to `decisions/log.md`, run the
[[ingest-skill]] steps, refresh touched project READMEs, git **commit without push**, and give
Moemen a session summary (from `templates/session-summary.md`). Detail →
[SKILL.md](../../.claude/skills/wrap/SKILL.md).

## Relationships
- **uses** [[ingest-skill]] · **produces** the decision-log entries · **see** [[llm-wiki-method]]
