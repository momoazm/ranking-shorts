# Workflow: Build & query the multimodal vector database

**Objective:** Embed text, images, and video with `gemini-embedding-2` and store/search
them in a single Pinecone index for cross-modal semantic search.

**Working directory:** always `CS/`. Run tools as `python tools/<name>.py ...`.

## Required inputs / credentials

- `PINECONE_API_KEY` in `CS/.env` (paste your key).
- `GEMINI_API_KEY` — reused automatically from the shared root `API.env` (no need to
  duplicate it into `CS/.env`).
- Optional `.env` overrides: `PINECONE_INDEX` (default `media-memory`),
  `PINECONE_CLOUD` (`aws`), `PINECONE_REGION` (`us-east-1`).

## Canonical sequence

1. **One-time setup** — create the index:
   ```bash
   python tools/setup_pinecone.py
   ```
   Idempotent. Returns `created: true` the first time, `false` after. Index dimension
   is **3072, cosine** — fixed forever (see edge cases).

2. **Smoke-test embeddings** (no Pinecone needed) — proves the Gemini key/SDK work:
   ```bash
   python tools/embed_content.py --text "hello world"
   ```
   Expect a 3072-length vector.

3. **Ingest** files into the index:
   ```bash
   python tools/ingest.py --path ./media --recursive
   ```
   - Text/`.md`/`.csv`/`.json`/PDF → chunked (~2k tokens/chunk), one vector per chunk.
   - Images/video/audio → one vector each.
   - Output lists upserted ids, plus `skipped` (unsupported types) and `errors`.

4. **Query** by text or by an example media file:
   ```bash
   python tools/query.py --text "a rainy city street at night" --top-k 5
   python tools/query.py --path some_image.jpg --top-k 5
   ```
   Returns ranked `matches` with score + metadata (`source_path` points back to the
   original file on disk).

## Expected outputs

Every tool prints exactly one JSON object to stdout (exit 0), or `{"error": ...}`
(exit 1). Progress lines go to stderr.

## Edge cases & constraints

- **Dimension is permanent.** Pinecone fixes index dimension at creation. To change
  it, create a new index (new `PINECONE_INDEX`) and re-ingest. `setup_pinecone.py`
  refuses to reuse an index whose dimension ≠ 3072.
- **Large files → Files API.** Files > ~15 MB (most videos) are uploaded via the
  Gemini Files API instead of inline bytes. Handled automatically in `embed_content.py`.
- **Token limit.** `gemini-embedding-2` accepts ≤ 8,192 tokens; long text is chunked.
- **Pinecone metadata cap** is 40 KB/vector — `text_snippet` is truncated to 30k chars
  and media bytes are never stored (only `source_path`).
- **Rate limits.** `embed_content._embed_contents` retries with exponential backoff on
  429/5xx. A whole-batch failure surfaces as an error rather than looping silently.
- **Re-ingesting** the same file overwrites its vectors (ids are a stable hash of
  path + chunk index), so it's safe to re-run.

## Lessons learned

- _(2026-06-20)_ Project created. `gemini-embedding-2` is natively multimodal on the
  Gemini Developer API (single API key) — text, image, video, audio, PDF all map into
  one 3072-dim space, so no Vertex AI or caption step is needed. Confirmed from
  https://ai.google.dev/gemini-api/docs/embeddings.
- _(2026-07-01)_ **Bug fixed:** `webapp/app.py` resolved the shared keys file as
  `CS/../API.env` (`projects/website/API.env`), which doesn't exist — the real `API.env`
  is at the repo root, several levels up. Locally this left `GEMINI_API_KEY` unset, so every
  question failed with "GEMINI_API_KEY is not set" (and `api.py`, which imports `app.py`,
  inherited it — the whole website backend was broken in local dev). Fixed `_load_local_env`
  to walk up parents for the nearest `API.env`, matching `tools/_common.py`. Verified end to
  end: ingest 3 text files → ask 4 questions → correct grounded answers, and an out-of-DB
  question correctly returns "I don't have that information."
- _(add notes here as you hit real rate limits, file-size quirks, or SDK changes)_
