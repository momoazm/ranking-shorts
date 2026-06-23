---
name: send-email
description: Use when Moemen wants to send an email via Gmail — delivering a newsletter, a report, or any message from his account. Sending is irreversible; always confirm first.
---

# Send Email (Gmail)

Send mail through Gmail. **This is the only irreversible step — never send without explicit confirmation.**

## Steps (run from the relevant `projects/<name>/`)
1. **Build the message** — `python tools/build_email_mime.py ...` → a `.eml` whose exact bytes are inspectable.
2. **Gate:** show Moemen the **resolved recipient address**, subject, and attachments, and wait for an explicit "go."
3. **Send** — `python tools/send_gmail_email.py ...` only after confirmation.

## Config
- Uses `GMAIL_*` from `API.env` (sender `moemenyasserazmy@gmail.com`) + `credentials.json` / `token.json` (gitignored).
- Standing format for newsletters: short email body, the branded newsletter as an attached **PDF**.
