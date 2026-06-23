"""Ingest files into the Pinecone vector database. Walks a file or directory,
embeds each item with gemini-embedding-2 (via embed_content.py), and upserts the
vectors with metadata.

- Text/markdown/PDF files are chunked into ~2,000-token windows (the model caps at
  8,192 tokens); each chunk becomes its own vector with id `<file>#<n>`.
- Images and videos are embedded whole, one vector each.
- Media bytes are NOT stored in Pinecone — only a source_path reference plus small
  metadata (Pinecone caps metadata at 40 KB/vector), so keep originals on disk.

Usage:
    python tools/ingest.py --path ./media [--recursive] [--namespace default]

Prints JSON: {"upserted": N, "vectors": [...ids...], "skipped": [...], "errors": [...]}
"""
import argparse
import datetime
import hashlib
from pathlib import Path

from _common import load_env, pinecone_config, emit, fail, log, EMBED_DIM
from embed_content import embed_text, embed_path, guess_mime, modality_for_mime

# Extensions we treat as plain text to read + chunk (mimetypes misses some).
TEXT_EXTS = {".txt", ".md", ".markdown", ".rst", ".csv", ".json", ".log"}
# Rough chars-per-token heuristic for chunking (≈4 chars/token → 2000 tokens).
CHUNK_CHARS = 8000
SNIPPET_CHARS = 500
META_TEXT_CAP = 30000  # keep well under Pinecone's 40 KB/vector metadata limit


def stable_id(path, chunk=0):
    h = hashlib.sha1(f"{path}#{chunk}".encode("utf-8")).hexdigest()[:24]
    return f"{h}-{chunk}"


def chunk_text(text):
    """Split text into ~CHUNK_CHARS windows on paragraph/whitespace boundaries."""
    text = text.strip()
    if len(text) <= CHUNK_CHARS:
        return [text] if text else []
    chunks, start = [], 0
    while start < len(text):
        end = min(start + CHUNK_CHARS, len(text))
        if end < len(text):
            # Prefer to break at the last newline/space in the window.
            brk = text.rfind("\n", start, end)
            if brk == -1 or brk <= start:
                brk = text.rfind(" ", start, end)
            if brk > start:
                end = brk
        chunks.append(text[start:end].strip())
        start = end
    return [c for c in chunks if c]


def read_text_file(path):
    return path.read_text(encoding="utf-8", errors="replace")


def iter_files(root, recursive):
    p = Path(root)
    if p.is_file():
        yield p
    elif p.is_dir():
        it = p.rglob("*") if recursive else p.iterdir()
        for f in sorted(it):
            if f.is_file():
                yield f
    else:
        raise FileNotFoundError(f"No such file or directory: {root}")


def is_text_file(path, mime):
    return path.suffix.lower() in TEXT_EXTS or (mime or "").startswith("text/")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True, help="File or directory to ingest")
    parser.add_argument("--recursive", action="store_true", help="Recurse into subdirs")
    parser.add_argument("--namespace", default="", help="Pinecone namespace")
    args = parser.parse_args()

    load_env()
    try:
        cfg = pinecone_config()
        from pinecone import Pinecone
        pc = Pinecone(api_key=cfg["api_key"])
        index = pc.Index(cfg["index"])
    except Exception as e:
        fail(f"Could not connect to Pinecone index: {e}")

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    vectors, upserted_ids, skipped, errors = [], [], [], []

    try:
        files = list(iter_files(args.path, args.recursive))
    except FileNotFoundError as e:
        fail(str(e))

    for f in files:
        mime = guess_mime(f)
        try:
            if is_text_file(f, mime):
                chunks = chunk_text(read_text_file(f))
                if not chunks:
                    skipped.append({"path": str(f), "reason": "empty text file"})
                    continue
                for i, chunk in enumerate(chunks):
                    log(f"Embedding text {f.name} chunk {i + 1}/{len(chunks)}")
                    vec = embed_text(chunk)
                    vid = stable_id(str(f), i)
                    vectors.append({
                        "id": vid,
                        "values": vec,
                        "metadata": {
                            "modality": "text",
                            "source_path": str(f.resolve()),
                            "filename": f.name,
                            "mime_type": mime or "text/plain",
                            "chunk": i,
                            "text_snippet": chunk[:META_TEXT_CAP],
                            "ingested_at": now,
                        },
                    })
                    upserted_ids.append(vid)
            elif mime and (mime.startswith(("image/", "video/", "audio/")) or mime == "application/pdf"):
                log(f"Embedding {modality_for_mime(mime)} {f.name}")
                vec, mime_type = embed_path(f, mime)
                vid = stable_id(str(f), 0)
                vectors.append({
                    "id": vid,
                    "values": vec,
                    "metadata": {
                        "modality": modality_for_mime(mime_type),
                        "source_path": str(f.resolve()),
                        "filename": f.name,
                        "mime_type": mime_type,
                        "chunk": 0,
                        "ingested_at": now,
                    },
                })
                upserted_ids.append(vid)
            else:
                skipped.append({"path": str(f), "reason": f"unsupported type ({mime})"})
        except Exception as e:
            log(f"ERROR on {f}: {e}")
            errors.append({"path": str(f), "error": str(e)})

    # Upsert in batches (Pinecone recommends <= 100 vectors / <= 2 MB per request).
    try:
        kwargs = {"namespace": args.namespace} if args.namespace else {}
        for i in range(0, len(vectors), 100):
            batch = vectors[i:i + 100]
            index.upsert(vectors=batch, **kwargs)
            log(f"Upserted {min(i + 100, len(vectors))}/{len(vectors)}")
    except Exception as e:
        fail(f"Upsert to Pinecone failed: {e}",
             embedded=len(vectors), errors=errors)

    emit({
        "upserted": len(upserted_ids),
        "vectors": upserted_ids,
        "skipped": skipped,
        "errors": errors,
        "namespace": args.namespace or None,
        "dimension": EMBED_DIM,
    })


if __name__ == "__main__":
    main()
