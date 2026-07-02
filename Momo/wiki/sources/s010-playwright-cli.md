---
type: source
tags: [momo]
updated: 2026-07-01
---
# s010 — Playwright CLI installed (shared, token-frugal)
Installed [[playwright-cli]] globally + Chromium, workspace-wide. Decision →
[log.md](../../../decisions/log.md) (2026-07-01).

## Key points
- `npm install -g playwright` (v1.61.1) + `playwright install chromium` → shared cache
  `%LOCALAPPDATA%\ms-playwright`; verified with example.com screenshot.
- **CLI over MCP** = token-frugal: costs nothing until a command runs, returns only what we read.
- SOP with usage rules → [playwright-cli.md](../../../references/sops/playwright-cli.md).

## Relationships
- **introduces** [[playwright-cli]]
- **can power** [[website]] screenshot verification
