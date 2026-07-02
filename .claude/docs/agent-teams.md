# Agent Teams — Reference Guide

Source: https://code.claude.com/docs/en/agent-teams (Claude Code docs, as of v2.1.186).
Status in this repo: **enabled but never auto-used** — `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`
is set in `.claude/settings.local.json` (not committed), and root `CLAUDE.md` carries a standing
rule that teams are spawned **only on Moemen's explicit request**, never proposed or spawned
proactively for a task that merely looks parallelizable. Default is always a single session or a
subagent.

## What it is

Multiple independent Claude Code instances ("teammates") coordinate on one task. One session
is the **team lead** — it spawns teammates, assigns/synthesizes work, and is the only one you
were originally talking to. Teammates run in their own context window and can message each
other directly, not just report back to the lead.

## Agent teams vs. subagents — decision rule

| | Subagents (`Agent` tool) | Agent teams |
|---|---|---|
| Context | Own window, results return to caller | Own window, fully independent |
| Communication | Reports to the main agent only | Teammates message each other directly |
| Coordination | Main agent manages everything | Shared task list, teammates self-coordinate |
| Token cost | Lower (summarized back) | Higher (every teammate is a full session) |
| Best for | Focused task where only the result matters | Work needing discussion/debate between workers |

**Default to subagents.** Reach for an agent team only when the workers genuinely need to talk
to each other mid-task (debate, shared findings, cross-checking) — not just "this is big, split
it up." Sequential work, same-file edits, or tasks with heavy dependencies are worse with a team
(coordination overhead, no payoff) — use a single session or subagents instead.

**Strongest use cases (from docs):**
- Research/review where teammates investigate different angles then challenge each other
- New, independently-ownable modules/features (no shared files)
- Debugging via competing hypotheses, arguing to disprove each other (avoids anchoring on the
  first plausible theory)
- Cross-layer work (frontend/backend/tests) with a clean owner per layer

## How to start one

Plain language to the lead — no setup tool call needed (pre-v2.1.178 required `TeamCreate`;
that tool is gone now):

```
I'm designing a CLI tool that helps developers track TODO comments across their codebase.
Spawn three teammates to explore this from different angles: one on UX, one on technical
architecture, one playing devil's advocate.
```

Claude can also *propose* spawning a team itself when it judges the task fits — you still
approve before it proceeds either way.

To pin team size/model explicitly:

```
Spawn 4 teammates to refactor these modules in parallel. Use Sonnet for each teammate.
```

Teammates don't inherit the lead's `/model` by default — set "Default teammate model" in
`/config`, or pick "Default (leader's model)" to follow the lead. They do inherit the lead's
effort level.

## Reusable roles: point at a subagent definition

Reference any existing subagent (project/user/plugin/CLI-defined) by name to reuse a role as
both a delegated subagent *and* a teammate:

```
Spawn a teammate using the security-reviewer agent type to audit the auth module.
```

The teammate honors that definition's `tools` allowlist and `model`; the definition's body is
*appended* to the teammate's system prompt (not a replacement). `SendMessage` and task tools are
always available regardless of the `tools` allowlist. Note: a subagent definition's `skills` and
`mcpServers` frontmatter fields are **ignored** when run as a teammate — teammates always load
skills/MCP servers from project + user settings, same as a normal session.

→ This repo's subagents (`update`, etc.) live under `.claude/agents/` per
`.claude/skill-builder/agent-builder.md` — any of them can be spawned as a teammate this way.

## Plan approval gate for risky teammate work

```
Spawn an architect teammate to refactor the authentication module.
Require plan approval before they make any changes.
```

Teammate plans (read-only) → submitted to lead → lead approves/rejects with feedback → teammate
revises and resubmits until approved → then implements. The lead decides autonomously; steer its
judgment by giving criteria in the spawn prompt ("only approve plans with test coverage").

## Talking to / controlling teammates

- **In-process** (default mode): agent panel below the prompt. ↑/↓ select a teammate, Enter opens
  its transcript and lets you message it directly, `x` stops it, Ctrl+T toggles the task list.
  Idle teammates' rows hide after 30s but keep running — message them by name to bring the row back.
- **Split panes**: each teammate in its own tmux/iTerm2 pane, click in to interact. Needs tmux or
  iTerm2 + the `it2` CLI. Not supported in VS Code's integrated terminal, Windows Terminal, or
  Ghostty. Set via `teammateMode` in `~/.claude/settings.json` (`"auto"`, `"tmux"`, `"iterm2"`,
  `"in-process"`) or `--teammate-mode` flag. Default changed to `"in-process"` as of v2.1.179.

To end a teammate cleanly: `Ask the researcher teammate to shut down` — it can accept or reject
with an explanation. Team directories clean up automatically when the session ends (no manual
cleanup step).

## Task coordination

Shared task list, three states: pending / in progress / completed. Tasks can depend on other
tasks — a pending task with unresolved deps can't be claimed yet, and the system auto-unblocks
dependents when the blocker completes. Either the lead assigns tasks explicitly, or teammates
self-claim the next unblocked task when free. Claiming uses file locking to avoid race conditions.

**Sizing tasks:** too small → coordination overhead beats the benefit. Too large → teammates run
long without check-ins, risking wasted effort if they go sideways. Right size = a self-contained
deliverable (one function, one test file, one review). Aim for **5–6 tasks per teammate**.

**Team size:** no hard cap, but token cost scales linearly with active teammates and coordination
overhead grows with headcount — returns diminish past a point. **Start with 3–5 teammates.** With
15 independent tasks, 3 teammates is a reasonable start. Three focused teammates usually beat
five scattered ones.

## Architecture (for understanding behavior, not for hand-editing)

| Component | Role |
|---|---|
| Team lead | Main session; spawns teammates, coordinates, synthesizes |
| Teammates | Separate full Claude Code instances on assigned tasks |
| Task list | Shared work-item list teammates claim/complete |
| Mailbox | Inter-agent messaging |

- Stored under a session-derived name: `session-<first 8 chars of session ID>`.
- `~/.claude/teams/{team-name}/config.json` — runtime state (session IDs, tmux pane IDs).
  **Never hand-edit or pre-author this** — it's overwritten on every state update. Removed when
  the session ends.
- `~/.claude/tasks/{team-name}/` — task list. Persists locally (never uploaded), survives session
  resume, governed by the same `cleanupPeriodDays` setting as transcripts.
- A `.claude/teams/teams.json` in a *project* directory is **not** recognized as config — it's
  just an ordinary file to Claude.
- Team config has a `members` array (name, agent ID, agent type) — teammates can read it to
  discover each other.

**Context per teammate:** loads the same project context as a normal session start (CLAUDE.md,
MCP servers, skills) + the spawn prompt from the lead. It does **not** inherit the lead's
conversation history — so the spawn prompt must carry every detail the teammate needs (see Best
practices below).

**Permissions:** teammates start with the lead's permission mode (including
`--dangerously-skip-permissions` if the lead has it). You can change an individual teammate's
mode after spawn, but not at spawn time.

**Communication mechanics:** messages deliver automatically to recipients (lead doesn't poll);
idle teammates auto-notify the lead on stopping; everyone sees shared task state; to reach
multiple teammates you send one message per recipient (no broadcast). Names are assigned by the
lead at spawn — tell it what to call each teammate up front if you'll want to address them later.

## Quality gates via hooks

- `TeammateIdle` — fires when a teammate is about to go idle; exit code 2 sends feedback and
  keeps it working.
- `TaskCreated` — fires on task creation; exit code 2 blocks creation + sends feedback.
- `TaskCompleted` — fires when a task is marked complete; exit code 2 blocks completion + sends
  feedback.

Useful for enforcing "don't mark done without tests passing," etc., without relying on the lead
remembering to check.

## Best practices checklist

1. **Front-load context in the spawn prompt.** No conversation history carries over — restate
   the relevant constraints, file paths, and acceptance criteria explicitly.
2. **3–5 teammates, 5–6 tasks each**, as a starting point — scale only when the work genuinely
   parallelizes.
3. **One owner per file.** Never let two teammates edit the same file — partition by file/module
   up front.
4. **Start with research/review, not implementation**, the first few times — lower coordination
   risk, same parallel-exploration payoff, good for building intuition before trying parallel
   code edits.
5. **Don't let the team run unattended too long.** Check in, redirect bad approaches, synthesize
   as findings arrive rather than waiting for a single final report.
6. **If the lead starts doing the work itself instead of delegating/waiting**, say so explicitly:
   `Wait for your teammates to complete their tasks before proceeding`.
7. **Pre-approve common permissions** before spawning a team — teammate permission prompts bubble
   up to the lead and otherwise create constant friction.
8. **For debugging, make teammates adversarial on purpose** — have them try to disprove each
   other's hypotheses rather than independently confirm. This is what prevents anchoring on the
   first plausible cause.

## Troubleshooting quick table

| Symptom | Fix |
|---|---|
| Teammates don't appear | Check agent panel (↑/↓, Enter); task may not have been "complex enough" for Claude to spawn a team; for split panes confirm `tmux`/`it2` is on PATH |
| Idle teammate row vanished | It's hidden (30s timeout), not stopped — message it by name to bring it back |
| Too many permission prompts | Pre-approve common ops in permission settings before spawning |
| Teammate stopped on an error | Open its transcript/pane, give it more instructions, or spawn a replacement |
| Lead calls it "done" early | Tell it to keep going / wait for teammates |
| Orphaned tmux session after exit | `tmux ls` then `tmux kill-session -t <name>` |
| Resumed session, lead messages dead teammates | Expected — in-process teammates don't survive `/resume`/`/rewind`; tell the lead to respawn |

## Known limitations (experimental, current as of v2.1.186)

- No session resumption for in-process teammates (`/resume`/`/rewind` don't restore them).
- Task status can lag — teammates sometimes fail to mark tasks complete, blocking dependents;
  may need a manual status nudge.
- Shutdown isn't instant — teammates finish their current tool call/request first.
- One team per session, scoped to that session — no multiple named teams, no sharing across
  sessions.
- No nested teams — only the lead spawns/manages teammates; teammates can't spawn their own.
- Lead role is fixed for the session's lifetime — no promotion/transfer.
- Permissions are fixed at spawn (lead's mode); per-teammate mode changes are post-spawn only.
- Split panes need tmux or iTerm2 — unsupported in VS Code's terminal, Windows Terminal, Ghostty.

`CLAUDE.md` in the working directory loads normally for every teammate — it's a reliable channel
for project-wide guidance to the whole team.

## When NOT to use a team (use a single session or subagent instead)

- The task is sequential / has heavy inter-step dependencies.
- Everything funnels through edits on the same one or two files.
- It's a quick, focused lookup where only the final answer matters (→ subagent).
- You're not prepared to monitor/steer for the duration — unattended teams risk wasted spend.

## Related

- Subagents: `.claude/skill-builder/agent-builder.md` (this repo's pattern for defining reusable
  subagent roles, which double as teammate role definitions per "Reusable roles" above).
- Upstream docs: [subagents](https://code.claude.com/docs/en/sub-agents),
  [worktrees](https://code.claude.com/docs/en/worktrees) (manual parallel sessions, no auto
  coordination), [hooks](https://code.claude.com/docs/en/hooks),
  [costs](https://code.claude.com/docs/en/costs#agent-team-token-costs).
