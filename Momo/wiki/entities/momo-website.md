---
type: entity
tags: [project, web]
created: 2026-07-01
updated: 2026-07-01
sources: [s007, s008]
status: active
---

# MOMO website — "Knowledge Oracle"

The public MOMO site (`projects/website/CS/index.html`): **"Upload your archive. Ask it anything"**
— a front-end to the [[cs-rag]] system. Deployed **Vercel static** via the `momoazm/CS` repo.
Includes a password-gated **"My Calendar"** panel backed by a Vercel serverless function
(`api/gcal.py`) that lists/creates/edits events on the owner's Google Calendar.
Detail → [CALENDAR_SETUP.md](../../projects/website/CS/CALENDAR_SETUP.md).

Also hosts a password-gated **"Run my pipelines"** panel (`api/runner.py`) that triggers the
self-hosted pipelines on demand — see [[s008-runner-buttons]].

## Relationships
- **front-end for** [[cs-rag]] · **is part of** [[website]] · **on brand** [[momo-brand]]
- **triggers** [[ranking-shorts]] + [[clipping-auto]] via [[s008-runner-buttons]] · **uses** [[21st-dev-magic]]
- **verify** serve + screenshot before any push (see [[website]])
