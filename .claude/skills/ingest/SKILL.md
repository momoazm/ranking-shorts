---
name: ingest
description: Ingest a change into the Momo brain — a new/changed project, skill, subagent, feature, site, integration, or logged decision. Creates the tiny sNNN source node with typed edges and updates index.md + log.md. Run the same turn anything meaningful changes.
argument-hint: [what changed]
---

# Momo Ingest — inline

Execute `Momo/CLAUDE.md`'s **Ingest op** for the change named in `$ARGUMENTS` (or, with no
arguments, for the meaningful change(s) made this session that aren't in the brain yet).
Goal: the graph stays the workspace's accurate map at minimal token cost — **link, don't
duplicate**.

## Steps
1. **Scope the change.** From `$ARGUMENTS` / the current conversation, state in one line what
   changed and which existing nodes it touches. If nothing meaningful changed, say so and stop.
2. **Read `Momo/index.md` only** (never browse the vault) — find the touched nodes and the next
   free `sNNN` id.
3. **Write the source node** `Momo/wiki/sources/sNNN-<slug>.md` (lowercase-kebab slug, ≤~12
   lines): frontmatter `type: source`, `tags: [momo]`, `updated: <today, Cairo date>`; body =
   what happened + key points **as `[[links]]`**, plus a path/pointer to the real file(s) —
   never restate their content.
4. **Wire the edges.** On each touched entity/concept node: add/refresh typed edges (*uses, is
   part of, produces, posts to, competes with, supersedes, contradicts, see*) and the `sNNN` in
   its `sources:` list. If a node is missing, create a tiny stub (or leave the `[[link]]` as a
   TODO — both are valid) and, when the change **supersedes** an old fact, add the
   *supersedes/contradicts* edge instead of deleting history.
5. **Update the map:** add the `[[sNNN-slug]]` line under **Sources** in `index.md` (+ any new
   entity/concept lines), bump its `updated:` date.
6. **Append to `Momo/log.md`:** `## [YYYY-MM-DD] ingest | <title>` + 2–5 lines summarizing with
   `[[links]]`. Append-only — never edit past entries.

## Notes
- Absolute Cairo dates everywhere; filenames unique across the vault.
- Multiple related changes in one turn → ONE `sNNN` node covering them, not one each.
- A decision just appended to `decisions/log.md` counts as a change — link the decision's topic
  nodes rather than copying its text.
