---
name: website-selftest
description: Test the MOMO website's backends end to end — the CS RAG pipeline (ingest → ask → verify → clean up) and, when a server URL is given, the live /api/ endpoints (RAG answer, Calendar, pipeline runner). Use to confirm the site actually works before a deploy, or to debug "is the RAG/calendar broken?".
---

# Website self-test

A one-command health check for the MOMO **Knowledge Oracle** site. It proves the
real backends work — not just that files exist — and cleans up after itself so the
production vector DB is left exactly as it was.

Deterministic work lives in `selftest.py` (WAT: it prints one JSON object and exits
non-zero on failure). You orchestrate: run it, read the JSON, report pass/fail and
what broke.

## When to use
- Before pushing/deploying the site (`momoazm/CS` repo) — sanity-check the RAG.
- When Moemen says the RAG or calendar "isn't answering / is broken."
- After changing anything in `CS/tools/`, `CS/webapp/`, or the site's `/api/*`.

## What it checks
- **RAG round-trip (always, critical):** ensures the Pinecone index exists, ingests
  a throwaway doc with a random passphrase, queries it back, and asserts that doc is
  the top match — then **deletes only the vectors it added** (never `delete_all`, so
  any real data is untouched).
- **Live endpoints (only with `--url`, best-effort):** `GET /api/health`,
  `POST /api/ask` (full Gemini answer — checks it responds), `POST /api/gcal {list}`
  (Calendar; needs Google creds, so reported not fatal), `GET /api/runner?repo=ranking`.

## How to run
RAG only (no server needed — uses the `CS/.venv` and real Gemini + Pinecone keys):
```bash
python projects/website/skills/website-selftest/selftest.py
```

Also test the live endpoints — first serve the site so `/api/*` is same-origin:
```bash
cd projects/website/CS && .venv/Scripts/python webapp/api.py    # serves on :8000
python projects/website/skills/website-selftest/selftest.py --url http://localhost:8000
```
Add `--strict` to also fail the run if `/api/health` or `/api/ask` fail.

Exit code `0` = pass, `1` = a critical check failed. Read the printed JSON: each
section has an `ok` boolean plus a `detail`/`error` explaining any failure.

## Notes / gotchas
- **Uses real API calls.** Each run makes a few Gemini embedding calls (and one chat
  call if `--url` is set). It's cheap, but per house rules, don't loop it needlessly.
- Requires the CS venv (`CS/.venv`). If missing, the script says so — set it up per
  `CS/CS.md` → *Environment setup*.
- Keys resolve the same way the app does: `PINECONE_API_KEY` from `CS/.env`,
  `GEMINI_API_KEY` from the shared root `API.env` (walked up automatically).
- The frontend (the gumball companions, layout) is verified separately by the
  serve-and-screenshot flow in `web.md` — this skill covers the *backends*.

## Lessons learned
- _(2026-07-01)_ Created after a real bug: `webapp/app.py` resolved the shared
  `API.env` to the wrong path, so every question failed with "GEMINI_API_KEY is not
  set" locally. A backend self-test catches that class of regression instantly.
- _(2026-07-02)_ The site is now **multi-page** (index/oracle/study/calendar/pipelines) and
  `CS/webapp/api.py` mounts the whole `website/` dir. The deploy clone is
  `C:\Users\monar\Downloads\CS-deploy` — if you serve locally to test `/api/*`, serve from
  there so you're testing what actually ships. Frontend flow lives in the `site-update` skill.
