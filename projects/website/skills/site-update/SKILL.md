---
name: site-update
description: Build or change anything on the MOMO website (momoazm/CS → Vercel) — new pages, redesigns, study tools, mascot work. Owns the end-to-end flow: edit the CS-deploy clone, serve + screenshot to verify, then commit + push (always). Read this before touching any site file.
---

# MOMO site update — end-to-end flow

The one workflow for making or changing the MOMO website. `web.md` (this folder) holds the
standing rules; this skill is the ordered checklist plus the site's architecture map so you
don't have to rediscover it.

## Where the site lives (get this right first)
- **Edit `C:\Users\monar\Downloads\CS-deploy`** — the real clone of `momoazm/CS`.
  `projects/website/CS` is a **stale fork — never edit it** for site work.
- Vercel deploys from every push to `main` (`vercel.json` → `outputDirectory: "website"`,
  static). All site files are in `CS-deploy/website/`.
- Local API serving: `CS/webapp/api.py` mounts the whole `website/` dir (html=True) after the
  `/api/*` routes, so multi-page + same-origin `/api` works at `localhost:8000`.

## The flow

1. **Rules + design first.** Read `projects/website/web.md`. Invoke the `frontend design`
   skill (or `video to website` if the input is a video) before writing any frontend code.
2. **21st.dev Magic is required** on every build/change (`/ui ...`, or use it as visual
   reference and hand-build to that craft level if the MCP is down). Restyle everything to
   brand — never ship defaults.
3. **Build in `CS-deploy/website/`**, following the architecture below. New pages copy an
   existing page's header/footer and set `data-page`.
4. **Verify: serve + screenshot, ≥2 rounds.**
   - Serve: `python -m http.server 3000 --bind 127.0.0.1` from `CS-deploy/website`
     (background). If port 3000 404s or misbehaves, **stale servers are squatting it** —
     `netstat -ano | findstr :3000`, kill the old pythons, restart.
   - Shoot: from `projects/website/`: `python screenshot.py http://localhost:3000/<page> <label>`
     (desktop + mobile PNGs → `temporary screenshots/`). Read the PNGs, fix, re-shoot.
     Screenshot study-hub tabs via hash URLs (`study.html#papers` etc.). A one-off
     `Page.screenshot: Timeout` is transient — just retry once before debugging.
   - If you touched `CS/webapp/` or `/api/*`, also run the **`website-selftest`** skill.
5. **Clean up:** delete everything in `temporary screenshots/` (use bash `rm -f`; PowerShell
   `Remove-Item` is blocked on that path). Stop the local server.
6. **Ship: commit + push CS-deploy.** Standing rule (Moemen, 2026-07-02): **always push
   website changes once verified** — don't stop and wait for review. Then tell Moemen what
   went live.
7. **Same turn:** ingest meaningful changes into the Momo brain (`/ingest`) and append any
   locked-in decision to `decisions/log.md`.

## Site architecture (as of 2026-07-02 redesign)

Five pages, shared assets, Gumball-only mascot:

- **Pages:** `index.html` (hero + today-snapshot + tool cards), `oracle.html` (RAG
  upload/ask — JS talks to `/api` with in-browser BM25 fallback), `study.html` (9618 study
  hub), `calendar.html` (`/api/gcal`), `pipelines.html` (`/api/runner`).
- **Shared assets (`website/assets/`):**
  - `site.css` — all shared styles: `.site-head`/`.site-nav` (active link = pure CSS via
    `body[data-page=X] a[data-nav=X]`), `.card`/`.card-2`, `.btn-*`, `.page-head`, mascot +
    hero animation, `prefers-reduced-motion` kill-all. Keep motion calm: fadeUp entrances and
    small hover lifts only — no spring/wiggle (that was the old "unprofessional" look).
  - `tw.js` — shared Tailwind CDN config (brand colors + Cinzel/Poppins/Space Mono). Include
    right after the Tailwind CDN script on every page.
  - `site.js` — `window.toast()`, Gumball pose system, `window.momoStudySnapshot()`.
  - `syllabus9618.js` — `SYLLABUS_9618` (AS units 1–12, A2 13–20) + `STARTER_DECK_9618`.
- **Gumball mascot (the only character):** add `data-mascot="<pose> <corner>"` to a card
  (poses: peek/wink/think/cheer; used sparingly — 1–2 per page). `window.gumballSVG(pose)`
  and `window.gumballCheer()` (celebration popup) live in `site.js`. Never reintroduce the
  other characters (Darwin/Anais/etc.).
- **Study hub localStorage keys** (all client-side, no backend):
  `momo.study.syllabus.v1`, `momo.study.decks.v1` (SM-2-lite scheduling),
  `momo.study.papers.v1`, `momo.study.pomo.v1`. The home page reads them via
  `momoStudySnapshot()` — keep zero-state defaults at `0`, not null/em-dash.

## Notes
- Brand: navy `#05090F` bg, panel `#0B1828`, gold `#D4AF37`/`#ECD27E`, ink `#F2E9D8` — load
  from `brand/`, never re-derive.
- Mobile: nav shrinks + hero Gumball hides ≤640px (`site.css` media queries) — check mobile
  PNGs every round, not just desktop.
- The always-push rule is site-specific. Emails, video uploads, and social posts still need
  an explicit go-ahead.

## Lessons learned
- _(2026-07-02)_ Multiple orphaned `http.server` processes can all bind 127.0.0.1:3000 on
  Windows and serve stale directories — a mystery 404 on a file you can see on disk means
  kill-and-restart, not "the file is missing."
