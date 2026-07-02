---
type: entity
tags: [agent]
created: 2026-07-02
updated: 2026-07-02
sources: [s015]
status: active
---

# runner (subagent)

Subagent (`haiku`): runs a project's deterministic `tools/` scripts (project venv,
one-JSON-object contract) in isolation and returns only the parsed result + diagnosed error —
run logs stay off the main thread. **Hard-blocked** from irreversible/public scripts
(uploads/sends/deploys) and from retrying paid calls. Detail →
[runner.md](../../.claude/agents/runner.md).

## Relationships
- **is part of** [[wat-framework]] (the "run a tool" step) · **serves** [[ranking-shorts]], [[clipping-auto]], [[follower-race]]
