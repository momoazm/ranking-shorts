"""Transcribe the voiceover with faster-whisper to get WORD-LEVEL timestamps, then write an
.ass subtitle file in the signature faceless-Shorts style: a small rolling window of words,
the currently-spoken word highlighted. Burned into the video by assemble_video.py.

If a dialogue --segments timeline is given, each word is tinted with ITS speaker's color (so the
two arguing characters read differently), the active word pops white, and cues break on speaker
change. Without segments it's the single-narrator look (cream text, brand-gold active word).

faster-whisper runs locally on CPU (free). The first run downloads the model (~150 MB for
'base'), so it's slow once, then cached.

Usage:
    python tools/align_captions.py --audio .tmp/narration.mp3 [--model base]
        [--segments .tmp/segments.json] [--words-per-cue 3] [--out .tmp/captions.ass]

Prints JSON: {"path": ..., "words": N, "model": ..., "per_speaker": bool}
"""
import argparse
import json
import os

from _common import load_theme, emit, fail

VIDEO_W, VIDEO_H = 1080, 1920
WHITE = "#FFFFFF"


def hex_to_ass(hex_color):
    """#RRGGBB -> ASS &H00BBGGRR (alpha 00 = opaque)."""
    h = hex_color.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H00{b}{g}{r}".upper()


def fmt_time(t):
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def load_segments(path):
    """Return list of {start, end, color(ASS)} or None."""
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        segs = []
        for s in data.get("segments", []):
            color = s.get("caption_color")
            segs.append({
                "start": float(s["start"]), "end": float(s["end"]),
                "color": hex_to_ass(color) if color else None,
            })
        return segs or None
    except (OSError, json.JSONDecodeError, KeyError, ValueError):
        return None


def color_for_time(t, segs, fallback):
    if not segs:
        return fallback
    for s in segs:
        if s["start"] - 0.06 <= t < s["end"] + 0.25:
            return s["color"] or fallback
    # No exact bucket (small gap/drift): use the most recent segment that has started.
    started = [s for s in segs if s["start"] <= t]
    if started:
        return started[-1]["color"] or fallback
    return fallback


def build_ass(words, default_base, highlight, words_per_cue, segs):
    base_default = hex_to_ass(default_base)
    hi = hex_to_ass(highlight)

    # Per-word base color (speaker tint in dialogue mode; uniform otherwise).
    bases = [color_for_time(w["start"], segs, base_default) for w in words]

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {VIDEO_W}
PlayResY: {VIDEO_H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Arial,110,{base_default},{hi},&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,8,2,5,80,80,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    # Group into cues of <= words_per_cue, breaking when the speaker color changes.
    cues, cur = [], []
    for i in range(len(words)):
        if cur and (len(cur) >= words_per_cue or bases[i] != bases[cur[0]]):
            cues.append(cur)
            cur = []
        cur.append(i)
    if cur:
        cues.append(cur)

    lines = []
    n = len(words)
    for cue in cues:
        for i in cue:
            w = words[i]
            start = w["start"]
            end = words[i + 1]["start"] if i + 1 < n else w["end"]
            if end <= start:
                end = start + 0.12
            rendered = []
            for j in cue:
                token = words[j]["text"].strip().replace("{", "(").replace("}", ")")
                col = hi if j == i else bases[j]
                rendered.append(f"{{\\c{col}}}{token}")
            text = " ".join(rendered)
            lines.append(f"Dialogue: 0,{fmt_time(start)},{fmt_time(end)},Caption,,0,0,0,,{text}")
    return header + "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", required=True)
    parser.add_argument("--model", default="base", help="faster-whisper model size (tiny/base/small/medium)")
    parser.add_argument("--words-per-cue", type=int, default=2)
    parser.add_argument("--segments", default=".tmp/segments.json",
                        help="Optional dialogue timeline for per-speaker caption colors")
    parser.add_argument("--playbook", default=".tmp/playbook.json", help="Optional; reads caption_style.words_per_cue")
    parser.add_argument("--out", default=".tmp/captions.ass")
    args = parser.parse_args()

    if not os.path.isfile(args.audio):
        fail(f"Audio not found: {args.audio}")
        return

    words_per_cue = args.words_per_cue
    if os.path.isfile(args.playbook):
        try:
            with open(args.playbook, "r", encoding="utf-8") as f:
                wpc = json.load(f).get("caption_style", {}).get("words_per_cue")
                if isinstance(wpc, int) and wpc > 0:
                    words_per_cue = wpc
        except (OSError, json.JSONDecodeError):
            pass

    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        fail(f"faster-whisper not installed: {e}. Install requirements.txt into the project venv.")
        return

    try:
        model = WhisperModel(args.model, device="cpu", compute_type="int8")
        # Force English: the script is always English text (even when voiced by a non-English
        # TTS voice, e.g. the Italian brainrot cast). Auto-detect otherwise mis-IDs the accent
        # as Russian/etc. and emits garbled Cyrillic captions, especially on the tiny model.
        segments, _info = model.transcribe(args.audio, word_timestamps=True, language="en")
        words = []
        for seg in segments:
            for w in (seg.words or []):
                if w.word and w.word.strip() and w.start is not None and w.end is not None:
                    words.append({"text": w.word, "start": w.start, "end": w.end})
    except Exception as e:
        fail(f"Whisper transcription failed: {e}")
        return

    if not words:
        fail("No words detected in the audio — cannot build captions.")
        return

    theme = load_theme()
    colors = theme["colors"]
    segs = load_segments(args.segments)
    # Dialogue: active word pops white over the speaker tint. Single: brand-gold active word.
    highlight = WHITE if segs else colors["gold"]
    ass = build_ass(words, colors["text_on_dark"], highlight, words_per_cue, segs)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(ass)

    emit({"path": args.out, "words": len(words), "model": args.model,
          "words_per_cue": words_per_cue, "per_speaker": bool(segs)})


if __name__ == "__main__":
    main()
