---
name: momo-format-specifics
description: MOMO ranking-shorts project's actual current format/constraints, needed to ground the YouTube gap analysis in what MOMO can realistically change
metadata:
  type: project
---

From `projects/ranking shorts/ranking-shorts.md` (read 2026-06-29) — use this to keep Phase 2 gap
analysis grounded in real constraints, not generic advice:

- **Format:** strict `#5 → #1` countdown of real clips (fails/cats/dogs/kids etc.), sourced from
  Reddit/YouTube/Tenor — no AI narrator, each clip keeps its **original audio**.
- **No crop-zoom** — whole frame shown over blurred 9:16 fill.
- **Hard cap: under 1 minute** (~58s default), per an explicit 2026-06-24 user rule — "strictly
  less than a minute, not exactly 60s."
- **Audio rule:** NO whoosh/boom/fail SFX, no intro swoosh (2026-06-23 user rule) — only the
  clip's original sound + one background-music bed (pitch/tempo-shifted to dodge Content ID).
- **Brand:** gold `#C9A96C`, navy `#0B1622`, cream `#F2E9D8`, Cinzel/Poppins fonts, from
  `brand/theme.json` — never re-derive.
- **Pipeline is fully automated** (`rank_autopost.py`): topic pick → clip sourcing → LLM ranking →
  video build → captions → multi-platform deliver, with an explicit confirm gate before any
  upload.

**How to apply:** when recommending a competitor-inspired change (e.g. WatchMojo's kinetic text,
FailArmy's front-loaded best-moment), check it's compatible with these hard constraints (no SFX,
under 60s, original audio only) before suggesting it as an action item — otherwise it's a strategy
pivot that needs Moemen's explicit sign-off per the project's CLAUDE.md, not a tuning tweak.
