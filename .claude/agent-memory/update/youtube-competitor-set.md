---
name: youtube-competitor-set
description: Cited Social Blade stats for MOMO's named YouTube competitors (FailArmy, WatchMojo, AFV) as of 2026-06-29, and the sourcing-thinness reality for small countdown-format channels
metadata:
  type: project
---

Confirmed via Social Blade scrape (cited, not estimated) on 2026-06-29:

- **FailArmy** (@failarmy): 17.5M subs, ~4.96B views, 981 videos. https://socialblade.com/youtube/handle/failarmy
- **WatchMojo** (@watchmojo): 25.8M subs, ~18.0B views, 33,258 videos. https://socialblade.com/youtube/handle/watchmojo
  — added this run as MOMO's closest **true format twin** among large channels: literal numbered
  Top-10 countdown, kinetic on-screen text, punchy per-item pacing. Wasn't in `named_competitors`
  before; added 2026-06-29.
- **AFV** (@afv): 7.84M subs, ~4.48B views, 3,574 videos. https://socialblade.com/youtube/handle/afv

**Sourcing reality for the actual scale-peer tier** (small/mid faceless Top-N Shorts channels,
MOMO's real competitive set): these don't show up in indexed search/Social Blade easily — search
results return generic "best faceless niches" listicle content, not real channel handles. Reddit
threads (e.g. r/NewTubers) discuss this exact niche but Firecrawl's scrape tool **refuses
reddit.com** ("we do not support this site") — search snippets only, no full scrape. Don't fabricate
handles/numbers for this tier; flag as thin/anecdotal per CLAUDE.md's "thin sourcing is expected"
rule rather than inventing a fake "Top-N competitor" with numbers.

**How to apply:** Reuse these 3 named/cited competitors as the stable anchor set each run; only
re-scrape if the data is >1 run old (numbers shift slowly for legacy channels) or Moemen asks for
fresh pulls. Keep trying to find concrete small-channel handles each run since that's the more
directly competitive tier — but don't block the report on it.

**Reconfirmed 2026-07-01:** re-ran multiple targeted searches ("Polar Ranks Social Blade",
"faceless top 5 countdown Shorts channel viral", "countdown shorts channel case study") — still no
citable handles for the small/mid scale-peer tier, including re-verifying "Polar Ranks" itself
(Social Blade has several unrelated "Polar..." channels, none matching the third-party roundup's
description). Don't keep burning searches on the exact same query phrasing each run — it's
consistently unindexed. Next attempt should try a genuinely different method (e.g. browsing
YouTube's Shorts shelf directly, or asking Moemen if he has channels he's already noticed).
