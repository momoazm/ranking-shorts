---
type: entity
tags: [project, web, ai]
created: 2026-07-01
updated: 2026-07-01
sources: [s007]
status: active
---

# CS — MOMO RAG / multimodal vector DB

MOMO's **multimodal RAG system** (`projects/website/CS/`): embed text, images, video & audio with
Google `gemini-embedding-2` into one shared vector space and store/search them in **Pinecone**
(index `media-memory`, 3072 dims) — true cross-modal search. Pipeline `setup_pinecone → ingest →
query` (core `embed_content.py`); answers via `gemini-2.5-flash`. Also ships a Gradio "CS Chat"
RAG webapp. Rules → [CS.md](../../projects/website/CS/CS.md).

## Relationships
- **is part of** [[website]] · **powers** [[momo-website]] · **uses** Gemini + Pinecone
- **api-keys** [[api-fallback-chains]] (`GEMINI_API_KEY` shared, `PINECONE_API_KEY` in `CS/.env`)
