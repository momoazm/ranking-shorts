"""Shared helpers for tools/ scripts: env loading, brand theme loading, JSON I/O.

Every tool is a standalone CLI script that prints one JSON object to stdout and
exits 0 on success. On failure it still prints a JSON object (with an "error"
key) so callers can parse stdout either way, and exits 1.
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# All API keys/credentials live in a single shared API.env at the repo root.
# Walk up from the project folder to find it, so it works whether the project
# sits one or more levels below the repo root.
SHARED_ENV = next(
    (p / "API.env" for p in REPO_ROOT.parents if (p / "API.env").is_file()),
    REPO_ROOT.parent / "API.env",
)


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


# --- English-audience title screen (shared by the clip finders) -------------------------------
# The channel is English-language: a Hindi Zee News segment slipped through on 2026-07-05
# because its title carried English keywords ("Messi ... World Cup Goals Record ... ZEENews").
# Two deterministic checks, applied BEFORE any LLM sees the candidates:
#   1. Script check -- any Devanagari/Arabic/CJK/etc. characters in the title.
#   2. Keyword check -- news/talk-show/analysis markers and romanized Hindi/Urdu stopwords;
#      these are studio talking-head videos, never the raw footage the channel posts.
import re as _re

_NON_LATIN = _re.compile(
    "[Ѐ-ӿ"            # Cyrillic
    "֐-׿"             # Hebrew
    "؀-ۿݐ-ݿ"  # Arabic (incl. Urdu)
    "ऀ-෿"             # Devanagari, Bengali, Gurmukhi, Gujarati, Oriya, Tamil,
                                # Telugu, Kannada, Malayalam, Sinhala
    "฀-๿"             # Thai
    "ᄀ-ᇿ가-힯"  # Hangul
    "぀-ヿ㐀-鿿"  # Japanese kana + CJK
    "]")

_TALK_OR_FOREIGN = _re.compile(
    r"\b(news|zee|zeenews|aaj\s*tak|abp|ndtv|republic|india\s*tv|dd\s+sports|breaking|"
    r"preview|prediction|predictions|analysis|debate|podcast|interview|press\s+conference|"
    r"explained|record|rankings?|stats?|comparison|"
    r"hindi|urdu|tamil|telugu|malayalam|bangla|bengali|marathi|punjabi|bhojpuri|"
    r"ka|ki|ke|ko|hai|kya|kaun|nahi|wala|dekho|mein|aur)\b",
    _re.IGNORECASE)


def title_ok(title):
    """True if a candidate's title looks like English-language actual-footage content.

    Rejects non-Latin-script titles and news/analysis/talking-head markers. Deliberately
    conservative: a false reject just skips one candidate; a false accept posts an
    off-audience video to the channel.
    """
    t = title or ""
    if _NON_LATIN.search(t):
        return False
    if _TALK_OR_FOREIGN.search(t):
        return False
    return True
