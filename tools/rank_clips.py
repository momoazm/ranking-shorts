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
import re
import sys

from _common import channel_ok, load_env, emit, fail
from _llm import llm_complete, parse_json

ANGLE_DESC = {
    "fan": "crowd/supporters only -- chants, celebrations, reactions in the stands. Exclude anything "
           "showing on-pitch match action, mascots, animals, or unrelated novelty clips.",
    "match": "on-pitch match action only -- goals, saves, skills, fouls, ref calls/VAR. Exclude "
             "anything showing crowd/fan shots, mascots, animals, or unrelated novelty clips.",
    "streamer": "famous streamers/creators (e.g. FaZe Clan, Marlon, Adin -- NEVER iShowSpeed) reacting to, "
                "attending, or playing football at/around the World Cup -- their live reactions, "
                "celebrations, or IRL moments tied to football or the tournament. Exclude pure pro "
                "match footage with no streamer, generic crowd shots with no streamer, and any "
                "streamer clip unrelated to football / the World Cup (gaming, random IRL, etc.).",
}

FALLBACK_LABELS = ("Instant Chaos", "Chat Lost It", "Streamer Moment", "Caught Live", "Final Boss")

# The recent high-reach streamer posts were not generic "best moments" packages. They named a
# legible social event (called out / roasted / cringe / rigged) and let the viewer wait for the
# consequence. Keep this signal deterministic so a provider timeout cannot silently choose weak
# generic gameplay as the fallback.
CONFLICT_TERMS = (
    "called out", "roast", "roasted", "cringe", "rigged", "caught", "busted", "chat",
    "rage", "meltdown", "freak", "embarrass", "exposed", "awkward", "fails",
)
ACTION_TERMS = (
    "eliminat", "loses", "lost", "break", "throws", "falls", "fails", "smash", "hits",
    "says", "answer", "challenge", "react", "reaction", "surprise", "win", "clutch",
)
GENERIC_TERMS = (
    "funny moments", "best moments", "top moments", "compilation", "montage", "gameplay",
    "highlights", "stream highlights",
)


def streamer_signal_score(candidate):
    """Score how quickly a streamer candidate communicates a concrete payoff.

    This is a ranking aid, not a claim that title text equals virality. It gives the deterministic
    path a sensible quality floor and exposes the signal to the LLM alongside view count.
    """
    text = " ".join(str(candidate.get(key) or "") for key in
                    ("title", "channel", "uploader", "streamer_identity")).lower()
    score = 35
    score += min(24, sum(8 for term in CONFLICT_TERMS if term in text))
    score += min(20, sum(6 for term in ACTION_TERMS if term in text))
    if candidate.get("streamer_identity") or candidate.get("channel"):
        score += 8
    if re.search(r"\$\s?\d|\b(?:one|two|three|million|thousand)\b", text):
        score += 7
    score -= min(25, sum(8 for term in GENERIC_TERMS if term in text))
    try:
        duration = float(candidate.get("duration"))
        if 12 <= duration <= 45:
            score += 6
        elif duration > 60:
            score -= 8
    except (TypeError, ValueError):
        pass
    return max(0, min(100, int(score)))


def classify_angle(cands, angle):
    """Return (matching_indices, err) -- err is set only on a real LLM/parse failure, NOT when too
    few candidates match (callers decide what "too few" means for their purpose: filter_by_angle
    below treats <5 as fatal, but a probe call just wants the raw count)."""
    def candidate_line(i, c):
        meta = []
        if c.get("channel"):
            meta.append(f"channel={c['channel']}")
        if c.get("duration"):
            meta.append(f"duration={c['duration']}s")
        if c.get("view_count"):
            meta.append(f"views={c['view_count']}")
        return f"[{i}] {c['title']}" + (f" ({', '.join(meta)})" if meta else "")

    listing = "\n".join(candidate_line(i, c) for i, c in enumerate(cands))
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


def extract_ranking_entries(data):
    """Return the model's selected rows while tolerating harmless wrapper-key drift."""
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        raise ValueError("LLM JSON response was not an object or array")
    entries = data.get("entries")
    if entries is None:
        for key in ("ranking", "rankings", "ranked_clips", "clips", "items", "results"):
            candidate = data.get(key)
            if isinstance(candidate, list):
                entries = candidate
                break
    if not isinstance(entries, list):
        raise ValueError("LLM JSON response did not contain an entries array")
    return entries


def _candidate_index(entry, cands):
    """Normalize harmless provider drift while keeping selection inside the candidate list."""
    if not isinstance(entry, dict):
        return None

    values = []
    for key in ("candidate_index", "index", "clip_index", "candidate"):
        value = entry.get(key)
        if isinstance(value, dict):
            values.extend(value.get(key) for key in ("candidate_index", "index", "clip_index"))
        else:
            values.append(value)
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            if 0 <= value < len(cands):
                return value
        elif isinstance(value, str) and value.strip().isdigit():
            index = int(value.strip())
            if 0 <= index < len(cands):
                return index

    # Some otherwise valid JSON responses identify a clip by its stable video id or title
    # instead of returning the requested numeric index. Exact matches avoid guessing.
    for key in ("candidate_id", "video_id", "id", "url"):
        value = entry.get(key)
        if value in (None, ""):
            continue
        value = str(value).strip()
        for index, candidate in enumerate(cands):
            if value in {str(candidate.get(key) or "").strip(),
                         str(candidate.get("id") or "").strip(),
                         str(candidate.get("url") or "").strip()}:
                return index
    title = str(entry.get("title") or entry.get("candidate_title") or "").strip()
    if title:
        for index, candidate in enumerate(cands):
            if title == str(candidate.get("title") or "").strip():
                return index
    return None


def clean_ranking_entries(entries, cands):
    """Convert provider rows into the strict five-row shape consumed by the video builder."""
    clean = []
    seen = set()
    for entry in entries or []:
        idx = _candidate_index(entry, cands)
        if idx is None or idx in seen:
            continue
        seen.add(idx)
        candidate = cands[idx]
        label = str((entry or {}).get("label") or (entry or {}).get("caption") or "").strip()[:16]
        if not label:
            label = FALLBACK_LABELS[len(clean)]
        clean.append({"rank": 5 - len(clean), "candidate_index": idx, "id": candidate["id"],
                      "title": candidate["title"], "url": candidate["url"],
                      "duration": candidate.get("duration"), "label": label,
                      "channel": candidate.get("channel") or candidate.get("uploader"),
                      "uploader": candidate.get("uploader") or candidate.get("channel"),
                      "signal_score": streamer_signal_score(candidate),
                      "source": candidate.get("source"), "source_feed": candidate.get("source_feed"),
                      "content_type": candidate.get("content_type"),
                      "streamer_identity": candidate.get("streamer_identity"),
                      "content_policy": candidate.get("content_policy")})
    return clean[:5]


def deterministic_streamer_fallback(cands):
    """Keep the account live when the LLM is unavailable; candidates already passed hard gates."""
    top = sorted(range(len(cands)),
                 key=lambda index: (-streamer_signal_score(cands[index]), index))[:5]
    if len(top) >= 5:
        # Rank #5 is the strongest opener and rank #1 is the strongest payoff. We do not have
        # visual semantics in this fallback, so reserve the single best signal for the payoff
        # and use the runner-up as the cold-open clip.
        top = [top[1], top[2], top[3], top[4], top[0]]
    return clean_ranking_entries(
        [{"candidate_index": index, "label": FALLBACK_LABELS[position]}
         for position, index in enumerate(top)], cands)


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
        candidate_doc = json.load(open(args.candidates, encoding="utf-8"))
        cands = candidate_doc["candidates"]
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

    if topic.get("genre") == "streamer":
        streamer_hints = (
            "streamer", "twitch", "kai cenat", "kaicenat", "jynxzi", "caseoh", "xqc",
            "adin ross", "adinlive", "pokimane", "ludwig", "hasan", "hasanabi", "tarik",
            "nmplol", "sodapoppin", "faze", "clix", "fanum", "plaqueboymax", "ddg",
        )
        invalid = []
        for c in cands:
            identity = str(c.get("streamer_identity") or c.get("channel") or "").strip()
            haystack = f"{c.get('title', '')} {identity} {c.get('uploader', '')}".lower()
            if (c.get("content_policy") != "streamer-only"
                    or c.get("content_type") != "streamer_clip"
                    or not identity
                    or not channel_ok(identity)
                    or not any(hint in haystack for hint in streamer_hints)):
                invalid.append(c.get("id") or c.get("title") or "unknown")
        if invalid:
            fail("Streamer-only ranking received candidates without a verified streamer identity.",
                 content_policy="streamer-only", invalid_candidates=invalid[:10])
            return

    angle = topic.get("angle") if topic.get("genre") == "worldcup" else None
    if angle in ANGLE_DESC:
        cands, aerr = filter_by_angle(cands, angle)
        if aerr:
            fail(aerr)
            return

    listing = "\n".join(
        f"[{i}] {c['title']} (signal={streamer_signal_score(c)}/100)"
        for i, c in enumerate(cands)
    )
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
For YouTube Shorts, metadata is only a supporting signal: prefer a self-contained, specific action
with an obvious funny payoff over a high-view generic title. Do not choose repost compilations,
montages, commentary-only videos, or clips whose title does not identify a real moment. The selected
clip should contain the main funny beat, not just the setup.
`label` is a SHORT punchy Gen-Z meme caption for that clip (1-3
words, <=16 chars), DIFFERENT for each rank -- e.g. "Aura Lost", "Skill Issue", "Pure Pain",
"Certified Bruh", "Massive L", "Caught in 4K". Use each candidate_index at most once. Output JSON only."""
    genre_guard = ""
    if topic.get("genre") == "streamer":
        genre_guard = (
            "STREAMER MODE: every selected candidate must clearly be a specific live-streamer or "
            "creator moment. Prefer an obvious reaction, fail, rage, surprise, chat interaction, "
            "or punchline. Prefer titles that name the concrete conflict and consequence (for "
            "example: called out, roasted, cringe question, rigged game, meltdown, or an obvious "
            "fail) over generic reaction wording. Reject podcasts, news/interviews, compilations, "
            "generic gameplay, and titles that do not identify a creator or streamer.\n\n"
        )
    prompt = (f"TOPIC: {topic.get('title')}\nRANK BY: {topic.get('criterion')}\n"
              f"GENRE: {topic.get('genre')}\n\n{genre_guard}"
              f"CANDIDATES:\n{listing}\n\n{schema}")

    ranking_system = "You rank clips for viral countdown Shorts. English. Strict JSON."
    out = None
    entries = []
    ranking_error = None
    try:
        out = llm_complete(prompt, system=ranking_system, json_mode=True, temperature=0.85)
        try:
            entries = extract_ranking_entries(parse_json(out["text"]))
        except Exception:
            # Some providers honor JSON mode but still vary the top-level key. A single
            # low-temperature retry keeps a transient schema miss from failing the whole
            # media build; the candidate/content-policy guards below still reject unsafe rows.
            retry_prompt = (prompt + "\n\nYour previous response was not usable. Return ONLY one JSON object "
                            'with exactly this top-level key: "entries". The value must be an '
                            "array of exactly five objects, each with candidate_index and label. "
                            "candidate_index is a zero-based integer from the supplied list.")
            out = llm_complete(retry_prompt, system=ranking_system, json_mode=True, temperature=0.2)
            entries = extract_ranking_entries(parse_json(out["text"]))
    except Exception as e:
        ranking_error = str(e)

    clean = clean_ranking_entries(entries, cands)
    fallback_reason = ranking_error
    if len(clean) < 5 and topic.get("genre") == "streamer" and len(cands) >= 5:
        fallback_reason = fallback_reason or (
            f"LLM returned {len(clean)} valid rows after normalization")
        print(f"::warning::Using deterministic streamer ranking fallback: {fallback_reason}",
              file=sys.stderr)
        clean = deterministic_streamer_fallback(cands)
        provider = "deterministic-fallback"
    else:
        provider = (out or {}).get("provider") if isinstance(out, dict) else None

    if len(clean) < 5:
        message = f"Ranking produced only {len(clean)} valid entries."
        if ranking_error:
            message += f" {ranking_error}"
        fail(message, entries=clean)
        return

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"title": topic.get("title"), "hook": topic.get("hook"),
                   "genre": topic.get("genre"),
                   "content_policy": "streamer-only" if topic.get("genre") == "streamer" else None,
                   "entries": clean, "provider": provider,
                   "fallback_reason": fallback_reason},
                  f, indent=2, ensure_ascii=False)
    emit({"count": len(clean), "entries": [{"rank": e["rank"], "title": e["title"][:50]} for e in clean],
          "provider": provider, "fallback_reason": fallback_reason, "path": args.out})


if __name__ == "__main__":
    main()
