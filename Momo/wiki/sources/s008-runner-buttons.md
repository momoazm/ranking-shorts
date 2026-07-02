---
type: source
tags: [momo]
updated: 2026-07-01
---
# s008 — On-demand "Run" buttons replace pipeline cron schedules
Both self-hosted pipelines are now fired from the MOMO site instead of cron. Detail → decision
log [2026-07-01] + [runner-helper README](../../../runner-helper/README.md).

## Key points
- **Schedules removed** from `clipping_daily.yml` + `autopost.yml`; kept `workflow_dispatch`.
- **Vercel `api/runner.py`** holds the GitHub PAT, dispatches the workflow, **gated** while a run is active (mirrors `api/gcal.py`, password-gated).
- **`runner-helper/`** (always-on, his PC) polls GitHub → launches `run.cmd --once` so the runner starts → runs one job → exits.
- **Badge UI** in [[momo-website]] hand-built to [[21st-dev-magic]] be-ui-animated-badge, restyled to MOMO gold.

## Relationships
- **adds feature to** [[momo-website]] · **triggers** [[ranking-shorts]] · **triggers** [[clipping-auto]]
- **uses** [[21st-dev-magic]] · **see** decision log 2026-07-01 (deploy + live test pending Moemen's go)
