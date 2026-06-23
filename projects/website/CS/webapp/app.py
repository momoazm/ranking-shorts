"""CS Chat — a mobile-friendly RAG web app over the CS Pinecone vector database.

Two tabs:
  • Chat     — ask questions; the app embeds the question, retrieves the most
               relevant items from Pinecone, and Gemini answers grounded in them.
  • Add data — upload files (image/video/text/pdf) and/or paste text to embed and
               store in the vector DB.

Self-contained on purpose: a Hugging Face Space is its own repo, so the small bit
of embed/Pinecone logic from CS/tools/ is inlined here rather than imported.

Credentials come from environment variables (Space secrets in production). For
local dev it also loads CS/.env then the shared root API.env, applying only
non-empty local values so a blank GEMINI_API_KEY line doesn't shadow the real key.
"""
import datetime
import hashlib
import mimetypes
import os
import time
from pathlib import Path

import gradio as gr

# ---------------------------------------------------------------------------
# Config & environment
# ---------------------------------------------------------------------------
EMBED_MODEL = "gemini-embedding-2"
EMBED_DIM = 3072
INLINE_MAX_BYTES = 15 * 1024 * 1024  # ≤15 MB inline; larger → Files API

TEXT_EXTS = {".txt", ".md", ".markdown", ".rst", ".csv", ".json", ".log"}
CHUNK_CHARS = 8000          # ≈2k tokens
SNIPPET_CHARS = 500
META_TEXT_CAP = 30000       # keep under Pinecone's 40 KB/vector metadata cap
TOP_K = 5


def _load_local_env():
    """Local-dev convenience: load CS/.env then ../API.env, non-empty wins.
    On a Space there's no .env file, so this is a harmless no-op there."""
    try:
        from dotenv import dotenv_values, load_dotenv
    except Exception:
        return
    here = Path(__file__).resolve()
    cs_root = here.parent.parent            # .../CS
    shared = cs_root.parent / "API.env"     # repo-root shared keys
    if shared.exists():
        load_dotenv(shared)
    local = cs_root / ".env"
    if local.exists():
        for k, v in dotenv_values(local).items():
            if v:
                os.environ[k] = v


_load_local_env()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_CHAT_MODEL = os.environ.get("GEMINI_CHAT_MODEL", "gemini-2.5-flash")
PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY", "")
PINECONE_INDEX = os.environ.get("PINECONE_INDEX", "media-memory")

# ---------------------------------------------------------------------------
# Lazy clients (built once)
# ---------------------------------------------------------------------------
_genai_client = None
_pc_index = None


def genai_client():
    global _genai_client
    if _genai_client is None:
        from google import genai
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set.")
        _genai_client = genai.Client(api_key=GEMINI_API_KEY)
    return _genai_client


def pinecone_index():
    global _pc_index
    if _pc_index is None:
        from pinecone import Pinecone
        if not PINECONE_API_KEY:
            raise RuntimeError("PINECONE_API_KEY is not set.")
        _pc_index = Pinecone(api_key=PINECONE_API_KEY).Index(PINECONE_INDEX)
    return _pc_index


# ---------------------------------------------------------------------------
# Embedding (ported from CS/tools/embed_content.py)
# ---------------------------------------------------------------------------
def _embed(contents):
    from google.genai import types
    client = genai_client()
    last_err = None
    for attempt in range(4):
        try:
            result = client.models.embed_content(
                model=EMBED_MODEL,
                contents=contents,
                config=types.EmbedContentConfig(output_dimensionality=EMBED_DIM),
            )
            return list(result.embeddings[0].values)
        except Exception as e:
            last_err = e
            msg = str(e).lower()
            if any(s in msg for s in ("429", "rate", "quota", "503", "500", "unavailable", "timeout")):
                time.sleep(2 ** attempt)
                continue
            raise
    raise RuntimeError(f"Embedding failed after retries: {last_err}")


def embed_text(text):
    if not text or not text.strip():
        raise ValueError("Cannot embed empty text.")
    return _embed([text])


def embed_file(path, mime_type=None):
    from google.genai import types
    p = Path(path)
    mime_type = mime_type or mimetypes.guess_type(str(p))[0]
    if not mime_type:
        raise ValueError(f"Could not infer MIME type for {p.name}.")
    if p.stat().st_size <= INLINE_MAX_BYTES:
        part = types.Part.from_bytes(data=p.read_bytes(), mime_type=mime_type)
        return _embed([part]), mime_type
    uploaded = genai_client().files.upload(file=str(p))
    return _embed([uploaded]), mime_type


# ---------------------------------------------------------------------------
# Ingest helpers (ported from CS/tools/ingest.py)
# ---------------------------------------------------------------------------
def _stable_id(key, chunk=0):
    h = hashlib.sha1(f"{key}#{chunk}".encode("utf-8")).hexdigest()[:24]
    return f"{h}-{chunk}"


def _chunk_text(text):
    text = text.strip()
    if len(text) <= CHUNK_CHARS:
        return [text] if text else []
    chunks, start = [], 0
    while start < len(text):
        end = min(start + CHUNK_CHARS, len(text))
        if end < len(text):
            brk = text.rfind("\n", start, end)
            if brk == -1 or brk <= start:
                brk = text.rfind(" ", start, end)
            if brk > start:
                end = brk
        chunks.append(text[start:end].strip())
        start = end
    return [c for c in chunks if c]


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _upsert(vectors):
    index = pinecone_index()
    for i in range(0, len(vectors), 100):
        index.upsert(vectors=vectors[i:i + 100])


def _ingest_text_blob(label, text):
    """Embed a text string (chunked) → list of Pinecone vector dicts."""
    vectors = []
    for i, chunk in enumerate(_chunk_text(text)):
        vectors.append({
            "id": _stable_id(label, i),
            "values": embed_text(chunk),
            "metadata": {
                "modality": "text",
                "source_path": label,
                "filename": label,
                "mime_type": "text/plain",
                "chunk": i,
                "text_snippet": chunk[:META_TEXT_CAP],
                "ingested_at": _now(),
            },
        })
    return vectors


# ---------------------------------------------------------------------------
# UI-facing functions
# ---------------------------------------------------------------------------
def ingest_uploads(files, pasted_text):
    """Embed uploaded files + pasted text and upsert to Pinecone. Returns status."""
    vectors, added, errors = [], [], []

    # Pasted text
    if pasted_text and pasted_text.strip():
        try:
            label = f"pasted-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
            vs = _ingest_text_blob(label, pasted_text)
            vectors.extend(vs)
            added.append(f"pasted text ({len(vs)} chunk(s))")
        except Exception as e:
            errors.append(f"pasted text: {e}")

    # Uploaded files
    for fobj in files or []:
        fpath = Path(fobj.name if hasattr(fobj, "name") else fobj)
        mime = mimetypes.guess_type(str(fpath))[0]
        try:
            if fpath.suffix.lower() in TEXT_EXTS or (mime or "").startswith("text/"):
                text = fpath.read_text(encoding="utf-8", errors="replace")
                vs = _ingest_text_blob(fpath.name, text)
                if not vs:
                    errors.append(f"{fpath.name}: empty")
                    continue
                vectors.extend(vs)
                added.append(f"{fpath.name} ({len(vs)} chunk(s))")
            elif mime and (mime.startswith(("image/", "video/", "audio/")) or mime == "application/pdf"):
                vec, mime_type = embed_file(fpath, mime)
                modality = mime_type.split("/", 1)[0]
                vectors.append({
                    "id": _stable_id(fpath.name, 0),
                    "values": vec,
                    "metadata": {
                        "modality": modality,
                        "source_path": fpath.name,
                        "filename": fpath.name,
                        "mime_type": mime_type,
                        "chunk": 0,
                        "ingested_at": _now(),
                    },
                })
                added.append(f"{fpath.name} ({modality})")
            else:
                errors.append(f"{fpath.name}: unsupported type ({mime})")
        except Exception as e:
            errors.append(f"{fpath.name}: {e}")

    if not vectors:
        msg = "Nothing was added."
        if errors:
            msg += "\n\nErrors:\n- " + "\n- ".join(errors)
        return msg

    try:
        _upsert(vectors)
    except Exception as e:
        return f"Embedding worked but saving to Pinecone failed: {e}"

    msg = f"✅ Added {len(vectors)} item(s) to the database:\n- " + "\n- ".join(added)
    if errors:
        msg += "\n\n⚠️ Skipped:\n- " + "\n- ".join(errors)
    return msg


def _retrieve(question):
    qvec = embed_text(question)
    res = pinecone_index().query(vector=qvec, top_k=TOP_K, include_metadata=True)
    return res.get("matches", [])


def _build_context(matches):
    blocks, sources = [], []
    for m in matches:
        md = m.get("metadata", {}) or {}
        name = md.get("filename", "unknown")
        modality = md.get("modality", "item")
        snippet = md.get("text_snippet")
        if snippet:
            blocks.append(f"[{name}] ({modality}):\n{snippet}")
        else:
            blocks.append(f"[{name}] is a {modality} in the database (no text content).")
        sources.append(f"{name} ({modality}, score {m.get('score', 0):.2f})")
    return "\n\n---\n\n".join(blocks), sources


SYSTEM_INSTRUCTION = (
    "You are a helpful assistant answering questions about the user's personal "
    "knowledge base. Use ONLY the provided context to answer. If the answer is not "
    "in the context, say you don't have that information in the database. Be concise."
)


def rag_chat(message, history):
    if not message or not message.strip():
        return "Ask me something about your database."
    try:
        matches = _retrieve(message)
    except Exception as e:
        return f"⚠️ Could not search the database: {e}"

    if not matches:
        return ("I couldn't find anything relevant in your database yet. "
                "Add some data in the **Add data** tab first.")

    context, sources = _build_context(matches)
    prompt = (
        f"{SYSTEM_INSTRUCTION}\n\n"
        f"=== CONTEXT FROM DATABASE ===\n{context}\n\n"
        f"=== QUESTION ===\n{message}"
    )
    try:
        resp = genai_client().models.generate_content(
            model=GEMINI_CHAT_MODEL, contents=prompt
        )
        answer = (resp.text or "").strip() or "(no answer generated)"
    except Exception as e:
        return f"⚠️ Gemini failed to answer: {e}"

    return f"{answer}\n\n---\n*Sources:* " + "; ".join(sources)


# ---------------------------------------------------------------------------
# Gradio UI
# ---------------------------------------------------------------------------
def build_ui():
    with gr.Blocks(title="CS Chat") as demo:
        gr.Markdown("# 💬 CS Chat\nAsk questions about your data, or add more to it.")
        with gr.Tab("Chat"):
            gr.ChatInterface(
                fn=rag_chat,
                examples=["What's in my database?", "Summarize what I've added."],
            )
        with gr.Tab("Add data"):
            gr.Markdown(
                "Upload files (text, images, video, audio, PDF) and/or paste text, "
                "then press **Ingest**. Note: media files are embedded for search but "
                "their raw bytes aren't stored."
            )
            files_in = gr.File(file_count="multiple", label="Files to add")
            text_in = gr.Textbox(label="Or paste text", lines=6,
                                 placeholder="Paste notes, an article, anything…")
            ingest_btn = gr.Button("Ingest", variant="primary")
            status_out = gr.Markdown()
            ingest_btn.click(ingest_uploads, [files_in, text_in], status_out)
    return demo


if __name__ == "__main__":
    # 0.0.0.0 so it's reachable on the LAN; HF Spaces also expects this.
    build_ui().launch(
        server_name="0.0.0.0",
        server_port=int(os.environ.get("PORT", 7860)),
        theme=gr.themes.Soft(),
    )
