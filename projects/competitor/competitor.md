# CLAUDE.md — Competitor Analysis Project Rules

> All paths below are relative to this folder (`projects/competitor/`). Run every tool with
> this folder as the working directory — `tools/_common.py` resolves `REPO_ROOT` as `tools/`'s
> parent, so `brand/` and `.tmp/` resolve correctly from here. API keys load from the shared
> `API.env` at the repo root.

## What this project does

A WAT project that runs the **competitor-analysis** automation. It shares the same tools,
conventions, and shared root `API.env` as the newsletter project. The governing SOP is
[workflows/competitor_analysis.md](workflows/competitor_analysis.md) — **read it before
running the pipeline**; it owns the canonical tool-call sequence, edge cases, and a living
"Lessons learned" log.

The tracked subject lives in `company_profile.json`.

## Environment setup

```bash
cd projects/competitor
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m playwright install chromium   # needed by chart/card/PDF tools
python tools/gmail_auth_setup.py                       # one-time OAuth → token.json
```

**Credentials:** shares the one **`API.env` at the repo root** (`tools/_common.py` loads
`../API.env`). Don't make a per-project `.env`. `API.env`, `credentials.json`, `token.json`,
`.tmp/`, and `.venv/` are gitignored.

## Hard rules specific to this project

- **Branding is not optional.** Load `brand/theme.json` and pass it through; never re-derive
  colors/fonts per issue.
- **Never call `send_gmail_email.py` without explicit user confirmation** at the gate, and
  always echo the resolved recipient address there.
- Chromium can't load `file://` images from `set_content()` pages — the PDF tool writes HTML
  to a temp file and `goto`s it, using `Path.as_uri()` (this repo's path has a space).
  Preserve that approach.
