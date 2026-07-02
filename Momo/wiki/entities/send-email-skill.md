---
type: entity
tags: [skill]
created: 2026-07-01
updated: 2026-07-01
sources: [s007]
status: active
---

# send-email (skill)

Inline skill: send an email via **Gmail** as a step in the current flow (deliver the artifact just
produced). Builds a `.eml`, **gates on explicit confirmation** (sending is the only irreversible
step), then sends. Gmail tools + OAuth live in `projects/ranking shorts/` (`send_gmail_email.py`).
Detail → [SKILL.md](../../.claude/skills/send-email/SKILL.md).

## Relationships
- **runs from** [[ranking-shorts]] (Gmail tools/OAuth) · **used by** [[infographics-skill]]
- **confirm-before-send** rule — irreversible
