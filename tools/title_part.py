"""Generate a per-part post title + a short burned hook banner from one part's transcript.

Competitor evidence (top Shark Tank Shorts, 826K–2.4M views): the post title is a short
curiosity/stakes line ("The Best Negotiation", "This Greedy Offer"), while the video itself
carries a 2–5 word ALL-CAPS banner. Neither carries a "(Part 3/8)" label — the part number
belongs in the description.

This tool takes the words JSON produced by transcribe_segment.py and returns:

    {"title": "He Asked For $150K — Then The Sharks Went Quiet.",
     "hook": "HE ASKED $150K", "provider": "groq"|"deterministic", "evidence": "..."}

Rules enforced on every path (LLM or deterministic):
  * complete sentence, 18–80 chars, capitalised, terminal punctuation
  * no "(Part i/N)", no hashtags, no emoji, no quotes
  * the deterministic fallback can never cut mid-word or emit an ASR fragment

Usage:
    python tools/title_part.py --transcript .tmp/sharktank/part_3_words.json \
        --source-title "..." --show "Shark Tank" --part 3 --total 8 --out .tmp/part_title.json
"""
import argparse
import json
import os
import re

from _common import REPO_ROOT, load_env, emit

# Openers that make a transcript sentence read like a fragment when shown alone.
_LEADING_FILLER = re.compile(
    r"^(?:and|but|so|then|now|well|okay|ok|yeah|like|you know|i mean|basically|"
    r"actually|literally|right)\b[\s,:-]*",
    re.IGNORECASE,
)
_TRAILING_FILLER = re.compile(r"[\s,;:-]+$")
_MONEY = re.compile(
    r"\$\s?\d[\d,.]*\s?(?:k|m|million|thousand|billion)?|"
    r"\b\d[\d,.]*\s?%|"
    r"\b(?:\d[\d,.]*|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"fifteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred)\s*"
    r"(?:percent|thousand|million|billion)\b",
    re.I,
)
_DEAL_WORDS = re.compile(
    r"\b(?:offer|deal|invest|investment|equity|royalt(?:y|ies)|percent|equity|valuation|"
    r"sharks?|dragons?|negotiat\w*|refus\w*|reject\w*|walk\w*|accept\w*|close\w*|"
    r"million|thousand|revenue|profit|company|business|pitch)\b",
    re.IGNORECASE,
)
# A dependent clause ("Even though the workouts...", "Because he...") is never a title:
# it reads as a fragment even when the words themselves are complete.
_SUBORDINATE = re.compile(
    r"^(?:even\s+though|although|though|while|whereas|because|when|whenever|if|since|"
    r"after|before|as|once|unless|until|which|that)\b",
    re.I,
)
# A lead-in phrase ("For this, ...", "With that offer, ...") only makes sense mid-story; shown
# alone it reads like a fragment even though the sentence itself is complete.
_PREPOSITIONAL = re.compile(
    r"^(?:for|with|without|from|at|in|on|about|because|to|by|after|before|when|as|if|"
    r"that|which|so)\b", re.I)
_PART_LABEL = re.compile(r"\(\s*part\s*\d+\s*/\s*\d+\s*\)|\bpart\s*\d+\s*/\s*\d+\b", re.I)
_TERMINAL = (".", "!", "?")
_GENERIC = re.compile(r"^(?:shark tank|dragons'? den|a pitch|watch this)\b", re.I)
_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}


def _clean(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


# Exotic hyphens/dashes and no-break spaces that LLMs and ASR emit; they render as tofu in
# the burned ASS banner and look broken in a caption.
_ODD_CHARS = str.maketrans({
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": " - ",
    "\u2212": "-", "\u00a0": " ", "\u2009": " ", "\u202f": " ", "\u200b": "",
})


def _clean_chars(text):
    return re.sub(r"\s+", " ", str(text or "").translate(_ODD_CHARS)).strip()


def transcript_text(transcript):
    """Read either {"words":[...]} or a raw word list / plain text blob."""
    if isinstance(transcript, str):
        return _clean(transcript)
    if isinstance(transcript, list):
        words = transcript
    elif isinstance(transcript, dict):
        words = transcript.get("words") or []
        if not words and transcript.get("text"):
            return _clean(transcript["text"])
    else:
        words = []
    return _clean(" ".join(str((w or {}).get("w") or "") for w in words))


def _punch_numbers(text):
    """'ten percent' -> '10%', 'one hundred and fifty thousand dollars' -> '$150,000'."""
    def percent(match):
        word = match.group(1).lower()
        return f"{_NUMBER_WORDS.get(word, word)}%"

    text = re.sub(
        r"\b(" + "|".join(_NUMBER_WORDS) + r"|\d+)\s+percent\b", percent, text,
        flags=re.IGNORECASE)

    def words_to_number(phrase):
        total, current = 0, 0
        for token in phrase.lower().replace("-", " ").split():
            if token in _NUMBER_WORDS:
                current += _NUMBER_WORDS[token]
            elif token == "hundred":
                current = (current or 1) * 100
            elif token in {"thousand", "million", "billion"}:
                total += (current or 1) * {"thousand": 1_000, "million": 1_000_000,
                                           "billion": 1_000_000_000}[token]
                current = 0
            elif token == "and":
                continue
            else:
                return None
        return total + current

    def money(match):
        phrase = match.group(1)
        value = words_to_number(phrase)
        return f"${value:,}" if value else match.group(0)

    number_words = "|".join(_NUMBER_WORDS)
    text = re.sub(
        r"\b((?:(?:" + number_words + r"|hundred|and|thousand|million|billion)\s+){1,7})"
        r"dollars?\b", money, text, flags=re.IGNORECASE)
    return text


def _fit_sentence(sentence, max_len=76):
    """Keep a long sentence inside the title budget at a clause/word boundary."""
    text = _clean(sentence)
    if len(text) <= max_len:
        return text
    # Prefer ending on a real pause inside the window ("... for 10%." rather than mid-clause).
    stops = [m.end() for m in re.finditer(r"[,;:]\s", text)]
    fit = [s for s in stops if 30 <= s <= max_len]
    if fit:
        text = text[:max(fit)].rstrip(" ,;:")
    else:
        text = text[:max_len].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return text


def clean_sentence(sentence):
    """One transcript sentence -> a standalone, capitalised, punctuated clause."""
    text = _clean(sentence)
    text = _clean_chars(text)
    text = text.replace("’", "'").replace("“", '"').replace("”", '"')
    # Drop a leading conjunction/discourse marker that only makes sense mid-story. Repeat:
    # ASR often chains them ("And so, basically, ...").
    for _ in range(3):
        stripped = _LEADING_FILLER.sub("", text)
        if stripped == text:
            break
        text = stripped
    text = _TRAILING_FILLER.sub("", text).strip(" \"'")
    if not text:
        return ""
    # Drop a short lead-in clause with no concrete stake in it: "For this, we're willing to
    # give you a 25% stake..." -> "We're willing to give you a 25% stake...". A lead-in that
    # carries money ("For $150,000, I'll...") is kept, because that IS the hook.
    lead = re.match(r"^([A-Za-z' ]{2,32}),\s+(?=\S)", text)
    if lead:
        head = lead.group(1).strip()
        if (len(head.split()) <= 4 and not re.search(r"\d|\$|%", head)
                and _PREPOSITIONAL.match(head)):
            text = text[lead.end():]
    text = _punch_numbers(text)
    # Capitalise the first alphabetical character without touching the rest (keeps names,
    # acronyms and already-correct casing intact).
    match = re.search(r"[A-Za-z]", text)
    if match:
        index = match.start()
        text = text[:index] + text[index].upper() + text[index + 1:]
    if text[-1] not in _TERMINAL:
        text += "."
    return text


def _sentence_score(sentence):
    score = 0
    if _MONEY.search(sentence):
        score += 6
    score += min(5, len(set(m.lower() for m in _DEAL_WORDS.findall(sentence))) * 2)
    if 28 <= len(sentence) <= 68:
        score += 4
    elif len(sentence) <= 76:
        score += 2
    if sentence.endswith("?"):
        score += 1
    if re.match(r"^(?:he|she|they|this|that|the)\b", sentence, re.I):
        score += 1
    # "That is the only way..." / "It is..." read like a continuation, not a title.
    if re.match(r"^(?:that|this|it|there)\s+(?:is|was|are|were)\b", sentence, re.I):
        score -= 3
    # "For this, we're willing to give you a 25% stake." is a REPLY, not a headline.
    if _PREPOSITIONAL.match(sentence):
        score -= 4
    return score


def sentence_candidates(text):
    parts = re.split(r"(?<=[.!?])\s+", _clean(text))
    out = []
    for part in parts:
        cleaned = clean_sentence(part)
        if not cleaned:
            continue
        if len(cleaned) > 82:
            # Long ASR sentences are usually several clauses; keep the strongest clause that
            # actually fits instead of dropping real evidence.
            clauses = [c for c in re.split(r"\s+(?:and|but|because|so|which|that)\s+", cleaned) if c]
            cleaned = max(clauses, key=lambda c: (_MONEY.search(c) is not None, len(c))) \
                if clauses else cleaned
            cleaned = _fit_sentence(cleaned, 76)
            if cleaned and cleaned[-1] not in _TERMINAL:
                cleaned += "."
        if not (16 <= len(cleaned) <= 82):
            continue
        if _PART_LABEL.search(cleaned) or _SUBORDINATE.match(cleaned):
            continue
        out.append(cleaned)
    return out


def word_cut(text, max_len=76):
    """Hard cap at a WORD boundary and finish the sentence, never mid-word."""
    text = _clean(text)
    if len(text) <= max_len:
        return text
    cut = text[:max_len].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return cut + ("" if cut.endswith(_TERMINAL) else ".")


def title_problem(title):
    """Return a reason string if `title` would read as an ASR fragment, else None."""
    text = _clean(title)
    if not text:
        return "empty"
    if len(text) < 16:
        return "too short"
    if len(text) > 84:
        return "too long"
    if _PART_LABEL.search(text):
        return "part label"
    if "#" in text or re.search(r"[\U0001F300-\U0001FAFF]", text):
        return "hashtag or emoji"
    if not re.match(r"^[0-9A-Z]", text):
        return "does not start with a capital or number"
    if re.match(r"^(?:and|but|so|then|well|okay|yeah|like|you know)\b", text, re.I):
        return "starts with a filler word"
    if len(text.split()) > 16:
        return "too many words for one title"
    if len(re.findall(r"[.!?](?:\s|$)", text)) > 1 and not _MONEY.search(text):
        return "multiple sentences"
    if text[-1] not in _TERMINAL:
        return "no terminal punctuation (fragment)"
    if _GENERIC.search(text):
        return "generic show name, not a hook"
    return None


def _source_fallback_title(source_title, show):
    raw = _PART_LABEL.sub("", _clean(source_title))
    segs = [_clean(s) for s in re.split(r"[|•]", raw) if _clean(s)]
    show_words = set(re.findall(r"[a-z0-9']+", f"{show} shark tank dragons den".lower()))
    kept = [s for s in segs
            if set(re.findall(r"[a-z0-9']+", s.lower())) - show_words]
    base = max(kept, key=len) if kept else (segs[0] if segs else raw)
    base = re.sub(r"\s*[-–—]\s*(?:full episode|highlights?|official).*$", "", base, flags=re.I)
    base = clean_sentence(base)
    if len(base) < 16:
        return ""
    return word_cut(base, 76)


def deterministic_title(transcript, source_title="", show="Shark Tank"):
    """Complete, clean fallback title derived from the strongest transcript sentence."""
    text = transcript_text(transcript)
    candidates = sentence_candidates(text)
    if candidates:
        best = max(candidates, key=_sentence_score)
        # Prefer a money/stakes sentence when one exists, even if longer.
        money = [c for c in candidates if _MONEY.search(c) and len(c) <= 76]
        if money:
            best = max(money, key=_sentence_score)
        title = word_cut(best, 76)
    else:
        title = _source_fallback_title(source_title, show) or ""
    if not title:
        # Never invent a claim; a neutral, factual label is the last resort.
        label = _clean(show) or "The Pitch"
        title = f"A {label} Pitch That Got Heated."
    if title_problem(title):
        # Repair the two repairable classes instead of discarding real transcript evidence.
        title = clean_sentence(title)
        if title_problem(title):
            fallback = _source_fallback_title(source_title, show)
            title = fallback if fallback and not title_problem(fallback) else \
                f"A {(_clean(show) or 'Pitch Show')} Pitch That Got Heated."
    return title


_HOOK_STOPWORDS = {
    "a", "an", "the", "for", "of", "at", "to", "in", "on", "and", "but", "so", "or",
    "that", "this", "these", "those", "is", "are", "was", "were", "be", "been", "being",
    "we", "i", "you", "your", "our", "my", "me", "us", "it", "its", "they", "them",
    "he", "she", "his", "her", "their", "with", "from", "as", "by", "if", "then",
    "will", "would", "can", "could", "should", "do", "does", "did", "have", "has", "had",
    "just", "really", "very", "like", "get", "got", "am", "what", "which", "when",
    "because", "though", "although", "while", "since", "until", "unless", "than",
    "where", "who", "why", "how", "there", "here", "about", "over", "after", "before",
}
_HOOK_CONNECTORS = {"for", "of", "at", "in", "on", "to", "with", "from", "by"}
_HOOK_SUBJECTS = {"he", "she", "they", "we", "i"}


def _hook_core(token):
    return re.sub(r"[^a-z0-9$%.]", "", str(token or "").lower())


def deterministic_hook(title, limit=28):
    """2-5 ALL-CAPS words built around the strongest signal in the title.

    Prefix-taking ("first five words") produced banners like "YOU A 25%" on a real part:
    the title opened with "For this, we're willing to give you...". The banner is now built
    around the anchor -- money first (the stakes stop the scroll), then a deal word, then the
    first content word -- with the subject pronoun when one sits beside it ("HE WALKED AWAY").
    """
    tokens = [t.strip(" ,;:-") for t in _clean(title).split()]
    tokens = [t for t in tokens if t]
    if not tokens:
        return "THE PITCH"
    cores = [_hook_core(t) for t in tokens]

    anchor = next((i for i, t in enumerate(tokens) if _MONEY.search(t)), None)
    if anchor is None:
        anchor = next((i for i, t in enumerate(cores) if _DEAL_WORDS.search(tokens[i])), None)
    if anchor is None:
        anchor = next((i for i, c in enumerate(cores)
                       if c and c not in _HOOK_STOPWORDS), 0)

    # Start at a nearby subject pronoun when the whole run fits ("HE TURNED DOWN $150,000").
    start = anchor
    for index in range(anchor - 1, max(-1, anchor - 6), -1):
        if cores[index] in _HOOK_SUBJECTS:
            if len(" ".join(tokens[index:anchor + 1])) <= limit:
                start = index
            break

    picked = tokens[start:anchor + 1]
    cursor = anchor + 1

    def fits(extra):
        return len(" ".join(picked + [extra])) <= limit

    if len(picked) < 2:
        # A bare anchor reads thin ("SHARKS"); grab the next content word it modifies.
        for index in range(anchor + 1, len(tokens)):
            core = cores[index]
            if core in _HOOK_STOPWORDS:
                continue
            if fits(tokens[index]):
                picked.append(tokens[index])
                cursor = index + 1
            break

    for index in range(cursor, len(tokens)):
        core = cores[index]
        if core in _HOOK_CONNECTORS:
            nxt = cores[index + 1] if index + 1 < len(tokens) else ""
            if not nxt or nxt in _HOOK_STOPWORDS or nxt in _HOOK_CONNECTORS:
                break
        elif core in _HOOK_STOPWORDS:
            break
        if not fits(tokens[index]):
            break
        picked.append(tokens[index])

    hook = " ".join(picked).strip(" ,;:-.!?").upper()
    # A banner must not end on a hanging connector ("... $50,000 FOR").
    while hook and _hook_core(hook.split()[-1]) in (_HOOK_CONNECTORS | {"no", "not", "but"}):
        hook = " ".join(hook.split()[:-1])
    hook = hook.strip(" ,;:-.!?")
    return hook[:limit].rstrip() or "THE PITCH"


PROMPT = """You write titles for a Shark Tank / Dragons' Den clip channel.

You get the transcript of ONE ~60 second part of a full pitch. Write:
1. "title": the post title.
   - 35-70 characters, ONE complete sentence, sentence case, terminal punctuation.
   - Use the concrete stakes from the transcript (a number, an offer, a valuation, a royalty).
   - Tease the outcome or the conflict without inventing anything not said.
   - BANNED: "Part 3/8", "Shark Tank", "Dragons' Den", "Watch this", "You won't believe",
     hashtags, emoji, quotation marks, ALL CAPS.
   - Never describe the video ("In this clip..."). Write it as the moment itself.
2. "hook": the burned on-screen banner.
   - 2-5 words, ALL CAPS, at most 28 characters.
   - The single strongest teaser of the same moment (e.g. "HE WALKED AWAY", "$150K FOR 10%").

Return ONE JSON object: {"title": "...", "hook": "..."}"""


def _user_prompt(text, source_title, show):
    return (f"SHOW: {show or 'Shark Tank'}\n"
            f"SOURCE TITLE: {_clean(source_title)[:200]}\n"
            f"TRANSCRIPT (one part):\n{text[:1800]}\n\nReturn the JSON object only.")


def _groq_title(text, source_title, show, model=None):
    """Fast path. gpt-oss is a REASONING model: `max_tokens` is spent on the hidden
    reasoning first, so a 300-token budget returned `failed_generation: ''`
    (json_validate_failed) on every part. Budget the completion, not the thoughts."""
    from groq import Groq

    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GROQ_API_KEY not set")
    client = Groq(api_key=key, timeout=40.0, max_retries=0)
    resp = client.chat.completions.create(
        model=model or os.environ.get("TITLE_MODEL", "openai/gpt-oss-120b"),
        messages=[{"role": "system", "content": PROMPT},
                  {"role": "user", "content": _user_prompt(text, source_title, show)}],
        temperature=0.7,
        response_format={"type": "json_object"},
        max_completion_tokens=int(os.environ.get("TITLE_MAX_TOKENS", "1500")),
        reasoning_effort=os.environ.get("TITLE_REASONING_EFFORT", "low"),
    )
    raw = resp.choices[0].message.content or ""
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        raise RuntimeError(f"no JSON in model output: {raw[:160]!r}")
    return json.loads(match.group(0))


def _llm_title(text, source_title, show, model=None):
    """One title call -> (data, provider). Groq first (fast), then the shared chain so a
    Groq rate limit or outage degrades to another free provider instead of a raw ASR title."""
    errors = []
    try:
        return _groq_title(text, source_title, show, model), "groq"
    except Exception as exc:
        errors.append(f"groq: {str(exc)[:200]}")
    try:
        from _llm import llm_complete, parse_json

        out = llm_complete(_user_prompt(text, source_title, show), system=PROMPT,
                           json_mode=True, temperature=0.7)
        return parse_json(out["text"]), out["provider"]
    except Exception as exc:
        errors.append(f"chain: {str(exc)[:300]}")
    raise RuntimeError("; ".join(errors))


def _valid_hook(hook, limit=28):
    text = _clean_chars(hook).upper().strip(" \"'.,!?")
    words = text.split()
    if not (2 <= len(words) <= 6) or len(text) > limit:
        return ""
    if _PART_LABEL.search(text):
        return ""
    return text


def generate(transcript, source_title="", show="Shark Tank", part=1, total=1,
             use_llm=True, model=None):
    """Return {"title","hook","provider","evidence"} for one part (never raises)."""
    text = transcript_text(transcript)
    deterministic = deterministic_title(transcript, source_title, show)
    fallback_hook = deterministic_hook(deterministic)
    if use_llm and text.strip():
        try:
            data, provider = _llm_title(text, source_title, show, model)
            title = clean_sentence(data.get("title") or "")
            title = word_cut(title, 76)
            hook = _valid_hook(data.get("hook") or "")
            if title_problem(title) or not hook:
                raise RuntimeError(f"model title rejected: {title_problem(title) or 'bad hook'}")
            return {"title": title, "hook": hook, "provider": provider,
                    "evidence": text[:280]}
        except Exception as exc:
            return {"title": deterministic, "hook": fallback_hook,
                    "provider": "deterministic", "evidence": text[:280],
                    "llm_error": str(exc)[:200]}
    return {"title": deterministic, "hook": fallback_hook,
            "provider": "deterministic", "evidence": text[:280]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--transcript", required=True,
                        help="Words JSON from transcribe_segment.py (or a .txt transcript)")
    parser.add_argument("--source-title", default="")
    parser.add_argument("--show", default="Shark Tank")
    parser.add_argument("--part", type=int, default=1)
    parser.add_argument("--total", type=int, default=1)
    parser.add_argument("--out", default=".tmp/part_title.json")
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    load_env()
    path = args.transcript if os.path.isabs(args.transcript) else str(REPO_ROOT / args.transcript)
    try:
        if path.lower().endswith((".txt", ".md")):
            with open(path, encoding="utf-8") as handle:
                transcript = handle.read()
        else:
            with open(path, encoding="utf-8") as handle:
                transcript = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        emit({"error": f"could not read transcript: {exc}", "title": "", "hook": ""})
        return

    result = generate(transcript, args.source_title, args.show,
                      args.part, args.total,
                      use_llm=not args.no_llm, model=args.model)
    out = args.out if os.path.isabs(args.out) else str(REPO_ROOT / args.out)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, ensure_ascii=False)
    emit({"path": args.out, **result})


if __name__ == "__main__":
    main()
