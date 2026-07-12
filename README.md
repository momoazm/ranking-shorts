# ranking shorts

**One-liner:** Faceless vertical YouTube Shorts pipeline — "ranking" / Top-N list videos (the core
MOMO content engine). A character-dialogue format also exists in the tooling as an option.

- **Status:** Active (primary focus)
- **momoclips (2026-07-04):** channel rebranding to @momoclips (YouTube + Instagram) + a new
  single-clip World-Cup format (`clip_autopost.py`), triggered by ~20-min polling. Go-live is
  GATED — see the header of `.github/workflows/worldcup_clips.yml`. The #5->#1 countdown
  (`rank_autopost.py`) still exists (paused for the WC).
- **Sourcing (2026-07-08):** priority tiers = the GAME itself > other events; **TOD-by-beIN**
  (`@tod_bybein`) is the preferred FIFA source with a TOD-only bottom-branding crop; `popular`
  broadened to trending off-pitch moments. All 3 workflows now run the BgUtils **PO-token
  provider** so cloud YouTube sourcing beats the datacenter bot-wall (verified: built a clip, no
  bot-wall).
- **iShowSpeed BLOCKED again (2026-07-12):** Moemen's call — no iShowSpeed content anywhere on
  momoclips. `speed_watch.yml` is manually **disabled** (not deleted — `gh workflow enable
  speed_watch.yml` to bring it back). `find_worldcup_clips.py`'s `speed` category is removed
  entirely, and `_common.py` now hard-blocks his name/handle in both the title and channel
  screens (`title_ok`/`channel_ok`) as a deterministic backstop behind the existing LLM
  relevance screen. Reverses the 2026-07-08 un-block and retires the 2026-07-09
  `watch_speed.py` parallel-watcher feature described below.
- **Duplicate-goal fix (2026-07-12):** ESPN's live feed can report the same goal with a
  slightly different `clock.value` between polls, minting a second internal key and causing
  `watch_worldcup.py` to post the same goal twice (caught: Mac Allister's goal double-posted to
  YouTube+Instagram). Now deduped by scorer+minute within a match, not just the raw key.
- **News/analysis filtering tightened (2026-07-12):** more talk-show markers (recap, roundup,
  breakdown, post-match show) added to the deterministic title screen, and the LLM relevance
  screen (`clip_autopost.screen_candidates`, already excludes news/analysis/iShowSpeed) is now
  also applied inside `watch_worldcup.py`'s goal hunts, star recaps, and TOD-highlights hunt —
  previously only the `clip_autopost.py` polling path used it.
- ~~**iShowSpeed watcher (2026-07-09):**~~ *(retired 2026-07-12, see above)* a `watch_speed.py`
  + `speed_watch.yml` ran IN PARALLEL with the goal-clip watcher: while Speed was live on a WC
  match it recorded his stream in chunks and auto-posted a clip of every big moment (goal /
  penalty / celebration / chant / creator collab) to Instagram. Detection = ESPN goals +
  audio-energy peaks + a Groq→Gemini vision label. All Speed capture was removed from
  `watch_worldcup.py` to avoid double-posting. Built via the `/new-watcher` skill's pattern.
- **Weekly IG style experiment (2026-07-12):** whichever of `clip_autopost.py` /
  `watch_worldcup.py` / `watch_speed.py` lands the FIRST successful @momoclips Instagram post in
  a new ISO week tries a rotated follow-CTA variant (`tools/pick_weekly_style.py`); a new Monday
  cron (`style_experiment.yml` → `tools/check_style_experiment.py`) compares it to recent posts
  via Zernio analytics and WhatsApps Moemen (CallMeBot) if it clearly won. Notification only —
  never auto-changes the default CTA.
- **Rules / how-to:** [ranking-shorts.md](ranking-shorts.md)
- **Key dates:** Tied to the #1 priority — make these videos viral. Reduced availability ~2026-07-07.
