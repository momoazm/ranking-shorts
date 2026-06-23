# Building & Using Skills and Subagents

Reference for creating and invoking reusable capabilities. **Read this before building a new skill
or subagent.** Two kinds — pick by context, not by name:

| | **Inline skill** | **Subagent** |
|---|---|---|
| Runs in | the **current flow** (shares its context) | its **own context window** (isolated) |
| Returns | continues the flow | a summary back to the main thread |
| Best for | a **step inside/at the end of an automation** (e.g. email the report we just built) | a **self-contained job** whose noise (search results, render logs) should stay off the main thread |
| Model | inherits the flow's model | own **task-suited model** (saves tokens) |

**Required for both:** YAML frontmatter with a **`name`** and a **`description`** — the only required
fields. Write `description` as *when to use it* (this is what drives auto-delegation / the `/menu`).
Everything else (`model`, `tools`, `context`…) is optional.

## Inline skills
- **Create at:** `.claude/skills/<name>/SKILL.md` — put the **full instructions in the body**, and do
  **not** set `context: fork` (forking would isolate it). For `name`: optional (defaults to the
  folder name); set it for clarity.
- **Use by:** Moemen typing `/<name>`, or I run them as a step within a flow.
- All skills here are inline. Current: **`/send-email`**, **`/cross-post-video`** (both irreversible —
  stop at the confirmation gate and get an explicit "go").

## Subagents (best practice)
From the Claude Code subagents docs (code.claude.com/docs/en/sub-agents) + our conventions.

- **Create at:** `.claude/agents/<name>.md` (project scope — version-controlled, shareable) or
  `~/.claude/agents/<name>.md` for ones meant to work across all projects.
- **Use by:** I **delegate automatically** when a task matches the agent's `description`, or it's
  launched via the Agent tool.
- **Frontmatter:**
  - `name` — lowercase-with-hyphens, unique across the tree.
  - `description` — *when to delegate*; specific and action-oriented. Add "Use proactively…" /
    "MUST BE USED for…" when it should fire automatically.
  - `model` — the **lightest model that does the job well** (token-saving is a standing goal):
    `haiku` for mechanical work (run a tool, look up, format), `sonnet` for reasoning/creative,
    `opus` only when genuinely needed. Defaults to `inherit` if omitted.
  - `tools` — limit to only what's needed (omitting inherits all). Read-only agents get no
    `Edit`/`Write`. Prefer least privilege.
  - Optional when useful: `color` (UI id), `memory: project` (cross-session learning),
    `disallowedTools`, `permissionMode`.
- **Body = the agent's entire system prompt** — subagents do **not** receive CLAUDE.md or the main
  prompt. Make it **self-contained**: role, steps, provider/fallback order, branding, and the
  confirm-before-irreversible gate where relevant. **One job per subagent.**

## Standing defaults (both kinds)
- Echo the relevant `API.env` fallback chain (best provider → next on limit/error). Never print or
  commit secret values.
- **Confirm before anything irreversible or public** (email sends, uploads, deploys, deletes).
- Branding from the root `brand/` is not optional.

## When to make which
As a request starts repeating: an **inline skill** if it's a step in a flow, a **subagent** if it's
a self-contained job. `/agents` → "Generate with Claude" can scaffold a subagent draft — still apply
the above.

## Current capabilities
- **Inline skills:** `send-email`, `cross-post-video`.
- **Subagents:** `research`, `extract-article`, `generate-image` (haiku); `trend-research`,
  `generate-video`, `video-virality-pass` (sonnet).
