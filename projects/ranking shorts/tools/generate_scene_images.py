"""Generate the WHOLE video's visuals with Nano Banana (Gemini 2.5 Flash Image): one
illustrated 9:16 scene per dialogue beat, then hand off a timed manifest to assemble_video.

This replaces the gameplay-loop + static-avatar look with a fresh AI-drawn scene for every
line of the brainrot argument. The hard part is CHARACTER CONSISTENCY across ~12 frames, so:

  * the cast's existing PNGs (assets/characters/<key>.png) are passed to Gemini as REFERENCE
    images on every scene — this keeps Peter & Stewie on-model AND sidesteps name-based
    content refusals (we show the art instead of relying on a trademarked name), and
  * one fixed SETTING + one fixed art STYLE (from brand/theme.json) are reused in every
    prompt so the frames feel like one continuous video, not 12 unrelated pictures.

ALL-OR-NOTHING: if any scene can't be generated (free quota exhausted, key unset, safety
block), this emits a structured error with {"fallback": "gameplay"} so autopost.py downgrades
the whole video to the reliable gameplay-background mode rather than shipping a half-AI clip.

Budget guard: a date-stamped .tmp/image_budget.json tally plus a per-run --max-images cap keep
the free Nano Banana quota from being blown (the cloud loop's 6-runs/day schedule keeps the
daily total ~78 images, far under the free tier).

Usage:
    python tools/generate_scene_images.py --story .tmp/story.json --segments .tmp/segments.json \
        --out-dir .tmp/scenes --manifest .tmp/scenes.json [--max-images 20] [--daily-budget 400]

Prints JSON: {"manifest": ..., "count": N, "provider": "gemini", "out_dir": ...}
            or on failure {"error": ..., "fallback": "gameplay"} (exit 1).
"""
import argparse
import json
import os
import time
from datetime import date

from _common import REPO_ROOT, load_env, load_theme, emit, fail
from generate_ai_image import generate, FREE_ORDER, DEFAULT_ORDER

# Provider sequences for scene generation. Nano Banana (gemini) has NO free tier, so "free" is the
# default and skips it; "gemini" forces paid Nano Banana; "auto" tries gemini first then free.
PROVIDER_ORDERS = {"free": FREE_ORDER, "gemini": ["gemini"], "auto": DEFAULT_ORDER}

BUDGET_FILE = ".tmp/image_budget.json"


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def style_suffix(theme, preset="3d"):
    """One fixed art-direction string reused on every scene for a coherent look."""
    palette = ", ".join(str(c) for c in (theme or {}).get("palette", {}).values()) if theme else ""
    extra = f" Palette accents: {palette}." if palette else ""
    if preset == "2d":
        look = ("consistent vibrant 2D cartoon meme art style, bold thick outlines, saturated colors, "
                "exaggerated comedic facial expressions")
    else:  # 3d (default) — Pixar-style render so characters read as 3D, like AI-animation Shorts
        look = ("consistent 3D animated cartoon style, Pixar/DreamWorks-style 3D render, soft studio "
                "lighting with volumetric light, glossy detailed textures, shallow depth of field, "
                "expressive exaggerated 3D characters")
    return (f" — {look}, clean uncluttered background, dynamic vertical 9:16 composition.{extra} "
            "No on-screen text, no captions, no watermark, no logos.")


def expand_keyframes(scenes, fpb):
    """Split each beat into `fpb` sub-frames (progressive poses) so characters appear to MOVE —
    consecutive AI frames of the same moment, played in sequence, read as animation."""
    if fpb <= 1:
        for s in scenes:
            s["frame_idx"], s["frame_total"] = 1, 1
        return scenes
    out = []
    for s in scenes:
        st, en = float(s["start"]), float(s["end"])
        step = (en - st) / fpb
        for k in range(fpb):
            out.append({**s, "start": round(st + k * step, 3), "end": round(st + (k + 1) * step, 3),
                        "frame_idx": k + 1, "frame_total": fpb})
    return out


def ref_images(cast):
    """Absolute paths of the cast PNGs that actually exist — Gemini consistency references."""
    refs = []
    for c in cast:
        img = REPO_ROOT / c.get("image", "")
        if c.get("image") and img.is_file():
            refs.append(str(img))
    return refs


def bg_scene_prompt(i, n, desc, style, moment=""):
    """Prompt for an EMPTY 3D background (no characters) — real character PNGs are composited on top.
    `desc` is this scene's location (from the storyboard) so backgrounds CHANGE shot to shot."""
    return (
        f"Frame {i} of {n}: a 3D-animated BACKGROUND/environment for this scene — {desc} "
        f"Show the LOCATION only: NO people, NO characters at all. Keep the lower third relatively "
        f"open/simple so foreground characters can be placed there later. {moment}{style}"
    )


SHOTS = ["wide establishing shot", "medium shot", "low-angle dramatic shot",
         "over-the-shoulder shot", "close-up reaction shot", "high-angle shot"]


def movie_scene_prompt(i, n, visual, char_desc, style, shot, moment=""):
    """Cinematic, story-driven shot: the per-line storyboard IS the scene (location, on-screen
    characters incl. extras, action) — so settings and cast change shot to shot like a short movie."""
    return (
        f"{shot.capitalize()} — cinematic shot {i} of {n} of a short animated movie. THIS SHOT: "
        f"{visual} Make it CLEARLY DIFFERENT from the other shots (distinct location, framing and "
        f"camera angle). Recurring main characters look like — {char_desc} — keep them consistent "
        f"whenever they appear, FULLY visible (full body, not cropped), well inside the 9:16 frame. "
        f"{moment}{style}"
    )


def scene_prompt(i, n, speaker, text, char_desc, setting, style, moment=""):
    return (
        f"Frame {i} of {n} from a single continuous 3D-animated comedic short. "
        f"The characters are — {char_desc} — (keep them EXACTLY consistent: same faces, outfits, "
        f"colors, proportions, same camera framing). Right now {speaker} is talking and should be the "
        f"visual focus with a big expressive reaction; the other character reacts in the background. "
        f'The line being said is: "{text}". {moment}'
        f"Keep the SAME setting in every frame: {setting}. {style}"
    )


def build_scene_list(story, segments, audio_dur):
    """Return [{speaker, text, visual, start, end}] — one entry per beat to illustrate.

    `visual` is the per-line cinematic storyboard from write_story (location, on-screen characters,
    action), aligned to segments by index (both are the non-empty turns in order)."""
    if segments:
        turns = story.get("turns") or []
        out = []
        for i, s in enumerate(segments):
            if not s.get("text"):
                continue
            vis = turns[i].get("visual", "") if i < len(turns) and isinstance(turns[i], dict) else ""
            out.append({"speaker": s.get("speaker", ""), "text": s.get("text", ""), "visual": vis,
                        "start": float(s.get("start", 0)), "end": float(s.get("end", 0))})
        return out
    # Narration fallback: split prose into sentences spread evenly across the audio.
    narration = (story.get("narration") or "").strip()
    if not narration or not audio_dur:
        return []
    import re
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", narration) if s.strip()]
    if not sents:
        return []
    step = audio_dur / len(sents)
    return [{"speaker": "Narrator", "text": s, "start": round(i * step, 3),
             "end": round((i + 1) * step, 3)} for i, s in enumerate(sents)]


def coalesce(beats, max_n):
    """Merge adjacent beats into at most max_n contiguous groups (one image each), so a long
    script never blows the per-video image budget — it just shows each image a little longer."""
    n = len(beats)
    if n <= max_n:
        return beats
    base, extra, idx, groups = n // max_n, n % max_n, 0, []
    for g in range(max_n):
        cnt = base + (1 if g < extra else 0)
        if cnt == 0:
            continue
        chunk = beats[idx:idx + cnt]
        idx += cnt
        groups.append({
            "speaker": chunk[0]["speaker"],
            "text": " ".join(c["text"] for c in chunk),
            # Use the first non-empty storyboard in the group as this scene's shot.
            "visual": next((c.get("visual") for c in chunk if c.get("visual")), ""),
            "start": chunk[0]["start"],
            "end": chunk[-1]["end"],
        })
    return groups


def check_and_reserve_budget(n, daily_budget):
    """Date-stamped tally so repeated local runs can't blow the free daily image quota.

    Returns (ok, used_today). In the ephemeral cloud runner the file is fresh each run, so this
    mainly guards local/repeated invocations; cross-run daily volume is bounded by MAX_DAILY_VIDEOS.
    """
    today = date.today().isoformat()
    data = load_json(BUDGET_FILE) or {}
    used = data.get("count", 0) if data.get("date") == today else 0
    if used + n > daily_budget:
        return False, used
    os.makedirs(os.path.dirname(BUDGET_FILE) or ".", exist_ok=True)
    with open(BUDGET_FILE, "w", encoding="utf-8") as f:
        json.dump({"date": today, "count": used + n}, f)
    return True, used


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--story", default=".tmp/story.json")
    parser.add_argument("--segments", default=".tmp/segments.json")
    parser.add_argument("--audio", help="Voiceover (only needed to time narration-mode scenes)")
    parser.add_argument("--out-dir", default=".tmp/scenes")
    parser.add_argument("--manifest", default=".tmp/scenes.json")
    parser.add_argument("--provider", choices=list(PROVIDER_ORDERS), default="auto",
                        help="auto = try Nano Banana first, fall back to FREE providers on a limit "
                             "(429); free = skip Nano Banana; gemini = paid Nano Banana only")
    parser.add_argument("--style-preset", choices=["3d", "2d"], default="3d",
                        help="3d = Pixar-style 3D render (default); 2d = flat cartoon")
    parser.add_argument("--scene-content", choices=["with-characters", "background"],
                        default="with-characters",
                        help="background = empty 3D scenes (real character PNGs are composited on top "
                             "later); with-characters = draw the characters into each scene")
    parser.add_argument("--frames-per-beat", type=int, default=2,
                        help="Keyframes per dialogue beat (each a different camera angle of that beat)")
    parser.add_argument("--max-images", type=int, default=30,
                        help="Hard cap on TOTAL images per video; beats are grouped and split into "
                             "keyframes to fit (free Cloudflare FLUX allows plenty)")
    parser.add_argument("--throttle", type=float, default=2.0,
                        help="Seconds between image calls (free providers are fine at ~2s; raise it "
                             "if a paid Nano Banana key hits a per-minute limit)")
    parser.add_argument("--daily-budget", type=int,
                        default=int(os.environ.get("GEMINI_DAILY_IMAGE_BUDGET", "400")),
                        help="Max Gemini images per calendar day (free-tier guard, per-run in cloud)")
    args = parser.parse_args()

    load_env()

    story = load_json(args.story)
    if not story:
        fail(f"Could not read story: {args.story}", fallback="gameplay")
        return
    segs = (load_json(args.segments) or {}).get("segments") if os.path.isfile(args.segments) else None

    audio_dur = None
    if not segs and args.audio and os.path.isfile(args.audio):
        try:
            from _media import probe_duration
            audio_dur = probe_duration(args.audio)
        except Exception:
            audio_dur = None

    scenes = build_scene_list(story, segs, audio_dur)
    if not scenes:
        fail("No beats to illustrate (no segments and no narration).", fallback="gameplay")
        return
    # Cap TOTAL images = beats x frames-per-beat. Group beats so the cap holds, then split each beat
    # into keyframes (progressive poses) so characters appear to move.
    fpb = max(1, args.frames_per_beat)
    beat_cap = max(1, args.max_images // fpb)
    scenes = expand_keyframes(coalesce(scenes, beat_cap), fpb)

    ok, used = check_and_reserve_budget(len(scenes), args.daily_budget)
    if not ok:
        fail(f"Daily Gemini image budget reached ({used}/{args.daily_budget}).", fallback="gameplay")
        return

    cast = story.get("characters") or []
    names = [c.get("name") for c in cast] or ["the characters"]
    # Visual descriptors (from _characters.py) so Gemini can DRAW lesser-known brainrot characters
    # correctly, not just by name. Falls back to the name alone if no descriptor is set.
    char_desc = "; ".join(
        f"{c.get('name')} ({c['visual']})" if c.get("visual") else str(c.get("name"))
        for c in cast
    ) or "two cartoon characters"
    refs = ref_images(cast)
    setting = (story.get("background_type") or story.get("topic")
               or "a simple, funny everyday location that stays the same throughout")
    style = style_suffix(load_theme() if (REPO_ROOT / "brand" / "theme.json").is_file() else None,
                         args.style_preset)

    # Tools run with cwd = project root, so a relative out-dir (.tmp/scenes) resolves correctly
    # and the relative scene paths stored in the manifest match what assemble_video reads.
    out_dir = args.out_dir
    os.makedirs(out_dir, exist_ok=True)

    order = PROVIDER_ORDERS[args.provider]
    pinned = None   # once a provider works, stick to it so the whole video is consistent AND we
                    #   don't re-hit a dead provider (e.g. Nano Banana 429) on every scene.

    manifest_scenes = []
    n = len(scenes)
    for i, sc in enumerate(scenes, start=1):
        out_path = os.path.join(out_dir, f"scene_{i:02d}.png")
        moment = ""
        if sc.get("frame_total", 1) > 1:
            moment = (f"This is angle {sc['frame_idx']} of {sc['frame_total']} on this beat — "
                      "show it from a DIFFERENT camera angle/distance with a different pose. ")
        shot = SHOTS[(i - 1) % len(SHOTS)]
        if args.scene_content == "background":
            # Use this scene's storyboard LOCATION so composite backgrounds change shot to shot.
            desc = sc.get("visual") or f"{setting}: {sc.get('text', '')}"
            prompt = bg_scene_prompt(i, n, desc, style, moment)
            scene_refs = None   # no character references when drawing empty backgrounds
        elif sc.get("visual"):
            # Movie mode: the per-line storyboard drives the shot (changing locations + extra cast).
            prompt = movie_scene_prompt(i, n, sc["visual"], char_desc, style, shot, moment)
            scene_refs = refs
        else:
            prompt = scene_prompt(i, n, sc["speaker"], sc["text"], char_desc, setting, style, moment)
            scene_refs = refs
        if i > 1 and args.throttle > 0:
            time.sleep(args.throttle)   # stay under the per-minute image rate limit
        try:
            # Prefer the pinned provider; on the first scene (or if it dies) walk the full order —
            # which tries Nano Banana first under "auto" and falls back to the free chain on a 429.
            try:
                used, _errs = generate(prompt, out_path, refs=scene_refs,
                                       order=([pinned] if pinned else order))
            except Exception:
                if pinned:
                    used, _errs = generate(prompt, out_path, refs=scene_refs, order=order)
                else:
                    raise
            pinned = used
        except Exception as e:
            # All-or-nothing: a failure means the video wouldn't be visually coherent, so bail
            # rather than ship a half-generated clip. Caller decides (default: fail; no gameplay).
            fail(f"Scene {i}/{n} image generation failed across all providers ({e}).",
                 fallback="gameplay", scenes_done=i - 1)
            return
        manifest_scenes.append({
            "path": out_path, "index": i,
            "speaker": sc["speaker"], "text": sc["text"],
            "start": sc["start"], "end": sc["end"],
        })

    manifest = {"scenes": manifest_scenes, "count": n, "provider": pinned,
                "setting": setting, "characters": names}
    os.makedirs(os.path.dirname(args.manifest) or ".", exist_ok=True)
    with open(args.manifest, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    emit({"manifest": args.manifest, "count": n, "provider": pinned, "out_dir": out_dir})


if __name__ == "__main__":
    main()
