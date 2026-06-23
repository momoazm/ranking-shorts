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
2. **Render** (from `projects/ranking shorts/`) — pick a style:

   **A) Card list** (clean, fast, default): legible numbered cards.
   ```
   python tools/build_infographic.py --title "<TITLE>" --points "<p1|p2|...>" \
     [--icons "<i1.png|i2.png|...>"] --out .tmp/infographic.png
   ```
   Points separated by `|`, ≤7, one short phrase each. Optional `--icons` = one AI image per point
   (generate icon-only images first via `generate_ai_image.py`, no text, brand `--style`).

   **B) Flow diagram** (rich "glowing tech poster" look, like a node/flow graphic): two steps —
   1. Generate a **text-free hero scene** with `generate_ai_image.py` (e.g. a glowing diagram, nodes,
      icons — **NO text/words** in the prompt) → `.tmp/flow-scene.png`.
   2. Overlay crisp labels: `python tools/build_flow_infographic.py --scene .tmp/flow-scene.png
      --title "<TITLE>" --size 1200 --labels '[{"text":"...","sub":"...","x":0.2,"y":0.15}, ...]'
      --out .tmp/infographic.png`. `x`,`y` are 0..1 fractions = each label's center; tune them to the
      generated scene's node positions (overlaying on AI art means positions are per-scene).

   **Vary the design each run** (esp. the flow style — don't repeat the same look): rotate the scene's
   **layout** (circular flow / top-down pipeline / isometric nodes / hex grid / radial burst) and the
   **accent** (keep MOMO gold as the anchor, pair it with one of cyan/teal, scarab-red, or silver).
   Brand colors/fonts always come from `brand/theme.json`.
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
- All tools live in `projects/ranking shorts/`: renderers (`build_infographic.py`,
  `build_flow_infographic.py`, `generate_ai_image.py`) + email (`build_email_mime.py`,
  `send_gmail_email.py`, with the Gmail OAuth in `gmail/`).
