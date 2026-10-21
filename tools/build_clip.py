"""Build ONE branded vertical Short from a single source clip (momoclips pipeline).

Distinct from build_ranking_video.py (which stitches a #5->#1 countdown): this takes ONE
World-Cup moment -- a goal, a fan/streamer reaction, a viral clip -- and turns it into a
finished 1080x1920 Short: the whole frame fit into 9:16 over a blurred fill (no crop-zoom),
original clip audio kept (the commentary/crowd IS the appeal -- no SFX, per the project's
audio rule), with a compact on-brand title card and an @itsmomoclips watermark burned on.

Reuses the proven download() + normalize() from build_ranking_video (same 9:16 blurred-fill
fit, same "keep original audio / silence when quiet" behaviour, same yt-dlp WARP-proxy path).

Usage:
    python tools/build_clip.py --url <youtube_url> --title "RONALDO GOAL" \
        [--handle @itsmomoclips] [--max-secs 58] [--music path.mp3] [--out .tmp/final.mp4]

    Sequential chop of a long source into one part:
    python tools/build_clip.py --url <youtube_url> --title "SHARK TANK PITCH" \
        --start 116.0 --max-secs 58.7 --part-label "(Part 3/10)" --download-deadline 600

Prints JSON: {"path","duration_sec","byte_size","title","source_url","source_start_sec",...}
"""
import argparse
import json
import os
import re
import sys

from _common import REPO_ROOT, load_env, emit, fail, is_tod, TOD_CROP_FRAC, load_theme
from _media import run_ffmpeg, probe_duration

# Reuse the ranking pipeline's downloader + 9:16 normaliser (same module, sibling import).
import build_ranking_video as brv

OUT_W, OUT_H = brv.OUT_W, brv.OUT_H
CLIP_TMP = ".tmp/clip"
# The display font used by the winning clip formats (Anton, OFL). Copied into the render
# tmpdir and handed to libass through `fontsdir`, so a local render does not require the
# font to be installed system-wide.
BRAND_FONTS = REPO_ROOT / "brand" / "fonts"
KINETIC_FONT = "Anton"



def esc(text):
    """ASS-safe: strip braces/backslashes/newlines that would break the filter."""
    return (str(text).replace("\\", " ").replace("{", "(").replace("}", ")")
            .replace("\n", " ").strip())


def clean_title(raw):
    """Turn a noisy source title into a short, punchy card.

    'Cristiano Ronaldo Goal | Portugal 2-1 Croatia | FIFA World Cup 2026(TM)'
      -> 'Cristiano Ronaldo Goal - Portugal 2-1 Croatia'
    'Lionel Messi Goal vs Cape Verde During Argentina vs Cape Verde Fifa World Cup 2026 Match'
      -> 'Lionel Messi Goal vs Cape Verde'
    """
    t = raw.replace("™", " ").replace("®", " ")
    # Case-insensitive removal of FIFA/World-Cup boilerplate + junk phrases.
    for pat in (r"fifa\s+world\s+cup\s*20\d\d", r"world\s+cup\s*20\d\d", r"fifa\s+world\s+cup",
                r"full\s+match", r"highlights?", r"#\w+", r"\(\s*4k\s*\)", r"\b4k\b", r"\bhd\b"):
        t = re.sub(pat, " ", t, flags=re.IGNORECASE)
    # Split on separators; also break on a padded "During"/"vs ... vs" duplication so a repeated
    # "X vs Y During X vs Y" collapses to its first, most descriptive segment.
    t = re.sub(r"\s+during\s+", " | ", t, flags=re.IGNORECASE)
    parts = [re.sub(r"\s+", " ", p).strip(" -–—") for p in re.split(r"[|–—]|\s-\s", t)]
    # Removing boilerplate can leave its trailing separator dangling at the FRONT of a part
    # ("FIFA World Cup 2026: Messi..." -> ": Messi..." -- posted with a leading colon on
    # 2026-07-05). Titles must start with a letter or digit.
    parts = [re.sub(r"^[^0-9A-Za-z]+", "", p).strip() for p in parts]
    parts = [p for p in parts if p]
    # Prefer the first segment; add a second only if the first is short and the second adds a score.
    out = parts[0] if parts else re.sub(r"\s+", " ", t).strip()
    if parts and len(out) < 32 and len(parts) > 1 and re.search(r"\d", parts[1]):
        out = f"{out} - {parts[1]}"
    # Strip trailing filler words left dangling by the removals.
    out = re.sub(r"\b(match|game|video|clip|moment)\s*$", "", out, flags=re.IGNORECASE).strip(" -")
    # Word-boundary truncation so we never cut mid-word.
    if len(out) > 62:
        out = out[:62].rsplit(" ", 1)[0]
    # Belt-and-suspenders: never return a title that opens with punctuation/symbols.
    return re.sub(r"^[^0-9A-Za-z]+", "", out).strip(" -–—:;|.,!?")


def hex_to_ass_bgr(hex_color, alpha="00"):
    """Convert the shared MOMO #RRGGBB theme color to ASS AABBGGRR."""
    h = (hex_color or "#FFFFFF").lstrip("#")
    if len(h) != 6:
        h = "FFFFFF"
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha}{b}{g}{r}&"


def build_overlay_ass(title, handle, total, out_path, cta_dur=0.0, cta_text="", theme=None,
                      badge_text="MOMOCLIPS / FOOTBALL"):
    """A compact title card: bold title pinned top for the whole clip + a small handle
    watermark bottom-centre. Colours/anchoring mirror build_ranking_video's Header style so
    the two formats look like one channel. Gold accent = brand.

    Optional follow CTA (mirrors build_ranking_video's end-card): a bold pop-in over the
    LAST cta_dur seconds of footage that's already playing -- no dead time appended, no SFX
    (audio rule). Research on short-form CTAs backs this over a bolt-on end screen: baked
    into the video reads as natural, a separate end card kills momentum/rewatch."""
    def ass_time(t):
        h = int(t // 3600); m = int((t % 3600) // 60); s = t % 60
        return f"{h}:{m:02d}:{s:05.2f}"

    theme = theme or {"colors": {}}
    colors = theme.get("colors", {})
    gold = hex_to_ass_bgr(colors.get("gold", "#E6B23A"))
    gold_light = hex_to_ass_bgr(colors.get("gold_light", "#F4D277"))
    white = hex_to_ass_bgr(colors.get("text_on_dark", "#F2E9D8"))
    navy = hex_to_ass_bgr(colors.get("navy", "#040810"), "78")
    teal = hex_to_ass_bgr(colors.get("nile_teal", "#2E7C8C"))
    head = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 0\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        # Opaque navy panels keep the hook legible over pale pitch footage; gold and teal are
        # read from the shared MOMO theme instead of the old hard-coded yellow.
        "Style: Title,Liberation Sans,64," + white + "," + gold + ",&H00000000," + navy + ",1,0,0,0,100,100,0,0,3,14,0,8,70,70,122,1\n"
        "Style: Badge,Liberation Sans,30," + gold_light + "," + gold_light + ",&H00000000," + navy + ",1,0,0,0,100,100,0,0,3,8,0,8,70,70,64,1\n"
        "Style: Handle,Liberation Sans,40," + gold_light + "," + gold_light + ",&H00000000," + navy + ",1,0,0,0,100,100,0,0,3,8,0,2,60,60,148,1\n"
        "Style: CTA,Liberation Sans,56," + white + "," + gold + ",&H00000000," + teal + ",1,0,0,0,100,100,0,0,3,10,0,2,60,60,258,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    rows = [
        f"Dialogue: 0,{ass_time(0)},{ass_time(total)},Badge,,0,0,0,,"
        "{\\fad(120,0)}" + esc(badge_text),
        # Title pops in with a quick scale-down so it punches on the open, then holds.
        f"Dialogue: 0,{ass_time(0)},{ass_time(total)},Title,,0,0,0,,"
        "{\\fad(120,0)\\fscx112\\fscy112\\t(0,240,\\fscx100\\fscy100)}" + esc(title),
        f"Dialogue: 0,{ass_time(0)},{ass_time(total)},Handle,,0,0,0,,{esc(handle)}",
    ]
    if cta_dur > 0 and cta_text:
        eff = min(cta_dur, total)
        cs = max(0.0, total - eff)
        rows.append(
            f"Dialogue: 1,{ass_time(cs)},{ass_time(total)},CTA,,0,0,0,,"
            "{\\fad(150,0)\\fscx120\\fscy120\\t(0,250,\\fscx100\\fscy100)}" + esc(cta_text)[:26])
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(head + "\n".join(rows) + "\n")


def _ass_time(t):
    t = max(0.0, float(t))
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


# Words the competitor hook banners treat as the emotional beat (red) or the business
# object (teal). Deliberately small: 1-2 accent colors per banner, not confetti.
KINETIC_RED = {
    "REFUSED", "REJECTED", "WALKED", "WALKS", "FIRED", "BACKFIRED", "GREEDY", "MISTAKE",
    "WRONG", "LOST", "LOSES", "FAILED", "FAILS", "QUIT", "QUITS", "NEVER", "OUT", "BROKE",
    "SCAM", "DESPERATE", "BEGGED", "CRIED", "ANGRY", "FURIOUS", "STORMED",
}
KINETIC_TEAL = {
    "DEAL", "DEALS", "OFFER", "OFFERED", "INVEST", "INVESTOR", "INVESTMENT", "EQUITY",
    "ROYALTY", "MILLION", "BILLION", "THOUSAND", "SHARKS", "SHARK", "DRAGONS", "DRAGON",
    "PROFIT", "PROFITS", "COMPANY", "BUSINESS", "VALUATION", "REVENUE", "SALES",
}
_MONEY_TOKEN = re.compile(r"[$%]|\d", re.UNICODE)


def _hook_lines(text, max_chars=19, max_lines=3):
    """Wrap the banner to <=3 short ALL-CAPS lines (competitor pattern), never mid-word."""
    tokens = [w for w in str(text or "").split() if w]
    lines, current = [], []
    for token in tokens:
        trial = " ".join(current + [token])
        if len(trial) <= max_chars or not current:
            current.append(token)
        else:
            lines.append(current)
            current = [token]
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1] + ["..."]
    return lines


def _hook_layout(text, max_lines=3):
    """(font_size, lines) for the banner: shrink the type until the hook fits whole.

    A fixed 100px banner truncated a real source hook mid-thought
    ("...THIS ENTREPRENEUR'S …" on the 2026-10-21 no-upload run). The banner keeps its
    3-line ceiling; the font gives way instead of the sentence.
    """
    tokens = [w for w in str(text or "").split() if w]
    for size in (100, 94, 88, 82, 76, 70, 64, 58):
        budget = max(12, int((OUT_W * 0.86) / (size * 0.52)))
        lines = _hook_lines(text, budget, max_lines)
        if [token for line in lines for token in line] == tokens:
            return size, lines
    budget = max(12, int((OUT_W * 0.86) / (58 * 0.52)))
    return 58, _hook_lines(text, budget, max_lines)


def _kinetic_color(token, is_last_word, colors):
    bare = token.strip(".,!?;:\"'()[]")
    upper = bare.upper()
    if _MONEY_TOKEN.search(bare):
        return colors["gold"]
    if upper in KINETIC_RED:
        return colors["red"]
    if upper in KINETIC_TEAL:
        return colors["teal"]
    if is_last_word:
        return colors["gold"]
    return colors["white"]


def _kinetic_banner(text, colors, lines=None):
    """ASS text for the multi-color hook banner (per-word color tags, explicit line breaks)."""
    lines = lines if lines is not None else _hook_lines(text)
    flat = [(token, index == len(lines) - 1 and pos == len(line) - 1)
            for index, line in enumerate(lines) for pos, token in enumerate(line)]
    rendered_lines = []
    position = 0
    for line in lines:
        parts = []
        for _ in line:
            token, is_last = flat[position]
            position += 1
            color = _kinetic_color(token, is_last, colors)
            safe = esc(token.upper())
            if color == colors["white"]:
                parts.append(safe)
            else:
                parts.append(f"{{\\c{color}}}{safe}{{\\c{colors['white']}}}")
        rendered_lines.append(" ".join(parts))
    return "\\N".join(rendered_lines)


def _group_caption_words(words, per_screen=3, gap_break=0.9):
    """Break word timings into readable 2-3 word screens at pauses and sentence ends."""
    screens, current = [], []
    for index, word in enumerate(words):
        current.append(word)
        nxt = words[index + 1] if index + 1 < len(words) else None
        ends = str(word.get("w") or "").rstrip("\"')]").endswith((".", "!", "?", "…"))
        gap = (float(nxt.get("start") or 0) - float(word.get("end") or 0)) if nxt else 0
        if len(current) >= per_screen or ends or gap >= gap_break or nxt is None:
            screens.append(current)
            current = []
    return screens


def _caption_events(words, total, colors, per_screen=3):
    events = []
    screens = _group_caption_words(words, per_screen)
    for screen_index, screen in enumerate(screens):
        next_screen_start = None
        if screen_index + 1 < len(screens) and screens[screen_index + 1]:
            next_screen_start = float(screens[screen_index + 1][0].get("start") or 0.0)
        for index, word in enumerate(screen):
            start = max(0.0, float(word.get("start") or 0.0))
            if index + 1 < len(screen):
                end = max(start + 0.08, float(screen[index + 1].get("start") or start))
            else:
                end = max(start + 0.12, float(word.get("end") or start + 0.12))
                if next_screen_start is not None:
                    # The next screen owns the same layer; never let the two overlap.
                    end = min(end, next_screen_start)
            end = min(total, end)
            if end <= start:
                continue
            parts = []
            for pos, token in enumerate(screen):
                text = esc(str(token.get("w") or "").upper())
                if pos == index:
                    parts.append(
                        "{\\c" + colors["gold"] + "\\fscx110\\fscy110}" + text +
                        "{\\c" + colors["white"] + "\\fscx100\\fscy100}")
                else:
                    parts.append(text)
            events.append(f"Dialogue: 1,{_ass_time(start)},{_ass_time(end)},WordCap,,0,0,0,,"
                          + " ".join(parts))
    return events


def build_kinetic_ass(title, handle, total, out_path, words=None, cta_dur=0.0,
                      cta_text="", theme=None):
    """Competitor-format overlay: persistent multi-color hook banner + burned word captions.

    Evidence (top Shark Tank / MrBeast clip Shorts): full-bleed crop, a 2-3 line ALL-CAPS
    hook banner pinned at the top for the WHOLE clip, centered word-level captions with the
    spoken word highlighted, a tiny handle, and a CTA. No top title card, no badge, no
    "(Part i/N)" stamp -- those are the old MOMOCLIPS look and stay available as `classic`.
    """
    colors = {
        "gold": hex_to_ass_bgr((theme or {}).get("colors", {}).get("gold", "#E6B23A")),
        "gold_light": hex_to_ass_bgr((theme or {}).get("colors", {}).get("gold_light", "#F4D277")),
        "teal": hex_to_ass_bgr((theme or {}).get("colors", {}).get("nile_teal", "#2E7C8C")),
        "red": hex_to_ass_bgr((theme or {}).get("colors", {}).get("red_flag", "#E2564A")),
        "white": hex_to_ass_bgr("#FFFFFF"),
    }
    hook_size, hook_lines = _hook_layout(title)
    head = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n"
        "WrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        # Banner: top-centre, persistent. Thick black stroke instead of a panel so the
        # footage stays visible (the competitor look). The size shrinks for a long hook so
        # the sentence is never truncated with an ellipsis (_hook_layout).
        f"Style: HookBanner,{KINETIC_FONT},{hook_size},{colors['white']},{colors['gold']},"
        f"&H00000000,&H50000000,0,0,0,0,100,100,0,0,1,9,3,8,80,80,150,1\n"
        # Captions: centered lower third, 3 words, active word gold.
        f"Style: WordCap,{KINETIC_FONT},92,{colors['white']},{colors['gold']},"
        f"&H00000000,&H50000000,0,0,0,0,100,100,0,0,1,8,2,2,70,70,560,1\n"
        # Tiny handle, always on, clear of the captions and the phone UI.
        f"Style: Handle,{KINETIC_FONT},34,&H50FFFFFF,&H50FFFFFF,&H00000000,&H00000000,"
        f"0,0,0,0,100,100,0,0,1,2,0,2,40,40,110,1\n"
        # CTA: last ~2s, above the handle.
        f"Style: CTA,{KINETIC_FONT},58,{colors['gold']},{colors['gold']},&H00000000,"
        f"&H50000000,0,0,0,0,100,100,0,0,1,9,3,2,60,60,250,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    events = []
    if title:
        events.append(
            f"Dialogue: 0,{_ass_time(0)},{_ass_time(total)},HookBanner,,0,0,0,,"
            "{\\fad(150,0)}" + _kinetic_banner(title, colors, hook_lines))
    if words:
        events.extend(_caption_events(words, total, colors))
    events.append(f"Dialogue: 2,{_ass_time(0)},{_ass_time(total)},Handle,,0,0,0,,"
                  + esc(handle))
    if cta_dur > 0 and cta_text:
        eff = min(float(cta_dur), total)
        start = max(0.0, total - eff)
        events.append(
            f"Dialogue: 3,{_ass_time(start)},{_ass_time(total)},CTA,,0,0,0,,"
            "{\\fad(150,0)\\fscx120\\fscy120\\t(0,250,\\fscx100\\fscy100)}"
            + esc(cta_text.upper())[:26])
    with open(out_path, "w", encoding="utf-8") as handle_:
        handle_.write(head + "\n".join(events) + "\n")


def normalize_crop(src, offset, dur, out):
    """Full-bleed 9:16 CENTER CROP (competitor format) while keeping the original audio.

    `normalize()` in build_ranking_video fits the whole frame over a blurred fill. The
    winning pitch-show Shorts instead fill the phone screen with the center of the 16:9
    frame. Audio behaviour is copied exactly: keep the source audio when audible, use
    silence when the slice is quiet (no SFX, per the channel's audio rule).
    """
    vf = (f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
          f"crop={OUT_W}:{OUT_H},setsar=1,fps={brv.FPS},format=yuv420p[v]")
    level = brv.mean_volume_db(src, offset, dur)
    audible = level is not None and level > brv.SILENCE_DB
    inputs = ["-ss", f"{offset:.2f}", "-i", src]
    if audible:
        audio = ["[0:a]aresample=44100,volume=1.0[a]"]
    else:
        inputs += ["-f", "lavfi", "-t", f"{dur:.2f}", "-i", "anullsrc=r=44100:cl=stereo"]
        audio = ["[1:a]volume=1.0[a]"]
    chain = vf + ";" + ";".join(audio)
    run_ffmpeg([*inputs, "-filter_complex", chain, "-map", "[v]", "-map", "[a]",
                "-t", f"{dur:.2f}", "-ar", "44100", "-ac", "2",
                "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                "-c:a", "aac", "-b:a", "160k", out])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="Source YouTube (or direct media) URL")
    ap.add_argument("--title", required=True, help="Overlay/card title (already punchy)")
    ap.add_argument("--start", type=float, default=0.0,
                    help="Seconds into the source where this part begins (sequential chops).")
    ap.add_argument("--source-file", default="",
                    help="Reuse an already-downloaded source file instead of fetching it again.")
    ap.add_argument("--part-label", default="",
                    help='Appended to the cleaned card title, e.g. "(Part 3/10)".')
    ap.add_argument("--download-deadline", type=float, default=0.0,
                    help="Total seconds the downloader may spend. Long sources (a full episode "
                         "instead of a 15s Short) pass a larger budget here; 0 keeps the default.")
    ap.add_argument("--download-attempt-timeout", type=float, default=0.0,
                    help="Per-route ceiling for one yt-dlp attempt (0 = Short default).")
    ap.add_argument("--max-height", type=int, default=0,
                    help="Cap the download ladder. A 16:9 source fit into 9:16 never uses more "
                         "than the output width, so >1080p is wasted bandwidth (0 = uncapped).")
    ap.add_argument("--handle", default="@itsmomoclips", help="Watermark handle")
    ap.add_argument("--max-secs", type=float, default=58.0, help="Hard cap (<60s Shorts length)")
    ap.add_argument("--music", default=None, help="Optional music bed path (default: keep original audio only)")
    ap.add_argument("--music-volume", type=float, default=0.12)
    ap.add_argument("--source-handle", default="",
                    help="Uploader @handle of the source. TOD-by-beIN clips get their bottom "
                         "branding bar cropped off before the 9:16 fit; every other source is untouched.")
    ap.add_argument("--badge", default="MOMOCLIPS / FOOTBALL",
                    help="Small top badge burned into the video (classic style only)")
    ap.add_argument("--style", choices=["classic", "kinetic"], default="classic",
                    help="classic = title card + badge + handle; kinetic = competitor format "
                         "(persistent multi-color hook banner + burned word captions, no card).")
    ap.add_argument("--fit", choices=["fit", "crop"], default="fit",
                    help="fit = whole frame over a blurred fill (landscape sources); "
                         "crop = full-bleed 9:16 center crop (competitor format).")
    ap.add_argument("--captions", choices=["off", "words"], default="off",
                    help="words = burn word-level captions (transcribed from this slice when "
                         "--words is not supplied). Failures degrade to overlay-only.")
    ap.add_argument("--words", default="",
                    help="Pre-computed word timings JSON (transcribe_segment.py) for --captions.")
    ap.add_argument("--cta", dest="cta", action="store_true", default=True,
                    help="Follow CTA pop-in over the last --cta-dur seconds (default ON; no SFX, "
                         "per the audio rule -- purely on-screen text, same pattern as build_ranking_video).")
    ap.add_argument("--no-cta", dest="cta", action="store_false", help="Disable the follow CTA.")
    ap.add_argument("--cta-dur", type=float, default=2.2, help="CTA pop-in length in seconds.")
    ap.add_argument("--cta-text", default="FOLLOW FOR MORE", help="Follow CTA on-screen text.")
    ap.add_argument("--out", default=".tmp/final.mp4")
    args = ap.parse_args()

    load_env()
    # Always tidy the card title (strip trademark junk / FIFA boilerplate, cap length) so any
    # caller can hand us a raw source title and still get a clean, legible card. The part label
    # is appended AFTER cleaning: clean_title keeps only the first "|" segment, which would
    # otherwise drop "(Part 3/10)" off the end of a multi-part chop.
    args.title = clean_title(args.title)
    if args.part_label:
        args.title = f"{args.title} {args.part_label}".strip()
    tmpdir = REPO_ROOT / CLIP_TMP
    tmpdir.mkdir(parents=True, exist_ok=True)
    src_base = str(tmpdir / "src")

    # 1) download the whole (short) source clip -- yt-dlp routes via WARP on cloud runners.
    #    Sequential chops of a full episode override the Short-sized download budget and cap
    #    the ladder; both are read by build_ranking_video at call time, never at import time.
    if args.download_deadline > 0:
        os.environ["YTDLP_DEADLINE_SEC"] = f"{args.download_deadline:.0f}"
    if args.download_attempt_timeout > 0:
        os.environ["YTDLP_ATTEMPT_TIMEOUT_SEC"] = f"{args.download_attempt_timeout:.0f}"
    if args.max_height > 0:
        os.environ["YTDLP_MAX_HEIGHT"] = str(int(args.max_height))
    src = None
    if args.source_file:
        cached = args.source_file if os.path.isabs(args.source_file) else str(REPO_ROOT / args.source_file)
        if os.path.isfile(cached):
            src = cached
    if src is None:
        try:
            src = brv.download(args.url, src_base)
        except Exception as e:
            fail(f"download failed: {e}", url=args.url)
            return
    if not src or not os.path.isfile(src):
        fail("download produced no file", url=args.url)
        return

    dur = probe_duration(src)
    if not dur or dur <= 0:
        fail("could not read source duration", src=src)
        return
    # Sequential chop: take [start, start+seg) of a longer source, never past its end.
    start = max(0.0, min(float(args.start), dur))
    seg = min(dur - start, args.max_secs)   # every part stays under the <60s Shorts ceiling
    if seg <= 0:
        fail("start offset is past the end of the source", start=args.start, duration_sec=dur)
        return

    # 1b) TOD-by-beIN clips carry a bottom branding bar; crop it off BEFORE the 9:16 fit so it's
    #     gone from both the sharp foreground and the blurred fill. TOD-only (is_tod gate) --
    #     every other source is left untouched. A crop failure falls back to the uncropped source.
    if is_tod("", args.source_handle) and TOD_CROP_FRAC > 0:
        cropped = str(tmpdir / "src_crop.mp4")
        keep_h = f"trunc(ih*{1.0 - TOD_CROP_FRAC:.4f}/2)*2"   # even height; y=0 keeps the top, drops the bottom bar
        try:
            run_ffmpeg(["-i", os.path.abspath(src), "-vf", f"crop=iw:{keep_h}:0:0",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                        "-c:a", "aac", "-b:a", "192k", os.path.abspath(cropped)])
            if os.path.isfile(cropped):
                src = cropped
        except Exception as e:
            print(f"::warning::TOD bottom-crop failed ({str(e)[:120]}); using uncropped source", file=sys.stderr)

    # 1c) Caption words: use pre-computed timings (the batch transcribes once) or transcribe
    #     this slice now. A caption outage must never fail the render -- degrade to the banner.
    caption_words = []
    if args.words:
        words_path = args.words if os.path.isabs(args.words) else str(REPO_ROOT / args.words)
        try:
            with open(words_path, encoding="utf-8") as handle:
                payload = json.load(handle)
            caption_words = payload.get("words") if isinstance(payload, dict) else payload
            caption_words = caption_words or []
        except (OSError, json.JSONDecodeError) as exc:
            print(f"::warning::caption words unreadable ({str(exc)[:120]}); "
                  f"falling back to transcription", file=sys.stderr)
    if args.captions == "words" and not caption_words:
        try:
            from transcribe_segment import transcribe_slice
            caption_words = transcribe_slice(src, start, seg).get("words") or []
            print(f"::warning::transcribed {len(caption_words)} caption words for this slice",
                  file=sys.stderr)
        except Exception as exc:
            print(f"::warning::caption transcription failed ({str(exc)[:160]}); "
                  f"rendering the hook banner without captions", file=sys.stderr)
            caption_words = []

    # 2) fit/crop to 9:16, keep original audio (or silence if the clip is quiet).
    body = str(tmpdir / "body.mp4")
    try:
        if args.fit == "crop":
            normalize_crop(src, start, seg, body)
        else:
            brv.normalize(src, start, seg, body)
    except Exception as e:
        fail(f"normalize failed: {e}", src=src)
        return

    # 3) burn the overlay. Bare filename + cwd=.tmp/clip so ffmpeg's filtergraph parser never
    #    sees the repo path's drive-colon/space (same rule as the ranking/clipping ass burns).
    body_dur = probe_duration(body) or seg
    ass_name = "clip_overlay.ass"
    try:
        theme = load_theme()
    except Exception:
        theme = {"colors": {}}
    if args.style == "kinetic":
        build_kinetic_ass(args.title, args.handle, body_dur, str(tmpdir / ass_name),
                          words=caption_words,
                          cta_dur=args.cta_dur if args.cta else 0.0,
                          cta_text=args.cta_text, theme=theme)
    else:
        build_overlay_ass(args.title, args.handle, body_dur, str(tmpdir / ass_name),
                          args.cta_dur if args.cta else 0.0, args.cta_text, theme=theme,
                          badge_text=args.badge)

    out_path = args.out if os.path.isabs(args.out) else str(REPO_ROOT / args.out)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    if args.style == "kinetic":
        # Copy the display font next to the ASS file and point libass at it, so the render is
        # identical on a machine that never installed Anton system-wide.
        fonts_dir = tmpdir / "fonts"
        fonts_dir.mkdir(exist_ok=True)
        if BRAND_FONTS.is_dir():
            for font in BRAND_FONTS.glob("*.ttf"):
                target = fonts_dir / font.name
                if not target.is_file():
                    target.write_bytes(font.read_bytes())
        vf = f"ass=filename={ass_name}:fontsdir=fonts"
    else:
        vf = f"ass={ass_name}"
    inputs = ["-i", os.path.abspath(body)]
    amap = ["-map", "0:a?"]
    achain = None
    music = args.music
    if music and os.path.isfile(music):
        # Mix a quiet bed UNDER the original audio; ducking so commentary/crowd stays on top.
        inputs += ["-stream_loop", "-1", "-i", os.path.abspath(music)]
        achain = (f"[1:a]volume={args.music_volume}[m];"
                  f"[0:a][m]sidechaincompress=threshold=0.03:ratio=8:attack=5:release=250[duck];"
                  f"[0:a][duck]amix=inputs=2:duration=first:dropout_transition=0[a]")
        amap = ["-map", "[a]"]

    cmd = [*inputs]
    if achain:
        cmd += ["-filter_complex", f"[0:v]{vf}[v];{achain}", "-map", "[v]", *amap]
    else:
        cmd += ["-vf", vf, "-map", "0:v", *amap]
    # `-t` must be THIS slice's length, not the requested max: on the tail part of a chop
    # (start>0, remainder < max_secs) the requested max would otherwise be wrong by seconds.
    cmd += ["-t", f"{seg:.3f}", "-r", "30",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", os.path.abspath(out_path)]
    try:
        run_ffmpeg(cmd, cwd=str(tmpdir))
    except Exception as e:
        fail(f"overlay burn failed: {e}")
        return

    out_dur = probe_duration(out_path)
    emit({
        "path": args.out,
        "duration_sec": round(out_dur, 2) if out_dur else None,
        "byte_size": os.path.getsize(out_path),
        "title": args.title,
        "source_url": args.url,
        "source_start_sec": round(start, 2),
        # Always report the file the slice was cut from: the batch poster downloads once and
        # reuses it for every later part via --source-file.
        "source_file": src,
        "downloaded_source_file": None if args.source_file else src,
        "source_reused": bool(args.source_file),
        "style": args.style,
        "fit": args.fit,
        "caption_word_count": len(caption_words),
        "width": OUT_W, "height": OUT_H,
        "music": os.path.basename(music) if (music and os.path.isfile(music)) else None,
        "badge": args.badge if args.style == "classic" else None,
    })


if __name__ == "__main__":
    main()
