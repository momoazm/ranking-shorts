# Subagent Authoring (best practice)

When building a new subagent for Moemen, follow these — from the Claude Code subagents docs
(code.claude.com/docs/en/sub-agents) plus our conventions. New subagents go in `.claude/agents/`.

## Location & format
- Save to **`.claude/agents/<name>.md`** (project scope — version-controlled and shareable). Use
  `~/.claude/agents/` only for ones meant to work across all projects.
- Markdown file = **YAML frontmatter + body**. Only `name` and `description` are required.

## Frontmatter
- **`name`** — lowercase-with-hyphens, unique across the tree.
- **`description`** — write it as *when to delegate to this agent*: specific and action-oriented.
  Add "Use proactively…" / "MUST BE USED for…" when it should fire automatically.
- **`model`** — set the **lightest model that does the job well** (token-saving is a standing goal):
  `haiku` for mechanical work (run a tool, look up, format), `sonnet` for reasoning/creative,
  `opus` only when genuinely needed. Defaults to `inherit` if omitted.
- **`tools`** — limit to only what the agent needs (omitting inherits all). Read-only agents get
  no `Edit`/`Write`. Prefer least privilege.
- Optional when useful: `color` (UI identification), `memory: project` (cross-session learning),
  `disallowedTools`, `permissionMode`.

## Body (the system prompt)
- The body is the agent's **entire** system prompt — subagents do **not** receive CLAUDE.md or the
  main prompt. Make it **self-contained**: role, the steps, provider/fallback order, branding, and
  the confirm-before-irreversible gate where relevant.
- **One job per subagent** (single responsibility). Keep it focused.

## Our standing defaults
- Echo the relevant `API.env` fallback chain (best provider → next on limit/error). Never print or
  commit secret values.
- **Confirm before anything irreversible or public** (email sends, uploads, deploys, deletes).
- Branding from the root `brand/` is not optional.

> Tip: `/agents` → "Generate with Claude" can scaffold a draft, but still apply the above.
