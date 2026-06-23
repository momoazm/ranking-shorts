"""Shared helpers for CS/ tools: env loading, Pinecone config, JSON I/O.

Every tool is a standalone CLI script that prints one JSON object to stdout and
exits 0 on success. On failure it still prints a JSON object (with an "error"
key) so callers can parse stdout either way, and exits 1.

Key precedence: the project-local `.env` is loaded FIRST (PINECONE_*, optional
GEMINI_API_KEY), then the shared root `API.env` as a fallback so GEMINI_API_KEY
is reused without duplication. python-dotenv does not override already-set vars,
so the local `.env` wins.
"""
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent          # the CS/ folder
SHARED_ENV = next(                                          # nearest API.env above CS/
    (p / "API.env" for p in REPO_ROOT.parents if (p / "API.env").is_file()),
    REPO_ROOT.parent / "API.env",
)
LOCAL_ENV = REPO_ROOT / ".env"                              # CS/.env (PINECONE_*)


def load_env():
    """Load env from the shared root API.env, then let the project-local .env
    override — but only for keys with a NON-EMPTY value. This way a blank line
    like `GEMINI_API_KEY=` in CS/.env doesn't shadow the real key in API.env."""
    from dotenv import load_dotenv, dotenv_values
    load_dotenv(SHARED_ENV)                                  # shared base
    for key, val in dotenv_values(LOCAL_ENV).items():        # local non-empty wins
        if val:
            os.environ[key] = val


def require(name):
    """Return env var `name` or raise a clear error naming where to set it."""
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(
            f"{name} not set. Put it in CS/.env (or the shared root API.env)."
        )
    return val


def pinecone_config():
    """Resolve Pinecone settings from env, with sensible defaults."""
    return {
        "api_key": require("PINECONE_API_KEY"),
        "index": os.environ.get("PINECONE_INDEX", "media-memory"),
        "cloud": os.environ.get("PINECONE_CLOUD", "aws"),
        "region": os.environ.get("PINECONE_REGION", "us-east-1"),
    }


# Embedding model config — kept here so every tool agrees on model + dimension.
EMBED_MODEL = "gemini-embedding-2"
EMBED_DIM = 3072


def log(message):
    """Progress/diagnostics go to stderr so stdout stays one clean JSON object."""
    print(message, file=sys.stderr, flush=True)


def emit(data):
    text = json.dumps(data, indent=2, ensure_ascii=False)
    try:
        print(text)
    except UnicodeEncodeError:
        # Windows console codepages (e.g. cp1252) can't print arbitrary Unicode
        # (curly quotes, em-dashes, emoji) that scraped text often contains.
        # Fall back to escaping non-ASCII rather than crashing.
        print(json.dumps(data, indent=2, ensure_ascii=True))


def fail(message, **extra):
    emit({"error": message, **extra})
    sys.exit(1)
