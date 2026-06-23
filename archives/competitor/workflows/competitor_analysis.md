# Competitor Analysis Automation

## Objective

On request ("compare me to my competitors" / "run a competitor analysis"), research how
**MOMO** (a short-form **video-clipping + AI-video** social-media business) stacks up against
the top creators/accounts in its niche, find the specific points where they are *better*, and
email MOMO a **branded PDF report** of concrete ways to improve and **exceed** them — only
after explicit human approval.

This automation is the competitive-research layer that feeds two planned follow-on automations:
one for **video clipping** skill and one for **AI-video creation**. So bias the analysis toward
actionable craft insight for those two skills, not generic business metrics.

## Required inputs

- `company_profile.json` (repo root of this project) — MOMO's baseline. **Read it first.**
  If it still contains `<...>` placeholders, interview the user to fill the real values
  (niche, platforms, handles, tools, cadence, metrics, named competitors, goals) before
  proceeding — the comparison is meaningless without it.
- `recipient` (optional) — defaults to `GMAIL_SENDER_EMAIL` (`moemenyasserazmy@gmail.com`).
- Any extra focus the user calls out this run (a specific platform, a specific rival, "focus
  on hooks", etc.).

## Branding (always apply — not optional)

Every report uses `brand/theme.json` (colors, fonts, logo, button/icon style). Don't re-derive
brand styling — load the theme file and pass it through (the render/chart/card tools already
read it). Logo cid is `logo` → `brand/logo.png`.

## Tool-call sequence

All tools run from this project directory (`competitor/`) so `_common.py` resolves `REPO_ROOT`,
`.env`, `brand/`, and `.tmp/`. Use the project venv: `.venv/Scripts/python tools/<name>.py ...`.
Every tool prints exactly one JSON object to stdout (success → exit 0; failure → `{"error":...}`
→ exit 1) — parse stdout either way.

1. **Load profile** — read `company_profile.json`. Resolve the niche, platforms, named
   competitors, current metrics, and stated goals. If placeholders remain, fill them with the
   user first.
2. **Discover competitors** — `python tools/tavily_search.py --query "<q>"` for the top
   creators/accounts in the niche on the relevant platforms, e.g.:
   - `"best <niche> clip accounts TikTok"`
   - `"top AI-video creators YouTube Shorts <niche>"`
   - `"fastest growing <niche> Reels 2026"`
   Falls back to Exa automatically on Tavily error/quota — note it in your summary if it
   happened. Merge the discovered accounts with `named_competitors` from the profile (dedup).
   Settle on a working set of ~3–6 competitors.
3. **Research each competitor** — `python tools/tavily_search.py` per creator (reach/followers,
   formats, posting cadence, viral hooks, clipping style, AI-video tools/techniques,
   engagement), then `python tools/extract_article.py --url "<url>"` on 1–3 strongest sources
   each (add `--clean-with-groq` if the raw text is long/noisy). Keep every URL you use — it
   becomes a citation in `sources`.
4. **Gap analysis** *(your own reasoning, no tool call — this is the core deliverable)* —
   compare each competitor to MOMO's profile, centered on the two skills MOMO cares about:
   - **Clipping**: hook in first 1–2s, pacing/cuts, captions/subtitles, retention edits,
     trend-jacking, thumbnail/cover, length.
   - **AI-video creation**: which tools they use, realism/consistency, prompt/format quality,
     originality, how they blend AI with real footage.
   - **Social mechanics**: posting cadence, cross-posting, reach, engagement rate, series/format
     consistency.
   For every dimension where a competitor leads, record: the **gap**, the **evidence/source**,
   and a **concrete way MOMO can match then exceed it**. Prefer specific, do-this-next advice.
5. **Plan the report** — draft `subject`, `preheader`, and sections. Suggested arc:
   - *Executive summary* — the 2–3 biggest opportunities.
   - *Who's winning in your niche* — the competitor set and why they win.
   - *Where they out-clip / out-AI you* — the gaps, grouped by the two skills.
   - *Action plan to exceed* — prioritized, concrete moves (what to change in clipping, which
     AI-video techniques/tools to adopt, cadence/format changes).
   - *Sources*.
   Decide visuals per section (don't force one into every section):
   - **chart** (`generate_chart.py`) when there's a real metric to compare — followers, avg
     views, posting cadence, or engagement — MOMO vs competitors (bar chart).
   - **stat card** (`generate_card_image.py --type stat`) for the single most striking gap or
     opportunity number.
6. **Generate visuals** to `.tmp/` with stable `cid` names that stay identical through render +
   PDF, e.g.:
   - `python tools/generate_chart.py --data '{"type":"bar","title":"Avg views per post","labels":["MOMO","Rival A","Rival B"],"values":[...],"ylabel":"Views"}' --out .tmp/chart1.png`
   - `python tools/generate_card_image.py --type stat --data '{"value":"3x","label":"more views on hook-first clips"}' --out .tmp/card1.png`
7. **Write content JSON + render** — write `.tmp/content.json`:
   ```json
   { "subject":"...", "preheader":"...",
     "sections":[ {"heading":"...","body":"...","image_cid":"chart1"|null,"cta":null} ],
     "sources":[ {"title":"...","url":"..."} ] }
   ```
   `image_cid` values must match the `cid`s from step 6. Then:
   `python tools/render_email_html.py --data .tmp/content.json --out .tmp/report.html`
8. **Generate the PDF** (the standing delivery format — the email body stays short, the report
   is the attached PDF):
   `python tools/generate_pdf.py --data .tmp/content.json --images '[{"cid":"logo","path":"brand/logo.png"},{"cid":"chart1","path":".tmp/chart1.png"},{"cid":"card1","path":".tmp/card1.png"}]' --out .tmp/competitor_report.pdf`
   (`generate_pdf.py` takes `--data` — the same content JSON — plus the `--images` list it uses
   to swap `cid:` refs for local `file://` paths; it is **not** `--html`.)
9. **Short email body** — write `.tmp/body.html`: greeting, one-line summary of the top
   opportunity, "your full competitive analysis is attached as a PDF", sign-off. This is the
   email body, not the rendered report HTML.
10. **Assemble MIME** —
    `python tools/build_email_mime.py --html .tmp/body.html --subject "MOMO Competitive Analysis — <date>" --to moemenyasserazmy@gmail.com --attachments '[{"path":".tmp/competitor_report.pdf","filename":"competitor_report.pdf"}]' --out .tmp/report.eml`
    (no `--images` — the short body has no inline visuals; those live in the PDF).
11. **Confirmation gate — never skip.** Show the user: subject, preheader, section summary, the
    visuals generated, the **resolved recipient address**, and the rendered HTML byte size from
    step 7 (warn if `render_email_html.py` reported `gmail_clip_warning: true`). Wait for an
    explicit go-ahead. If they want changes, loop back to step 4/5 — don't re-research unless
    the change requires it.
12. **Only after explicit confirmation:** `python tools/send_gmail_email.py --eml .tmp/report.eml`
    then report the result (status, message/thread ID).

## Edge cases

- **Thin/no research** for an obscure niche → Tavily already falls back to Exa; if still thin,
  tell the user sourcing is weak (social-media stats are often gated/estimated) and ask before
  proceeding. Be honest in the report about which numbers are estimates vs. cited.
- **Whole fallback-chain failure** (not just a free-cap hit) on search/extract/image → surface
  it to the user before retrying anything metered; don't loop silently on a paid API.
- **Fallback chains** (ordered best-first; a provider that errors or hits its rate limit is
  skipped for the next): text cleanup = Groq → Cerebras → Gemini → Mistral → OpenRouter → raw;
  AI images = Cloudflare → Hugging Face → Gemini → Pollinations (keyless). Any provider whose
  key is unset is skipped. (This report normally uses only local charts/cards, so the image
  chain is rarely invoked.)
- **Chart/card/PDF generation failures** (Playwright browser missing, bad data shape) →
  free/local, safe to debug and retry. `.venv/Scripts/python -m playwright install chromium`
  if the Chromium binary is missing.
- **OAuth token expiry** → `send_gmail_email.py` refreshes silently first; if that fails
  (revoked), re-run `python tools/gmail_auth_setup.py`.
- **Recipient safety** → always echo the resolved "to" address at the confirmation gate; never
  send to an unconfirmed recipient.
- **Don't fabricate metrics.** If you can't source a competitor's real follower/view numbers,
  say so and compare qualitatively (formats, hooks, technique) rather than inventing values for
  a chart.

## Lessons learned (update this section as you go)

- **Run 2026-06-18 — AI cinematic/storytelling Shorts (@Moemen-i2f6l).** YouTube channel pages
  are JS-rendered: WebFetch + Tavily both return only the footer, so you can't scrape a target's
  own subs/views/cadence. Treat MOMO's own metrics as `unknown` and compare qualitatively — don't
  fabricate a numbers chart; instead chart the *competitors'* cited subs as "the bar to clear."
- **Discovery queries that work for this niche:** generic "top AI X creators" returns tool
  listicles, not creators. What surfaced real named channels: the OpenArt "7 types of AI videos"
  blog (named Chloe VS History, Tao Prompts, Curious Refuge, etc.) and per-creator searches once
  you have names. Reddit threads (r/aitubers) name channels but extract fails with 403 (blocked) —
  rely on the search snippet instead.
- **Real cited benchmarks captured:** Chloe VS History 292K subs/40 videos (creator Jonathan
  Laramie, Majestic Studios = 14M views/90 days, no film background); Curious Refuge 266K; Tao
  Prompts 185K. Tools competitors actually use: Midjourney omni-ref → LoRA (fal.ai) → Kling/Runway
  for consistency; Tao's 4-part prompt formula [Camera Movement]+[Scene]+[Action]+[Details].
- **Profile gap:** `company_profile.json` arrived all-placeholder; interview (niche/platforms/
  tools/competitor-strategy) took one AskUserQuestion batch. User's stated tool was just "Opus"
  (ambiguous — OpusClip vs. prompting model); recorded verbatim with a note.
