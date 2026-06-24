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
import random

from _common import load_env, emit, fail
from _llm import llm_complete, parse_json

GENRES = ["fails", "cats", "babies", "dogs", "worldcup"]
WORLDCUP_ANGLES = ["fan", "match"]

SCHEMA = """Return ONE JSON object with exactly these keys:
{
  "genre": string,         // EXACTLY one of: fails, cats, babies, dogs, worldcup -- pick the MOST TRENDING/viral right now.
                           //   "worldcup" = World Cup clips, committed to ONE single angle (see "angle" below).
  "angle": string,         // ONLY when genre is "worldcup": EXACTLY "fan" or "match" -- pick ONE, never mix:
                           //   - "fan": crowd/supporters only -- chants, celebrations, reactions in the stands.
                           //     No players, no match footage, no mascots/animals/unrelated novelty clips.
                           //   - "match": on-pitch action only -- goals, saves, skills, fouls, ref calls/VAR.
                           //     No crowd shots, no mascots/animals/unrelated novelty clips.
                           //   For every other genre, leave this "" (empty string).
  "title": string,         // A CURIOSITY-GAP / emotional countdown title, English, <=70 chars. It must
                           //   still read as a Top-5 ranking but open a loop or promise a payoff -- do
                           //   NOT use the flat "Ranking The Best X" pattern. Use one of these angles:
                           //   - payoff promise: "Top 5 Cat Fails -- #1 Made Me Scream"
                           //   - contrast/"shouldn't": "Top 5 Baby Fails That Shouldn't Be This Funny"
                           //   - escalation: "These Dog Fails Get Worse Every Single Time"
                           //   - dare/relatable: "Top 5 Fails You Can't Watch Without Laughing"
                           //   When genre is "worldcup", the title must clearly reflect the chosen angle
                           //   (e.g. "Top 5 Wildest World Cup Fan Reactions" or "Top 5 Most Insane World
                           //   Cup Goals") -- never a title that implies both fans AND match action.
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
    ap.add_argument("--force-genre", default=None, choices=GENRES,
                    help="Lock the genre instead of letting the model pick (e.g. 'worldcup' while "
                         "the tournament is live). Title/criterion/hook are still generated fresh.")
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

    genre_lock = (f"GENRE IS FIXED to '{args.force_genre}' for this run -- write the title/criterion/"
                  f"hook for that theme; still fill in the genre field with '{args.force_genre}'.\n"
                  if args.force_genre else "")
    angle_lock = ""
    forced_angle = None
    if args.force_genre == "worldcup":
        forced_angle = random.choice(WORLDCUP_ANGLES)
        angle_lock = (f"ANGLE IS FIXED to '{forced_angle}' for this run -- commit the title/criterion "
                      f"fully to that single angle (no mixing fan + match content).\n")
    prompt = (f"{pb}{genre_lock}{angle_lock}NICHE STEER (optional): {args.niche or '(you choose the best topic)'}\n\n{SCHEMA}")
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
    if args.force_genre:
        data["genre"] = args.force_genre   # don't trust the model to honor the lock
    if data["genre"] == "worldcup":
        # don't trust the model to honor the angle lock either -- enforce it directly
        data["angle"] = forced_angle if forced_angle else (
            data.get("angle") if data.get("angle") in WORLDCUP_ANGLES else random.choice(WORLDCUP_ANGLES))
    else:
        data["angle"] = ""

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    emit({**data, "provider": out["provider"], "path": args.out})


if __name__ == "__main__":
    main()
