---
name: generate-video
description: Slash entry point for the generate-video agent — build a ranking Short up to the preview gate.
disable-model-invocation: true
context: fork
agent: generate-video
---

Build a ranking (Top-N) Short for the request below. Run the full pipeline and STOP at the preview
gate (show title/description/tags/privacy + have me eyeball .tmp/final.mp4) — do not upload:

$ARGUMENTS
