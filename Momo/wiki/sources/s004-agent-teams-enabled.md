---
type: source
tags: [momo, automation, claude-code]
created: 2026-06-29
updated: 2026-06-29
---

# s004 — Agent Teams enabled, explicit-request-only (2026-06-29)

**Source:** Claude Code session in repo root.
[decisions/log.md](../../decisions/log.md) (2026-06-29, last entry) +
[.claude/docs/agent-teams.md](../../.claude/docs/agent-teams.md).

## Key points
- Enabled the experimental Agent Teams feature (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` in
  `.claude/settings.local.json`) — multiple coordinating Claude Code instances with a shared task
  list, vs. subagents which only report back to one caller.
- Wrote a condensed reference guide at `.claude/docs/agent-teams.md` (when to use, architecture,
  task sizing, best practices, limitations) to build better teams in future sessions.
- Standing rule added to root `CLAUDE.md`: never auto-propose or auto-spawn a team for a task
  that merely looks parallelizable — only spawn one when Moemen explicitly asks.

## Touches
[[agent-teams]]
