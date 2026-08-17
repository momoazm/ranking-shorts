"""Analyze selected clips and generate a specific, catchy title based on what they have in common.

Why: Pre-made titles are generic. After selecting the best 5 clips, we know what they're actually
about -- so we can generate a title that (1) matches the real clips, (2) is specific/catchy,
(3) ensures the video is cohesive.

Usage:
    python tools/refine_title.py --ranked .tmp/ranked.json --out .tmp/refined_title.json

Prints JSON: {"title": "...", "hook": "...", "refined": true, "provider": "groq"|...}
"""
import argparse
import json
import re

from _common import load_env, emit, fail
from _llm import llm_complete, parse_json


GENERIC_TITLE_RE = re.compile(
    r"\b(?:top\s*5|top\s*five|best|wild|crazy|insane|funny)\s+(?:streamer\s+)?"
    r"(?:moments?|clips?|highlights?|reactions?)\b|\bcompilation\b",
    re.IGNORECASE,
)
SPECIFIC_TITLE_RE = re.compile(
    r"\b(?:called\s+out|roast(?:ed|s|ing)?|cringe|rigged|caught|busted|meltdown|"
    r"rage|eliminat(?:ed|ion)|fails?|wins?|loses?|\$\s?\d+|million|challenge)\b",
    re.IGNORECASE,
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ranked", default=".tmp/ranked.json", help="Output from rank_clips.py")
    ap.add_argument("--out", default=".tmp/refined_title.json")
    args = ap.parse_args()

    load_env()
    try:
        ranked = json.load(open(args.ranked, encoding="utf-8"))
    except (OSError, json.JSONDecodeError, KeyError) as e:
        fail(f"Could not read ranked clips: {e}")
        return

    entries = ranked.get("entries", [])
    if len(entries) < 5:
        fail(f"Expected 5 ranked clips, got {len(entries)}")
        return

    # Extract clip titles and themes
    clip_titles = [e.get("title", "").strip() for e in entries]
    listing = "\n".join(
        f"[Rank {e.get('rank')}] {clip_titles[i]} (hook signal={e.get('signal_score', 'n/a')}/100)"
        for i, e in enumerate(entries)
    )

    prompt = f"""Analyze these 5 clips (ranked by virality, #1 = best) and generate a SPECIFIC, CATCHY title
that captures what they have in common. The title should be:
- Specific to the actual content (not generic like "Epic Fails" or "Top 5")
- Use one concrete actor + action + consequence whenever the clips support it: e.g. called out,
  roasted, cringe question, rigged game, meltdown, or an obvious fail.
- Catchy, punchy, Gen-Z style
- Optimized for shorts virality (curiosity, shock value, relatability)
- Under 50 chars
- Avoid "wild moments", "best moments", "top moments", "funny compilation", and other labels
  that do not tell the viewer what actually happens.
- Something like "POV: You're Worse Than Expected" or "Confidence Gone Wrong" or "The Skill Deficit"

CLIPS:
{listing}

Return ONE JSON object:
{{
  "title": "<specific catchy title, <50 chars>",
  "hook": "<1-sentence hook/why you should watch this (for description>",
  "reasoning": "<brief note on what tied these clips together>"
}}

Output JSON only."""

    try:
        out = llm_complete(
            prompt,
            system="You create viral Shorts titles. Catchy, specific, engaging. English. Strict JSON.",
            json_mode=True,
            temperature=0.9
        )
        data = parse_json(out["text"])
    except Exception as e:
        fail(f"Title refinement failed: {e}")
        return

    # Titles must open with a letter/digit -- LLMs like leading emoji/quotes, and a stripped
    # boilerplate prefix once left a title starting with ":" (2026-07-05).
    refined_title = re.sub(r"^[^0-9A-Za-z]+", "", data.get("title", "").strip())[:50].strip()
    refined_hook = data.get("hook", "").strip()[:200]
    reasoning = data.get("reasoning", "").strip()

    # Do not let a high-temperature title model erase the concrete event we measured in the
    # selected clips. If its result is generic, use the best selected source title as a factual
    # fallback; the selector/ranker already filtered that row for streamer-only safety.
    if GENERIC_TITLE_RE.search(refined_title) and not SPECIFIC_TITLE_RE.search(refined_title):
        rank_one = next((entry for entry in entries if entry.get("rank") == 1), entries[-1])
        source_title = re.sub(r"\s+", " ", str(rank_one.get("title") or "")).strip()
        if source_title:
            refined_title = source_title[:50].rstrip(" -,:;")
            reasoning = (reasoning + " Used the rank-one source title because the model title was "
                         "too generic.").strip()

    if not refined_title:
        fail("LLM returned empty title")
        return

    # Output
    result = {
        "title": refined_title,
        "hook": refined_hook,
        "reasoning": reasoning,
        "refined": True,
        "provider": out["provider"],
        "original_title": ranked.get("title", ""),
        "clip_count": len(entries),
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    emit(result)


if __name__ == "__main__":
    main()
