"""Word-level transcription of ONE slice of a source video (Groq Whisper API).

Why this exists: the Shark Tank competitor format burns word-by-word captions, but the
chop pipeline only knows the source video and the [start, start+duration) window. This tool
extracts just that window's audio and returns words timed RELATIVE TO THE SLICE, which is
exactly what build_clip.py's caption builder needs.

It is also callable as a library:

    from transcribe_segment import transcribe_slice
    data = transcribe_slice("source.mp4", 116.0, 58.0)   # {"words": [...], "text": ...}

Failure policy: raise, and let the caller degrade to an overlay-only render. A caption
outage must never fail a publish.

Usage:
    python tools/transcribe_segment.py --source .tmp/sharktank/source.mp4 \
        --start 116 --duration 58 --out .tmp/sharktank/part_3_words.json

Prints JSON: {"path","word_count","language","duration_sec","model","provider"}
"""
import argparse
import json
import os
import re

from _common import REPO_ROOT, load_env, emit, fail
from _media import run_ffmpeg

# -turbo is ~8x faster than large-v3 at near-identical word accuracy on clean speech and
# each request here is <60s of audio, so the cheap route is the right one for a batch.
DEFAULT_MODEL = os.environ.get("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo")
AUDIO_FILTER = "highpass=f=90,dynaudnorm=f=200:g=15"


def _as_dict(resp):
    for attr in ("model_dump", "to_dict"):
        fn = getattr(resp, attr, None)
        if callable(fn):
            try:
                return fn()
            except Exception:
                pass
    if isinstance(resp, dict):
        return resp
    return {"text": getattr(resp, "text", ""),
            "words": getattr(resp, "words", None),
            "segments": getattr(resp, "segments", None),
            "language": getattr(resp, "language", None)}


def _clean_word(raw):
    """Whisper sometimes emits empty/whitespace tokens; keep the spoken token only."""
    return re.sub(r"\s+", " ", str(raw or "")).strip()


def _words_from_segments(segments, fallback_duration):
    """Last-resort timing when the API returns segments but no words.

    Distributes each segment's tokens evenly across its span. Less precise than real word
    timestamps, but keeps the caption look instead of dropping captions entirely.
    """
    words = []
    for seg in segments or []:
        text = _clean_word(seg.get("text"))
        if not text:
            continue
        try:
            start = float(seg.get("start") or 0.0)
            end = float(seg.get("end") or start)
        except (TypeError, ValueError):
            continue
        tokens = text.split()
        if not tokens:
            continue
        span = max(0.05, end - start) / len(tokens)
        for index, token in enumerate(tokens):
            words.append({"w": token, "start": round(start + index * span, 3),
                          "end": round(start + (index + 1) * span, 3)})
    return [w for w in words if w["end"] <= fallback_duration + 0.5]


def transcribe_slice(source, start, duration, model=None, language="en",
                     timeout=150.0):
    """Return {"words":[{w,start,end}], "text": str, "language": str} for one slice."""
    load_env()
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set")
    source = os.path.abspath(source)
    if not os.path.isfile(source):
        raise RuntimeError(f"source not found: {source}")
    start = max(0.0, float(start or 0.0))
    duration = float(duration or 0.0)
    if duration <= 0:
        raise RuntimeError("duration must be > 0")

    tmp_dir = REPO_ROOT / ".tmp" / "transcribe"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    audio = tmp_dir / f"slice_{int(start * 10)}.mp3"
    try:
        # Input-side seek (-ss before -i) is the fast path and is sample-accurate for audio
        # in modern ffmpeg; the trim is then relative to the slice, which is what we want.
        run_ffmpeg(["-ss", f"{start:.3f}", "-i", source, "-t", f"{duration:.3f}",
                    "-vn", "-ac", "1", "-ar", "16000", "-af", AUDIO_FILTER,
                    "-b:a", "64k", str(audio)])
        if not audio.is_file() or audio.stat().st_size < 512:
            raise RuntimeError("extracted audio is empty")

        from groq import Groq
        client = Groq(api_key=api_key, timeout=timeout, max_retries=1)
        with open(audio, "rb") as handle:
            resp = client.audio.transcriptions.create(
                file=(os.path.basename(str(audio)), handle.read()),
                model=model or DEFAULT_MODEL,
                response_format="verbose_json",
                timestamp_granularities=["word"],
                language=language or "en",
                temperature=0.0,
            )
        data = _as_dict(resp)
        words = []
        for item in (data.get("words") or []):
            token = _clean_word(item.get("word") or item.get("text"))
            if not token:
                continue
            try:
                w_start = float(item.get("start") or 0.0)
                w_end = float(item.get("end") or w_start)
            except (TypeError, ValueError):
                continue
            # Clamp to the slice so a small timestamp drift never contributes an event that
            # libass draws past the end of the rendered clip.
            w_start = max(0.0, min(duration, w_start))
            w_end = max(w_start + 0.05, min(duration, w_end))
            words.append({"w": token, "start": round(w_start, 3), "end": round(w_end, 3)})
        if not words:
            words = _words_from_segments(data.get("segments"), duration)
        if not words:
            raise RuntimeError("Whisper returned no word timestamps")
        text = _clean_word(data.get("text")) or " ".join(w["w"] for w in words)
        return {"words": words, "text": text,
                "language": data.get("language") or language or "en",
                "duration": round(duration, 2),
                "model": model or DEFAULT_MODEL, "provider": "groq"}
    finally:
        try:
            os.remove(audio)
        except OSError:
            pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, help="Local source video (fetch_source.py)")
    parser.add_argument("--start", type=float, required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--out", default=".tmp/transcribe/words.json")
    parser.add_argument("--model", default=None)
    parser.add_argument("--language", default="en")
    parser.add_argument("--timeout", type=float, default=150.0)
    args = parser.parse_args()

    try:
        data = transcribe_slice(args.source, args.start, args.duration,
                                model=args.model, language=args.language,
                                timeout=args.timeout)
    except Exception as exc:
        fail(f"transcription failed: {exc}")
        return

    out = args.out if os.path.isabs(args.out) else str(REPO_ROOT / args.out)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
    emit({"path": args.out, "word_count": len(data["words"]),
          "language": data.get("language"), "duration_sec": data.get("duration"),
          "model": data.get("model"), "provider": data.get("provider")})


if __name__ == "__main__":
    main()
