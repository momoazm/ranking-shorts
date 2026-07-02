---
name: youtube-monetization-framing
description: The concrete YPP Shorts monetization threshold and community-sourced reality of how small channels actually hit it — use to weight Phase 2 gap analysis toward views/subs velocity
metadata:
  type: project
---

Confirmed 2026-07-01 (cited, not estimated): YouTube Partner Program Shorts path = **1,000
subscribers + 10,000,000 public Shorts views in a trailing 90 days**
(https://miraflow.ai/blog/youtube-shorts-watch-time-2026-how-much-you-need). There's also a lower
fan-funding tier (500 subs, 3M Shorts views/90 days) if the 10M bar is framed as too far out for a
"first monetization milestone" conversation.

**Community reality check** (r/NewTubers, anecdotal — flag as such, not a primary metric source):
- Consistent daily posting alone doesn't get you there on the math: e.g. 2 Shorts/day for 90 days
  = 180 uploads needing ~111K avg views *each* to sum to 10M. That's not a realistic average for a
  new/small channel.
- The threshold is realistically hit via a **small number of breakout-viral Shorts**, not a high
  floor across all uploads — see thread "I got monetized with 5 viral shorts. Here's how"
  (r/NewTubers, https://www.reddit.com/r/NewTubers/comments/1d1zoj0/). Several other threads
  describe it as "lottery"-like: satisfaction/completion-driven virality matters far more than
  upload count.
- Watch time / retention (not raw views) is what the algorithm actually optimizes the Shorts feed
  around per miraflow.ai's synthesis of YouTube's public docs — hook (0-2s), pattern breaks every
  1-3s, and a loop-worthy payoff ending are the concrete levers, with 60-80% retention on a
  ~60s Short cited as the "strong" benchmark band.

**How to apply:** when Moemen's framing for a Phase 2 run is monetization/YPP-threshold-focused
(as it was 2026-07-01), weight the gap analysis and action plan toward **hook strength, topic
virality/curiosity-gap selection, and posting cadence/volume together** — not generic "improve
quality" advice. Call out explicitly that MOMO's `rank_autopost.py` has **no fixed cadence**
(on-demand only, confirmed from `projects/ranking shorts/ranking-shorts.md`) as a structural gap:
without consistent daily+ volume, even strong per-Short quality can't accumulate 10M views in a
rolling 90-day window. See [[momo-format-specifics]] for what changes are actually compatible with
MOMO's hard format constraints before recommending them.
