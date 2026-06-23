---
name: send-email
description: Send an email via Gmail as a step in the current flow — e.g. delivering the report/newsletter/PDF just produced at the end of an automation. Runs INLINE (keeps the flow's context). Sending is irreversible — always confirm first.
---

# Send Email (Gmail) — inline

Send mail through Gmail as part of the current flow, using the context already built (the artifact
just produced, the recipient, attachments). **Sending is the only irreversible step — never send
without explicit confirmation from Moemen.**

## Steps (run from the relevant `projects/<name>/`)
1. **Build the message** — `python tools/build_email_mime.py ...` → a `.eml` whose exact bytes are
   inspectable. Use the artifact from the current flow (e.g. the PDF just generated).
2. **Gate:** show Moemen the **resolved recipient address**, subject, and attachments, and wait for
   an explicit "go." If you can't get confirmation, stop and report — do not send.
3. **Send** — `python tools/send_gmail_email.py ...` only after confirmation. Report the result.

## Config
- Uses `GMAIL_*` from `API.env` (sender `moemenyasserazmy@gmail.com`) + gitignored
  `credentials.json` / `token.json`.
- Standing format for newsletters: short email body, the branded newsletter as an attached **PDF**.
