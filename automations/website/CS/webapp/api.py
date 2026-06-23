"""FastAPI bridge — exposes the CS RAG backend as JSON endpoints for the MOMO website.

Reuses the embed / retrieve / generate logic already in `app.py` (no duplication):
the same Gemini `gemini-embedding-2` embeddings + Pinecone store + Gemini chat that
power the Gradio app now back the MOMO front-end. Adds CORS so the static page can
call it, and serves the website itself so everything runs on one origin.

Run from the `CS/` directory:
    .venv/Scripts/python webapp/api.py
or:
    .venv/Scripts/python -m uvicorn webapp.api:api --host 0.0.0.0 --port 8000

Then open http://localhost:8000  (the MOMO page talks to /api/* same-origin).

Endpoints:
    GET  /api/health   -> {ok, has_gemini, has_pinecone}
    GET  /api/stats    -> {ok, vectors}                  (Pinecone vector count)
    POST /api/ingest   -> multipart files[] + text       -> {ok, message}
    POST /api/ask      -> {question}                     -> {ok, answer, sources[]}
"""
import os
import sys
import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Make `import app` resolve to webapp/app.py regardless of how we're launched.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import app as rag  # importing does NOT launch Gradio (guarded by __main__)

WEBSITE_DIR = Path(__file__).resolve().parent.parent.parent / "website"

api = FastAPI(title="MOMO x CS RAG")
api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
@api.get("/api/health")
def health():
    return {
        "ok": True,
        "has_gemini": bool(rag.GEMINI_API_KEY),
        "has_pinecone": bool(rag.PINECONE_API_KEY),
    }


@api.get("/api/stats")
def stats():
    try:
        s = rag.pinecone_index().describe_index_stats()
        total = int((s.get("total_vector_count") if isinstance(s, dict) else getattr(s, "total_vector_count", 0)) or 0)
        return {"ok": True, "vectors": total}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=200)


@api.post("/api/ingest")
async def ingest(files: list[UploadFile] = File(default=[]), text: str = Form(default="")):
    """Save uploads to a temp dir under their real names, then reuse app.ingest_uploads."""
    tmpdir = tempfile.mkdtemp(prefix="momo_ingest_")
    paths = []
    try:
        for f in files or []:
            dest = Path(tmpdir) / Path(f.filename).name
            with open(dest, "wb") as out:
                out.write(await f.read())
            paths.append(str(dest))  # app.ingest_uploads accepts path strings
        message = rag.ingest_uploads(paths, text)
        return {"ok": True, "message": message}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


class AskBody(BaseModel):
    question: str


@api.post("/api/ask")
def ask(body: AskBody):
    """Retrieve from Pinecone + answer with Gemini, returning structured sources."""
    q = (body.question or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="Empty question.")
    try:
        matches = rag._retrieve(q)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database search failed: {e}")

    if not matches:
        return {"ok": True, "answer": "Nothing relevant is in the database yet. Add some files first.", "sources": []}

    context, _ = rag._build_context(matches)
    prompt = (
        f"{rag.SYSTEM_INSTRUCTION}\n\n"
        f"=== CONTEXT FROM DATABASE ===\n{context}\n\n"
        f"=== QUESTION ===\n{q}"
    )
    try:
        resp = rag.genai_client().models.generate_content(model=rag.GEMINI_CHAT_MODEL, contents=prompt)
        answer = (resp.text or "").strip() or "(no answer generated)"
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Answer generation failed: {e}")

    sources = []
    for m in matches:
        md = m.get("metadata", {}) or {}
        sources.append({
            "name": md.get("filename", "unknown"),
            "modality": md.get("modality", "item"),
            "score": round(float(m.get("score", 0) or 0), 3),
            "snippet": (md.get("text_snippet") or "")[:600],
        })
    return {"ok": True, "answer": answer, "sources": sources}


# ---------------------------------------------------------------------------
# Serve the MOMO website on the same origin (so /api/* is same-origin)
# ---------------------------------------------------------------------------
if (WEBSITE_DIR / "brand").is_dir():
    api.mount("/brand", StaticFiles(directory=str(WEBSITE_DIR / "brand")), name="brand")


@api.get("/")
def index():
    f = WEBSITE_DIR / "index.html"
    if not f.exists():
        raise HTTPException(status_code=404, detail="website/index.html not found")
    return FileResponse(str(f))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(api, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
