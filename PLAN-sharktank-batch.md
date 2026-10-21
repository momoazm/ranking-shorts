# PLAN — Shark Tank: post every part, competitor visual format (2026-10-21)

Status: in progress
Owner: Moemen / opencode session
Sibling plan: `../clipping-auto/PLAN-competitor-format.md`
Vault summary: `PLAN-sharktank-batch-and-formats.md`

## Goal

1. **Upload all the clips.** One scheduled run must post a batch of the remaining parts of
   the current episode (default 4, capped by a 24h IG budget), not exactly one part.
2. **Never get stuck on a part.** A failed part/upload must not be retried forever while the
   rest of the episode waits. Per-part strikes + a durable ledger in git fix this.
3. **Adopt the winning competitor format** (evidence: top Shark Tank Shorts 826K–2.4M views):
   full-bleed 9:16 crop, centered word-level burned captions, persistent all-caps multi-color
   hook banner, tiny handle, CTA. No top title card, no "(Part N/N)" in the title.
4. **Competitor-style post titles** (curiosity gap, no part label); part info moves to the
   description. Deterministic fallback must always be a clean, complete phrase.

## Root causes (evidence from the repo + Actions runs)

- `rank_autopost.py` builds exactly one entry per run (`for entry in verified: ... break`).
- `state/` lives only in the Actions cache; the cache post-step is success-gated, so a failed
  IG delivery rolls `used_clips.json` + `sharktank_inprogress.json` back and the same part is
  reposted next run (observed: `Part 2/8` failed 5+ times on 2026-10-20/21).
- The failing posts were hosted on `tmpfiles.org/dl/...`; successful posts used
  `litter.catbox.moe`. IG's transcoder threw `progressive_video_not_ready` /
  `MediaInfoExtractionException` on the tmpfiles URL.
- The overlay is the old top title card + badge + part label, not the competitor pattern.
- `title_part.py`'s Groq call used `max_tokens=300`; gpt-oss-120b is a reasoning model, so the
  hidden reasoning consumed the whole budget and Groq returned
  `json_validate_failed ... failed_generation: ''` — EVERY part fell back to the deterministic
  sentence. Fixed with `max_completion_tokens=1500` + `reasoning_effort=low`, plus a fallback
  onto the shared `_llm` provider chain so a Groq 429 does not lose the LLM title.

## Work checklist

### A. Batch posting (rank_autopost.py)

- [x] A1. New `--parts-per-run` flag (env `SHARKTANK_PARTS_PER_RUN`, default 4; `0` = all
      remaining parts), plus `--part-gap-sec` (default 45) pacing between posts.
- [x] A2. `run_sharktank_batch()`: pick the front in-progress video, download its source
      ONCE (`fetch_source.py`), then for each remaining part: transcribe → title → build →
      prepare media → captions → host → publish → `record_used` immediately.
- [x] A3. Per-part attempt strikes `state/sharktank_attempts.json` (3 strikes / 7 days =
      skip that part for the run, keep the episode moving; never delete a part).
- [x] A4. Rolling 24h post budget `state/sharktank_daily.json` (default 15/24h, under IG's
      25-posts/24h API limit); sharktank bypasses the old per-run `MAX_DAILY_VIDEOS` gate.
- [x] A5. On IG transcode failure: re-host the SAME mp4 on the next provider and retry once;
      record both provider + attempt in the result JSON.
- [x] A6. `--no-upload` keeps the single-part QA path (and gets the new kinetic overlay).
- [x] A7. Batch result JSON includes per-part status, so the artifact/log shows exactly which
      parts published, failed, or were skipped.
- [x] A8. Cleanup: keep the downloaded source + built parts out of the repo; delete scratch
      only on a publishing run.

### B. Hosting reliability (host_public.py)

- [x] B1. Verify every candidate URL actually serves video bytes (HTTP 200, video content
      type, non-trivial length) before returning it; try the next host on failure.
- [x] B2. Add Pixeldrain as an additional provider; keep catbox/litterbox first and tmpfiles
      late (it is the host that failed IG's transcoder).
- [x] B3. Add `--exclude <provider>` so the retry path can force a different host.

### C. Competitor visual format (build_clip.py)

- [x] C1. `--fit crop`: full-bleed 9:16 center crop (default stays `fit` for other formats;
      sharktank passes `crop`). Audio silence/keep logic mirrors `brv.normalize`.
- [x] C2. `--style kinetic`: persistent 2–3 line ALL-CAPS hook banner at the top, centered,
      multi-color key words (brand gold / teal / red-flag accent), thick black stroke; NO top
      title card, NO badge, NO part label; tiny `@itsmomoclips` handle at the bottom; CTA pop
      in the last 2.2s. `classic` keeps today's look.
- [x] C3. `--captions words` + `--words <json>`: burned word-level captions (3 words/screen,
      active word gold, font Anton), timed from Groq Whisper. Failure = overlay-only render,
      never a failed build.
- [x] C4. Hook text is derived from the part (LLM hook when available, clean source hook as
      fallback), uppercased and wrapped to ≤3 lines; part number is NOT burned in.
- [x] C5. Emit `downloaded_source_file` so the batch can reuse one download.
- [x] C6. Copy the OFL Anton font into `brand/fonts/` and install it in the workflow.

### D. New tools

- [x] D1. `fetch_source.py`: wraps `brv.download()` with `--url/--out/--max-height/
      --download-deadline/--download-attempt-timeout`; prints `{"path", "byte_size"}`.
- [x] D2. `transcribe_segment.py`: Groq Whisper word timestamps for one `[start, start+dur]`
      slice; library function + CLI; short timeout, graceful failure.
- [x] D3. `title_part.py`: per-part curiosity-gap post title + short banner hook (Groq-first,
      deterministic complete-sentence fallback, no "Part N", no mid-word cuts).

### E. Workflow (.github/workflows/autopost.yml)

- [x] E1. `workflow_dispatch` input `parts` (0–12, default from the env/default 4) →
      `SHARKTANK_PARTS_PER_RUN`.
- [x] E2. Commit the durable ledgers in the always() step: `used_clips.json`,
      `sharktank_inprogress.json`, `sharktank_attempts.json`, `sharktank_daily.json`.
- [x] E3. After the state-cache restore, reset those tracked ledgers to the git version so a
      stale cache can never resurrect an already-posted part.
- [x] E4. Install the brand font (`brand/fonts/*.ttf` → `~/.local/share/fonts`, `fc-cache`).

### F. Tests

- [x] F1. Batch planner: limit/pacing/strike/daily-budget logic with fake entries.
- [x] F2. Kinetic ASS: no title card/badge, ≤3 hook lines, caption events, handle, CTA.
- [x] F3. Title generator fallback: complete phrase, no part label, no mid-word cut.
- [x] F4. Host verification order + `--exclude`.
- [x] F5. Existing ranking-shorts suite still green.

## Verification

- [x] `python -m pytest tests -q` in the repo (offline tests only).
- [x] Render a real 45–60s part locally with `--style kinetic --fit crop --captions words`
      (video QA: hook banner, captions, handle, CTA, no title card).
- [ ] `--no-upload` run on a dispatch exercises the same render path.
- [x] Dry-run batch planning JSON shows N parts queued, pacing, and the daily budget.

## Ship

- [ ] Commit (own files only) → push `main` → watch the first scheduled run's artifact.
- [ ] Confirm the run posts >1 part and that `state/used_clips.json` is committed even if one
      part fails.
