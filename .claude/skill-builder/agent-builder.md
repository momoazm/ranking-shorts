---
name: agent-builder
description: Use when creating, optimizing, or auditing a Claude Code subagent (.claude/agents/) in this project. For inline skills, see .claude/skill-builder/skill-builder.md.
---

## What This Covers

Creating and optimizing Claude Code **subagents** — self-contained workers that run in **their own
context window** (isolated from the main conversation), built when a job's noise (search results,
render logs, git output) shouldn't flood the main thread.

For a step that runs inline in the current conversation, see
`.claude/skill-builder/skill-builder.md` instead.

Official ref: https://code.claude.com/docs/en/sub-agents

---

## Skill vs Subagent — quick check

| | **Subagent** | **Inline skill** |
|---|---|---|
| Runs in | its **own context window** (isolated) | the **current flow** (shares its context) |
| Returns | a summary back to the main thread | continues the flow |
| Best for | a **self-contained job** whose noise should stay off the main thread | a **step inside/at the end of an automation** |
| Invoked by | natural language, `@agent-name`, `--agent` flag — **never** a bare `/name` | `/name`, or Claude auto-loads it |
| Model | **declare an explicit `model`** — own task-suited model (saves tokens) | inherits the conversation's model (no-op `model` field) |
| Lives in | `.claude/agents/<name>.md` | `.claude/skills/<name>/SKILL.md` |

**Required:** YAML frontmatter with **`name`** and **`description`** (the only required fields).
The subagent `description` is what Claude matches against when deciding whether to delegate via
natural language — write it as *when to use it*. **Keep it short** (1–2 sentences) — skip
`<example>` blocks and long prose; a few concrete trigger keywords beat a paragraph.

---

## Important: subagents have no native slash command

Typing `/name` **only ever works for skills**. A file in `.claude/agents/` is invoked exclusively by:
- **Natural language** — "use the X subagent to …" — Claude decides based on the subagent's `description`
- **`@agent-<name>` mention** — guarantees that specific subagent runs
- **`--agent <name>` CLI flag / `agent` setting** — runs the *whole session* as that subagent

There is no frontmatter field or config that adds a bare `/name` trigger to an agent file. **This
is the default and stays the default** — most subagents in this project should remain
natural-language/`@agent-name`-only. Only add a slash trigger for the specific agent(s) where you
deliberately want one (e.g. `update`, see Current Capabilities).

### Make a subagent slash-invocable (opt-in, per agent — not the default)

Build a thin paired skill at `.claude/skills/<name>/SKILL.md` **only for the specific subagent(s)
where you want `/name` to work**:

```yaml
---
name: <name>
description: <small, keyword-rich — this is always loaded into context, every turn>
context: fork
agent: <name>     # the custom subagent file — its body becomes the system prompt
---

Run the <name> subagent's workflow now: <one-line restatement of the task>.
```

`/<name>` then hands this body to the named subagent as its task; the subagent's own markdown
file still supplies the system prompt, tool restrictions, and model. Both `description` fields
should stay **short** (1 sentence each) — the subagent's drives natural-language auto-delegation,
the skill wrapper's drives the always-loaded skill listing (it costs context every turn).

This is the only mechanism that makes a subagent typeable as `/name` — there's no shortcut that
skips building the wrapper skill.

---

## Mode 1: Build

Run the **Discovery Interview** first — don't write files until it's done.

### Discovery Interview

Ask with AskUserQuestion, **one round at a time**, until 95% confident. Skip rounds already answered.

1. **Goal & Name** — what it does; what to call it (lowercase-hyphens, ≤64 chars).
2. **Process** — exact steps trigger→output; per step, does it act directly, run a script, or
   delegate further? This also fixes the **model** — pick the lightest tier that fits the work
   (see Model routing below).
3. **Inputs / Outputs / Dependencies** — inputs needed; what it produces and where (default
   `.tmp/`); APIs/scripts and which fallback chain; reference files/templates/brand assets.
4. **Guardrails & Edge cases** — failure modes; hard boundaries; cost concerns; ordering; any
   irreversible step (needs a gate).
5. **Confirm** — summarize back, then build only on approval:
   ```
   Goal: … · When to use: … · Model: …
   Process: 1… 2… · Inputs/Outputs(+where)/Dependencies · Guardrails(+irreversible gate)
   ```

### Build the subagent

Create `.claude/agents/<name>.md`. Frontmatter: `name`, `description` (required — **short**, 1–2
sentences, no `<example>` blocks), **`model`** (required — always set one explicitly, see Model
routing); optional `tools` (least privilege — read-only agents get no `Edit`/`Write`), `color`,
`memory: project` (for cross-session learnings specific to this project). The **body is the
agent's entire system prompt** — it does NOT receive CLAUDE.md content the way the main
conversation does in the same depth, so make it self-contained (role, steps, fallback order,
branding, gate). **One job per subagent.**

### Build its slash wrapper (only if you specifically want one)

The default is **no slash command** — most subagents stay natural-language/`@agent-name`-only.
Only create the paired `.claude/skills/<name>/SKILL.md` per the pattern above when you (or the
user) explicitly decide this particular subagent should also be typeable as `/name`.

### Test

Natural-language trigger ("use the X subagent to…") · `@agent-<name>` mention · `/name` (via the
wrapper skill, confirm it actually forks rather than running inline) · edge cases (missing/empty
input, irreversible-step gate holds).

---

## Mode 2: Audit

Read the file first; fix issues before finishing.

- **Frontmatter:** `name` correct; `description` is **short** (1–2 sentences, real trigger
  keywords, no `<example>` blocks or long prose); **`model` is present and explicit** — never left
  unset/inherited — and is the lightest tier that works; `tools` restricted to least privilege; no
  unused fields.
- **Slash-invocability:** a subagent has **no** slash command by default — that's correct, not a
  bug. Only flag a missing wrapper if the user specifically asked for `/name` on this one. If a
  wrapper exists, check its `description` is short (it's always-loaded).
- **Content:** body is self-contained (doesn't assume CLAUDE.md context reached it); fallback
  chains correct; irreversible-action gate present if relevant; never hardcodes/prints secrets.
- **Integration:** in the CLAUDE.md index; single responsibility; doesn't duplicate info living
  elsewhere; predictable output paths.

---

## Project Conventions

Apply to every subagent (don't restate these in each file — they live here):

- **Model routing (token-saving) — every subagent declares an explicit `model`:** `haiku` =
  mechanical (run a tool, look up, format); `sonnet` = reasoning/creative (research, analysis,
  copywriting, design judgment); `opus` = rarely (only genuinely hard multi-step reasoning). Pick
  the lightest tier that does the job — never leave a subagent's `model` unset/inherited.
- **API.env fallback chains** — best provider first, next on rate-limit/error, surface only
  whole-chain failures; never print/commit secrets:
  - search Firecrawl→Tavily→Exa · extract Tavily→trafilatura(+Groq)
  - LLM Groq→Cerebras→OpenRouter(`:free`)→Mistral→Gemini
  - image Cloudflare→HF→Pollinations→Gemini · TTS Fish Audio→Edge-TTS
- **Confirm before anything irreversible/public** (sends, uploads, deploys, deletes) via a gate in
  the body — not by disabling invocation.
- **Branding** from the root `brand/` is not optional.
- **Document** each new subagent in the CLAUDE.md index.

## Current Capabilities
- **Subagents:** `update` (`sonnet`, `memory: project`) — runs the `competitor-analysis` project's
  combined Instagram-benchmarking + YouTube-channel-comparison workflow (the actual steps live in
  `projects/competitor-analysis/workflows/competitor_analysis.md`, not in the agent body);
  `researcher` (`sonnet`) — isolated web research on the search/extract fallback chains,
  returns a compact cited brief; `runner` (`haiku`) — runs a project's deterministic tools
  (venv python, one-JSON-object contract) and returns only the parsed result + errors, with a
  hard block on irreversible/public scripts. None have slash wrappers — invoke via natural
  language or `@agent-<name>`.

## Important Notes
- Always **read** an existing subagent before editing it.
- Before building, check whether a similar one exists to extend instead.
- Restart the session after hand-editing a file in `.claude/agents/` directly on disk — subagents
  load at session start (unlike skills, which live-reload).
