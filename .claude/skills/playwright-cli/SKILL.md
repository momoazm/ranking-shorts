---
name: playwright-cli
description: Use when a task needs a real browser driven by Playwright — scrape a page's data, fill/click/submit a form, log in once and reuse a saved session, screenshot/verify a rendered site, or turn any of that into a reusable WAT tool. Runs INLINE. Public/irreversible browser actions (logins that post, submits, uploads) are gated.
argument-hint: <the browser task, e.g. "scrape all product titles from URL" or "screenshot the run section of the local site">
---

# Playwright CLI — browser automation (inline)

Drive a real Chromium browser to do what has no clean API: read a JS-rendered page, act on a
logged-in account, or verify what a site actually looks like. This skill is the **actionable layer**
over the shared install — the token-frugal rules and common commands live in
[references/sops/playwright-cli.md](../../../references/sops/playwright-cli.md); the canonical
worked examples live in `projects/follower-race/tools/` (see Reference implementations below).
`$ARGUMENTS` is the task.

## Decide the cheapest tool for the job (in order)
1. **Just a screenshot / PDF of a URL?** Use the CLI directly — no script:
   `playwright screenshot --viewport-size=1280,800 [--full-page] <url> out.png`. Save to the
   session scratchpad; only `Read` (render) the PNG when you actually need to *see* it.
2. **Read data or interact once?** Write a small **Python** script (the projects already depend on
   `playwright`) that does the steps and **prints exactly one JSON object** to stdout — never dump
   full page HTML into context. Run it from the relevant project's venv (`.venv/Scripts/python`).
3. **Worth keeping / re-running?** Land it as a deterministic **WAT tool** under that project's
   `tools/` (one JSON object out, `_common.py`'s `emit`/`fail`), not a throwaway script.

## Steps
1. **Restate the task + target** from `$ARGUMENTS`: URL(s), what to read or do, and what the caller
   needs back (data fields? a screenshot path? a pass/fail?).
2. **Session?** If it needs a logged-in account, **never store a password** — reuse a saved
   `storageState` JSON captured once interactively (the `ig_login.py` pattern), and load it with
   `browser.new_context(storage_state=...)`. If none exists, capture one headfully first and tell
   Moemen it's a one-time step. Logged-in / same-account work runs **locally** (home IP), not in CI.
3. **Write the script** (unless step-1 CLI covers it): `sync_playwright()` → launch (headless by
   default; `headless=False` only for interactive login/debug) → `goto(url, wait_until=...)` →
   robust waits (`wait_for_selector`, not blind sleeps) → do the work → emit **one JSON object**.
   Use broad, fallback selectors and expect obfuscated/drifting DOM (IG etc.); support a
   `--debug-dump` that saves HTML to `.tmp/` to tune selectors.
4. **Dry-run first for anything that acts.** Read/scrape/screenshot are safe to just run. For
   fill/submit/login-that-posts/upload: print what *would* happen behind a `--dry-run`, and require
   an explicit `--confirm` for the live action.
5. **Gate public/irreversible actions** (posts, submits, uploads, sends): show the resolved
   target/account and the exact action, wait for Moemen's explicit "go" (per
   `.claude/rules/automation-practices.md`). Read-only actions need no gate.
6. **Run it, report small.** Print the JSON result (and screenshot *paths*); render a screenshot
   only when you need to verify it visually. Surface whole-chain failures clearly; don't retry-loop.

## Output
- **One JSON object** to stdout from any script/tool (the WAT contract): e.g.
  `{"status": "...", "url": "...", "items": [...], "screenshot": ".tmp/shot.png"}`.
- Screenshots/PDFs → files (scratchpad for throwaway checks, a project folder for deliverables).
- On failure: `{"error": "...", ...context}` and a clear next step (e.g. "re-run ig_login.py").

## Reference implementations (copy these patterns)
- **One-time session capture** → `projects/follower-race/tools/ig_login.py` (headful login →
  `storageState`; `--check` verifies it's still valid).
- **Logged-in scrape → JSON, with scroll + dedupe + safety guard** →
  `projects/follower-race/tools/sync_followers.py`.
- **Logged-in interact (reply) with `--dry-run`/`--confirm` gate + per-item dedupe** →
  `projects/follower-race/tools/reply_placements.py`.
- **Anonymous single-element scrape + asset download** → `projects/follower-race/tools/fetch_avatar.py`.
- **Serve + screenshot a local site to verify** → the `website-screenshot-flow` auto-memory.

## Notes
- **Token-frugal is the whole point** (why CLI over the MCP server): scripts print small, captures
  go to files, and reusable flows become tools. Don't render every screenshot or echo page HTML.
- **Headless vs headful:** headless for automation/CI; headful only for interactive login or
  selector debugging. The shared Chromium cache is `%LOCALAPPDATA%\ms-playwright` (no re-download).
- **Determinism / reliability:** prefer explicit waits and stable selectors; a flaky selector is a
  bug to fix (broaden it, add a fallback), not to paper over with longer sleeps.
- **Secrets:** never print or commit session files / tokens; add saved-session JSON to `.gitignore`
  (as `state/ig_session.json` is). Sessions expire — fail loudly and point to the re-login step.
