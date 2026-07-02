---
type: concept
tags: [momo, meta]
created: 2026-06-29
updated: 2026-07-01
sources: [s001, s003, s007]
---

# llm-wiki-method (concept)

How this brain itself works: small linked nodes (`entities/`, `concepts/`, `sources/`,
`comparisons/`), ingested by Claude reading a source once. Rules: [CLAUDE.md](../../CLAUDE.md).
As of [[s007-momo-map-and-backfill]] the brain **maps the whole workspace, not just decisions**:
root `CLAUDE.md` makes it the first-stop relationship map (consult before grepping, to save tokens)
and requires ingesting *every* meaningful addition same-turn.

## Relationships
- **triggered by** *any* meaningful workspace addition — new project/skill/feature/site/decision
  (standing rule, not a hook — see [[s003-momo-ingest-hook-abandoned]])
- **see** [[wat-framework]]
