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

Two formats on the momoclips channel:

**A) Single World-Cup clips (`clip_autopost.py`) — current focus (2026-07-04).** Every ~20 min a
cloud job polls YouTube for a FRESH World-Cup moment (Messi/Ronaldo/big-nation **goals**,
**iShowSpeed**, viral clips), builds ONE branded vertical Short from it, and posts to YouTube +
Instagram. "Only trigger when something happened" = dedup (`state/used_clips.json`) + an
upload-date=Today search, so a run posts only when a genuinely new clip exists.
Pipeline: `find_worldcup_clips → build_clip → host_public → upload_youtube/upload_instagram`.
⚠ Official goal footage is heavily Content-ID-claimed; posting it is Moemen's **accepted** risk
(decision log 2026-07-04). Go-live is gated: the `worldcup_clips.yml` 20-min cron ships COMMENTED
OUT until the handles are renamed and a sample is approved (see that file's header).

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
  (crowd/stands), `match` (on-pitch action), and `streamer` (iShowSpeed / FaZe / Marlon etc. at the
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
- **Clips must be no-copyright / fair-use safe.** Sourcing tools don't vet rights; the music bed is
  pitch-shifted to reduce Content ID matches but is not a guarantee.
- `state/used_clips.json` tracks clips already used — don't reuse without reason.
