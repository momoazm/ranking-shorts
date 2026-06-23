---
name: skills-and-agents
description: Use when creating, optimizing, or auditing a skill OR a subagent in this project. Guides capability development following Claude Code best practices plus this project's conventions.
---

## What This Covers

Creating and optimizing Claude Code **skills** and **subagents**. Use when building a new one,
optimizing/auditing an existing one, deciding inline-skill vs subagent, or troubleshooting one.

Official refs: skills → https://code.claude.com/docs/en/skills ·
subagents → https://code.claude.com/docs/en/sub-agents

---

## First Decision: Inline Skill vs Subagent

**Pick by context, not by name.**

| | **Inline skill** | **Subagent** |
|---|---|---|
| Runs in | the **current flow** (shares its context) | its **own context window** (isolated) |
| Returns | continues the flow | a summary back to the main thread |
| Best for | a **step inside/at the end of an automation** (e.g. email the report we just built) | a **self-contained job** whose noise (search results, render logs) should stay off the main thread |
| Model | inherits the flow's model | own **task-suited model** (saves tokens) |
| Lives in | `.claude/skills/<name>/SKILL.md` | `.claude/agents/<name>.md` |

**Required for either:** YAML frontmatter with a **`name`** and a **`description`** (the only required
fields). Write `description` as *when to use it* — that's what drives selection and auto-delegation.

**Project rules:**
- **All skills are inline** — never `context: fork`. A self-contained/heavy task → build a subagent.
- **Select by `name` + `description` only**; read a capability's full body **only after choosing it**.
- Descriptions are always loaded so Claude knows what's available; full bodies load only on use.

---

## Mode 1: Build

Run the **Discovery Interview** first — don't write files until it's done.

### Discovery Interview

Ask with AskUserQuestion, **one round at a time**, until 95% confident. Skip rounds already answered.

1. **Goal & Name** — what it does; what to call it (lowercase-hyphens, ≤64 chars).
2. **Inline skill or subagent?** — step-in-a-flow (skill) vs self-contained job (subagent). For a
   skill: user-only / auto-invocable / both; does it take arguments?
3. **Process** — exact steps trigger→output; per step, does Claude act directly, run a script, or delegate?
4. **Inputs / Outputs / Dependencies** — inputs needed; what it produces and where (default `.tmp/`);
   APIs/scripts and which fallback chain; reference files/templates/brand assets.
5. **Guardrails & Edge cases** — failure modes; hard boundaries; cost concerns; ordering; any
   irreversible step (needs a gate).
6. **Confirm** — summarize back, then build only on approval:
   ```
   Type: inline skill | subagent · Goal: … · When to use: … · Args: …
   Process: 1… 2… · Inputs/Outputs(+where)/Dependencies · Guardrails(+irreversible gate) · Model: …
   ```

### Build an inline skill
Create `.claude/skills/<name>/SKILL.md` with the **full instructions in the body**. Frontmatter:
`name` (matches the folder), `description`; optional `argument-hint` (args), `model`, `allowed-tools`.
Body = Context → numbered steps → output format (templates, paths) → Notes. Use `$ARGUMENTS`/`$N` for
input; keep under ~500 lines.

### Build a subagent
Create `.claude/agents/<name>.md`. Frontmatter: `name`, `description`; optional `model` (see model
routing in Conventions), `tools` (least privilege — read-only agents get no `Edit`/`Write`), `color`,
`memory: project`. The **body is the agent's entire system prompt** — it does NOT receive CLAUDE.md,
so make it self-contained (role, steps, fallback order, branding, gate). **One job per subagent.**

### Test
Natural-language trigger (revise `description` keywords if it doesn't fire) · direct `/name` with
args (check `$ARGUMENTS` substitute + output paths) · edge cases (missing/empty input).

---

## Mode 2: Audit

Read the file first; fix issues before finishing.

- **Frontmatter:** `name` correct; `description` has real trigger keywords, specific yet not
  false-firing; `argument-hint` if a skill takes args; `model` is the lightest that works;
  tools restricted (least privilege); skills have **no `context: fork`**; no unused fields.
- **Content:** under ~500 lines; numbered workflow; output format + all paths specified;
  `$ARGUMENTS`/`$N` where it takes input; subagent body self-contained; Notes cover edge cases +
  irreversible gate; uses the right fallback chain, never hardcodes/prints secrets.
- **Integration:** in the CLAUDE.md index; single responsibility; delegates to a subagent when output
  would flood the main context; doesn't duplicate info living elsewhere; predictable output paths.

---

## Project Conventions

Apply to every capability (don't restate these in each file — they live here):

- **Model routing (token-saving):** `haiku` = mechanical (run a tool, look up, format),
  `sonnet` = reasoning/creative, `opus` = rarely.
- **API.env fallback chains** — best provider first, next on rate-limit/error, surface only
  whole-chain failures; never print/commit secrets:
  - search Firecrawl→Tavily→Exa · extract Tavily→trafilatura(+Groq)
  - LLM Groq→Cerebras→OpenRouter(`:free`)→Mistral→Gemini
  - image Cloudflare→HF→Pollinations→Gemini · TTS Fish Audio→Edge-TTS
- **Confirm before anything irreversible/public** (sends, uploads, deploys, deletes) via a gate in
  the body — not by disabling invocation.
- **Branding** from the root `brand/` is not optional.
- **Document** each new capability in the CLAUDE.md index.

## Current Capabilities
- **Inline skills:** `send-email`, `cross-post-video` (irreversible — gate first); `infographics`
  (branded infographic from a video's key points, via AI image).
- **Subagents:** `research`, `extract-article`, `generate-image` (haiku); `trend-research`,
  `generate-video`, `video-virality-pass` (sonnet).

## Important Notes
- Always **read** an existing capability before editing it.
- Before building, check whether a similar one exists to extend instead.
