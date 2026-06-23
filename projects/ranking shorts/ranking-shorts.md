# CLAUDE.md — Ranking Shorts Project Rules

> All paths below are relative to this folder (`projects/ranking shorts/`). Run every tool with
> this folder as the working directory and the project venv (`.venv/Scripts/python tools/<name>.py`)
> — `tools/_common.py` resolves `REPO_ROOT` as `tools/`'s parent, so `brand/`, `assets/`, `state/`,
> and `.tmp/` resolve correctly from here. API keys load from the shared `API.env` at the repo root.

## What this project does

Produces finished **vertical (1080×1920) faceless ranking Shorts** for MOMO's YouTube channel
(`@Moemen-i2f6l`) and uploads them as **unlisted/public drafts only after explicit approval**.

**One format: the `#5 → #1` countdown.** Each video stitches together short, real funny clips
(fails, cats, dogs, kids, etc.) into a countdown:

- Clips are sourced from **Reddit** (CI-friendly, no cookies/bot-check), with YouTube/Tenor as
  fallbacks. Each clip plays with its **ORIGINAL audio** — there is no AI narrator.
- The **whole frame is shown** — fit into 9:16 over a blurred fill, **no crop-zoom**.
- A **countdown overlay** sits on each clip (`#N` + a short funny label) alongside a compact
  leaderboard that reveals from `#5` up to `#1`.
- A **trending background-music bed** is mixed in under the clip audio, pitch/tempo-shifted to
  dodge YouTube Content ID.
- The whole video is capped so it stays **≤ 2 minutes** (≤ 60 s for true Shorts).

## Pipeline (each step = one tool, cwd = project root)

```
rank_topic → find_ranking_clips → rank_clips → build_ranking_video → build_captions → deliver
```

- **`rank_topic.py`** — auto-picks a trending ranking topic/niche.
- **`find_ranking_clips.py`** — pulls candidate clips from Reddit RSS (one feed request per run;
  funny/wholesome subreddits per genre). yt-dlp downloads each post.
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

## Hard rules specific to this project

- **2-minute hard cap on any video** (user rule, 2026-06-18); `build_ranking_video.py` defaults to
  `--max-total 120` and caps per-clip time. For YouTube *Shorts* keep it ≤ 60 s.
- **Audio: NO whoosh/boom/fail SFX.** Each clip keeps ONLY its original sound (or sits on silence
  when it's quiet). The background-music bed is mixed in once over the whole video.
- **Branding is not optional.** Captions/thumbnails pull from `brand/theme.json` (gold `#C9A96C`,
  navy `#0B1622`, cream `#F2E9D8`, Cinzel/Poppins) and `brand/logo.png`. Never re-derive
  colors/fonts.
- **Never upload without explicit confirmation** at the gate. Show title, description, tags,
  resolved privacy, target channel (`@Moemen-i2f6l`), duration, byte size, and have me eyeball
  `.tmp/final.mp4` (overlay in sync, audio clean, no visible looping artifacts).
  `upload_youtube.py` / `upload_tiktok.py` / `upload_instagram.py` are the **only irreversible
  steps.**
- **Clips must be no-copyright / fair-use safe.** Sourcing tools don't vet rights; the music bed is
  pitch-shifted to reduce Content ID matches but is not a guarantee.
- `state/used_clips.json` tracks clips already used — don't reuse without reason.
