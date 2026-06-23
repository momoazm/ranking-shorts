---
title: CS Chat
emoji: 💬
colorFrom: indigo
colorTo: blue
sdk: gradio
app_file: app.py
pinned: false
---

# CS Chat

A mobile-friendly RAG chat app over the CS Pinecone vector database.

- **Chat** tab: ask questions; answers are grounded in your ingested data.
- **Add data** tab: upload files (text/image/video/audio/PDF) or paste text to embed
  and store in the vector DB.

Powered by Google `gemini-embedding-2` (multimodal embeddings) + `gemini-2.5-flash`
(answers) + Pinecone (vector store).

## Required Space secrets (Settings → Variables and secrets)

| Secret | Value |
| --- | --- |
| `GEMINI_API_KEY` | your Google Gemini API key |
| `PINECONE_API_KEY` | your Pinecone key |
| `PINECONE_INDEX` | `media-memory` |
| `GEMINI_CHAT_MODEL` | *(optional)* defaults to `gemini-2.5-flash` |

See `DEPLOY.md` for full deployment steps.
