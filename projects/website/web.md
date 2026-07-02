# CLAUDE.md — Frontend Website Rules

## Skills (`skills/`)
- **`site-update`** (`skills/site-update/SKILL.md`) — the end-to-end flow for building or
  changing anything on the MOMO site (edit CS-deploy → verify → push) plus the site's
  architecture map. **Read it before touching any site file.**
- **`frontend-design`** (`skills/frontend design/SKILL.md`) — invoke before writing any frontend code, every session, no exceptions. Owns aesthetic direction, typography, color, motion, and the anti-generic guardrails — don't restate that guidance here, just follow it.
- **`video-to-website`** (`skills/video to website/SKILL.md`) — invoke instead when the input is a video file to turn into a scroll-driven animated site. It builds on `frontend-design` for styling.
- **`website-selftest`** (`skills/website-selftest/SKILL.md`) — backend health check (RAG
  round-trip + live `/api/*`); run it whenever `CS/webapp/` or the API surface changes.

## 21st.dev — REQUIRED on every website build/change
**Standing rule (Moemen): on every website build or change, use 21st.dev Magic — it is required,
not optional.** Reach for it for hero sections, navs, marquees, kinetic typography, scroll reveals,
bento/feature grids, testimonials, pricing, CTAs — then restyle to the project brand.
- **Magic MCP** (`@21st-dev/magic`) is the live integration — invoke it in chat with **`/ui`**
  (e.g. "/ui a kinetic-typography hero"), pick/generate a component, then **restyle it to the
  project brand** (pure black + MOMO gold `#E6B23A`, Cinzel display / Poppins body) — never ship
  its defaults unchanged.
- Config: **`.mcp.json`** at the repo root (gitignored — holds the key); the key is also in
  **`API.env`** as `MAGIC_21ST_API_KEY`. Never print or commit the key. MCP servers load at
  startup, so after wiring/changing `.mcp.json` you must **restart Claude Code** for `/ui` to appear.
- If the MCP is ever unavailable, still use 21st.dev as the visual reference and hand-build to its
  craft level — don't skip it.

## Reference Images
- If a reference image is provided: match layout, spacing, typography, and color exactly. Swap in placeholder content (images via `https://placehold.co/`, generic copy). Do not improve or add to the design.
- If no reference image: design from scratch with high craft (see `frontend-design` skill).
- Screenshot your output, compare against reference, fix mismatches, re-screenshot. Do at least 2 comparison rounds. Stop only when no visible differences remain or user says so.

## Local Server
- **Always serve on localhost** — never screenshot a `file:///` URL.
- This machine (monar): serve from the site folder with **`python -m http.server 3000 --bind 127.0.0.1`**
  (Node v24 is also present → `npx serve . -l 3000` works too). Run it in the background before screenshotting.
- If the server is already running, do not start a second instance.

## Screenshot Workflow
- Use **`screenshot.py`** (project root) — Playwright + Chromium, already installed for monar (no Node needed).
  `python screenshot.py http://localhost:3000 label` → saves desktop + mobile full-page PNGs to `temporary screenshots/`.
  (The old `nateh` Puppeteer / `screenshot.mjs` paths in the skill are from another machine — ignore them.)
- **Scroll-driven (canvas/GSAP) pages** can't be captured in one full-page shot — the canvas is `position:fixed`.
  Expose the Lenis instance (`window.lenis = lenis`) and drive it to fixed scroll fractions, shooting the
  *viewport* at each (see a project's `scratchpad shoot.py` for the pattern).
- After screenshotting, read the PNG from `temporary screenshots/` with the Read tool — Claude can see and analyze the image directly.
- When comparing, be specific: "heading is 32px but reference shows ~24px", "card gap is 16px but should be 24px"
- Check: spacing/padding, font size/weight/line-height, colors (exact hex), alignment, border-radius, shadows, image sizing
- **When the change is done, delete everything inside `temporary screenshots/`** — they're disposable working files.

## Output Defaults
- Single `index.html` file, all styles inline, unless user says otherwise
- Tailwind CSS via CDN: `<script src="https://cdn.tailwindcss.com"></script>`
- Placeholder images: `https://placehold.co/WIDTHxHEIGHT`
- Mobile-first responsive

## Brand Assets
- Always check the `brand_assets/` folder before designing. It may contain logos, color guides, style guides, or images.
- If assets exist there, use them. Do not use placeholders where real assets are available.
- If a logo is present, use it. If a color palette is defined, use those exact values — do not invent brand colors.

## Deploying
- **Always push website changes when the work is verified** (Moemen, 2026-07-02 — supersedes the
  old "stop and let me review" rule). Flow: build → serve + screenshot to self-verify → commit +
  push → tell Moemen what went live and where. Vercel deploys from the push automatically.
- The MOMO site deploys from the **`momoazm/CS`** repo — edit and push the clone at
  `C:\Users\monar\Downloads\CS-deploy` (NOT `projects/website/CS`, a stale fork).

## Hard Rules
- Do not add sections, features, or content not in the reference
- Do not "improve" a reference design — match it
- Do not stop after one screenshot pass
