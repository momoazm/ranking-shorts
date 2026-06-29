# Competitor Analysis — Workflow SOP

Canonical step-by-step for the `competitor-analysis` project. Triggered via `/improver` (the
project's skill wrapper, which forks into the `update` subagent). Covers **two platforms** in one
workflow: Instagram (ranking-shorts accounts) and YouTube (MOMO Shorts channel).

> Read this file before running the workflow. The `update` subagent (`.claude/agents/update.md`)
> points here rather than restating these steps — keep this file as the single source of truth and
> update it (not the agent body) when the process changes.

---

## Phase 1 — Instagram: benchmark against competitors and sync repos

1. **Locate and inventory the `competitor/` folder.**
   - Find it at the repo root (or wherever it actually lives — search if it's not at the obvious path).
   - Catalog what's inside: account handles, follower counts, post/reel performance data, captions,
     hashtags, posting cadence, video formats, hooks, niches — whatever is present. Note the format
     (CSV, JSON, screenshots, markdown notes, etc.) and don't assume a fixed schema.

2. **Identify Moemen's 3 Instagram accounts to compare.**
   - Check `context/`, project READMEs, and `.claude` memory (e.g. `ranking-shorts-instagram.md`)
     for the 3 tracked IG accounts (e.g. `@rank_ingshorts` and others on `clipping-auto`).
   - If you can't confidently identify all 3, ask Moemen to confirm rather than guessing.

3. **Run the comparison.**
   - Compare each of Moemen's 3 accounts against same-niche competitors: growth rate, engagement
     rate, posting frequency, hook style, video length, caption style, hashtag strategy, content
     format (Top-N lists vs. other ranking formats), thumbnail/cover style.
   - Surface clear, actionable deltas, not raw numbers. Be honest about limited/noisy data — don't
     manufacture false confidence.

4. **Translate findings into concrete repo updates.**
   - Map each actionable insight to the right place in the codebase, following the WAT framework
     (Workflows / Agents / Tools): update workflow `.md` SOPs, tool configs, posting schedules,
     hashtag lists, brand/style parameters — wherever the relevant project reads its config from.
   - Only touch the projects whose accounts were actually compared (`ranking shorts` /
     `clipping-auto`). Prefer editing config/data files over rewriting logic.
   - Document *why* each change was made, tied to the specific competitor finding.

5. **Commit and push.**
   - Stage only the files intentionally changed.
   - Commit message summarizes what competitor insight drove which change.
   - Push so the changes are live for the next automation run. This is a repo push, not a
     public post/upload/send, so it doesn't require the irreversible-action gate — but flag and
     confirm first if a change would alter *public-facing* behavior in a way Moemen would want to
     sign off on (a strategy pivot, not a tuning tweak).

6. **Delete the `competitor/` folder.**
   - Only after the comparison is complete and repo updates are committed and pushed.
   - This is a standing exception to the project's archive rule, specific to this folder — confirm
     in the final summary that it was deleted (not archived). If there's any doubt the analysis is
     fully captured elsewhere, say so before deleting.

---

## Phase 2 — YouTube: compare MOMO's channel against rivals

7. **Load the baseline.** Read `projects/competitor-analysis/momo-profile.json`. Resolve niche,
   handle, known metrics, stated goals, and `named_competitors`. If the run is scoped to specific
   channels (a focus argument), treat those as the comparison set and skip discovery (step 8).

8. **Discover competitors** (skip if channels were named). Search for the top channels in MOMO's
   niche (faceless "ranking" Top-N Shorts), e.g. `"best faceless ranking Shorts channels YouTube"`,
   `"top Top-10 list Shorts creators 2026"`. Merge with `named_competitors` from the profile, dedup,
   settle on **~3–6 channels**.

9. **Research each channel.** Per channel: subscribers, avg views, posting cadence, video length,
   hook style, thumbnail/title patterns, best-performing Shorts. Use the `extract-article`
   subagent on the 1–3 strongest sources when a snippet isn't enough. Keep every URL — it becomes a
   cited source in the output.
   - **YouTube stat reality:** channel pages are JS-rendered, so subs/views usually can't be
     scraped directly. Use Social Blade / vidIQ-style sources or search snippets, and mark numbers
     as cited vs. estimated. Never fabricate a metric.
   - **Web research fallback chain, best-first:** Firecrawl (MCP `firecrawl_search`) →
     `TAVILY_API_KEY` → `EXA_API_KEY`. Surface only whole-chain failures.

10. **Gap analysis** (the deliverable). For each channel vs. MOMO, score the dimensions that
    actually drive ranking-Short performance: hook (first 1–2s), list structure & pacing, on-screen
    text/captions, thumbnail & title, audio, topic selection, cadence & consistency. For every
    dimension a rival leads, record the gap, the evidence (source), and a concrete move for MOMO to
    match then exceed it.

11. **Write the YouTube comparison in chat** (Markdown), in this order: bottom line (2–3 biggest
    opportunities, stated as actions) → competitor set table (`Channel | Subs | Avg views | Cadence
    | Why they win`) → where they beat MOMO (grouped by dimension) → action plan to exceed
    (prioritized, specific) → sources (every URL, flagged cited vs. estimate).

12. **Keep the profile current.** If a real competitor, metric, or handle is confirmed this run,
    update `projects/competitor-analysis/momo-profile.json` (especially `named_competitors`) so
    the next run starts smarter.

13. **Commit (no push).** If `momo-profile.json` changed, commit it automatically — same as
    Phase 1's no-gate reasoning (this is a data file, not a public-facing action), but **don't
    push**: this file isn't read by any deploy/automation, so there's no "live for the next run"
    reason to push immediately the way Phase 1's repo-config changes have. Push next time something
    else in the repo needs pushing anyway, or if Moemen asks for it directly.

---

## Report back (both phases)

14. Give Moemen a concise, bullet-point summary: what was compared on each platform, key findings,
    exactly what changed in the repo (files + reasoning) for the Instagram phase, the YouTube
    comparison's action plan, confirmation of the push (commit hash/branch) for Phase 1 and the
    commit (no push) for Phase 2, and confirmation the `competitor/` folder was deleted. If
    anything was skipped or inconclusive, say so plainly.

## Notes / Lessons learned

- **No publishing, no email** for the YouTube phase — it only researches and writes back to chat.
- **Don't fabricate metrics or competitor data** on either platform.
- Follow the WAT split: don't hand-roll logic that should live in a deterministic tool — check
  `tools/` first if a repeatable comparison script would help.
- If the `competitor/` folder doesn't exist or is empty, stop and tell Moemen rather than
  improvising fake comparisons for Phase 1; Phase 2 can still run independently.
