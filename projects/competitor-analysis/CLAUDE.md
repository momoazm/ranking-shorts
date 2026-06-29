# CLAUDE.md

This file provides guidance to Claude Code when working in the `competitor-analysis` project. It
follows the **WAT framework** (Workflows, Agents, Tools) used across this repo. Read the root
`CLAUDE.md` for the shared WAT philosophy.

## This project: competitor intelligence (Instagram + YouTube)

One combined workflow covering both platforms Moemen tracks competitors on. The governing SOP is
[workflows/competitor_analysis.md](workflows/competitor_analysis.md) — **read it before running
anything**; it owns the canonical step sequence for both phases and a "Lessons learned" log.

- **Phase 1 (Instagram):** reads the repo-root `competitor/` folder, benchmarks Moemen's 3 tracked
  IG accounts against same-niche rivals, pushes durable repo changes (config, hashtags, cadence),
  then deletes `competitor/` (a standing exception to the root archive rule, scoped to that folder
  only).
- **Phase 2 (YouTube):** reads [momo-profile.json](momo-profile.json) (MOMO's channel baseline),
  benchmarks against same-niche YouTube Shorts rivals, returns an in-chat gap analysis + action
  plan. No publishing, no email — chat output only.

## Agents & invocation
- **Agent:** `.claude/agents/update.md` (`model: sonnet`, `memory: project`) — does the actual
  work, orchestrated by reading this project's workflow SOP rather than duplicating it.
- **Slash entry point:** `.claude/skills/improver/SKILL.md` (`context: fork` → `agent: update`).
  Run `/improver` to kick off the full combined workflow. (Named `improver`, not `update` — the
  original `/update` skill didn't trigger for the user; renamed and re-verified. See
  `decisions/log.md`.)
- Natural language ("use the update subagent to benchmark competitors") and `@agent-update` also
  work, per the platform's normal subagent invocation rules.

## Hard rules specific to this project
- **Don't fabricate competitor data or metrics** on either platform — thin sourcing is expected
  for a small niche; say so rather than inventing numbers.
- **Repo pushes (Phase 1) don't need the irreversible-action gate** — they're not public-facing —
  but a drastic strategy pivot (not a tuning tweak) should still be flagged before pushing.
- **Deleting `competitor/` is a deliberate, scoped exception** to "don't delete — archive." Don't
  extend that exception to any other folder without Moemen saying so explicitly.
- **Keep `momo-profile.json` current** — update it when a real competitor/metric/handle is
  confirmed during a run, so the next run starts from a better baseline.
