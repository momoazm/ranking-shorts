---
name: wrap
description: Close out the current work session — append decisions to the decision log, ingest the session's changes into the Momo brain, refresh touched project READMEs, git commit (no push), and give Moemen a session summary.
---

# Session Wrap — inline

Close out the session cleanly so the next session starts oriented. Uses only what's already in
context — don't re-read the whole repo to "audit" the session.

## Steps
1. **Inventory the session.** List the meaningful changes made this session (features, fixes,
   new skills/agents, decisions, config changes). Run `git status --short` to catch file changes
   you forgot. If nothing meaningful happened, tell Moemen and stop.
2. **Decision log.** For each direction locked in / strategy change / non-obvious choice this
   session that isn't logged yet: append to `decisions/log.md` in the standard format
   (`[YYYY-MM-DD] DECISION: ... | REASONING: ... | CONTEXT: ...`). Append-only — never touch
   past entries.
3. **Momo brain.** Run the `/ingest` steps for anything from the inventory not yet in the brain
   (one combined `sNNN` node for the session's related changes is fine).
4. **Project READMEs.** For each project materially touched, update its `README.md` status
   section (2–3 lines max: what changed, what's pending). Skip untouched projects.
5. **Commit.** Stage the session's files and make one descriptive commit (or a few logical ones).
   **Never push** — pushing/deploying is irreversible-adjacent and stays behind Moemen's explicit
   go, outside this skill.
6. **Session summary.** Fill `templates/session-summary.md` inline in the chat (Date, Focus,
   What Got Done, Decisions Made, Open Items / Next Steps, Memory Updates). Lead with the one
   thing Moemen most needs to know or decide next.

## Notes
- Anything irreversible still pending (an unsent email, an unpushed deploy, an unposted video)
  goes under **Open Items** with what confirmation it's waiting on — never "just finish" it here.
- If a `.gitignore`'d secret shows up staged, unstage it and flag it in the summary.
