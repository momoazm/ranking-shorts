---
name: competitor-folder-state
description: Whether the repo-root competitor/ folder (Phase 1 Instagram data) exists, and how to avoid confusing it with archives/competitor
metadata:
  type: project
---

As of 2026-06-29, the repo-root `competitor/` folder referenced by Phase 1 of
`projects/competitor-analysis/workflows/competitor_analysis.md` does **not exist**. Verified via
multiple Glob searches (`competitor/**`, `**/Competitor*`, `**/competitors/**`) — no matches at
the repo root.

**Don't confuse it with `archives/competitor/`** — that's a completely different, unrelated
archived project (the old newsletter automation: has `.venv`, `tools/generate_pdf.py`,
`tools/send_gmail_email.py`, `workflows/newsletter_automation.md`, `credentials.json`). It has
nothing to do with Instagram competitor benchmarking data. Don't delete or touch it under the
"delete competitor/ after Phase 1" rule — that rule is scoped only to a literal `competitor/` at
the repo root containing IG benchmarking data, which has not been (re)populated since.

**How to apply:** When running the `update` workflow, check for `competitor/` at repo root first.
If absent/empty, per the workflow's own lesson: stop Phase 1, tell Moemen plainly, and proceed to
Phase 2 (YouTube) independently — don't improvise fake IG comparisons. If Moemen says he dropped
new competitor data in, re-check the literal path before assuming it's still missing.
