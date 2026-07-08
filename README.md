# ranking shorts

**One-liner:** Faceless vertical YouTube Shorts pipeline — "ranking" / Top-N list videos (the core
MOMO content engine). A character-dialogue format also exists in the tooling as an option.

- **Status:** Active (primary focus)
- **momoclips (2026-07-04):** channel rebranding to @momoclips (YouTube + Instagram) + a new
  single-clip World-Cup format (`clip_autopost.py`), triggered by ~20-min polling. Go-live is
  GATED — see the header of `.github/workflows/worldcup_clips.yml`. The #5->#1 countdown
  (`rank_autopost.py`) still exists (paused for the WC).
- **Sourcing (2026-07-08):** priority tiers = the GAME itself > iShowSpeed > other events;
  **TOD-by-beIN** (`@tod_bybein`) is the preferred FIFA source with a TOD-only bottom-branding
  crop; **iShowSpeed un-blocked** (reverses the 07-06 ban); `popular` broadened to trending
  off-pitch moments. All 3 workflows now run the BgUtils **PO-token provider** so cloud YouTube
  sourcing beats the datacenter bot-wall (verified: built a clip, no bot-wall).
- **iShowSpeed watcher (2026-07-09):** a NEW `watch_speed.py` + `speed_watch.yml` runs IN PARALLEL
  with the goal-clip watcher: while Speed is live on a WC match it records his stream in chunks and
  auto-posts a clip of every big moment (goal / penalty / **celebration / chant / creator collab**)
  to Instagram. Detection = ESPN goals + **audio-energy peaks** (the catch-all for moments no feed
  reports) + a **Groq→Gemini vision label** that titles the clip and filters false positives. All
  Speed capture was removed from `watch_worldcup.py` to avoid double-posting. Built via the new
  `/new-watcher` skill's pattern.
- **Rules / how-to:** [ranking-shorts.md](ranking-shorts.md)
- **Key dates:** Tied to the #1 priority — make these videos viral. Reduced availability ~2026-07-07.
