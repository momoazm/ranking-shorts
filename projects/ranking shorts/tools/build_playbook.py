"""Research what's working in the brainrot-Shorts niche right now and distill it into a reusable
playbook.json the pipeline reads on every run (hooks, title patterns, hashtags, pacing, topics).

Runs a handful of Tavily/Exa searches (best-effort — thin/absent research is fine, the LLM then
leans on priors), optionally folds in a --seed file of prior findings (e.g. the competitor
project's report text), then asks the LLM fallback chain to synthesize a structured playbook.
write_story.py consumes hook_formulas/title_patterns/etc.; autopost.py caches this ~daily so it
doesn't burn search quota every 4h run.

Usage:
    python tools/build_playbook.py [--niche "..."] [--seed path] [--out .tmp/playbook.json]

Prints JSON: {"path": ..., "hook_formulas": N, "trending_hashtags": [...], "sources": N, "provider": ...}
"""
import argparse
import json
import os
from datetime import date

from _common import load_env, emit, fail
from _llm import llm_complete, parse_json

DEFAULT_NICHE = ("Italian-brainrot / 'cartoon characters arguing' (Peter & Stewie style) "
                 "faceless AI-generated YouTube Shorts")

SCHEMA_HINT = """Return ONE JSON object with exactly these keys:
{
  "niche": string,
  "hook_formulas": [string, ...],          // 5-8 opening-line/hook patterns that retain in the first 1-3s
  "title_patterns": [string, ...],         // 5-8 high-CTR Shorts title templates (use <PLACEHOLDERS>)
  "trending_hashtags": [string, ...],      // 10-20 currently-trending hashtags for this niche, WITHOUT the '#'
  "topic_ideas": [string, ...],            // 8-12 funny, debatable topics two characters could argue about
  "ideal_length_seconds": {"min": int, "max": int},
  "pacing_notes": string,                  // cut rhythm, line length, when to land the payoff
  "caption_style": {"position": string, "highlight": string, "words_per_cue": int, "notes": string},
  "trending_backgrounds": [string, ...],   // settings/backdrops trending now for this niche
  "story_genres": [string, ...],
  "dos": [string, ...],
  "donts": [string, ...]
}
Base it on the research provided. Be concrete and tactical, not generic. Output JSON only."""


def gather_research(niche, max_results):
    """Best-effort search; returns (snippets_text, sources). Never raises — thin research is OK."""
    try:
        from tavily_search import search_tavily, search_exa
    except Exception:
        return "", []

    queries = [
        f"best performing {niche} hooks retention 2026",
        f"trending hashtags {niche} youtube shorts tiktok 2026",
        f"viral brainrot shorts title formulas {niche}",
        "cartoon characters arguing shorts what makes them go viral",
    ]
    snippets, sources = [], []
    for q in queries:
        results = []
        try:
            results = search_tavily(q, max_results, "general")
        except Exception:
            try:
                results = search_exa(q, max_results)
            except Exception:
                results = []
        for r in results:
            if r.get("snippet"):
                snippets.append(f"- ({q}) {r.get('title')}: {r['snippet']}")
            if r.get("url"):
                sources.append({"title": r.get("title"), "url": r.get("url")})
    return "\n".join(snippets), sources


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--niche", default=DEFAULT_NICHE)
    parser.add_argument("--seed", help="Optional path to prior findings (e.g. competitor report text)")
    parser.add_argument("--max-results", type=int, default=4)
    parser.add_argument("--out", default=".tmp/playbook.json")
    args = parser.parse_args()

    load_env()

    research, sources = gather_research(args.niche, args.max_results)

    seed_text = ""
    if args.seed:
        try:
            with open(args.seed, "r", encoding="utf-8") as f:
                seed_text = f.read()[:8000]
        except OSError as e:
            fail(f"Could not read --seed: {e}")
            return

    prompt = (
        f"NICHE: {args.niche}\n\n"
        f"PRIOR FINDINGS (may be empty):\n{seed_text or '(none)'}\n\n"
        f"WEB RESEARCH SNIPPETS (may be thin):\n{research or '(none)'}\n\n"
        f"{SCHEMA_HINT}"
    )

    try:
        out = llm_complete(
            prompt,
            system="You are a short-form video strategist who reverse-engineers what makes "
            "brainrot/cartoon-argument Shorts go viral. You output strict JSON.",
            json_mode=True,
            temperature=0.6,
        )
        playbook = parse_json(out["text"])
    except Exception as e:
        fail(f"Playbook synthesis failed: {e}")
        return

    playbook["generated_at"] = date.today().isoformat()
    playbook["sources"] = sources
    if not research:
        playbook["low_confidence"] = "Web research was thin/unavailable; playbook leans on model priors."

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(playbook, f, indent=2, ensure_ascii=False)

    emit({
        "path": args.out,
        "provider": out["provider"],
        "hook_formulas": len(playbook.get("hook_formulas", [])),
        "trending_hashtags": playbook.get("trending_hashtags", []),
        "trending_backgrounds": playbook.get("trending_backgrounds", []),
        "sources": len(sources),
    })


if __name__ == "__main__":
    main()
