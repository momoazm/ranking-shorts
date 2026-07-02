---
type: concept
tags: [momo]
updated: 2026-07-01
---
# Playwright CLI
Shared, global browser-automation CLI (Chromium) for testing web apps, screenshots/PDFs, and
driving/fixing repos. Chosen over the Playwright MCP server to save tokens. SOP →
[playwright-cli.md](../../../references/sops/playwright-cli.md)

Invocable as the **`/playwright-cli` inline skill** (`.claude/skills/playwright-cli/`) — the
action layer over the SOP: pick cheapest tool → save/reuse session → emit one JSON object → gate
public actions.

## Relationships
- **supersedes** the Playwright MCP option (token-frugal choice)
- **is part of** [[wat-framework]] (reusable automations land as deterministic `tools/`)
- **exposed as** the `/playwright-cli` inline skill
- **powers** [[follower-race]]'s local IG tools (login, follower-sync, comment-replies)
- **can power** [[website]] serve+screenshot verification
- **guarded by** confirm-before-irreversible rule (browser logins/posts)
- **see** [[s010-playwright-cli]] · [[s013-follower-race-instagram-playwright]]
