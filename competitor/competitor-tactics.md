# Winning tactics in the faceless ranking / Top-N Reels niche — vs. MOMO

Synthesized 2026-07-01 from the 2026 Reels ranking model (see `reels-algorithm-2026.md`) and the
YouTube-side competitor notes already in `projects/competitor-analysis/momo-profile.json`
(WatchMojo, Polar Ranks, faceless Top-N countdown tier). The format patterns transfer across
Shorts/Reels since the same videos are cross-posted.

## What winning ranking/countdown accounts do (patterns, not metrics)
- **Cold-open teaser hook:** front-load the most shocking entry or the payoff question in the
  first 1–2s ("You won't believe what's #1"). Completion rate is the #1 Reels signal — a weak
  first second kills the whole video.
- **Kinetic on-screen text + numbered reveals:** big animated numbers, punchy captions synced to
  narration. This is WatchMojo's core (per momo-profile.json) and drives retention.
- **Curiosity-gap topic selection:** they win on *topic*, not production. Surprising/rankable
  topics people want to DM to a friend (share signal) or save (save signal).
- **Tight pacing, clear payoff at #1:** no dead air; the reveal must land.
- **Consistency over volume:** a steady, sustainable cadence beats flooding (see cadence rule).

## Deltas vs. MOMO's current IG setup (actionable)
| Dimension | Winning pattern | MOMO now | Move |
|---|---|---|---|
| Cadence | 3–5 strong/week; daily only if all strong | ~6×/day auto to brand-new accts | **Throttle IG to ≤1/day, best videos only** |
| Hook | Cold-open teaser in 1–2s | (verify current hook style) | Front-load shock/question; A/B 3 hooks |
| Hashtags | 3–5 relevant; classification only | (verify caption block) | Cut to 3–5 tight, invest caption in hook + keywords |
| Optimize-for | Completion → shares → saves | (likely optimizing views) | Measure completion rate; design for DM-share + save |
| Topic | Curiosity-gap, shareable, rankable | ranking/Top-N (good wrapper) | Point format at fun-facts/science/psychology for growth; finance/tech for $ ceiling |
| Series | Connected Reels drive follows | one-off videos | Build a recurring series ("Top 5 X, part N") |

## Where these map in the repo (for Phase 1 sync)
- `projects/ranking shorts/tools/upload_instagram.py` / `upload_zernio.py` — the live IG posting
  path for `@rank_ingshorts` (Zernio switch happened — confirm which is current from git log).
- `projects/clipping-auto/` — the `rankingshorts1` posting path.
- Cadence lives in the automation's schedule (autopost cron / run_daily) + `rank_autopost.py`
  auto-appending `instagram` every run — the ~6/day flooding originates there.
- Caption/hashtag construction — wherever captions are built before the IG publish call.

## Honesty note
No specific rival handles with verified follower counts were obtainable (login-gated + not
indexed). These are pattern-level tactics + the cited 2026 ranking model, deliberately not
fabricated numbers.
