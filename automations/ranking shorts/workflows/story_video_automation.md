# Story-Video Automation (Faceless Storytelling Shorts)

## Objective

On request ("make me a story video" / "new minecraft parkour story short"), produce a finished
**vertical (1080×1920) faceless short** for MOMO's YouTube Shorts channel (`@Moemen-i2f6l`): an
**original AI-written story** narrated over looping gameplay footage (Minecraft parkour / Subway
Surfers / whatever's trending), with word-by-word captions, then upload it to YouTube as an
**unlisted draft** — only after explicit human approval.

This is the **AI-video creation** automation foreshadowed by the competitor-analysis SOP. The
format uses **gameplay footage, not an AI video generator**, so there is **no paid video model**:
voiceover (Edge-TTS), captions (faster-whisper), and assembly (ffmpeg) are all free/local. The only
metered calls are free-tier LLM script generation and the (free) YouTube upload.

## Required inputs

- A **topic/genre** (optional). If omitted, `write_story.py` picks one from the playbook/genre.
- A **background**: a cached gameplay clip in `assets/backgrounds/`. If the needed one isn't
  cached yet, download it once with `download_background.py` (point it at a **no-copyright / CC**
  source you have the right to use — the tool does not vet rights).
- Target length in seconds (default 50). **Hard cap: clips are 2 minutes max** (user rule,
  2026-06-18) — `write_story.py` clamps `--seconds` to ≤ 120. For YouTube *Shorts* specifically,
  keep it ≤ 60 s; the 2-minute ceiling is the absolute max for any clip.

## Branding (always apply — not optional)

Captions and the optional thumbnail pull from `brand/theme.json` (gold `#C9A96C` highlight, navy
`#0B1622`, cream text `#F2E9D8`, Cinzel/Poppins). Don't re-derive colors/fonts. Logo: `brand/logo.png`.

## Tool-call sequence

All tools run from this project directory (`ai videos/`) so `_common.py` resolves `REPO_ROOT`, the
shared `../API.env`, `brand/`, and `.tmp/`. Use the project venv:
`.venv/Scripts/python tools/<name>.py ...`. Every tool prints exactly one JSON object to stdout
(success → exit 0; failure → `{"error": ...}` → exit 1) — parse stdout either way.

1. **(Periodic) Refresh the playbook** — `python tools/build_playbook.py [--seed <competitor findings>]`
   → `.tmp/playbook.json` (hook formulas, title patterns, ideal length, caption style, trending
   backgrounds, genres). Run on its own cadence; you don't rebuild it every video. You can seed it
   with the competitor project's report/findings to fold that research in.
2. **Write the story** — `python tools/write_story.py [--topic "..."] [--genre nosleep|aita|revenge|...]
   --playbook .tmp/playbook.json --seconds 50` → `.tmp/story.json`
   (`hook`, `narration`, `title`, `description`, `tags`, `background_type`, `estimated_seconds`).
3. **Voiceover** — `python tools/generate_voiceover.py --text-from .tmp/story.json [--voice en-US-GuyNeural]`
   → `.tmp/narration.mp3` (+ `duration_sec`).
4. **Captions** — `python tools/align_captions.py --audio .tmp/narration.mp3` → `.tmp/captions.ass`
   (word-level, brand-gold highlight). First run downloads the Whisper model (~150 MB) — slow once.
5. **Background** — ensure the clip exists:
   `python tools/download_background.py --url "<no-copyright gameplay URL>" --name minecraft_parkour`
   (skips if `assets/backgrounds/minecraft_parkour.mp4` is already cached). Map `background_type`
   from the story to one of your cached names.
6. **Assemble** — `python tools/assemble_video.py --audio .tmp/narration.mp3 --captions .tmp/captions.ass
   --background assets/backgrounds/<name>.mp4 [--music assets/music/bed.mp3] --out .tmp/final.mp4`.
   Optional cover: `python tools/generate_thumbnail.py --story .tmp/story.json --out .tmp/thumb.png`.
7. **Confirmation gate — never skip.** Show the user: `title`, `description`, `tags`, resolved
   **privacy = unlisted**, the **target channel** (`@Moemen-i2f6l`), duration, byte size, and that
   they should eyeball `.tmp/final.mp4` (captions in sync? audio clean? background not visibly
   looping?). Wait for an explicit go-ahead. Changes → loop back to step 2 (re-script) or just
   step 6 (re-assemble) as needed.
8. **Only after explicit confirmation:** `python tools/upload_youtube.py --video .tmp/final.mp4
   --story .tmp/story.json [--thumbnail .tmp/thumb.png] --privacy unlisted` → report video ID + URL.

## Dialogue mode — two characters arguing (the "Peter & Stewie" format)

A second format (added 2026-06-18) where two cartoon characters argue, each line in its own
voice, with both avatars on screen and the **active speaker lit up**. Same pipeline, a few flags:

- **Cast registry** — `tools/_characters.py` (tracked, unlike gitignored `assets/`) maps each
  character → Edge-TTS voice, persona (the LLM writes in-character), caption color, and the
  transparent PNG at `assets/characters/<key>.png`. Default duo: `peter`, `stewie`. A character
  with **no image on disk is simply not overlaid** (voice + captions still carry the format), so
  the pipeline never hard-depends on a copyrighted asset.
- **Character art** — two paths:
  - Already transparent: `python tools/fetch_character.py --key stewie --url "<png url>"` —
    normalizes to PNG and **reports `has_alpha`**. Insist on `has_alpha: true`; most "transparent"
    results are fake (baked checkerboard) or white-bg JPEGs and overlay as an ugly rectangle.
  - **White/checker background (the reliable path for a MATCHED pair):** grab high-quality OFFICIAL
    art (usually on white or a light checkerboard) and cut it out with
    `python tools/cutout_white_bg.py --in raw.png --out assets/characters/<key>.png [--thresh 70]`.
    It flood-fills the background inward from the borders, so interior whites (Stewie's head, Peter's
    shirt) survive. Bump `--thresh` to ~70 for a light-gray checkerboard. **Won't work on a BLACK
    background** (black = the line-art color, so the fill eats the outlines) — pick a light-bg source.
  - Either way, composite over a solid color and eyeball it before trusting it. Sourcing both
    characters as the same flat-2D standing style on a light bg gives the cleanest matched pair.
- **Script** — `python tools/write_story.py --format dialogue --characters peter,stewie
  --topic "..." --seconds 40` → `story.json` with `turns` (`speaker`,`text`) + the resolved `characters`.
- **Voiceover** — `python tools/generate_voiceover.py --text-from story.json` auto-detects `turns`,
  synthesizes each line in that speaker's `voice` **+ `pitch`** (from `_characters.py`), stitches
  them, and writes `.tmp/segments.json` (per-line `speaker`/`start`/`end`/`caption_color`). Default
  rate **+20%** (user pref, 2026-06-18). Current cast: Peter `en-US-RogerNeural` @-8Hz, Stewie
  `en-GB-RyanNeural` @+22Hz. **Engine** `--engine auto|edge|fish`: `auto` uses **Fish Audio** (the
  *real* Peter/Stewie voices via each character's `fish_voice_id`) when `FISH_AUDIO_API_KEY` is set,
  else Edge; on a Fish error (e.g. 402 no credits) `auto` falls back to Edge and notes `fish_error`.
- **Captions** — `python tools/align_captions.py --audio narration.mp3 --segments .tmp/segments.json`
  tints each word by its speaker (Peter **amber** `#FFB300`, Stewie **cyan** `#1FC3FF`), active word
  pops **white**, cues break on speaker change. (On orange/yellow backgrounds amber is low-contrast —
  the black outline keeps it legible, or re-roll the background window / pick a cooler color.)
- **Sound effects** — fetch once: `python tools/fetch_audio.py --url "<no-copyright url>" --name whoosh
  --dir assets/sfx --duration 1.3` (and `boom`; optional `--dir assets/music --name bed` for a track).
  Then mix: `python tools/build_audio_mix.py --audio narration.mp3 --segments .tmp/segments.json
  --whoosh assets/sfx/whoosh.mp3 --boom assets/sfx/boom.mp3 --boom-on both [--music assets/music/bed.mp3]
  --out .tmp/narration_mixed.mp3` → a whoosh on every line change + a boom on hook & punchline (+ ducked
  music). Skip any SFX you don't pass.
- **Assemble** — `python tools/assemble_video.py --audio .tmp/narration_mixed.mp3 ... --story story.json
  --segments .tmp/segments.json [--bounce]` (use the **mixed** audio if you ran the SFX step). Overlays
  the two avatars (A bottom-left, B bottom-right), each dimmed by default and at full opacity + slightly
  larger while speaking. **`--bounce`** makes the active avatar hop at each line start (a half-sine in the
  overlay `y` expression, single-quoted so its commas survive the filtergraph parser). The gate is identical.

## Whole-video AI visuals, hashtags & multi-platform posting (added 2026-06-20)

A third visual style and a distribution upgrade, used by the autonomous `ai-videos-auto` loop and
available here too. Same script/voice/caption pipeline; the visuals and uploads change.

- **Nano Banana visuals (`--visual-mode aigen`).** Instead of gameplay + avatar overlays, the whole
  video is drawn by **Gemini 2.5 Flash Image** ("Nano Banana"):
  - `python tools/generate_scene_images.py --story story.json --segments .tmp/segments.json
    --out-dir .tmp/scenes --manifest .tmp/scenes.json` makes **one 9:16 scene per dialogue beat**.
    **Character consistency** is held by passing the cast PNGs (`assets/characters/<key>.png`) as
    Gemini **reference images** every frame — this also sidesteps name-based content refusals (show
    the art, don't rely on a trademarked name) — plus one fixed SETTING + one fixed art STYLE
    (from `brand/theme.json`) reused in every prompt so the frames read as one continuous video.
  - The Gemini branch lives in `generate_ai_image.py:generate_gemini()` (REST `generateContent`,
    `responseModalities:["IMAGE"]`, optional inlined refs). Default chain is gemini → cloudflare →
    huggingface → pollinations, so non-Gemini calls still work.
  - `assemble_video.py --scenes .tmp/scenes.json` turns the manifest into a **Ken-Burns slideshow**
    (slow zoom per scene, hard cuts on the beats where the whoosh SFX already sits). Pass the same
    `--audio/--captions/--segments` as usual; `--scenes` takes precedence over `--background`.
  - **ALL-OR-NOTHING + budget:** any scene failure (free quota out, key unset, safety block) makes
    `generate_scene_images.py` emit `{"error":..., "fallback":"gameplay"}` so the caller downgrades
    that one video to gameplay mode rather than shipping a half-AI clip. A date-stamped
    `.tmp/image_budget.json` + `--max-images` guard the free Nano Banana quota.
- **Research-driven hashtags (the reach lever).** `write_story.py` already folds the playbook's
  `trending_hashtags`/`topic_ideas` into titles+tags; then
  `python tools/build_captions.py --story story.json --playbook .tmp/playbook.json` emits
  **per-platform** caption blocks (YouTube `#Shorts`+tags, TikTok inline ~8, IG up to 30) so every
  upload is well-tagged. Hashtags are merged from a niche core set + the LLM `tags` + the playbook.
- **3-platform posting.** `upload_youtube.py` (working), `upload_tiktok.py` (Content Posting API,
  Direct Post; `SELF_ONLY` until the app is content-audited), `upload_instagram.py` (Graph API Reels
  two-step container→publish) with `host_public.py` providing the **public URL Instagram requires**.
  All keep the `--confirm` gate. TikTok/IG need approved developer apps (TikTok ~2–6 wk + audit; Meta
  ~2–4 wk + IG Business account & linked FB Page); until approved they're skipped, YouTube still posts.

## Edge cases

- **Whisper first-run download** is slow (model fetch) and needs network; subsequent runs are
  cached and offline. If `base` is too slow on this machine, use `--model tiny`.
- **Edge-TTS** calls Microsoft's endpoint — a failure is almost always transient network, not
  quota. Retry; no credits are consumed. (Documented fallback to Gemini TTS is not yet wired.)
- **LLM fallback chain** (`_llm.py`): Groq → Cerebras → Gemini → Mistral → OpenRouter; a provider
  whose key is unset or that errors/rate-limits is skipped. A *whole-chain* failure is surfaced —
  tell the user before retrying; don't loop silently.
- **Background shorter than the narration** → `assemble_video.py` loops it automatically; if it's
  long enough it instead takes a random window so successive videos don't reuse the same segment.
- **ffmpeg** is the libx264+libass build bundled by `imageio-ffmpeg` — no system install. If the
  `ass=` filter errors on a path, ensure `captions` is a cwd-relative path (the tool already
  converts it; avoid passing an absolute `C:\...` path — the drive colon breaks the filter syntax).
- **YouTube OAuth** is a **separate** scope/token from Gmail → `youtube_token.json`. Needs YouTube
  Data API v3 enabled and your account added as a **Test user**, else `access_denied`. Custom
  thumbnails require a **verified** channel; `upload_youtube.py` reports if the thumbnail was skipped.
- **Copyright** — only download backgrounds from genuinely no-copyright/CC sources; the tool caches
  but does not check rights. Music beds in `assets/music/` must be cleared for use too.
- **Recipient/destination safety** — `upload_youtube.py` is the only irreversible step; always echo
  channel + privacy at the gate and never upload without confirmation.

## Lessons learned (update this section as you go)

- **Build + smoke test, 2026-06-18.** Full local pipeline validated end-to-end on Python 3.14.6:
  `generate_voiceover` (Edge-TTS, en-US-GuyNeural) → `align_captions` (faster-whisper `tiny`/`base`,
  CPU int8) → `assemble_video` produced a valid **1080×1920 H.264 + AAC, 30fps** short with the
  gold word-by-word captions burned in. `write_story` and `build_playbook` work on the Groq tier of
  the `_llm.py` chain. All deps (incl. `ctranslate2`/`faster-whisper`/`av`) had cp314 wheels — no
  source builds.
- **Python 3.14 argparse gotcha:** argparse now validates `help=` strings as `%`-format templates,
  so a literal `%` in help text raises "badly formed help string". Keep `%` out of `help=` (or
  escape as `%%`). Fixed once already in `generate_voiceover.py`'s `--rate` help.
- **`google.generativeai` is deprecated** (prints a FutureWarning to stderr; still functional). It's
  only the 3rd LLM fallback. If it ever breaks, migrate `_llm.py:_gemini` to the `google-genai` SDK.
- **Whisper first run** downloads the model from HF (prints a harmless "unauthenticated"/symlink
  warning to stderr); set `HF_TOKEN` for faster pulls if needed. JSON stdout stays clean.
- **`write_story` background_type:** without a playbook the model may pick a thematic word; the
  schema hint now steers it to a real gameplay background, and a playbook's `trending_backgrounds`
  overrides it. Map whatever it returns to one of your cached `assets/backgrounds/` names.
- **First real end-to-end run, 2026-06-18.** Made "I Found A Door In My Basement" (nosleep, 13s)
  over a real Minecraft parkour background and emailed it for review. Findings:
  - **Background download:** `--download-sections` (ffmpeg byte-range) gets **403 Forbidden** from
    googlevideo — YouTube throttles ffmpeg range requests. yt-dlp's **native** downloader works.
    For a quick clip, pull a small **progressive** format full (`-f 18`, 360p ≈ 165 MB for ~30 min)
    rather than the 1080p AV1 (≈ 1 GB). 360p upscaled to 1080×1920 is fine for tests, soft for
    production — grab a higher-res format for real posts.
  - **Email as a review channel** (not the standing delivery — YouTube is): the `ai videos` project
    has no Gmail setup, so reuse the **newsletter** project's OAuth. Note the **newsletter venv
    lacks `python-dotenv`** — run its `send_gmail_email.py` with the `ai videos` venv interpreter
    from the `newsletter/` dir so `token.json` resolves.
  - **Gmail API inline send times out (~60s socket) on ~11 MB over a slow link** ("write operation
    timed out"). Re-encode the short down (720×1280, CRF 30 → ~2.5 MB) before emailing.
- **Caption `.ass` bug (fixed 2026-06-18):** the `[Events]` `Format:` line MUST list all 10
  standard fields — `Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text`.
  Omitting `Name`/`MarginV` made libass parse the `0,0,0,,` margin/effect values as part of the
  caption text, so every line showed a literal `0,,` prefix on screen. The `[V4+ Styles]` Format
  likewise needs `SecondaryColour`. Keep the Dialogue values aligned to that 10-field layout.
- **Dialogue mode built + tested, 2026-06-18.** Made a Peter-vs-Stewie "Is a hot dog a sandwich?"
  short (12 turns, 29s) over Minecraft parkour. Multi-voice VO (Peter `en-US-GuyNeural`, Stewie
  `en-GB-RyanNeural`), per-speaker captions, and active-speaker avatar highlight all verified by
  extracting frames. Findings:
  - **Transparency is the trap.** `fetch_character.py` reports `has_alpha`; trust it, not the
    thumbnail. The first Stewie (vhv.rs) had a *baked-in checkerboard* (alpha present but a grey
    checker pattern painted into the pixels) → showed as a grey box on screen. clipartmax/cleanpng
    "PNG/webp" were white-bg JPEGs (`has_alpha:false`). The clean one was a Fandom wiki render.
    Always composite the PNG over a solid color and eyeball it before compositing the full video.
  - **Style consistency:** the working Stewie is a 3D render while Peter is flat 2D — usable but
    mismatched. For a polished channel, source both avatars in the same art style (or generate an
    original matched pair). The registry makes swapping a one-liner.
  - **Edge-TTS ≠ character voices.** It gives *distinct* voices (deep US male, posh British male),
    not the actual cartoon voices. Good enough for the format; set expectations accordingly.
  - **Copyright:** famous-character art + likeness is copyrighted (user accepted the risk,
    2026-06-18). `fetch_character.py` does **not** vet rights. Demonetization/strike risk on a real
    channel — flag it; keep assets swappable so they can be replaced with originals later.
- **Matched art + Subway Surfers run, 2026-06-18.** Second dialogue clip "Pineapple Pizza Freakout"
  (21 turns, **46s** — longer) over a 4K **vertical** no-copyright Subway Surfers background
  (`assets/backgrounds/subway_surfers.mp4`, 3.5 min, ~1080×1920). Vertical source = no cropping.
  Findings:
  - **`cutout_white_bg.py` is the fix for the transparency trap.** Sourced both Peter (white-shirt
    standing) and Stewie as official flat-2D art on light backgrounds and flood-cut them → a clean,
    *matched* pair. `--thresh 70` handled the light checkerboard; black-bg art is unusable (eats the
    outlines). Verify each cutout's `opaque_ratio` (a value near 1.0 means nothing was removed) and
    eyeball it over a solid color.
  - **Email size scales with length:** 46s → the 720×1280/CRF30 re-encode was 13 MB (over the ~11 MB
    Gmail-timeout line). Dropped to 640×1138/CRF34/80k audio → 8.3 MB, sent fine. For longer clips,
    push CRF/scale down further before emailing (YouTube is the real delivery; email is review-only).
  - **Pillow** added to the venv for the cutout tool (numpy was already present; PIL/scipy/imageio
    were not).
- **Voice/pitch/color tuning, 2026-06-18 (clip #3 "Duck Horse Showdown").** Per-character casting
  now lives in `_characters.py`: each has `voice`, **`pitch`** (Edge-TTS `<sign><n>Hz`), and a vivid
  `caption_color`. Current duo: Peter = `en-US-RogerNeural` @ `-8Hz` (bigger/goofier), amber `#FFB300`;
  Stewie = `en-GB-RyanNeural` @ `+22Hz` (high posh baby-genius), cyan `#1FC3FF`. Pitch + accent does
  the "sounds like the character" work. Default speech rate raised to **+20%** (was +12%).
  `generate_voiceover.py` passes per-line `pitch`; colors flow story.json → segments.json → captions.
  - **Caption contrast depends on the background window.** Amber over a bright-orange Minecraft
    (nether) section is low-contrast; the thick black outline keeps it legible, but for orange/yellow
    backgrounds prefer a cooler caption color or re-roll the background window. Cyan pops everywhere.
  - **Gmail timeout is transient, not just size:** a 5.3 MB attachment still hit "write operation
    timed out" once over a slow link, then **sent on a simple retry**. The `.eml` is already built,
    so just re-run `send_gmail_email.py --eml ...` — don't rebuild.
- **Sound effects added, 2026-06-18 (clip #4 "Birds Are Spy Drones!").** Research: every competitor
  tool advertises "sound effects & captions" — the standard kit is a ducked music bed + a transition
  **whoosh** on each line + an impact **boom** on the punchline. Implemented as two new tools:
  `fetch_audio.py` (httpx for direct audio URLs / yt-dlp for YouTube + page URLs → trimmed mp3) and
  `build_audio_mix.py` (VO + whoosh-per-turn + boom-on-hook/punchline + optional looped/ducked music
  → one `narration_mixed.mp3`, fed to assemble as `--audio`). Findings:
  - **Sourcing:** grabbed boom from the Internet Archive and whoosh from a single-SFX YouTube short via
    yt-dlp (`--via ytdlp`, both tiny). Royalty-free **music** with a clean direct-download URL is harder
    (Pixabay needs a token; Bensound/library pages aren't hotlinkable) — left music as an optional flag;
    whoosh + boom are the core SFX and reliably fetchable.
  - **Mixing:** `amix=...:normalize=0` (so levels aren't divided down) + a final `alimiter` to avoid
    clipping when a boom and the voice overlap. `adelay=<ms>:all=1` places each SFX; one whoosh input is
    `asplit`-duplicated to N line-change times. Keep VO at 1.0, whoosh ~0.45, boom ~0.8, music ~0.10.
  - 19-turn script → 18 whooshes; booms on hook + final. The mixed track is the same length as the VO,
    so the existing assemble/`-t` logic is unchanged.
- **Fish Audio voices + bounce, 2026-06-18 (clip #5 "Stewie's World Domination Plan").**
  - **Fish Audio** wired in as a TTS engine (`fish-audio-sdk`): per-character `fish_voice_id` in
    `_characters.py` (Peter `d75c270e...`, Stewie `e91c4f59...`), key in the **shared `API.env`** as
    `FISH_AUDIO_API_KEY` (NOT a per-project `.env` — repo convention). The user's key authenticates,
    but the account returned **402 Payment Required** (no credits), so renders still use the Edge
    fallback. `--engine auto` catches the 402 and falls back to Edge automatically (records `fish_error`).
    Once credits are added, `auto` will use the real character voices with no other change.
  - **Bounce** (`assemble_video.py --bounce`): the active avatar hops at each line start. Implemented
    as a half-sine bump added to the active overlay's `y` per the speaker's segment starts; the `y`
    value MUST be single-quoted (`y='...'`) so the commas inside `between()/sin()` aren't read as
    filtergraph separators. ~36px / 0.3s reads as a subtle, on-format hop. Verified by comparing a
    peak-hop frame vs. a settled frame (the bright active copy lifts above its dim base copy).
  - **Music** still pending a clean no-copyright source (user skipped the search this round).
- **Not yet exercised (need your input):** `youtube_auth_setup`/`upload_youtube` (need YouTube
  Data API v3 enabled + OAuth consent). Mirrors the Gmail OAuth flow; import/path-validated.
- **Nano Banana visuals + hashtags + 3-platform, 2026-06-20.** Added whole-video AI imagery, per-
  platform hashtags, and TikTok/Instagram uploaders (see the new section above). Findings:
  - **aigen ffmpeg path validated** end-to-end with fixtures: 2 scene PNGs + silent VO + minimal
    `.ass` → a valid **1080×1920 H.264+AAC** clip via `zoompan` (oversample 2× to keep the zoom
    smooth) + `concat` (hard cuts) + burned captions. `assemble_video.py --scenes` branch verified.
  - **Graceful degradation verified:** with no `GEMINI_API_KEY`, `generate_scene_images.py` emits
    `fallback:"gameplay"` (exit 1) and `autopost.py` downgrades that video to gameplay mode;
    `upload_tiktok.py`/`upload_instagram.py` emit a clean JSON error (not a crash) when creds are
    absent, so `autopost` records them as `skipped` and still posts YouTube.
  - **Free tier (decided with user):** free image tier only; default **6 videos/day cross-posted to
    all 3 platforms** (YouTube's free ceiling), enforced by a date-stamped `.tmp/daily_count.json` +
    `MAX_DAILY_VIDEOS`. ~78 images/day, far under the ~500/day free Nano Banana figure (verify live;
    the newest image model may be stricter — the budget is config-driven with a gameplay fallback).
  - **Source-first coupling:** `ai-videos-auto/sync_from_source.py` re-copies pipeline tools FROM
    here, so all new tools were mirrored into `ai videos/tools/` and added to its sync list to avoid
    a future sync clobbering them. Edit here, then `python sync_from_source.py` in the copy.
- **Nano Banana has NO free tier; auto-fallback + Gmail delivery, 2026-06-21.** Confirmed via a live
  call: `gemini-2.5-flash-image` returns **HTTP 429 with `generate_content_free_tier_requests
  limit: 0`** — it only works on a **billing-enabled** Google project (~$0.039/image). So
  `generate_scene_images.py` now takes `--provider auto` (default): try Nano Banana first, fall back
  to the **FREE** chain (Cloudflare FLUX → HF → Pollinations) on failure, and **pin** the first
  working provider so the whole video stays consistent (and we don't re-hit the dead Gemini call per
  scene). Character consistency on the free path leans on the per-character `visual` descriptors in
  `_characters.py` (free providers ignore reference images).
  - **End-to-end verified:** built "Tung vs Tralalero: Brainrot Supremacy" (6 Cloudflare-FLUX scenes,
    1080x1920 H.264, 32.6s, 8.5 MB) and **emailed it** via `email_video.py` (reuses the
    newsletter/competitor Gmail `gmail.send` token; `GMAIL_TOKEN_PATH` → that token.json). Nano
    Banana was attempted first, 429'd, and the run transparently used Cloudflare.
  - **Delivery for manual posting:** IG/TikTok official APIs were blocked at account/business
    verification, so the chosen workflow is **semi-manual** — `autopost.py --platforms youtube,email`
    auto-posts YouTube and emails the video + per-platform captions for the user to post by hand
    (`export` saves the same to `exports/` / a CI artifact).
  - **To enable real Nano Banana later:** turn on Gemini billing; no code change needed (auto picks it
    up). `write_story`'s `background_type` doubles as the aigen scene "setting" — consider a dedicated
    scene-setting field if subway-surfers-as-AI-scene isn't wanted.
