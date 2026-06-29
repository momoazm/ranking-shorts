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

from _common import load_env, emit, fail
from _llm import llm_complete, parse_json


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
    listing = "\n".join(f"[Rank {e.get('rank')}] {clip_titles[i]}" for i, e in enumerate(entries))

    prompt = f"""Analyze these 5 clips (ranked by virality, #1 = best) and generate a SPECIFIC, CATCHY title
that captures what they have in common. The title should be:
- Specific to the actual content (not generic like "Epic Fails" or "Top 5")
- Catchy, punchy, Gen-Z style
- Optimized for shorts virality (curiosity, shock value, relatability)
- Under 50 chars
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

    refined_title = data.get("title", "").strip()[:50]
    refined_hook = data.get("hook", "").strip()[:200]
    reasoning = data.get("reasoning", "").strip()

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
