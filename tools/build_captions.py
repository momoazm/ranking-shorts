"""Turn a story.json (+ optional playbook.json) into per-platform caption/hashtag blocks so
EVERY upload ships with strong, niche-correct hashtags (the lever for reach the user asked for).

No network: it merges three hashtag sources — a niche core set, the LLM's per-video `tags`, and
the playbook's `trending_hashtags` — dedupes them, and formats each platform the way that platform
wants:
  * YouTube  : title (+#Shorts), description with the first few hashtags (YouTube surfaces the
               first 3 above the title), and a `tags` array (<=15, <=500 chars total).
  * TikTok   : one caption line + inline hashtags (~6-8; TikTok rewards a tight set).
  * Instagram: caption + a TIGHT ~5-hashtag set (2026 Reels rewards a few relevant tags, not 30).

Usage:
    python tools/build_captions.py --story .tmp/story.json [--playbook .tmp/playbook.json] \
        --out .tmp/captions_meta.json

Prints JSON: the per-platform blocks (also written to --out).
"""
import argparse
import json
import os
import re

from _common import emit, fail

# Niche core — always present so even a bare run is well-tagged. Niche-correct tags FIRST
# (faceless "ranking" Top-N countdown Shorts of funny clips / fails — see momo-actual-niche; the
# old Family Guy/"brainrot" framing was dropped 2026-06-23), then broad short-form discovery tags.
# Ordered niche-first so the per-platform caps below keep the relevant tags and drop the generics.
CORE = [
    "ranking", "top5", "countdown", "funnyfails", "fails", "satisfying", "tierlist", "ranked",
    "shorts", "youtubeshorts", "shortsfeed", "fyp", "foryou", "foryoupage",
    "viral", "viralshorts", "trending", "funny", "comedy", "memes",
]


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def norm_tag(raw):
    """'#Italian Brainrot!' -> 'italianbrainrot' (strip #, lowercase, keep alnum only)."""
    t = re.sub(r"[^0-9a-z]+", "", str(raw).lower().lstrip("#"))
    return t


def dedupe(seq):
    seen, out = set(), []
    for x in seq:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def cast_tags(story):
    """Character-aware hashtags, e.g. peter+stewie -> petervsstewie; tung/tralalero -> italianbrainrot."""
    names = [norm_tag(c.get("name", "")) for c in (story.get("characters") or [])]
    tags = list(names)
    nameset = set(names)
    # Per-character canonical tags so the cast name in the story maps to how viewers search.
    char_tags = {
        "peter": ["petergriffin", "peter", "familyguy"],
        "stewie": ["stewiegriffin", "stewie", "familyguy"],
        "brian": ["briangriffin", "familyguy"],
        "lois": ["loisgriffin", "familyguy"],
        "tung": ["tungtungtung", "italianbrainrot"],
        "tralalero": ["tralalerotralala", "italianbrainrot"],
    }
    for n in names:
        tags += char_tags.get(n, [])
    if {"peter", "stewie"} <= nameset:
        tags += ["petervsstewie", "peterandstewie", "familyguymemes", "familyguyshorts"]
    if "familyguy" in [t for v in char_tags.values() for t in v] and nameset & {"peter", "stewie", "brian", "lois"}:
        tags += ["familyguyclips", "familyguyfunny"]
    if {"tung", "tralalero"} <= nameset:
        tags += ["italianbrainrot", "tralalerotralala", "brainrotanimals"]
    return tags


def hashtag_str(tags):
    return " ".join(f"#{t}" for t in tags)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--story", default=".tmp/story.json")
    parser.add_argument("--playbook", default=".tmp/playbook.json")
    parser.add_argument("--out", default=".tmp/captions_meta.json")
    args = parser.parse_args()

    story = load_json(args.story)
    if not story:
        fail(f"Could not read story: {args.story}")
        return
    playbook = load_json(args.playbook) or {}

    title = (story.get("title") or "Untitled").strip()
    base_desc = (story.get("description") or title).strip()
    # Strip any hashtags the LLM already baked into the description; we re-attach a curated set.
    base_desc_clean = re.sub(r"#\S+", "", base_desc).strip().rstrip("#").strip()

    story_tags = [norm_tag(t) for t in (story.get("tags") or [])]
    trend_tags = [norm_tag(t) for t in (playbook.get("trending_hashtags") or [])]
    all_tags = dedupe(cast_tags(story) + CORE + story_tags + trend_tags)

    # YouTube: ensure shorts present; description leads with the 3 hashtags YouTube surfaces.
    yt_tags = dedupe(["shorts"] + all_tags)[:15]
    yt_hashtags = dedupe(["Shorts"] + [t for t in all_tags if t != "shorts"])[:5]
    yt_description = f"{base_desc_clean}\n\n{hashtag_str(yt_hashtags)}".strip()

    # TikTok: tight inline set.
    tt_hashtags = dedupe(["fyp", "foryou"] + all_tags)[:8]
    tiktok_caption = f"{title} {hashtag_str(tt_hashtags)}".strip()

    # Instagram Reels: a TIGHT, niche-relevant set. Per the 2026 Reels ranking model, 3-5 relevant
    # hashtags perform as well as 30 (IG classifies via caption text/audio/visuals now, not hashtag
    # volume) -- so cap at 5 and keep the niche-first tags rather than padding with generics.
    ig_hashtags = dedupe(all_tags + ["reels"])[:5]
    instagram_caption = f"{base_desc_clean}\n\n{hashtag_str(ig_hashtags)}".strip()

    result = {
        "title": title[:100],
        "youtube": {"title": title[:100], "description": yt_description, "tags": yt_tags},
        "tiktok": {"caption": tiktok_caption[:2200]},
        "instagram": {"caption": instagram_caption[:2200]},
        "all_hashtags": all_tags,
    }

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    emit({"path": args.out, **result})


if __name__ == "__main__":
    main()
