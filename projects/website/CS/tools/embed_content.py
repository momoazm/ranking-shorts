"""Core embedding module for the CS vector database. Embeds text, images, or
video into a 3072-dim vector using Google's multimodal `gemini-embedding-2` model.

Every modality maps into the SAME vector space, so a text query can match an image
or video and vice versa. This module is imported by ingest.py and query.py; it can
also be run standalone to sanity-check a single item.

Usage:
    python tools/embed_content.py --text "a rainy city street at night"
    python tools/embed_content.py --path photo.png
    python tools/embed_content.py --path clip.mp4 --mime-type video/mp4

Prints JSON: {"dimension": 3072, "modality": "text|image|video|...", "vector": [...]}
"""
import argparse
import mimetypes
import os
import time
from pathlib import Path

from _common import load_env, require, emit, fail, log, EMBED_MODEL, EMBED_DIM

# Files at or below this size are sent inline via Part.from_bytes; larger files
# (most videos) go through the Files API to avoid the inline request-size limit.
INLINE_MAX_BYTES = 15 * 1024 * 1024  # ~15 MB

_client = None


def get_client():
    """Lazily build a single google-genai client from GEMINI_API_KEY."""
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client(api_key=require("GEMINI_API_KEY"))
    return _client


def modality_for_mime(mime_type):
    if not mime_type:
        return "unknown"
    top = mime_type.split("/", 1)[0]
    if top in ("image", "video", "audio", "text"):
        return top
    if mime_type == "application/pdf":
        return "pdf"
    return top


def guess_mime(path):
    mime, _ = mimetypes.guess_type(str(path))
    return mime


def _embed_contents(contents):
    """Call the embeddings API with simple retry/backoff on transient errors."""
    from google.genai import types

    client = get_client()
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
            # Back off on rate limits / transient server errors; fail fast otherwise.
            if any(s in msg for s in ("429", "rate", "quota", "503", "500", "unavailable", "timeout")):
                wait = 2 ** attempt
                log(f"Embed retry {attempt + 1}/4 after error: {e} (waiting {wait}s)")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError(f"Embedding failed after retries: {last_err}")


def embed_text(text):
    """Embed a string. Returns a 3072-float vector."""
    if not text or not text.strip():
        raise ValueError("Cannot embed empty text.")
    return _embed_contents([text])


def embed_path(path, mime_type=None):
    """Embed a media file (image/video/audio/pdf). Returns (vector, mime_type)."""
    from google.genai import types

    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"No such file: {path}")

    mime_type = mime_type or guess_mime(p)
    if not mime_type:
        raise ValueError(
            f"Could not infer MIME type for {p.name}; pass --mime-type explicitly."
        )

    size = p.stat().st_size
    if size <= INLINE_MAX_BYTES:
        data = p.read_bytes()
        part = types.Part.from_bytes(data=data, mime_type=mime_type)
        vector = _embed_contents([part])
    else:
        # Large file (most videos): upload via the Files API, then reference it.
        log(f"{p.name} is {size / 1e6:.1f} MB > inline limit; using Files API upload...")
        client = get_client()
        uploaded = client.files.upload(file=str(p))
        vector = _embed_contents([uploaded])

    return vector, mime_type


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--text", help="Text to embed")
    group.add_argument("--path", help="Path to an image/video/audio/pdf file to embed")
    parser.add_argument("--mime-type", help="Override MIME type for --path")
    args = parser.parse_args()

    load_env()
    try:
        if args.text is not None:
            vector = embed_text(args.text)
            modality = "text"
        else:
            vector, mime_type = embed_path(args.path, args.mime_type)
            modality = modality_for_mime(mime_type)

        emit({"dimension": len(vector), "modality": modality, "vector": vector})
    except Exception as e:
        fail(str(e))


if __name__ == "__main__":
    main()
