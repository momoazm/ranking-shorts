# Momo Brain — Log

Append-only timeline. Each entry: `## [YYYY-MM-DD] <op> | <title>`.
Greps cleanly: `grep "^## \[" log.md | tail -5`.

---

## [2026-06-28] meta | Brain created
Set up the relationship-first LLM Wiki inside the existing `Momo/` Obsidian vault. Schema =
`CLAUDE.md`; structure = `raw/` + `wiki/{entities,concepts,sources,comparisons}` + `index.md`.
Design pivots per Moemen: **relationships over prose, token-frugal nodes, no web by default.**

## [2026-06-28] ingest | s001 — Claude Code Workspace (seed)
Seeded the brain from the whole repo. Created source [[s001-claude-code-workspace]] and entity
nodes: [[moemen]], [[momo-brand]], [[momo-niche]], [[ranking-shorts]], [[clipping-auto]],
[[follower-race]], [[website]]. Stubbed concept nodes (wat-framework, api-fallback-chains,
goals-and-priorities, ranking-shorts-instagram, llm-wiki-method) as link targets to fill on demand.

## [2026-06-29] ingest | s002 — Competitor-analysis merge + /improver
Created source [[s002-competitor-analysis-merge]] and entity [[competitor-analysis]]. Linked from
[[ranking-shorts]] and [[clipping-auto]] (the projects whose accounts it benchmarks).

## [2026-06-29] ingest | s003 — Momo auto-ingest hook tried, abandoned
Created source [[s003-momo-ingest-hook-abandoned]] and filled in the [[llm-wiki-method]] concept
(was a stub). Ingest is now a standing rule in root `CLAUDE.md`, not a hook.

## [2026-06-29] ingest | s004 — Agent Teams enabled, explicit-request-only
Created source [[s004-agent-teams-enabled]] and new concept [[agent-teams]]. Enabled the
experimental feature + wrote `.claude/docs/agent-teams.md`, but root `CLAUDE.md` now forbids
auto-proposing or auto-spawning a team — explicit request only.

## [2026-06-29] ingest | s005 — /improver skill removed
Created source [[s005-improver-skill-removed]] and updated [[competitor-analysis]]. The `update`
subagent lost its slash wrapper and now follows the platform default (natural language /
`@agent-update` only).

## [2026-07-01] ingest | s006 — website: PURE BLEND 3D site + skills + 21st.dev
Created source [[s006-website-3d-skills]] and ingested Moemen's new `projects/website/` work:
entity [[pureblend]] (scroll-driven 3D blender landing page, standalone repo `momoazm/pureblend`),
two skill entities [[frontend-design-skill]] + [[video-to-website-skill]], and concept
[[21st-dev-magic]] (required on every build). Updated [[website]] to link them all.

## [2026-07-01] ingest | s007 — Momo = workspace map; backfill skills + RAG + site
Created source [[s007-momo-map-and-backfill]]. Root `CLAUDE.md` now has a "Momo brain" section with
two standing rules — **consult** the vault first to find relations / save tokens, and **ingest
every meaningful addition** (not just decisions) same-turn; mirrored into `Momo/CLAUDE.md` Defaults.
Backfilled entities [[infographics-skill]], [[send-email-skill]], [[cs-rag]] (multimodal RAG /
vector DB) and [[momo-website]] (Knowledge Oracle site + calendar); linked into [[website]].
Updated [[llm-wiki-method]] scope (brain now maps the whole repo, not just decisions).

## [2026-07-01] ingest | s008 — on-demand Run buttons replace pipeline cron
Created [[s008-runner-buttons]]. Both self-hosted pipelines lose their `schedule:` and are now
fired from password-gated animated badges on [[momo-website]] → Vercel `api/runner.py`
(`workflow_dispatch`, gated while running) → local `runner-helper/` launches `run.cmd --once` so
the runner starts → runs → exits. Linked into [[ranking-shorts]] + [[clipping-auto]] +
[[21st-dev-magic]]. Deploy + live test pending Moemen's go (GitHub PAT + Vercel env).

## [2026-07-01] ingest | s009 World Cup streamer angle (ranking-shorts)

## [2026-07-01] ingest | s010 Playwright CLI installed (shared)
Installed the Playwright **CLI** globally (v1.61.1) + Chromium, shared across every project, for
browser automation (test web apps, screenshots/PDFs, drive/fix repos). **CLI over the MCP server**
to stay token-frugal. New nodes: source [[s010-playwright-cli]] + concept [[playwright-cli]];
linked to [[wat-framework]] + [[website]]. SOP at `references/sops/playwright-cli.md`. Verified
end-to-end (example.com screenshot).

## [2026-07-01] ingest | s011 monetization reach fixes (ranking-shorts)
Monetization pass (YouTube via [[update]] Phase 2 + Instagram). Shipped 3 reach fixes to
[[ranking-shorts]] (commit `db366cd`): hook opens on the strongest clip not the weakest; dropped
stale brainrot/Family-Guy hashtags (wrong niche) + capped IG to 5; visual follow-CTA end-card
(no SFX). IG cadence left manual. New node: source [[s011-monetization-reach-fixes]].

## [2026-07-01] ingest | s012 — RAG fix + gumball companions + website self-test
Created source [[s012-rag-fix-gumball-selftest]] and entity [[website-selftest-skill]]; stubbed
[[gumball-companions]]. Fixed the [[cs-rag]] env-path bug in `app.py` (broke [[momo-website]]
backend locally), added auto-populating Gumball mascots to the site (not deployed — preview
first), and shipped a backend self-test skill. Test data wiped; index back to 0 vectors.

## [2026-07-01] ingest | Follower-race → Instagram + Playwright + race polish + site button
Created source [[s013-follower-race-instagram-playwright]]; enriched [[follower-race]] with
Instagram/Playwright edges. Connected follower-race to IG end to end: **Zernio posts** from the
cloud runner, **comment-replies + follower-list auto-sync run locally** via [[playwright-cli]] on
a one-time saved IG session (`ig_login.py`). New local tools `reply_placements.py` (place replies)
and `sync_followers.py` (followers modal → usernames+pfps → racer count). Polished race.html
(leaderboard, finish zoom+flash, winner banner, snappier podium; determinism held) and added a
"Run follower race" button to [[momo-website]]. Nothing posted/pushed — awaiting Moemen's go.

## [2026-07-01] ingest | /playwright-cli inline skill
Built the **`/playwright-cli`** inline skill (`.claude/skills/playwright-cli/`) — the action layer
over the [[playwright-cli]] SOP (pick cheapest tool → save/reuse session → one JSON object → gate
public actions), pointing at [[follower-race]]'s tools as reference implementations. Registered in
root CLAUDE.md + skill-builder capabilities; enriched the [[playwright-cli]] concept with the
`exposed as` / `powers` edges. Also: demo race video emailed to Moemen for review (not posted).

## [2026-07-02] ingest | follower-race reply = top-level @mention
Rewrote [[follower-race]]'s `reply_placements.py` `post_reply()` to post a **top-level @mention
comment** (`@username You finished 2nd place! 🥈`) instead of a threaded per-comment reply —
headless IG threaded-reply silently dropped posts / landed top-level anyway and throttled
`the_followers_racer`. Pushed (f9fd4cc), still `--confirm`-gated. [[momo-website]] "Run follower
race" button verified live on the multi-page site (pipelines.html + runner.py). See
[[s014-follower-race-toplevel-mention-reply]] (supersedes the threaded approach in [[s013-follower-race-instagram-playwright]]).

## [2026-07-02] ingest | CLAUDE.md overhaul + 4 core capabilities
Root `CLAUDE.md` rewritten so **this brain is the canonical catalog** — project/skill lists are no
longer restated there (they had drifted); navigate `index.md` → node → path. Built the
most-sessions capability set: [[researcher-agent]] (sonnet, isolated web research → cited brief),
[[runner-agent]] (haiku, tools run → parsed JSON only, irreversible scripts blocked),
[[ingest-skill]] (`/ingest`, this op as a skill) and [[wrap-skill]] (`/wrap`, session close-out).
Decision logged 2026-07-02; see [[s015-claudemd-overhaul-core-capabilities]]. Subagents load at
session start — restart before first `researcher`/`runner` use.
