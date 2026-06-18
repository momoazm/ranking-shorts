# ai-videos-auto

Autonomous **Peter-vs-Stewie dialogue Shorts** poster. A self-contained copy of the `ai videos/`
pipeline that, on a schedule, writes a script → multi-voice voiceover → word-synced captions →
whoosh/boom SFX mix → assembles a 1080×1920 Short with avatar bounce → and uploads it to the
connected YouTube channel — **fully unattended, even when your laptop is off** (it runs in GitHub
Actions' cloud, not on your machine).

> This is a **deployable copy**. Keep editing/experimenting in the original `ai videos/`; pull
> improvements into this copy with `python sync_from_source.py`, then `git push`.

## How it runs
`.github/workflows/autopost.yml` triggers every 4 hours (`cron: 0 */4 * * *`, UTC) — 6 posts/day,
just under YouTube's 10,000-unit/day quota (1,600 units × 6 = 9,600). You can also trigger a run
manually from the repo's **Actions → autopost → Run workflow** button.

Each run: `python tools/autopost.py --privacy public`, which chains the tools in `tools/` and
publishes via `upload_youtube.py`.

## Cost / limits (per run, ×6/day)
- **YouTube Data API:** 1,600 units/upload → 9,600 / 10,000 day ✓ (binding limit → why 4h not 3h).
- **Groq** (script): 1 small completion/run — well under free-tier rate limits.
- **Edge-TTS / faster-whisper / ffmpeg:** free / local / keyless.
- **Fish Audio:** never called — the loop forces `--engine edge`. **$0.**

## Secrets (set in the repo: Settings → Secrets and variables → Actions)
The repo must be **private**. Two secrets, reconstructed into the ephemeral runner at runtime and
never committed:
- `GROQ_API_KEY` — your Groq key (from the shared `API.env`).
- `YOUTUBE_TOKEN_JSON` — the **entire contents** of `clipping/token.json` (the long-lived YouTube
  OAuth refresh token for the "ai videos" channel).

`.gitignore` excludes `API.env`, `token.json`, `*token*.json`, `.env` — these never enter git.

## Local testing
```bash
# uses the shared API.env one level up for keys; --no-upload skips publishing
python tools/autopost.py --no-upload --keep-tmp        # build .tmp/final.mp4 only
python tools/autopost.py --privacy unlisted            # build + upload UNLISTED (safe end-to-end)
```

## Layout
```
tools/        copied pipeline (write_story, generate_voiceover, align_captions,
              build_audio_mix, assemble_video) + upload_youtube.py + autopost.py
brand/        theme.json + logo
assets/       characters/{peter,stewie}.png, sfx/{whoosh,boom}.mp3, backgrounds/subway_loop.mp4
.github/workflows/autopost.yml     the every-4h schedule
sync_from_source.py                refresh tools from ../ai videos and ../clipping
```

## Copyright note
~6 public uploads/day of copyrighted characters risks Content-ID claims / strikes. To soften:
flip the workflow's `--privacy public` to `--privacy unlisted` (one line) and/or reduce cadence.
