---
type: entity
tags: [agent]
created: 2026-07-02
updated: 2026-07-02
sources: [s015]
status: active
---

# researcher (subagent)

Subagent (`sonnet`): web research in its **own context window** — search/extract fallback
chains, 3–6 strong sources, returns a ≤40-line cited brief so raw dumps never hit the main
thread. Read-only; never posts/edits. Detail → [researcher.md](../../.claude/agents/researcher.md).

## Relationships
- **uses** [[api-fallback-chains]] · **see** [[competitor-analysis]] (heavier, IG/YT-specific sibling)
