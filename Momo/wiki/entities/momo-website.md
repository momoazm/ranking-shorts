---
type: entity
tags: [project, web]
created: 2026-07-01
updated: 2026-07-02
sources: [s007, s008, s016]
status: active
---

# MOMO website — "Knowledge Oracle"

The public MOMO site — since [[s016-site-redesign-study-hub]] a **5-page site** (index /
oracle / study / calendar / pipelines) in `CS-deploy/website/`, deployed **Vercel static**
via the `momoazm/CS` repo. Oracle = front-end to [[cs-rag]]; **Study hub** = 9618 syllabus
tracker + flashcards + paper timer + pomodoro (all localStorage); Calendar (`api/gcal.py`)
and "Run my pipelines" (`api/runner.py`, [[s008-runner-buttons]]) have their own pages.
Only mascot: animated Gumball ([[gumball-companions]] superseded by s016).

## Relationships
- **front-end for** [[cs-rag]] · **is part of** [[website]] · **on brand** [[momo-brand]]
- **triggers** [[ranking-shorts]] + [[clipping-auto]] via [[s008-runner-buttons]] · **uses** [[21st-dev-magic]]
- **built/changed via** [[site-update-skill]] — verify locally, then **always push** ([[s016-site-redesign-study-hub]])
