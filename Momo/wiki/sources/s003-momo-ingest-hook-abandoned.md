---
type: source
tags: [momo, automation, claude-code]
created: 2026-06-29
updated: 2026-06-29
---

# s003 — Momo auto-ingest hook tried, abandoned (2026-06-29)

**Source:** Claude Code session in repo root.
[decisions/log.md](../../decisions/log.md) (2026-06-29, last two entries).

## Key points
- Tried a `PostToolUse` agent-type hook in `.claude/settings.json` to auto-ingest every
  `decisions/log.md` entry into this vault. It never fired (even after `/hooks` reloads) — a
  sibling `command`-type hook in the same matcher fired fine, so the bug is specific to
  `"type": "agent"`, which turned out to be experimental and gating-oriented, not built for
  side-effecting tasks.
- Replaced with a **standing rule** instead (root `CLAUDE.md`): ingest happens manually, same
  turn, every time a decision is appended — no hook involved.

## Touches
[[llm-wiki-method]]
