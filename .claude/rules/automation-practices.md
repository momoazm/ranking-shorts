# Automation Practices

How to build and run my automations. My standing pain point is wanting them to be **flawless** —
treat reliability as the priority.

## Build philosophy (WAT)
- Keep the split clean: **deterministic Python in `tools/`**, **plans in `workflows/`**, you
  **orchestrate**. Don't do work directly that a tool should do — check `tools/` first, build a
  new script only when nothing fits.
- Each project runs from **its own folder** with its own venv; tools print exactly one JSON
  object to stdout. Read the project's rules `.md` before working in it.
- When something breaks: read the full error, fix the tool, verify, then update the workflow's
  "Lessons learned" so it doesn't happen again. Surface whole-chain failures to me — don't loop
  silently. If a fix burns paid API calls/credits, check with me before re-running.

## Confirm before anything irreversible or public
- **Never publish, post, send an email, or upload without my explicit confirmation.** This
  includes `send_gmail_email.py`, YouTube/TikTok/Instagram uploads, and deploys.
- At the gate, **show me exactly what will happen**: resolved recipient/target account, privacy
  setting, title/description, file, and size. Wait for an explicit "go."
- For low-risk, easily-undone steps, use good judgment, do it, and tell me what you did.

## Quality bar
- Aim for "as close to perfect as possible." Don't ship an automation as "done" until it's been
  verified actually working end to end — say so plainly if a step was skipped or a test failed.
