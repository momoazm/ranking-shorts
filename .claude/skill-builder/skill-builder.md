---
name: skill-builder
description: Use when creating, optimizing, or auditing a Claude Code inline skill (.claude/skills/) in this project. For subagents, see .claude/skill-builder/agent-builder.md.
---

## What This Covers

Creating and optimizing Claude Code **inline skills** — a step that runs in the **current
conversation** (shares its context), invoked with `/name` or auto-detected from `description`.

For a self-contained background worker with its **own** context window, see
`.claude/skill-builder/agent-builder.md` instead.

Deep reference (frontmatter fields, advanced patterns, argument passing, troubleshooting):
`.claude/skill-builder/reference.md`.

Official ref: https://code.claude.com/docs/en/skills

---

## Skill vs Subagent — quick check

| | **Inline skill** | **Subagent** |
|---|---|---|
| Runs in | the **current flow** (shares its context) | its **own context window** (isolated) |
| Invoked by | `/name`, or Claude auto-loads it | natural language, `@agent-name`, or `--agent` — **never** a bare `/name` |
| Lives in | `.claude/skills/<name>/SKILL.md` | `.claude/agents/<name>.md` |
| Model | runs inline, inherits the conversation's model (`model` field is a no-op unless `context: fork`) | declares its own `model` explicitly |

Full decision guidance lives in `agent-builder.md` (it owns the "which one do I build" call,
since most new capabilities here start as a Build/Audit pass on a subagent).

**A skill can also be the slash-command front door for a subagent.** Set `context: fork` and
`agent: <custom-subagent-name>` in the skill's frontmatter — `/name` then hands the skill body to
that subagent as its task, while the subagent's own markdown body still supplies the system
prompt, tools, and model. This is the **only** way a subagent becomes typeable as `/name`. See
`agent-builder.md` → "Make a subagent slash-invocable."

**Required:** YAML frontmatter with **`name`** and **`description`** (the only required fields).
Write `description` as *when to use it* — that's what drives selection and auto-invocation, and
it's always loaded into context, so keep it concise.

**Project rules:**
- **All skills here are plain inline** (no `context: fork`) unless they're a subagent's slash
  wrapper. A self-contained/heavy task → build a subagent (see `agent-builder.md`), not a skill.
- **Select by `name` + `description` only**; read a skill's full body **only after choosing it**.
- Descriptions are always loaded so Claude knows what's available; full bodies load only on use.

---

## Mode 1: Build

Run the **Discovery Interview** first — don't write files until it's done.

### Discovery Interview

Ask with AskUserQuestion, **one round at a time**, until 95% confident. Skip rounds already answered.

1. **Goal & Name** — what it does; what to call it (lowercase-hyphens, ≤64 chars).
2. **User-only / auto-invocable / both?** — does it take arguments?
3. **Process** — exact steps trigger→output; per step, does Claude act directly, run a script, or
   delegate to a subagent (Agent tool)?
4. **Inputs / Outputs / Dependencies** — inputs needed; what it produces and where (default
   `.tmp/`); APIs/scripts and which fallback chain; reference files/templates/brand assets.
5. **Guardrails & Edge cases** — failure modes; hard boundaries; cost concerns; ordering; any
   irreversible step (needs a gate).
6. **Confirm** — summarize back, then build only on approval:
   ```
   Goal: … · When to use: … · Args: …
   Process: 1… 2… · Inputs/Outputs(+where)/Dependencies · Guardrails(+irreversible gate)
   ```

### Build

Create `.claude/skills/<name>/SKILL.md` with the **full instructions in the body**. Frontmatter:
`name` (matches the folder), `description`; optional `argument-hint` (args), `allowed-tools`.
**No `model` field** — skills run inline in the current conversation, so they always use whatever
model the conversation is already on; `model` only takes effect with `context: fork`.

Body = Context → numbered steps → output format (templates, paths) → Notes. Use `$ARGUMENTS`/`$N`
for input; keep under ~500 lines.

### Test

Natural-language trigger (revise `description` keywords if it doesn't fire) · direct `/name` with
args (check `$ARGUMENTS` substitute + output paths) · edge cases (missing/empty input).

---

## Mode 2: Audit

Read the file first; fix issues before finishing.

- **Frontmatter:** `name` correct; `description` has real trigger keywords, specific yet not
  false-firing, and is **short** (it's always loaded into every conversation's context);
  `argument-hint` if it takes args; **no `model`** (no-op without `context: fork`) and no stray
  `context: fork` unless this skill is intentionally a subagent's slash wrapper; no unused fields.
- **Content:** under ~500 lines; numbered workflow; output format + all paths specified;
  `$ARGUMENTS`/`$N` where it takes input; Notes cover edge cases + irreversible gate; uses the
  right fallback chain, never hardcodes/prints secrets.
- **Integration:** in the CLAUDE.md index; single responsibility; delegates to a subagent (Agent
  tool, or `context: fork`) when output would flood the main context; doesn't duplicate info living
  elsewhere; predictable output paths.

---

## Project Conventions

Apply to every skill (don't restate these in each file — they live here):

- **API.env fallback chains** — best provider first, next on rate-limit/error, surface only
  whole-chain failures; never print/commit secrets:
  - search Firecrawl→Tavily→Exa · extract Tavily→trafilatura(+Groq)
  - LLM Groq→Cerebras→OpenRouter(`:free`)→Mistral→Gemini
  - image Cloudflare→HF→Pollinations→Gemini · TTS Fish Audio→Edge-TTS
- **Confirm before anything irreversible/public** (sends, uploads, deploys, deletes) via a gate in
  the body — not by disabling invocation.
- **Branding** from the root `brand/` is not optional.
- **Document** each new skill in the CLAUDE.md index.

## Current Capabilities
- **Inline skills:** `send-email` (irreversible Gmail send, gate first);
  `infographics` (branded infographic from a video's key points, HTML→PNG, emailed);
  `playwright-cli` (drive a real browser — scrape/interact/screenshot/session-reuse; public
  actions gated; leans on the Playwright SOP + follower-race tools as reference);
  `ingest` (run the Momo-brain Ingest op — sNNN source node, typed edges, index + log);
  `wrap` (session close-out — decision log, `/ingest`, README statuses, commit without push,
  session summary).
- **Subagent slash wrappers** (`context: fork`, opt-in — see agent-builder.md): none currently.
  `update` (the `competitor-analysis` subagent) has no wrapper — invoke via natural language or
  `@agent-update`.

## Important Notes
- Always **read** an existing skill before editing it.
- Before building, check whether a similar one exists to extend instead.
