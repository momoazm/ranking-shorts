---
name: infographics
description: Use when Moemen wants a standalone, on-brand infographic made from a finished video's key points (or a topic) — rendered with legible text and EMAILED to him. Runs inline; renders HTML→PNG with the MOMO brand assets, then sends it via Gmail.
argument-hint: [key points, or path to .tmp/story.json]
---

## What This Skill Does

Turn a title + key points into a branded **MOMO infographic** (legible HTML→PNG) and **email it to
Moemen** — the email is the deliverable, not a saved file. Uses the real brand assets
(`brand/theme.json` + `brand/logo.png`). Inline.

## Steps

1. **Gather title + key points.** Prefer the current flow's video (`.tmp/story.json`: title + 3–6
   short labels from hook/narration). Else use `$ARGUMENTS`. Else ask Moemen.
2. **Render** (from `projects/ranking shorts/`):
   ```
   python tools/build_infographic.py --title "<TITLE>" --points "<p1|p2|...>" --out .tmp/infographic.png
   ```
   Points separated by `|`, ≤7, one short phrase each. Brand colors/fonts/logo applied automatically.
3. **Build the email** (also from `projects/ranking shorts/` — the Gmail tools + OAuth live here now):
   - Write a short HTML body to `.tmp/ig_body.html` (e.g. "Here's your **&lt;title&gt;** infographic.").
   - ```
     python tools/build_email_mime.py --to <recipient> --subject "<TITLE> — infographic" \
       --html .tmp/ig_body.html \
       --attachments '[{"path":"<ABSOLUTE path to infographic.png>","filename":"<TITLE>.png"}]' \
       --out .tmp/ig_email.eml
     ```
   - Recipient defaults to `GMAIL_TO` / `GMAIL_SENDER_EMAIL` (`moemenyasserazmy@gmail.com`).
4. **Confirmation gate (never skip — sending is irreversible):** show Moemen the resolved
   **recipient**, subject, and attachment (filename + size). Wait for an explicit "go." No go → stop.
5. **Send** only after confirmation:
   ```
   python tools/send_gmail_email.py --eml .tmp/ig_email.eml
   ```
   Report the result.

## Output
- An **email to Moemen's Gmail** with the infographic attached. (`.tmp/infographic.png` is just the
  working file behind it.)

## Notes
- **Irreversible:** never send without explicit confirmation; always echo the resolved recipient at the gate.
- **Brand assets** are applied automatically by the renderer — never re-derive colors.
- Keep each point short (a phrase, one line); ≤7 points. Rendering is local/free — re-roll wording freely.
- Tools split across projects: renderer in `projects/ranking shorts/`, email in `projects/newsletter/` (shared Gmail OAuth).
