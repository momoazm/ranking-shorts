# CLAUDE.md — Newsletter Project Rules

> All paths below are relative to this folder (`projects/newsletter/`). Run every tool with
> this folder as the working directory — `tools/_common.py` resolves `REPO_ROOT` as `tools/`'s
> parent, so `brand/` and `.tmp/` resolve correctly from here. API keys load from the shared
> `API.env` at the repo root.

## What this project does

A single end-to-end pipeline: turn "make me a newsletter about X" into a researched,
branded newsletter, rendered to a PDF, and emailed via Gmail after explicit human approval.
The governing SOP is [workflows/newsletter_automation.md](workflows/newsletter_automation.md)
— **read it before running the pipeline**; it owns the canonical tool-call sequence, edge
cases, and a living "Lessons learned" log.

## Environment setup

```bash
cd projects/newsletter
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m playwright install chromium   # needed by chart/card/PDF tools
python tools/gmail_auth_setup.py                       # one-time OAuth → token.json
```

**Credentials:** shares the one **`API.env` at the repo root** (`tools/_common.py` loads
`../API.env`) — search/LLM/image keys plus Gmail config. Don't make a per-project `.env`.
`API.env`, `credentials.json`, `token.json`, `.tmp/`, and `.venv/` are gitignored.

## Pipeline data flow

1. Research: `tavily_search.py` → `extract_article.py` (your reasoning drafts the copy).
2. Visuals → `.tmp/`: `generate_chart.py` (real numeric data), `generate_card_image.py`
   (one striking stat/quote), `generate_ai_image.py` (sparingly). Each visual's `cid` name
   (e.g. `chart1`) **must stay identical across generate → render → MIME-build steps.**
3. Render: write a content JSON, then `render_email_html.py` runs
   Jinja2 (`tools/templates/*.j2`) → MJML → premailer to produce email-safe inlined HTML.
4. `generate_pdf.py` turns that HTML into the **delivery PDF** — the standing format: the
   email body stays short, the branded newsletter is the attached PDF (user pref, 2026-06-17).
5. `build_email_mime.py` assembles the `.eml` (kept separate from sending so exact bytes are
   inspectable at the gate); `send_gmail_email.py` is the **only irreversible step.**

## Hard rules specific to this project

- **Branding is not optional.** Load `brand/theme.json` and pass it through; never re-derive
  colors/fonts per issue.
- **Never call `send_gmail_email.py` without explicit user confirmation** at the gate, and
  always echo the resolved recipient address there.
- Chromium can't load `file://` images from `set_content()` pages — `generate_pdf.py` writes
  HTML to a temp file and `goto`s it, and uses `Path.as_uri()` (this repo's path has a space).
  Preserve that approach.
