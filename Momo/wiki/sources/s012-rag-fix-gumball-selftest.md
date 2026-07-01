---
type: source
tags: [momo, web, ai]
updated: 2026-07-01
---
# s012 — RAG bug fix + gumball companions + website self-test

One session on the MOMO site: tested [[cs-rag]] end to end, fixed a real bug, added mascots,
and shipped a backend test skill. Detail lives in the files + [decisions/log.md](../../../decisions/log.md).

## Key points
- **Bug fixed:** `CS/webapp/app.py` loaded the shared `API.env` from the wrong path
  (`projects/website/API.env`, absent) → `GEMINI_API_KEY` unset → whole [[momo-website]] RAG
  backend broke locally. Now walks parents like `tools/_common.py`. Verified: 3 files in, 4
  correct grounded answers, out-of-DB question refused. Test data wiped (index → 0).
- **Gumball companions:** auto-populating mascots on every card/section of the site, with a
  `MutationObserver` so new sections get one automatically → produces [[gumball-companions]].
  Not deployed — preview-before-push.
- **New skill:** [[website-selftest-skill]] — backend health check (RAG round-trip + `/api/*`).

## Relationships
- **tests / fixes** [[cs-rag]] · **decorates** [[momo-website]] · **produces** [[website-selftest-skill]]
- **is part of** [[website]] · **see** [[21st-dev-magic]]
