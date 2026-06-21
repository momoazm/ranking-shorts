# ai-videos-auto

Autonomous **Peter-vs-Stewie brainrot Shorts** poster. A self-contained copy of the `ai videos/`
pipeline that, on a schedule, writes a script → multi-voice voiceover → word-synced captions →
whoosh/boom SFX mix → **builds the whole video from Nano Banana (Gemini) AI scene images** →
attaches research-driven hashtags → and **cross-posts to YouTube + TikTok + Instagram** —
**fully unattended, even when your laptop is off** (it runs in GitHub Actions' cloud).

## What's new
- **Fully-AI visuals (`--visual-mode aigen`, default):** `generate_scene_images.py` draws one 9:16
  scene per dialogue beat; `assemble_video.py` turns them into a Ken-Burns slideshow cut on the
  beats. **No gameplay/subway background** — the whole video is AI-generated.
- **Provider = `auto` (Nano Banana when it works, else free):** tries **Gemini 2.5 Flash Image
  (Nano Banana)** first, and on a limit error falls back to the **FREE** chain (Cloudflare FLUX →
  Pollinations). ⚠️ Nano Banana has **no free tier** (quota `limit: 0`) — it only runs once you
  enable **paid** Gemini billing; until then videos are made free by Cloudflare FLUX. The working
  provider is "pinned" so a whole video stays visually consistent.
- **Brainrot cast:** default duo is the Italian-brainrot memes **Tung Tung Tung Sahur + Tralalero
  Tralala** (with visual descriptors so the model draws them right). Peter/Stewie remain alternates.
- **Research-driven hashtags:** `build_playbook.py` (cached ~daily) pulls trending hooks/hashtags
  into `write_story`, and `build_captions.py` emits per-platform caption/hashtag blocks.
- **Delivery:** `upload_youtube.py` auto-posts; **`email`** Gmails the finished video + ready-to-paste
  IG/TikTok/YouTube captions to you (default, via `email_video.py`); **`export`** saves the same to
  `exports/<date>-<title>/`. `upload_tiktok.py`/`upload_instagram.py` exist for when you get API
  access; unconfigured platforms are skipped cleanly.
- **Limits:** hard cap of **12 images/video** (long scripts are grouped), throttle between calls,
  and a date-stamped `--max-videos` (default **6**) so retries/overlaps can't over-post.

> This is a **deployable copy**. Keep editing/experimenting in the original `ai videos/`; pull
> improvements into this copy with `python sync_from_source.py`, then `git push`.

## How it runs
`.github/workflows/autopost.yml` triggers every 4 hours (`cron: 0 */4 * * *`, UTC) — 6 posts/day,
just under YouTube's 10,000-unit/day quota (1,600 units × 6 = 9,600). You can also trigger a run
manually from the repo's **Actions → autopost → Run workflow** button.

Each run: `python tools/autopost.py --privacy public --platforms youtube,tiktok,instagram`, which
chains the tools in `tools/` and publishes one video to each configured platform.

## Cost / limits (per run, ×6/day)
- **YouTube Data API:** 1,600 units/upload → 9,600 / 10,000 day ✓ (binding limit → why 4h not 3h).
- **Nano Banana (Gemini 2.5 Flash Image):** ~12–13 images/video → ~78/day across 6 runs. Free tier
  is ~500/day (verify; the newest model may be stricter). On exhaustion → gameplay fallback. **$0** on free tier.
- **Groq** (script): 1 small completion/run — well under free-tier rate limits.
- **Edge-TTS / faster-whisper / ffmpeg:** free / local / keyless.
- **Fish Audio:** never called — the loop forces `--engine edge`. **$0.**

## Secrets (set in the repo: Settings → Secrets and variables → Actions)
The repo must be **private**. Secrets are reconstructed into the ephemeral runner at runtime and
never committed. **Required:**
- `GROQ_API_KEY` — your Groq key (from the shared `API.env`).
- `YOUTUBE_TOKEN_JSON` — the **entire contents** of `clipping/token.json` (the long-lived YouTube
  OAuth refresh token for the "ai videos" channel).

**Optional (enable as you get them):**
- `GEMINI_API_KEY` — Nano Banana visuals (without it, `aigen` downgrades to gameplay mode).
- `TAVILY_API_KEY`, `EXA_API_KEY` — playbook research (degrades to model priors if absent).
- TikTok: `TIKTOK_ACCESS_TOKEN` (+ optional `TIKTOK_REFRESH_TOKEN`/`TIKTOK_CLIENT_KEY`/`TIKTOK_CLIENT_SECRET`).
- Instagram: `IG_USER_ID`, `IG_ACCESS_TOKEN`.

> **TikTok/Instagram need approved apps before auto-posting works** — TikTok Content Posting API
> (~2–6 wk review; **posts are forced private until the app is content-audited**) and a Meta app
> with `instagram_business_content_publish` (~2–4 wk review, IG Business account + linked FB Page).
> Until then those platforms are skipped automatically and only YouTube posts.

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
