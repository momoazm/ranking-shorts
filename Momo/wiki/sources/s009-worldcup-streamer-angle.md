---
type: source
tags: [momo, ranking-shorts, worldcup]
updated: 2026-07-01
---
# s009 — World Cup "streamer" angle (2026-07-01)

Added a third [[ranking-shorts]] World Cup angle: **streamer** (iShowSpeed / FaZe / Marlon / xQc at
the 2026 WC), on top of the existing fan/match. Detail → [decisions/log.md](../../../decisions/log.md).

## Key points
- **produces** a new source tool `find_streamer_clips.py` — sources via **YouTube search**, not Reddit
  (Reddit's streamer subs are drama-heavy + off-theme; YouTube titles are on-theme + classifiable).
- **depends on** the self-hosted home-IP runner ([[s008-runner-buttons]]) — YouTube bot-checks cloud IPs.
- **uses** a strict football/WC-only classifier in `rank_clips.py`; `rank_autopost.py` now randomizes
  fan/match/streamer so each rotates, with fallback streamer→Reddit→mixed→fails.
- Roster editable in `STREAMER_QUERIES`; Content-ID risk of streamer footage accepted by Moemen.

## Relationships
- **is part of** [[ranking-shorts]] · **see** [[momo-niche]] · **builds on** [[s008-runner-buttons]]
