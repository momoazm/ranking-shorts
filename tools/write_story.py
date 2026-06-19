"""Write the script for a faceless short via the LLM fallback chain, shaped by the playbook.

Two formats:
  - narration (default): one original micro-story read by a single narrator.
  - dialogue: a punchy back-and-forth ARGUMENT between two cartoon characters (the "Peter &
    Stewie" style that's trending), each line performed by that character's own voice.

Original AI-written content (no scraping). Hook in the first line, escalating tension, sharp payoff.

Usage:
    python tools/write_story.py [--topic "..."] [--genre nosleep|aita|revenge|motivational]
        [--playbook .tmp/playbook.json] [--seconds 50] [--out .tmp/story.json]
    python tools/write_story.py --format dialogue --characters peter,stewie --topic "..."

Prints JSON: {"path": ..., "title": ..., "format": ..., "words": N, "estimated_seconds": F, "provider": ...}
"""
import argparse
import json
import os

from _common import load_env, emit, fail
from _llm import llm_complete, parse_json
from _characters import resolve_characters

WORDS_PER_SEC = 2.6  # typical faceless-Shorts narration pace; used to size the script
MAX_SECONDS = 120    # hard cap — clips are 2 minutes max (user rule, 2026-06-18)

NARRATION_SCHEMA = """Return ONE JSON object with exactly these keys:
{
  "hook": string,            // the first spoken line; <=14 words; must create an open loop / curiosity gap
  "narration": string,       // the FULL story to be read aloud, INCLUDING the hook as its first sentence.
                             //   plain prose, no stage directions, no emojis, no headings.
  "title": string,           // YouTube Shorts title, <=90 chars, high-CTR
  "description": string,     // 1-3 sentences + a few relevant #hashtags on the last line
  "tags": [string, ...],     // 8-15 lowercase search tags, no '#'
  "background_type": string  // the gameplay background that best fits, e.g. "minecraft parkour",
                             //   "subway surfers", "gta driving", "satisfying asmr". If a playbook
                             //   with trending_backgrounds is given, choose from those.
}
Output JSON only, no commentary."""

DIALOGUE_SCHEMA = """Return ONE JSON object with exactly these keys:
{
  "title": string,           // YouTube Shorts title, <=90 chars, high-CTR
  "description": string,     // 1-3 sentences + a few relevant #hashtags on the last line
  "tags": [string, ...],     // 8-15 lowercase search tags, no '#'
  "background_type": string, // gameplay background, e.g. "minecraft parkour", "subway surfers"
  "turns": [                 // the argument, in order. ALTERNATE strictly between the two speakers.
    {"speaker": "<EXACT character name>", "text": "<one short spoken line, 1 sentence, <=18 words>"},
    ...
  ]
}
Rules: the FIRST line is the hook and must grab attention instantly. Keep each line short and
punchy (spoken-word rhythm). Make them genuinely argue/banter and escalate, then land a funny
or surprising payoff on the last line. Use ONLY the exact character names given. No stage
directions, no emojis, no parentheticals. Output JSON only, no commentary."""


def load_playbook(path):
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        return None  # playbook is an optional accelerant, not a hard dependency


def build_pb_context(playbook):
    if not playbook:
        return ""
    return (
        "PLAYBOOK GUIDANCE (apply it):\n"
        f"- Hook formulas: {playbook.get('hook_formulas')}\n"
        f"- Title patterns: {playbook.get('title_patterns')}\n"
        f"- Story genres that perform: {playbook.get('story_genres')}\n"
        f"- Trending backgrounds: {playbook.get('trending_backgrounds')}\n"
        f"- Pacing: {playbook.get('pacing_notes')}\n\n"
    )


def write_narration(args, playbook, target_words, seconds):
    prompt = (
        f"{build_pb_context(playbook)}"
        f"TOPIC: {args.topic or '(you choose a gripping one that fits the genre/playbook)'}\n"
        f"GENRE: {args.genre or '(you choose the best-performing genre)'}\n"
        f"TARGET LENGTH: about {target_words} words (~{seconds}s of narration). Stay within +/-15%.\n\n"
        "Write a complete, original micro-story engineered for retention: a hook that opens a "
        "curiosity gap in the first sentence, rising tension, and a sharp twist or payoff at the "
        "end. No filler. Conversational, spoken-word rhythm.\n\n"
        f"{NARRATION_SCHEMA}"
    )
    out = llm_complete(
        prompt,
        system="You are a viral short-form story writer for faceless YouTube Shorts. "
        "You write tight, original, spoken-word stories and output strict JSON.",
        json_mode=True,
        temperature=0.9,
    )
    story = parse_json(out["text"])
    required = ["hook", "narration", "title", "description", "tags", "background_type"]
    missing = [k for k in required if k not in story or not story[k]]
    if missing:
        raise ValueError(f"Story JSON missing required keys: {missing} | raw: {out['text'][:400]}")
    story["format"] = "narration"
    story["words"] = len(story["narration"].split())
    return story, out["provider"]


def write_dialogue(args, playbook, target_words, seconds, cast):
    roster = "\n".join(f"- {c['name']}: {c['persona']}" for c in cast)
    names = " and ".join(c["name"] for c in cast)
    # Models tend to stop early with terse fragments, so enforce a hard floor on line count
    # and a per-line word range — this is what actually fills the target runtime.
    min_turns = max(12, target_words // 8)
    prompt = (
        f"{build_pb_context(playbook)}"
        f"FORMAT: a two-character argument/banter short, in the viral 'cartoon characters arguing' style.\n"
        f"CHARACTERS (write each strictly in-character):\n{roster}\n\n"
        f"TOPIC they argue about: {args.topic or '(you choose a funny, relatable, debatable topic)'}\n"
        f"TARGET LENGTH: about {target_words} words total across all lines (~{seconds}s of speech).\n"
        f"LENGTH IS MANDATORY: write AT LEAST {min_turns} alternating lines. Do NOT end early — keep the "
        f"argument escalating with new angles until you have at least that many lines. Each line must be a "
        f"complete spoken sentence of roughly 8-16 words (NOT 2-4 word fragments).\n\n"
        f"Write {names} arguing. Strictly alternate speakers. Open with a punchy hook line, escalate the "
        f"disagreement with quick jabs and rising stakes, and end on a funny or surprising payoff.\n\n"
        f"{DIALOGUE_SCHEMA}"
    )
    out = llm_complete(
        prompt,
        system="You are a viral short-form comedy writer for faceless YouTube Shorts. You write "
        "tight, punchy two-character argument scripts, perfectly in character, as strict JSON.",
        json_mode=True,
        temperature=0.95,
    )
    story = parse_json(out["text"])
    required = ["title", "description", "tags", "background_type", "turns"]
    missing = [k for k in required if k not in story or not story[k]]
    if missing:
        raise ValueError(f"Dialogue JSON missing required keys: {missing} | raw: {out['text'][:400]}")

    valid_names = {c["name"].lower(): c["name"] for c in cast}
    turns = []
    for t in story["turns"]:
        spk = str(t.get("speaker", "")).strip()
        txt = str(t.get("text", "")).strip()
        if not txt:
            continue
        canon = valid_names.get(spk.lower())
        if canon is None:
            # Snap unknown/garbled speaker labels to the alternating expectation.
            canon = cast[len(turns) % len(cast)]["name"]
        turns.append({"speaker": canon, "text": txt})
    if len(turns) < 2:
        raise ValueError("Dialogue produced fewer than 2 usable turns.")

    story["turns"] = turns
    story["format"] = "dialogue"
    story["characters"] = cast
    story["words"] = sum(len(t["text"].split()) for t in turns)
    return story, out["provider"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--format", choices=["narration", "dialogue"], default="narration",
                        help="narration = single narrator story; dialogue = two characters arguing")
    parser.add_argument("--characters", help="Dialogue cast, comma-separated registry keys (default: peter,stewie)")
    parser.add_argument("--topic", help="Optional seed topic; if omitted, the model picks a strong one")
    parser.add_argument("--genre", help="narration genres: nosleep, aita, revenge, motivational, mystery")
    parser.add_argument("--playbook", default=".tmp/playbook.json")
    parser.add_argument("--seconds", type=int, default=40)
    parser.add_argument("--out", default=".tmp/story.json")
    args = parser.parse_args()

    load_env()

    playbook = load_playbook(args.playbook)
    seconds = max(5, min(args.seconds, MAX_SECONDS))  # clips are 2 minutes max
    target_words = int(seconds * WORDS_PER_SEC)

    try:
        if args.format == "dialogue":
            names = [s for s in (args.characters or "").split(",") if s.strip()] or None
            cast = resolve_characters(names)
            if len(cast) != 2:
                fail("Dialogue format needs exactly 2 characters (e.g. --characters peter,stewie)")
                return
            story, provider = write_dialogue(args, playbook, target_words, seconds, cast)
        else:
            story, provider = write_narration(args, playbook, target_words, seconds)
    except ValueError as e:
        fail(f"Script generation failed: {e}")
        return
    except Exception as e:
        fail(f"Script generation failed: {e}")
        return

    story["topic"] = args.topic
    story["genre"] = args.genre
    story["estimated_seconds"] = round(story["words"] / WORDS_PER_SEC, 1)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(story, f, indent=2, ensure_ascii=False)

    result = {
        "path": args.out,
        "title": story["title"],
        "format": story["format"],
        "background_type": story["background_type"],
        "words": story["words"],
        "estimated_seconds": story["estimated_seconds"],
        "provider": provider,
    }
    if story["format"] == "dialogue":
        result["turns"] = len(story["turns"])
        result["cast"] = [c["name"] for c in story["characters"]]
    emit(result)


if __name__ == "__main__":
    main()
