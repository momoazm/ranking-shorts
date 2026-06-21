"""Pick & ORDER the best 5 candidate clips into a #5->#1 countdown, with subjective commentary
and the spoken narration for each (LLM fallback chain).

Usage:
    python tools/rank_clips.py --candidates .tmp/rank_candidates.json --topic .tmp/rank_topic.json \
        [--out .tmp/ranked.json]

Prints JSON: {"entries":[{rank, candidate_index, id, title, line}], "provider"}  (entries are #5..#1)
"""
import argparse
import json
import os

from _common import load_env, emit, fail
from _llm import llm_complete, parse_json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", default=".tmp/rank_candidates.json")
    ap.add_argument("--topic", default=".tmp/rank_topic.json")
    ap.add_argument("--out", default=".tmp/ranked.json")
    args = ap.parse_args()

    load_env()
    try:
        cands = json.load(open(args.candidates, encoding="utf-8"))["candidates"]
        topic = json.load(open(args.topic, encoding="utf-8"))
    except (OSError, json.JSONDecodeError, KeyError) as e:
        fail(f"Could not read inputs: {e}")
        return

    listing = "\n".join(f"[{i}] {c['title']}" for i, c in enumerate(cands))
    schema = """Return ONE JSON object:
{
  "entries": [   // EXACTLY 5 items, ordered from rank 5 (first/worst) to rank 1 (last/best)
    {"rank": 5, "candidate_index": <int index from the list>, "label": "<short funny meme caption, 1-3 words>"},
    {"rank": 4, ...}, {"rank": 3, ...}, {"rank": 2, ...}, {"rank": 1, ...}
  ]
}
Pick the 5 BEST candidates for the topic and rank them subjectively by the criterion. Each `label`
is a SHORT punchy Gen-Z meme caption for that clip (1-3 words, <=16 chars), DIFFERENT for each rank
-- e.g. "Aura Lost", "Skill Issue", "Pure Pain", "Certified Bruh", "Massive L", "Caught in 4K".
Use each candidate_index at most once. Output JSON only."""
    prompt = (f"TOPIC: {topic.get('title')}\nRANK BY: {topic.get('criterion')}\n\n"
              f"CANDIDATES:\n{listing}\n\n{schema}")

    try:
        out = llm_complete(prompt, system="You rank clips for viral countdown Shorts. English. Strict JSON.",
                           json_mode=True, temperature=0.85)
        data = parse_json(out["text"])
        entries = data["entries"]
    except Exception as e:
        fail(f"Ranking failed: {e}")
        return

    clean = []
    seen = set()
    for e in entries:
        idx = e.get("candidate_index")
        if not isinstance(idx, int) or not (0 <= idx < len(cands)) or idx in seen:
            continue
        seen.add(idx)
        c = cands[idx]
        clean.append({"rank": e.get("rank"), "candidate_index": idx, "id": c["id"],
                      "title": c["title"], "url": c["url"], "duration": c.get("duration"),
                      "label": str(e.get("label", "")).strip()[:16]})
    if len(clean) < 5:
        fail(f"Ranking produced only {len(clean)} valid entries.", entries=clean)
        return
    clean = clean[:5]

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"title": topic.get("title"), "hook": topic.get("hook"), "entries": clean},
                  f, indent=2, ensure_ascii=False)
    emit({"count": len(clean), "entries": [{"rank": e["rank"], "title": e["title"][:50]} for e in clean],
          "provider": out["provider"], "path": args.out})


if __name__ == "__main__":
    main()
