---
name: send-email
description: Slash entry point for the send-email agent — build and send a Gmail message (gated).
disable-model-invocation: true
context: fork
agent: send-email
---

Prepare this email, then STOP at the confirmation gate (show resolved recipient, subject,
attachments) and wait for an explicit go before sending:

$ARGUMENTS
