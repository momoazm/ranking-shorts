"""Deterministically pick this ISO week's experimental follow-CTA variant for the
@momoclips account, and gate it to exactly ONE post so an experiment never
overrides the whole week's output.

Rotation is keyed by ISO week number, so calling it more than once in the same
week always returns the same variant (idempotent across retried polls).
`--consume` claims it: the FIRST caller in a given week to actually land a
successful Instagram post gets credit for the experiment; every later call
that week gets style=null (fall back to the normal default CTA baked into
build_clip.py, "FOLLOW FOR MORE" / 2.2s).

Called (peek, then consume-on-success) by clip_autopost.py, watch_worldcup.py,
and watch_speed.py -- all three post to the same account, so whichever lands a
real post first that week claims the slot. And by check_style_experiment.py
for visibility into what's queued.

Usage:
    python tools/pick_weekly_style.py             # peek this week's queued variant
    python tools/pick_weekly_style.py --consume    # claim it for the caller's post

Prints JSON: {"week":"2026-W29","name":"cta_daily","cta_text":"FOLLOW FOR DAILY CLIPS",
              "cta_dur":2.2,"used":false}
             --consume: same shape + "consumed":true
                     or {"week":...,"style":null,"consumed":false} (already used this week)
"""
import argparse
import datetime
import json

from _common import REPO_ROOT, emit

STATE_PATH = REPO_ROOT / "state" / "style_experiment.json"
VARIANTS = [
    {"name": "default_cta", "cta_text": "FOLLOW FOR MORE", "cta_dur": 2.2},
    {"name": "cta_daily", "cta_text": "FOLLOW FOR DAILY CLIPS", "cta_dur": 2.2},
    {"name": "cta_directional", "cta_text": "MORE LIKE THIS →", "cta_dur": 2.6},
]
# "default_cta" matches build_clip.py's own default -- rotating through it too keeps
# the baseline honest (some weeks the "experiment" is just a no-op control).


def _load():
    if STATE_PATH.is_file():
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"history": []}


def _save(data):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--consume", action="store_true",
                        help="Claim this week's experimental variant for the caller's post")
    args = parser.parse_args()

    iso = datetime.date.today().isocalendar()
    week_key = f"{iso[0]}-W{iso[1]:02d}"

    data = _load()
    cur = data.get("current")
    if not cur or cur.get("week") != week_key:
        variant = VARIANTS[iso[1] % len(VARIANTS)]
        cur = {"week": week_key, "variant": variant, "used": False}
        data["current"] = cur
        _save(data)

    if not args.consume:
        emit({"week": week_key, "used": cur["used"], **cur["variant"]})
        return

    if cur["used"]:
        emit({"week": week_key, "style": None, "consumed": False})
        return

    cur["used"] = True
    data.setdefault("history", []).append({"week": week_key, **cur["variant"]})
    _save(data)
    emit({"week": week_key, "consumed": True, **cur["variant"]})


if __name__ == "__main__":
    main()
