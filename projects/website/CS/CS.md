# CLAUDE.md — `CS/` project

This is a **WAT project** (Workflows, Agents, Tools) — see the repo-root `CLAUDE.md`
for the framework philosophy. This file covers what's specific to `CS/`.

## What this project does

A **multimodal vector database**: embed text, images, and video with Google's
`gemini-embedding-2` model and store/search the vectors in **Pinecone**. Because the
Gemini model maps every modality into the **same vector space**, a single Pinecone
index gives true cross-modal search — find the video that matches a sentence, or the
articles that match an image.

Pipeline: `setup_pinecone.py` (once) → `ingest.py` (load files) → `query.py` (search).
The reusable core is `embed_content.py`, which both ingest and query call.

The governing SOP is [workflows/build_vector_db.md](workflows/build_vector_db.md) —
read it before running the pipeline.

## Working directory & credentials

- **Run every tool with `CS/` as the working directory**, e.g.
  `python tools/ingest.py --path ...`. Tools import `_common` as a sibling (no
  `tools.` prefix), so they only work when invoked this way (matches `newsletter/`).
- **Key precedence:** `_common.load_env()` loads the project-local `.env` **first**,
  then the shared root `API.env` as a fallback. So `PINECONE_API_KEY` lives in
  `CS/.env`, and `GEMINI_API_KEY` is reused from the shared `API.env` automatically
  (no duplication). `.env` is gitignored.

## Environment setup

```bash
cd CS
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt
# paste PINECONE_API_KEY into CS/.env
.venv/Scripts/python tools/setup_pinecone.py
```

## Tool conventions (same as every WAT project)

- Standalone CLIs run as `python tools/<name>.py --flag ...` from `CS/`.
- **Always print exactly one JSON object to stdout.** Success → exit 0; failure → a
  JSON object with an `"error"` key and exit 1 (`_common.emit`/`fail`). Per-item
  progress goes to **stderr** so stdout stays a single clean JSON object.

## Hard rules specific to this project

- **The index dimension (3072) is permanent.** Pinecone fixes a vector index's
  dimension at creation. `gemini-embedding-2` runs at its native 3072 dims (already
  normalized — no renormalization needed). Changing the dimension later means a new
  index and a full re-ingest. Don't silently switch dims mid-stream.
- **Large files use the Files API, not inline bytes.** Files ≤ ~15 MB are sent inline
  via `Part.from_bytes`; larger ones (most videos) go through `client.files.upload`.
  Preserve this split in `embed_content.py`.
- **Media bytes are never stored in Pinecone** — only a `source_path` reference plus
  small metadata (Pinecone caps metadata at 40 KB/vector). Keep originals on disk.
- Text over the 8,192-token model limit is chunked (~2,000-token windows), one vector
  per chunk, id `<file>#<n>`.
