# CLAUDE.md — Ranking Shorts Project Rules

> All paths below are relative to this folder (`projects/ranking shorts/`). Run every tool with
> this folder as the working directory and the project venv (`.venv/Scripts/python tools/<name>.py`)
> — `tools/_common.py` resolves `REPO_ROOT` as `tools/`'s parent, so `brand/`, `assets/`, `state/`,
> and `.tmp/` resolve correctly from here. API keys load from the shared `API.env` at the repo root.

## Channel identity: momoclips
Both formats below post to the **same channel**, being rebranded to **`@momoclips`** on YouTube
and **Instagram** (Moemen renames the handles on-platform — Claude can't via API; update the
`--handle`/refs here once done). The Zernio IDs and YouTube OAuth token don't change with a handle
rename.

## What this project does

Three formats on the momoclips channel:

**A0) LIVE World-Cup watcher (`watch_worldcup.py`) — current focus (2026-07-07).** Event-driven
match coverage from **ESPN's free public scoreboard JSON** (`worldcup_live.py`, no key, no scrape).
A 15-min GitHub cron (`worldcup_live.yml`) runs a ~30s stdlib-only gate; when a match is
live/imminent the job stays up for the whole match, polling ESPN every ~75s and firing per event:
- **GOAL** → targeted hunt for THAT goal's fresh upload (`find_worldcup_clips.py --query/--require`,
  retried each poll until an upload appears, ~50 min max) → `build_clip` → post. (iShowSpeed
  reactions are NO LONGER captured here — see A0b.) Third-party Speed-clip uploads stay blocked in
  the finders (`_common.title_ok`), per 2026-07-06.

**A0b) iShowSpeed LIVE watcher (`watch_speed.py`) — PARALLEL to A0 (2026-07-09).** Own
`speed_watch.yml` (same `*/15` ESPN gate, own `concurrency: speed-watch` so it runs alongside A0).
While Speed is live on a WC match (`match_wc_stream` checks his `/live` title vs today's ESPN
fixtures) it records his stream in rolling ~210s chunks (yt-dlp native HLS — ffmpeg can't speak the
WARP SOCKS proxy) and posts a clip per big moment to **Instagram**. Detection FUSES: fresh ESPN
goals (title it "SPEED REACTS TO <SCORER> GOAL") + **audio-energy peaks** (`clip_speed_reaction.top_peaks`,
energy ≥ `--peak-ratio 1.6`×the chunk median — the catch-all for celebration/chant/collab moments
no feed reports) + a **vision label** (`_llm.vision_complete`: **Groq llama-4-scout → Gemini**;
Gemini alone 429'd) that writes the title + drops false positives (ads/menus/calm talking).
**Safe-degrade:** vision down → post a goal-driven peak generically but DROP an unlabelled pure-hype
peak. Idempotent via `state/speed_watch.json`; `--max-posts 8`/day; publishes paced
(`--post-spacing 45`, `--post-retries 2`). Test: dispatch with `no_upload=true`, or locally
`watch_speed.py --once --no-upload`. Built via the `/new-watcher` skill pattern.
- **FULL TIME** → star-player performance recap (`STAR_PLAYERS` list in `watch_worldcup.py`;
  card carries the box-score line, footage from a targeted highlight hunt) + **brace/hat-trick
  compilation** (`build_compilation.py` re-stitches that scorer's goal SOURCES — kept
  pre-watermark in `.tmp/wc/` — into one <58s Short).
Idempotent via `state/worldcup_watch.json` (Actions cache, same cache family as the poller);
`--max-posts 14`/day across all live formats. **Instagram publishes are PACED** (`--ig-spacing 60`s
min gap + `--ig-retries 2` with 30s→90s backoff): on 2026-07-07 five goal Shorts posted seconds
apart all got Zernio `status=failed` (Instagram burst-throttle) while a 6th built ~40s later
succeeded — pacing/retry fixes that. IG failures now record `platform_status` in the run summary.

**A) Single World-Cup clips (`clip_autopost.py`).** Every ~20 min a cloud job polls YouTube for a
FRESH World-Cup moment — now **viral/fan/streamer content only** (`--categories popular,streamer`):
**goals belong to the live watcher** (keeping them here too would double-post the same goal from a
different upload; dedup is per video id). No third-party iShowSpeed uploads (user rule 2026-07-06).
Builds ONE branded vertical Short and posts to YouTube + Instagram. "Only trigger when something
happened" = dedup (`state/used_clips.json`) + an upload-date=Today search.
Pipeline: `find_worldcup_clips → build_clip → host_public → upload_youtube/upload_instagram`.
⚠ Official goal footage is heavily Content-ID-claimed; posting it is Moemen's **accepted** risk
(decision log 2026-07-04, extended to livestream capture 2026-07-07).

**B) `#5 → #1` ranking countdowns (`rank_autopost.py`)** — the original format (below). Still
present; single-clips are the active World-Cup play.

Produces finished **vertical (1080×1920) faceless Shorts** and uploads them as
**unlisted/public drafts only after explicit approval**.

**One format: the `#5 → #1` countdown.** Each video stitches together short, real funny clips
(fails, cats, dogs, kids, etc.) into a countdown:

- Clips are sourced from **Reddit** (CI-friendly, no cookies/bot-check), with YouTube/Tenor as
  fallbacks. Each clip plays with its **ORIGINAL audio** — there is no AI narrator.
- The **whole frame is shown** — fit into 9:16 over a blurred fill, **no crop-zoom**.
- A **countdown overlay** sits on each clip (`#N` + a short funny label) alongside a compact
  leaderboard that reveals from `#5` up to `#1`.
- A **trending background-music bed** is mixed in under the clip audio, pitch/tempo-shifted to
  dodge YouTube Content ID.
- The whole video is capped so it stays **under 1 minute** (~58 s — true-Shorts length).

## Pipeline (each step = one tool, cwd = project root)

```
rank_topic → find_ranking_clips → rank_clips → build_ranking_video → build_captions → deliver
```

- **`rank_topic.py`** — auto-picks a trending ranking topic/niche.
- **`find_ranking_clips.py`** — pulls candidate clips from Reddit RSS (one feed request per run;
  funny/wholesome subreddits per genre). yt-dlp downloads each post. While the 2026 World Cup is
  live the pipeline is forced to the `worldcup` genre, which has **three angles** — `fan`
  (crowd/stands), `match` (on-pitch action), and `streamer` (FaZe / Marlon etc. -- no iShowSpeed -- at the
  World Cup, sourced from livestream-clip subs via `--angle streamer`). `rank_autopost.py`
  randomizes which angle it tries each run, so all three rotate; falls back to `mixed` then `fails`.
- **`rank_clips.py`** — the LLM ranks the best ~5 candidates and writes a short funny label per rank.
- **`build_ranking_video.py`** — trims, fits to 9:16 over blurred fill, mixes original audio + music
  bed, burns the countdown/leaderboard overlay, assembles `.tmp/final.mp4`.
- **`build_captions.py`** — optional captions/metadata.
- **Deliver** — `email_video.py`, `export_local.py`, or `upload_youtube.py` / `upload_tiktok.py` /
  `upload_instagram.py`.

**`rank_autopost.py`** is the autonomous orchestrator that runs the whole sequence end to end
(`--no-upload`, `--niche`, `--platforms`, `--privacy`, `--max-videos`). No paid video model is used:
sourcing (yt-dlp), captions (faster-whisper), and assembly (ffmpeg) are free/local.

## Environment setup

```bash
cd "projects/ranking shorts"
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m playwright install chromium    # if any visual tool needs it
python tools/youtube_auth_setup.py                      # one-time OAuth → token.json
```

**Credentials:** shares the one **`API.env` at the repo root** (`tools/_common.py` loads
`../API.env`). Don't make a per-project `.env`. `API.env`, `credentials.json`, `token.json`,
`.tmp/`, `assets/`, and `.venv/` are gitignored.

**Instagram (`--platforms instagram`):** needs `IG_ACCESS_TOKEN` (a long-lived Instagram USER
token from a Meta app's "API setup with Instagram business login → Generate access tokens", with
the `instagram_business_content_publish` permission) in `API.env`; `IG_USER_ID` optional (uses
"me"). The account must be an Instagram **Professional** (Business/Creator). The orchestrator
hosts the finished mp4 at a public URL via `host_public.py` (IG fetches the Reel from that URL),
then publishes via `upload_instagram.py`. Caveat: an IG Reel publish is **immediately public** —
there is no unlisted/draft privacy like YouTube; the only safe pre-test is the tool's dry run
(omit `--confirm`). Long-lived tokens expire ~60 days; refresh before relying on a daily run.

## Hard rules specific to this project

- **Under-1-minute hard cap on any video** (user rule, 2026-06-24 — strictly *less than* a minute,
  not exactly 60 s); `build_ranking_video.py` defaults to `--max-total 58` and caps per-clip time
  accordingly.
- **Audio: NO whoosh/boom/fail SFX and NO intro swoosh** (user rule, 2026-06-23). Each clip keeps
  ONLY its original sound (or sits on silence when it's quiet). The background-music bed is the only
  non-clip audio, mixed in once over the whole video. `--intro-swoosh` is OFF unless an explicit
  path is passed.
- **Branding is not optional.** Captions/thumbnails pull from `brand/theme.json` (gold `#C9A96C`,
  navy `#0B1622`, cream `#F2E9D8`, Cinzel/Poppins) and `brand/logo.png`. Never re-derive
  colors/fonts.
- **Never upload without explicit confirmation** at the gate. Show title, description, tags,
  resolved privacy, target channel (`@momoclips`), duration, byte size, and have me eyeball
  `.tmp/final.mp4` (overlay in sync, audio clean, no visible looping artifacts).
  `upload_youtube.py` / `upload_tiktok.py` / `upload_instagram.py` are the **only irreversible
  steps.**
- **English commentary only — no Indian/Hindi-commentary re-uploads** (user rule 2026-07-08). An
  English *title* can still front Hindi *audio*, so the title screen can't catch it — the **channel**
  is the signal. `_common.channel_ok()` hard-blocks Indian-language / Hindi-feed channels
  (hindi/india/Sports Tak/DD Sports/Star Sports/Sony/…) for every category, and the goal finder
  **prefers trusted broadcasters** (`channel_trusted()`: FIFA/FOX/CBS Golazo/ESPN/beIN/…), only
  falling back to the wider channel-screened pool when none of them have the moment yet. Already-
  posted Hindi-audio clips must be removed by hand (source channel isn't recorded post-publish).
- **Clips must be no-copyright / fair-use safe.** Sourcing tools don't vet rights; the music bed is
  pitch-shifted to reduce Content ID matches but is not a guarantee.
- `state/used_clips.json` tracks clips already used — don't reuse without reason.
