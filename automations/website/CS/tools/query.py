"""Search the Pinecone vector database. Embeds a query — either text OR a media
file (image/video/audio/pdf) — with the same gemini-embedding-2 model and returns
the nearest stored items. Because all modalities share one vector space, a text
query can surface images/videos and vice versa (cross-modal search).

Usage:
    python tools/query.py --text "rainy city street at night" [--top-k 5] [--namespace default]
    python tools/query.py --path query_image.jpg [--top-k 5]

Prints JSON: {"query": ..., "matches": [{"id","score","metadata"}, ...]}
"""
import argparse

from _common import load_env, pinecone_config, emit, fail
from embed_content import embed_text, embed_path


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--text", help="Text query")
    group.add_argument("--path", help="Image/video/audio/pdf file to search by")
    parser.add_argument("--mime-type", help="Override MIME type for --path")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--namespace", default="", help="Pinecone namespace")
    args = parser.parse_args()

    load_env()

    try:
        if args.text is not None:
            vector = embed_text(args.text)
            query_desc = {"type": "text", "value": args.text}
        else:
            vector, mime_type = embed_path(args.path, args.mime_type)
            query_desc = {"type": "media", "value": args.path, "mime_type": mime_type}
    except Exception as e:
        fail(f"Failed to embed query: {e}")

    try:
        cfg = pinecone_config()
        from pinecone import Pinecone
        pc = Pinecone(api_key=cfg["api_key"])
        index = pc.Index(cfg["index"])

        kwargs = {"namespace": args.namespace} if args.namespace else {}
        res = index.query(
            vector=vector,
            top_k=args.top_k,
            include_metadata=True,
            **kwargs,
        )
    except Exception as e:
        fail(f"Pinecone query failed: {e}")

    matches = [
        {
            "id": m.get("id"),
            "score": m.get("score"),
            "metadata": m.get("metadata", {}),
        }
        for m in res.get("matches", [])
    ]
    emit({"query": query_desc, "namespace": args.namespace or None, "matches": matches})


if __name__ == "__main__":
    main()
