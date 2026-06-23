# Newsletter Automation

## Objective

On request ("make me a newsletter about X"), research the topic, write the copy,
render it into a branded, email-safe HTML newsletter with a mix of embedded
infographics, get explicit human approval, then send it via Gmail.

## Required inputs

- `topic` — free text, from the user.
- `recipient` (optional) — defaults to `GMAIL_SENDER_EMAIL` (send to self) if not given.
- `tone`/`audience` hint (optional).

## Branding (always apply — not optional)

Every issue must use `brand/theme.json` (colors, fonts, logo, button/icon style),
sampled from `brand/logo.png` and `brand/brandguidelines.png`. Don't re-derive
brand styling per issue — load the theme file and pass it through.

## Tool-call sequence

1. `python tools/tavily_search.py --query "<topic>"` — review results. Falls back to
   Exa automatically on Tavily error/quota; note in your summary to the user if that happened.
2. `python tools/extract_article.py --url "<url>"` on 1–3 promising sources for fuller
   detail/data. Add `--clean-with-groq` if the raw extracted text looks long/noisy.
3. *(Your own reasoning, no tool call)* — draft `subject`, `preheader`, and per-section
   `heading`/`body` copy. For each section decide:
   - a **chart** if the research surfaced real numeric data (`generate_chart.py`),
   - a **stat/quote card** for a single striking number or quote (`generate_card_image.py`),
   - or — sparingly, at most once or twice per issue — an **AI illustrative image**
     (`generate_ai_image.py`).
   Most sections need no image at all; don't force one into every section.
4. Generate each planned visual, e.g.:
   - `python tools/generate_chart.py --data '{"type":"bar",...}' --out .tmp/chart1.png`
   - `python tools/generate_card_image.py --type stat --data '{"value":"42%","label":"..."}' --out .tmp/card1.png`
   - `python tools/generate_ai_image.py --prompt "..." --out .tmp/art1.png`
   Keep track of each image's chosen `cid` name (e.g. `chart1`, `card1`, `art1`) — it must
   match between this step, the render step, and the MIME-build step.
5. Write the content JSON (subject/preheader/sections with matching `image_cid`s/sources)
   to a file, then: `python tools/render_email_html.py --data <content.json> --out .tmp/newsletter.html`
6. Convert that rendered HTML into a PDF — the standing delivery format for every send
   (user preference, confirmed 2026-06-17): the email itself stays short, the branded
   newsletter only exists as an attached PDF.
   `python tools/generate_pdf.py --html .tmp/newsletter.html --images '[{"cid":"logo","path":"brand/logo.png"}, {"cid":"chart1","path":".tmp/chart1.png"}, ...]' --out .tmp/newsletter.pdf`
   (pass the same `images` list used for cid resolution — the tool swaps `cid:` refs for
   local `file://` paths since a standalone PDF has no MIME container to resolve them).
7. Write a short plain HTML body to `.tmp/body.html` (greeting, the issue's subject, "the
   newsletter is attached as a PDF", sign-off) — this is the email body, not the rendered
   newsletter HTML from step 5.
8. `python tools/build_email_mime.py --html .tmp/body.html --subject "..." --to <recipient> --attachments '[{"path":".tmp/newsletter.pdf","filename":"newsletter.pdf"}]' --out .tmp/newsletter.eml`
   (no `--images` needed here — the short body has no inline visuals; those live in the PDF).
9. **Confirmation gate — never skip this.** Show the user: subject, preheader, section
   summary, image list, resolved recipient address, and the rendered HTML byte size from
   step 5 (warn if `render_email_html.py` reported `gmail_clip_warning: true` — that
   threshold governs the PDF's source rendering, not the short email body). Wait for
   explicit go-ahead before sending. If they want changes, loop back to step 3 — don't
   re-research unless the changes require it.
10. Only after explicit confirmation: `python tools/send_gmail_email.py --eml .tmp/newsletter.eml`
11. Report the result back: confirmation of send, message/thread ID.

## Edge cases

- **Thin/no Tavily results** for obscure or very recent topics → the tool already falls
  back to Exa; if still thin, tell the user sourcing is weak and ask before proceeding.
- **AI image provider failures** (Cloudflare's 10,000 free-neurons/day cap hit, HF's thin
  credit exhausted, etc.) → `generate_ai_image.py` already falls through Cloudflare
  Workers AI → Hugging Face → Pollinations automatically. Only skip the image entirely if
  all three fail — surface that clearly, don't silently ship a newsletter with a missing
  visual. (Freepik/Magnific was removed from this chain — its "free" offering turned out
  to be a one-time signup credit, not a recurring tier; Gemini/Imagen was never added —
  confirmed paid-only, no free tier.)
- **Chart/card generation failures** (Playwright browser not installed, bad data shape) →
  free/local, safe to debug and retry directly. `playwright install chromium` if the
  browser binary is missing.
- **HTML body near/over ~100KB** (`gmail_clip_warning: true`) → trim a section or drop an
  image before sending; inline image bytes are separate MIME parts and don't count toward
  this clipping threshold, but do count toward Gmail's ~25MB total send ceiling. Since the
  rendered HTML is now only the PDF's source (not the email body itself), this mainly
  matters as a signal the PDF is getting bloated, not a Gmail-clipping risk anymore.
- **PDF generation failures** (`generate_pdf.py`) → same Playwright/Chromium dependency as
  the chart/card tools; `playwright install chromium` if the browser binary is missing.
- **OAuth token expiry** → `send_gmail_email.py` refreshes silently first; if that fails
  (e.g. revoked), re-run `python tools/gmail_auth_setup.py`.
- **Recipient safety** → always echo the resolved "to" address at the confirmation gate;
  never send to an unconfirmed recipient.
- **Cost awareness** — Tavily/Exa and Cloudflare/Hugging Face all have real recurring free
  tiers used as primary/fallback, so this pipeline should rarely hit a paid call. If an
  entire fallback chain fails outright (not just hits its free cap), surface it and check
  with the user before retrying — don't loop silently on a metered API.

## Lessons learned (update this section as you go)

- Hugging Face's exact free-tier rate limits aren't publicly published — note the real
  numbers here once observed in practice.
- `_common.py`'s `emit()` used to crash on Windows (cp1252 console codepage) whenever
  scraped article text contained curly quotes, em-dashes, or emoji. Fixed to fall back to
  ASCII-escaped JSON on `UnicodeEncodeError` instead of throwing — affects every tool that
  prints JSON, not just the search/extract ones that originally surfaced it.
- `generate_pdf.py`'s local images (including the logo) silently failed to render at
  first: Chromium refuses to load `file://` image sources from a page loaded via
  `page.set_content()` (opaque/about:blank origin) — fixed by writing the resolved HTML to
  a temp file and loading it with `page.goto('file://...')` instead (same-origin). Also
  switched to `Path.as_uri()` for the cid->file substitution since this repo's folder path
  has a space in it ("claude code"), which breaks unescaped `file://` URLs outright.
- *(add more as they come up)*
