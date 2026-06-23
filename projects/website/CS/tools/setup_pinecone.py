"""Create the Pinecone serverless index for the media vector database, if it
doesn't already exist. Idempotent — safe to run repeatedly.

The index dimension is fixed at creation (3072 = gemini-embedding-2 native dim,
cosine metric). Changing the dimension later requires a new index + re-ingest.

Usage:
    python tools/setup_pinecone.py

Prints JSON: {"index": ..., "dimension": 3072, "metric": "cosine",
              "cloud": ..., "region": ..., "created": true|false}
"""
from _common import load_env, pinecone_config, emit, fail, log, EMBED_DIM


def main():
    load_env()
    try:
        cfg = pinecone_config()
    except RuntimeError as e:
        fail(str(e))

    try:
        from pinecone import Pinecone, ServerlessSpec

        pc = Pinecone(api_key=cfg["api_key"])
        existing = [i.name for i in pc.list_indexes()]

        if cfg["index"] in existing:
            # Verify the existing index has the dimension we expect; warn if not.
            desc = pc.describe_index(cfg["index"])
            dim = getattr(desc, "dimension", None)
            if dim is not None and dim != EMBED_DIM:
                fail(
                    f"Index '{cfg['index']}' already exists with dimension {dim}, "
                    f"but this project embeds at {EMBED_DIM}. Use a different "
                    f"PINECONE_INDEX name or delete the old index.",
                    existing_dimension=dim,
                    expected_dimension=EMBED_DIM,
                )
            emit({
                "index": cfg["index"],
                "dimension": EMBED_DIM,
                "metric": "cosine",
                "cloud": cfg["cloud"],
                "region": cfg["region"],
                "created": False,
            })
            return

        log(f"Creating serverless index '{cfg['index']}' ({EMBED_DIM} dims, cosine)...")
        pc.create_index(
            name=cfg["index"],
            dimension=EMBED_DIM,
            metric="cosine",
            spec=ServerlessSpec(cloud=cfg["cloud"], region=cfg["region"]),
        )
        emit({
            "index": cfg["index"],
            "dimension": EMBED_DIM,
            "metric": "cosine",
            "cloud": cfg["cloud"],
            "region": cfg["region"],
            "created": True,
        })
    except Exception as e:
        fail(f"Pinecone setup failed: {e}")


if __name__ == "__main__":
    main()
