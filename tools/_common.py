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

# Ranked-list / stat-list / compilation markers: the single-clip pipeline posts ONE specific
# moment, and the countdown pipeline builds its own ranking -- neither should ever source a
# video that is itself a Top-N / "most X in history" / compilation piece ("Most Goal Scorer's
# in FIFA World Cup history" got posted 2026-07-05).
_LISTY = _re.compile(
    r"top\s*\d+|\branked\b|tier\s*list|all[\s-]*time|in\s+(?:fifa\s+)?(?:world\s+cup\s+)?history|"
    r"most\s+(?:\w+\s+){0,2}(?:goals?|scorers?|trophies|titles|assists)|"
    r"compilation|montage|\bquiz\b|\btrivia\b",
    _re.IGNORECASE)

# iShowSpeed / "Speed" content is ALLOWED again (user decision 2026-07-08, reverses the
# 2026-07-06 blanket block). No subject blocklist remains -- Speed clips (our own livestream
# captures AND third-party uploads) are sourced like any other creator.


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
    if _LISTY.search(t):
        return False
    return True


# --- Channel screen: block Indian/Hindi-commentary re-upload channels ------------------------
# The problem the title screen CAN'T solve: a goal clip with an English title
# ("Messi Goal | Argentina 3-2 Egypt") but HINDI commentary audio, re-uploaded by an Indian
# sports channel. The reliable signal is the CHANNEL / uploader handle, not the title. This
# blocklist matches Indian-language markers and known Hindi-feed broadcasters in the channel
# name/@handle; `channel_ok()` rejects them for every category.
_BAD_CHANNEL = _re.compile(
    r"hindi|\bindia\b|indian|bharat|desi|\bhind\b|"
    r"sports\s*tak|aaj\s*tak|dd\s*sports|jio|khel|"
    r"sony\s*(?:ten|liv|sports)|star\s*sports|sports\s*18|"
    r"\bbangla\b|\btamil\b|\btelugu\b|\bmalayalam\b|\burdu\b|pakistan|\bptv\b",
    _re.IGNORECASE)

# Trusted English-commentary sources: official + major broadcasters. The World Cup's own FIFA
# channel plus these cover essentially every goal with clean world-feed/English commentary, so
# the goal finder PREFERS them (see find_worldcup_clips) and only falls back to the wider,
# channel-screened pool when none of them have the moment yet.
_TRUSTED_CHANNELS = {
    # TOD by beIN (@tod_bybein) is the PREFERRED FIFA-highlights source (user 2026-07-08).
    "@tod_bybein",
    "@fifa", "@fifaworldcup", "@foxsoccer", "@foxsports", "@cbssportsgolazo", "@cbssports",
    "@espn", "@espnfc", "@espnuk", "@beinsports", "@beinsportsusa", "@tntsports", "@skysports",
    "@nbcsports", "@daznfootball", "@dazn", "@onefootball", "@goal", "@433", "@bbcsport",
}
_TRUSTED_NAME = _re.compile(
    r"\bfifa\b|fox\s*soccer|fox\s*sports|cbs\s*sports|golazo|\bespn\b|bein\s*sports|"
    r"tnt\s*sports|sky\s*sports|nbc\s*sports|\bdazn\b|onefootball|\bbbc\s*sport",
    _re.IGNORECASE)


def channel_ok(channel_text):
    """False if the channel name/@handle looks like an Indian/Hindi-commentary re-uploader."""
    return not _BAD_CHANNEL.search(channel_text or "")


def channel_trusted(channel_name, handle=""):
    """True if the channel is an official/major English-commentary broadcaster."""
    h = (handle or "").strip().lower()
    if h and h in _TRUSTED_CHANNELS:
        return True
    return bool(_TRUSTED_NAME.search(channel_name or ""))


# TOD by beIN (@tod_bybein): preferred FIFA-highlights source (user 2026-07-08). Its uploads
# carry a bottom branding bar, so build_clip crops the bottom off TOD clips ONLY (is_tod gate).
TOD_CROP_FRAC = 0.10   # fraction of source height to trim off the bottom for TOD clips


def is_tod(channel_name="", handle=""):
    """True if a candidate came from the TOD-by-beIN channel (so we crop its bottom bar)."""
    h = (handle or "").strip().lower().lstrip("@")
    if "tod_bybein" in h:
        return True
    n = (channel_name or "").lower()
    return "tod" in n and "bein" in n


# --- Zernio post-create with rate-limit retry -------------------------------------------------
# Both upload_youtube.py and upload_instagram.py publish through Zernio's single POST /posts
# endpoint, which shares one rate limit. Posting several clips in quick succession (a busy
# match) returns HTTP 429 Too Many Requests -- on 2026-07-08 four of Argentina-Egypt's posts
# 429'd on the YouTube side. This retries the CREATE call on 429/5xx with backoff (honoring a
# Retry-After header when present) so a burst self-throttles instead of dropping posts.
def zernio_create_post(api_url, payload, api_key, max_tries=5):
    """POST to Zernio /posts, retrying on 429/5xx. Returns (post_dict, error_str)."""
    import httpx
    import time as _t
    import uuid as _uuid
    backoff, last = 20, None
    for attempt in range(max_tries):
        headers = {"Authorization": f"Bearer {api_key}", "x-request-id": str(_uuid.uuid4())}
        try:
            r = httpx.post(api_url, json=payload, headers=headers, timeout=60)
        except Exception as e:                       # network blip -> retry
            last = str(e)
            _t.sleep(backoff); backoff *= 2
            continue
        if r.status_code == 429 or r.status_code >= 500:
            body = r.text[:200]
            last = f"HTTP {r.status_code}: {body}"
            # Distinguish a transient burst 429 (retry helps) from an ACCOUNT-level daily cap
            # ("temporarily rate-limited ... wait 18h ... before posting") -- the latter won't
            # clear for hours, so retrying is pointless; fail fast with the clear reason.
            if r.status_code == 429 and _re.search(r"wait\s+\d+\s*h|before\s+post", body, _re.IGNORECASE):
                return None, (f"Zernio account rate-limited (daily cap): {body}")
            ra = r.headers.get("Retry-After", "")
            wait = int(ra) if ra.isdigit() else backoff
            if attempt < max_tries - 1:
                _t.sleep(min(wait, 120)); backoff *= 2
            continue
        try:
            r.raise_for_status()
        except Exception as e:                       # 4xx other than 429 -> not retryable
            body = getattr(getattr(e, "response", None), "text", "")
            return None, f"Zernio post create failed: {e} {body}".strip()
        return r.json().get("post", {}), None
    return None, f"Zernio post create failed after {max_tries} tries ({last})"
