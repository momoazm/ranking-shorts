"""Pick a catchy Top-5 RANKING topic + a YouTube search query (LLM fallback chain).

Auto-picks a trending, broadly-appealing countdown topic for a faceless ranking Short, plus the
search query used to pull candidate clips, the ranking criterion, and a hook line.

Usage:
    python tools/rank_topic.py [--niche "..."] [--playbook .tmp/playbook.json] [--out .tmp/rank_topic.json]

Prints JSON: {"title","search_query","criterion","hook","provider"}
"""
import argparse
import json
import os

from _common import load_env, emit, fail
from _llm import llm_complete, parse_json

SCHEMA = """Return ONE JSON object with exactly these keys:
{
  "title": string,         // the video title, a punchy "Top 5 ..." countdown (<=80 chars, English)
  "search_query": string,  // a YouTube search query returning many SHORT, single standalone clips
                           //   (NOT hour-long compilations — avoid the word "compilation"; favor short funny clips)
  "criterion": string,     // what we're ranking by (e.g. "how jaw-dropping it is")
  "hook": string           // a 1-sentence spoken hook to open the video
}
Pick a TRENDING, highly visual, broadly-appealing topic that works as a 5-clip countdown using
real YouTube footage (e.g. craziest sports moments, most insane goals, wildest animal moments,
biggest mansions, fastest cars, most satisfying videos). Output JSON only."""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--niche", default="", help="Optional steer (e.g. 'sports', 'animals')")
    ap.add_argument("--playbook", default=".tmp/playbook.json")
    ap.add_argument("--out", default=".tmp/rank_topic.json")
    args = ap.parse_args()

    load_env()
    pb = ""
    try:
        with open(args.playbook, "r", encoding="utf-8") as f:
            data = json.load(f)
        pb = f"Trending now (lean into these): {data.get('topic_ideas')} / {data.get('trending_hashtags')}\n"
    except (OSError, json.JSONDecodeError):
        pass

    prompt = (f"{pb}NICHE STEER (optional): {args.niche or '(you choose the best topic)'}\n\n{SCHEMA}")
    try:
        out = llm_complete(prompt, system="You are a viral faceless-Shorts strategist who designs "
                           "ranking/countdown videos. Output strict JSON in English.",
                           json_mode=True, temperature=0.9)
        data = parse_json(out["text"])
    except Exception as e:
        fail(f"Topic pick failed: {e}")
        return

    for k in ("title", "search_query", "criterion", "hook"):
        if not data.get(k):
            fail(f"Topic JSON missing '{k}': {out['text'][:300]}")
            return

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    emit({**data, "provider": out["provider"], "path": args.out})


if __name__ == "__main__":
    main()
