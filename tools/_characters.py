"""Character registry for the two-character "arguing" dialogue format.

Single source of truth (tracked in git — unlike the gitignored assets/) mapping a character
name to the Edge-TTS voice that performs it, a persona the LLM writes in-character from, the
caption color used while that character speaks, and the transparent PNG overlaid on screen.

The PNGs themselves live in assets/characters/<key>.png (gitignored, fetched once with
fetch_character.py). A character with no image on disk simply isn't overlaid — captions + voice
still carry the format — so the pipeline never hard-depends on a copyrighted asset being present.

NOTE on the famous duo: Edge-TTS provides distinct *voices* (deep US male, posh British male),
not the exact cartoon voices, and the character art is copyrighted fan material. Swap any entry
(voice/persona/image) freely; keys are matched case-insensitively by write_story --characters.
"""
import os

from _common import REPO_ROOT

# Caption colors: vivid and well-separated so the two speakers read clearly differently on
# screen (and distinct from the white active-word highlight). #RRGGBB -> align_captions.hex_to_ass().
_AMBER = "#FFB300"   # Peter — warm, loud
_CYAN = "#1FC3FF"    # Stewie — cool, sharp

# pitch shifts the voice to better fit the character (Edge-TTS "<sign><n>Hz"): Peter down (bigger,
# dumber), Stewie up (higher, posh baby-genius). Combined with the accent it reads as each character.
CHARACTERS = {
    "peter": {
        "name": "Peter",
        "voice": "en-US-RogerNeural",     # Edge-TTS fallback: lively, animated American male
        "pitch": "-8Hz",                  # drop it for a bigger, goofier sound
        # Fish Audio model = the ACTUAL Peter Griffin voice (used when FISH_AUDIO_API_KEY is set).
        "fish_voice_id": "d75c270eaee14c8aa1e9e980cc37cf1b",
        "persona": (
            "Peter Griffin energy: loud, dim-witted, overconfident, blue-collar dad who derails "
            "into non-sequiturs, brags, and misunderstands simple things. Crude but good-natured."
        ),
        "caption_color": _AMBER,
        "image": "assets/characters/peter.png",
    },
    "stewie": {
        "name": "Stewie",
        "voice": "en-GB-RyanNeural",      # Edge-TTS fallback: posh British male
        "pitch": "+22Hz",                 # raise it for the high, sinister baby-genius tone
        "fish_voice_id": "e91c4f5974f149478a35affe820d02ac",   # Fish Audio = actual Stewie voice
        "persona": (
            "Stewie Griffin energy: posh British accent, condescending, theatrical evil-genius "
            "with a huge vocabulary who belittles the other character and is exasperated by their "
            "stupidity. Sophisticated, sarcastic, dramatic."
        ),
        "caption_color": _CYAN,
        "image": "assets/characters/stewie.png",
    },
    # --- Italian-brainrot meme duo (copyright-cleaner than the Family Guy cast; rides the
    # live Italian-brainrot trend). Edge-TTS Italian voices, separated further by pitch. ---
    "tung": {
        "name": "Tung",
        "voice": "it-IT-DiegoNeural",     # Italian male; deep/ominous after the pitch drop
        "pitch": "-12Hz",
        "fish_voice_id": None,             # no Fish model — Edge engine is used automatically
        "persona": (
            "Tung Tung Tung Sahur energy: a menacing, deadpan wooden baseball-bat creature who "
            "speaks in slow, ominous threats and keeps intoning 'tung tung tung'. Blunt, literal, "
            "intimidating, and utterly convinced he is the original and scariest brainrot."
        ),
        "caption_color": "#D9A441",        # wood amber
        "image": "assets/characters/tung.png",
    },
    "tralalero": {
        "name": "Tralalero",
        "voice": "it-IT-GiuseppeNeural",   # different Italian male voice for clear separation
        "pitch": "+2Hz",
        "fish_voice_id": None,
        "persona": (
            "Tralalero Tralala energy: a cocky, fast-talking blue shark in fresh sneakers who "
            "brags nonstop, throws playful insults, and insists HE is the real king of Italian "
            "brainrot. Slick, irreverent, hype, dismissive of everyone else."
        ),
        "caption_color": "#29B6F6",        # shark blue
        "image": "assets/characters/tralalero.png",
    },
    # Spare voice so the duo is easy to re-cast without editing this file's structure.
    "brian": {
        "name": "Brian",
        "voice": "en-US-AndrewNeural",
        "pitch": "+0Hz",
        "fish_voice_id": None,
        "persona": "Pretentious, calm, faux-intellectual; thinks he's the smartest in the room.",
        "caption_color": _CYAN,
        "image": "assets/characters/brian.png",
    },
}

DEFAULT_DUO = ["peter", "stewie"]


def resolve_characters(names=None):
    """Map a list of character keys/names to ordered registry entries with an A/B id.

    Returns a list of dicts: {id, key, name, voice, persona, caption_color, image, has_image}.
    Unknown names raise ValueError so the caller can surface a clean error.
    """
    keys = names or DEFAULT_DUO
    resolved = []
    for i, raw in enumerate(keys):
        key = str(raw).strip().lower()
        entry = CHARACTERS.get(key)
        if entry is None:
            # Allow matching by display name too (e.g. "Peter" -> peter).
            for k, v in CHARACTERS.items():
                if v["name"].lower() == key:
                    key, entry = k, v
                    break
        if entry is None:
            raise ValueError(f"Unknown character '{raw}'. Known: {', '.join(CHARACTERS)}")
        image_abs = REPO_ROOT / entry["image"]
        resolved.append({
            "id": chr(ord("A") + i),
            "key": key,
            "name": entry["name"],
            "voice": entry["voice"],
            "pitch": entry.get("pitch", "+0Hz"),
            "fish_voice_id": entry.get("fish_voice_id"),
            "persona": entry["persona"],
            "caption_color": entry["caption_color"],
            "image": entry["image"],
            "has_image": os.path.isfile(image_abs),
        })
    return resolved
