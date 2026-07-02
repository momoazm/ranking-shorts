# SOP: Playwright CLI (browser automation)

**What it is:** a shared, global install of the Playwright **CLI** (not the MCP server) for driving
a real Chromium browser — testing web apps, screenshots, PDFs, recording scripts, and general
browser automation. Chosen over the MCP server to stay **token-frugal**: the CLI costs nothing
until a command runs, and only returns what we choose to read back.

## Install (already done — reference only)
- CLI: `npm install -g playwright` → `playwright` command on PATH (global, shared by every project).
- Browser: `playwright install chromium` → Chromium in the shared cache
  `%LOCALAPPDATA%\ms-playwright` (reused across all projects and by a Python install too).
- Add `firefox` / `webkit` later only if a task needs cross-browser: `playwright install firefox`.
- Python flavor (optional, for WAT `tools/` scripts): `pip install playwright` — shares the same
  browser cache, no re-download.

## Token-frugal usage rules (the whole point of choosing CLI)
1. **Screenshots → files, render on demand.** Save to the session scratchpad for throwaway checks,
   or a project folder for deliverables. Only `Read` (render) the PNG when I actually need to *see*
   it — don't render every capture.
2. **Checks print small.** Prefer commands / scripts that emit an exit code or a short line of text
   over dumping full page HTML or an accessibility snapshot.
3. **Record once, replay cheaply.** `playwright codegen <url>` opens a live browser and writes the
   interactions to a script; run that script deterministically afterward at zero per-step token
   cost. (Also the best way to *learn* the API.) Note: `codegen` blocks on a human — run it
   yourself interactively, don't fire it as an automated step.
4. **Reusable automations = WAT tools.** Anything worth keeping lands as a deterministic script
   under a project's `tools/` (Node or Python), printing one JSON object to stdout like the other
   tools.

## Common commands
- Screenshot:   `playwright screenshot --viewport-size=1280,800 <url> out.png`
  (add `--full-page` for the whole scrollable page).
- PDF:          `playwright pdf <url> out.pdf`
- Record:       `playwright codegen <url>`   (interactive; emits a script)
- Version:      `playwright --version`
- Test runner:  `npx playwright test`  — needs `@playwright/test` installed **per-project**.

## Guardrails
- **Confirm before anything public / irreversible.** Logging into GitHub, submitting forms,
  posting, or uploading through the browser falls under `.claude/rules/automation-practices.md`:
  show exactly what will happen (target account, action) and wait for an explicit "go".
- Read-only actions (navigating, screenshotting public pages, local dev servers) are fine to just
  do and report.

## Related
- Can power the website serve+screenshot verification flow (see the `website-screenshot-flow`
  auto-memory) — the CLI is the engine; it can replace whatever currently captures those shots.
