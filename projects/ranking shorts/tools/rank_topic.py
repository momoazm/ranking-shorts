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

GENRES = ["fails", "cats", "babies", "dogs"]

SCHEMA = """Return ONE JSON object with exactly these keys:
{
  "genre": string,         // EXACTLY one of: fails, cats, babies, dogs -- pick the MOST TRENDING/viral right now
  "title": string,         // A CURIOSITY-GAP / emotional countdown title, English, <=70 chars. It must
                           //   still read as a Top-5 ranking but open a loop or promise a payoff -- do
                           //   NOT use the flat "Ranking The Best X" pattern. Use one of these angles:
                           //   - payoff promise: "Top 5 Cat Fails -- #1 Made Me Scream"
                           //   - contrast/"shouldn't": "Top 5 Baby Fails That Shouldn't Be This Funny"
                           //   - escalation: "These Dog Fails Get Worse Every Single Time"
                           //   - dare/relatable: "Top 5 Fails You Can't Watch Without Laughing"
  "criterion": string,     // what we're ranking by (e.g. "how hard it makes you laugh")
  "hook": string           // a 1-sentence opener for the description, written as a curiosity gap
}
You make single-genre "Ranking" Shorts from real funny clips. Choose the ONE genre from the allowed
list that is most trending and rewatchable. The TITLE is the thumbnail/feed hook -- topic framing
beats production, so make it a curiosity gap that promises the #1 payoff, never a flat label.
Output JSON only."""


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

    for k in ("genre", "title", "criterion", "hook"):
        if not data.get(k):
            fail(f"Topic JSON missing '{k}': {out['text'][:300]}")
            return
    if data["genre"] not in GENRES:
        data["genre"] = "fails"   # safe default if the model picks something off-list

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    emit({**data, "provider": out["provider"], "path": args.out})


if __name__ == "__main__":
    main()
