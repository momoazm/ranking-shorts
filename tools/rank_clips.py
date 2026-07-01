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

ANGLE_DESC = {
    "fan": "crowd/supporters only -- chants, celebrations, reactions in the stands. Exclude anything "
           "showing on-pitch match action, mascots, animals, or unrelated novelty clips.",
    "match": "on-pitch match action only -- goals, saves, skills, fouls, ref calls/VAR. Exclude "
             "anything showing crowd/fan shots, mascots, animals, or unrelated novelty clips.",
    "streamer": "famous streamers/creators (e.g. iShowSpeed, FaZe Clan, Marlon, Adin) reacting to, "
                "attending, or playing football at/around the World Cup -- their live reactions, "
                "celebrations, or IRL moments tied to football or the tournament. Exclude pure pro "
                "match footage with no streamer, generic crowd shots with no streamer, and any "
                "streamer clip unrelated to football / the World Cup (gaming, random IRL, etc.).",
}


def classify_angle(cands, angle):
    """Return (matching_indices, err) -- err is set only on a real LLM/parse failure, NOT when too
    few candidates match (callers decide what "too few" means for their purpose: filter_by_angle
    below treats <5 as fatal, but a probe call just wants the raw count)."""
    listing = "\n".join(f"[{i}] {c['title']}" for i, c in enumerate(cands))
    schema = ('Return ONE JSON object: {"matches": [<int indices that clearly fit>]}\n'
              f"From the CANDIDATES list, return the indices of every candidate whose title clearly "
              f"fits: {ANGLE_DESC[angle]} Output JSON only.")
    prompt = f"CANDIDATES:\n{listing}\n\n{schema}"
    try:
        out = llm_complete(prompt, system="You classify clip titles for a strict content filter. Strict JSON.",
                           json_mode=True, temperature=0.2)
        data = parse_json(out["text"])
        idxs = sorted({i for i in data.get("matches", []) if isinstance(i, int) and 0 <= i < len(cands)})
    except Exception as e:
        return None, f"Angle classification failed: {e}"
    return idxs, None


def filter_by_angle(cands, angle):
    """Pre-classify candidates by angle BEFORE ranking, so the ranking step never has to choose
    between violating the angle lock and failing to fill 5 slots (asking one LLM call to both
    reject off-angle clips AND always produce exactly 5 is a contradiction the model resolves by
    duplicating an index, which then gets dropped as invalid -- this splits it into two clean steps."""
    idxs, err = classify_angle(cands, angle)
    if err:
        return None, err
    if len(idxs) < 5:
        return None, (f"Only {len(idxs)} candidates fit the '{angle}' angle (need >=5) "
                      f"out of {len(cands)} total.")
    return [cands[i] for i in idxs], None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", default=".tmp/rank_candidates.json")
    ap.add_argument("--topic", default=".tmp/rank_topic.json")
    ap.add_argument("--out", default=".tmp/ranked.json")
    ap.add_argument("--classify-angle", default=None, choices=list(ANGLE_DESC),
                    help="Probe mode: just count/list candidates fitting this angle, no ranking. "
                         "Lets the caller pick a sourceable angle BEFORE committing to a topic title.")
    args = ap.parse_args()

    load_env()
    try:
        cands = json.load(open(args.candidates, encoding="utf-8"))["candidates"]
    except (OSError, json.JSONDecodeError, KeyError) as e:
        fail(f"Could not read candidates: {e}")
        return

    if args.classify_angle:
        idxs, aerr = classify_angle(cands, args.classify_angle)
        if aerr:
            fail(aerr)
            return
        emit({"angle": args.classify_angle, "count": len(idxs), "ids": [cands[i]["id"] for i in idxs]})
        return

    try:
        topic = json.load(open(args.topic, encoding="utf-8"))
    except (OSError, json.JSONDecodeError, KeyError) as e:
        fail(f"Could not read topic: {e}")
        return

    angle = topic.get("angle") if topic.get("genre") == "worldcup" else None
    if angle in ANGLE_DESC:
        cands, aerr = filter_by_angle(cands, angle)
        if aerr:
            fail(aerr)
            return

    listing = "\n".join(f"[{i}] {c['title']}" for i, c in enumerate(cands))
    schema = """Return ONE JSON object:
{
  "entries": [   // EXACTLY 5 items, ordered rank 5 (shown FIRST -- the hook) to rank 1 (shown LAST -- the best payoff)
    {"rank": 5, "candidate_index": <int index from the list>, "label": "<short funny meme caption, 1-3 words>"},
    {"rank": 4, ...}, {"rank": 3, ...}, {"rank": 2, ...}, {"rank": 1, ...}
  ]
}
Pick the 5 candidates that best MATCH THE TOPIC. HOOK RULE (critical for retention -- a countdown
lives or dies on its first 2 seconds): rank #5 is the FIRST clip the viewer sees after the cold-open
teaser, so it MUST be the single most instantly eye-catching / high-action / "wait, WHAT?!" clip of
the five -- the strongest opener, NOT the weakest. Rank #1 (shown last) stays the overall BEST payoff
(the teaser promises it). Order the middle three (ranks #4 -> #2) by the criterion, ascending. So:
pick the 5 best clips, put the best payoff at #1, put the most immediately gripping clip at #5, and
rank the middle three by the criterion. IMPORTANT: prefer
clips whose title shows the actual event the topic promises (for a "fails" topic pick real fails/
accidents/mishaps -- someone falls, crashes, slips, things go wrong; avoid merely cute or calm clips
unless nothing better exists). NEVER pick a clip whose title suggests death/injury, grief or tribute,
politics, war, or serious news -- skip those candidates even if no other clips are left; this matters
most for sports-adjacent feeds (e.g. r/soccer) which mix serious news in with the funny clips. Each
`label` is a SHORT punchy Gen-Z meme caption for that clip (1-3
words, <=16 chars), DIFFERENT for each rank -- e.g. "Aura Lost", "Skill Issue", "Pure Pain",
"Certified Bruh", "Massive L", "Caught in 4K". Use each candidate_index at most once. Output JSON only."""
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
