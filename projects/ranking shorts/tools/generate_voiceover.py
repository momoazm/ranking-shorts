"""Synthesize the dialogue/narration voiceover.

Two TTS engines:
  - edge (default, free, keyless): Microsoft neural voices via Edge-TTS. Distinct voices + pitch,
    a good *approximation* of each character.
  - fish (when FISH_AUDIO_API_KEY is set): Fish Audio character models = the ACTUAL Peter/Stewie
    voices, selected per character by `fish_voice_id` in _characters.py. Metered (paid credits).

Engine selection: --engine auto (default) uses Fish when the key is set AND every speaking
character has a fish_voice_id, otherwise Edge. --engine fish/edge forces one.

Two modes, auto-detected from the story file:
  - narration: one voice reads the 'narration' field.
  - dialogue:  each 'turns' line is spoken by ITS character's voice, then all lines are stitched
    into one mp3 + a segments timeline (speaker + start/end + caption_color).

Usage:
    python tools/generate_voiceover.py --text-from .tmp/story.json [--engine auto|edge|fish]
        [--rate "+20%"] [--fish-speed 1.1] [--out .tmp/narration.mp3]

Prints JSON: {"path": ..., "duration_sec": F, "provider": "edge-tts|fish-audio", "segments": ...}
"""
import argparse
import asyncio
import json
import os

from _common import emit, fail, load_env
from _media import probe_duration, run_ffmpeg

DEFAULT_VOICE = "en-US-GuyNeural"  # warm male storytelling voice; swap via --voice


# ----------------------------- Edge-TTS (free) -----------------------------
async def _synthesize(text, voice, rate, out_path, pitch="+0Hz"):
    import edge_tts
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await communicate.save(out_path)


async def _synthesize_many(jobs):
    """jobs: list of (text, voice, rate, pitch, out_path). Sequential (shared endpoint)."""
    for text, voice, rate, pitch, out_path in jobs:
        await _synthesize(text, voice, rate, out_path, pitch)


def synth_edge(lines, rate, fallback_voice):
    jobs = [(ln["text"], ln["voice"] or fallback_voice, rate, ln["pitch"] or "+0Hz", ln["out"])
            for ln in lines]
    asyncio.run(_synthesize_many(jobs))


# ----------------------------- Fish Audio (paid) -----------------------------
def _fish_save(session, text, reference_id, out_path, speed):
    from fish_audio_sdk import TTSRequest
    kwargs = dict(text=text, reference_id=reference_id, format="mp3", mp3_bitrate=128)
    try:
        req = TTSRequest(prosody={"speed": speed, "volume": 0}, **kwargs)
    except Exception:
        req = TTSRequest(**kwargs)  # older SDKs / prosody unsupported
    with open(out_path, "wb") as f:
        for chunk in session.tts(req):
            f.write(chunk)


def synth_fish(lines, api_key, speed):
    from fish_audio_sdk import Session
    session = Session(api_key)
    for ln in lines:
        if not ln.get("fish_id"):
            raise RuntimeError(f"No fish_voice_id for speaker '{ln['speaker']}' — can't use Fish engine.")
        _fish_save(session, ln["text"], ln["fish_id"], ln["out"], speed)


# ----------------------------- shared helpers -----------------------------
def voice_map(characters):
    """name(lower) -> {voice, pitch, fish_id, caption_color} from the resolved cast."""
    m = {}
    for c in characters:
        m[c["name"].lower()] = {
            "voice": c.get("voice"),
            "pitch": c.get("pitch", "+0Hz"),
            "fish_id": c.get("fish_voice_id"),
            "caption_color": c.get("caption_color"),
        }
    return m


def resolve_engine(requested, fish_ids_present, api_key):
    """Decide edge vs fish. fish_ids_present: True if every speaker has a fish_voice_id."""
    if requested == "edge":
        return "edge"
    if requested == "fish":
        if not api_key:
            raise RuntimeError("--engine fish but FISH_AUDIO_API_KEY is empty in API.env.")
        if not fish_ids_present:
            raise RuntimeError("--engine fish but a speaking character has no fish_voice_id.")
        return "fish"
    # auto
    return "fish" if (api_key and fish_ids_present) else "edge"


def concat_mp3(parts, out_path):
    """Concatenate mp3 parts into one file via the ffmpeg concat demuxer (re-encoded)."""
    listfile = out_path + ".concat.txt"
    with open(listfile, "w", encoding="utf-8") as f:
        for p in parts:
            ap = os.path.abspath(p).replace("\\", "/")
            f.write(f"file '{ap}'\n")
    try:
        run_ffmpeg(["-f", "concat", "-safe", "0", "-i", listfile, "-c:a", "libmp3lame", "-q:a", "2", out_path])
    finally:
        if os.path.isfile(listfile):
            os.remove(listfile)


def run_dialogue(story, args, api_key):
    turns = story["turns"]
    characters = story.get("characters") or []
    vmap = voice_map(characters)

    parts_dir = os.path.join(os.path.dirname(args.out) or ".", "vo_parts")
    os.makedirs(parts_dir, exist_ok=True)

    lines = []
    for i, t in enumerate(turns):
        spk = str(t.get("speaker", "")).strip()
        text = str(t.get("text", "")).strip()
        if not text:
            continue
        info = vmap.get(spk.lower()) or {}
        lines.append({
            "speaker": spk, "text": text,
            "voice": info.get("voice"), "pitch": info.get("pitch"),
            "fish_id": info.get("fish_id"), "caption_color": info.get("caption_color"),
            "out": os.path.join(parts_dir, f"part_{i:03d}.mp3"),
        })
    if not lines:
        fail("Dialogue has no usable turns to synthesize.")
        return

    fish_ids_present = all(ln.get("fish_id") for ln in lines)
    try:
        engine = resolve_engine(args.engine, fish_ids_present, api_key)
    except RuntimeError as e:
        fail(str(e))
        return

    fish_error = None
    try:
        if engine == "fish":
            synth_fish(lines, api_key, args.fish_speed)
        else:
            synth_edge(lines, args.rate, args.voice)
    except Exception as e:
        if engine == "fish" and args.engine == "auto":
            # auto picked Fish but it failed (e.g. 402 no credits) — fall back to the free engine.
            fish_error = str(e)
            engine = "edge"
            try:
                synth_edge(lines, args.rate, args.voice)
            except Exception as e2:
                fail(f"Fish failed ({e}) and Edge fallback also failed ({e2}).")
                return
        elif engine == "fish":
            fail(f"Fish Audio call failed: {e}. Check credits at fish.audio, or use --engine edge.")
            return
        else:
            fail(f"Edge-TTS failed: {e}. Usually transient network — retry; no credits consumed.")
            return

    # Build the segment timeline from each part's true duration (cumulative).
    segments, cursor = [], 0.0
    for ln in lines:
        part = ln["out"]
        if not os.path.isfile(part) or os.path.getsize(part) == 0:
            fail(f"No audio produced for a line ({ln['speaker']}) via {engine}.")
            return
        d = probe_duration(part)
        segments.append({
            "speaker": ln["speaker"], "text": ln["text"],
            "start": round(cursor, 3), "end": round(cursor + d, 3),
            "caption_color": ln["caption_color"],
        })
        cursor += d

    concat_mp3([ln["out"] for ln in lines], args.out)

    for ln in lines:
        try:
            os.remove(ln["out"])
        except OSError:
            pass
    try:
        os.rmdir(parts_dir)
    except OSError:
        pass

    seg_path = args.segments_out or os.path.join(os.path.dirname(args.out) or ".", "segments.json")
    with open(seg_path, "w", encoding="utf-8") as f:
        json.dump({"segments": segments}, f, indent=2, ensure_ascii=False)

    try:
        duration = probe_duration(args.out)
    except Exception:
        duration = round(cursor, 2)

    if engine == "fish":
        voices = sorted({ln["fish_id"] for ln in lines})
        provider, rate_field = "fish-audio", args.fish_speed
    else:
        voices = sorted({ln["voice"] or args.voice for ln in lines})
        provider, rate_field = "edge-tts", args.rate

    result = {
        "path": args.out, "duration_sec": round(duration, 2), "provider": provider,
        "engine": engine, "mode": "dialogue", "segments": seg_path, "turns": len(segments),
        "voices": voices, "rate": rate_field,
    }
    if fish_error:
        result["fish_error"] = fish_error + " (fell back to Edge-TTS)"
    emit(result)


def run_single(text, args, api_key):
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    use_fish = (args.engine == "fish") or (args.engine == "auto" and api_key and args.fish_voice_id)
    if use_fish and not args.fish_voice_id:
        fail("--engine fish in single mode needs --fish-voice-id.")
        return
    try:
        if use_fish:
            from fish_audio_sdk import Session
            _fish_save(Session(api_key), text, args.fish_voice_id, args.out, args.fish_speed)
        else:
            asyncio.run(_synthesize(text, args.voice, args.rate, args.out))
    except Exception as e:
        fail(f"Voiceover synthesis failed ({'fish' if use_fish else 'edge'}): {e}")
        return
    if not os.path.isfile(args.out) or os.path.getsize(args.out) == 0:
        fail("TTS produced no audio (empty file). Retry or try a different engine/voice.")
        return
    try:
        duration = probe_duration(args.out)
    except Exception:
        duration = None
    emit({"path": args.out, "duration_sec": duration,
          "provider": "fish-audio" if use_fish else "edge-tts",
          "engine": "fish" if use_fish else "edge", "mode": "narration", "segments": None})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--text-from", help="Path to story.json (dialogue 'turns' or 'narration')")
    parser.add_argument("--text", help="Raw narration text (alternative to --text-from)")
    parser.add_argument("--engine", choices=["auto", "edge", "fish"], default="auto",
                        help="auto = Fish if key+ids present, else Edge")
    parser.add_argument("--voice", default=DEFAULT_VOICE, help="Edge fallback voice (single / unmapped)")
    parser.add_argument("--rate", default="+20%", help="Edge speaking rate, signed percent")
    parser.add_argument("--fish-speed", type=float, default=1.1, help="Fish prosody speed multiplier")
    parser.add_argument("--fish-voice-id", help="Fish reference_id for single (narration) mode")
    parser.add_argument("--out", default=".tmp/narration.mp3")
    parser.add_argument("--segments-out", help="Where to write the dialogue timeline (default: alongside --out)")
    args = parser.parse_args()

    load_env()
    api_key = os.environ.get("FISH_AUDIO_API_KEY", "").strip()

    if args.text:
        run_single(args.text, args, api_key)
        return
    if not args.text_from:
        fail("Provide either --text or --text-from")
        return

    try:
        with open(args.text_from, "r", encoding="utf-8") as f:
            story = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        fail(f"Could not read --text-from: {e}")
        return

    if isinstance(story, dict) and story.get("turns"):
        run_dialogue(story, args, api_key)
        return

    text = (story.get("narration") if isinstance(story, dict) else None)
    if not text or not text.strip():
        fail("No 'turns' (dialogue) and no non-empty 'narration' (single) found in --text-from.")
        return
    run_single(text, args, api_key)


if __name__ == "__main__":
    main()
