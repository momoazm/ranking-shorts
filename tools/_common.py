"""Shared helpers for tools/ scripts: env loading, brand theme loading, JSON I/O.

Every tool is a standalone CLI script that prints one JSON object to stdout and
exits 0 on success. On failure it still prints a JSON object (with an "error"
key) so callers can parse stdout either way, and exits 1.
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# All API keys/credentials live in a single shared API.env one level ABOVE this
# project folder (the repo root), so every WAT project reads the same key file.
SHARED_ENV = REPO_ROOT.parent / "API.env"


def load_env():
    from dotenv import load_dotenv
    # Original layout: a shared API.env one level above the project (repo root).
    if SHARED_ENV.is_file():
        load_dotenv(SHARED_ENV)
    # Self-contained layout (the cloud automation copy): an API.env at the project root,
    # which OVERRIDES the shared one when present. Harmless in the original (no such file).
    local_env = REPO_ROOT / "API.env"
    if local_env.is_file():
        load_dotenv(local_env, override=True)


def load_theme():
    with open(REPO_ROOT / "brand" / "theme.json", "r", encoding="utf-8") as f:
        return json.load(f)


def emit(data):
    text = json.dumps(data, indent=2, ensure_ascii=False)
    try:
        print(text)
    except UnicodeEncodeError:
        # Windows console codepages (e.g. cp1252) can't print arbitrary
        # Unicode (curly quotes, em-dashes, emoji) that scraped articles
        # often contain. Fall back to escaping non-ASCII rather than crashing.
        print(json.dumps(data, indent=2, ensure_ascii=True))


def fail(message, **extra):
    emit({"error": message, **extra})
    sys.exit(1)
