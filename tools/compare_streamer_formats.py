"""Compare standalone streamer clips with ranked controls after analytics are available.

This is intentionally a measurement step, not a delete step.  It needs three mature posts per
format, uses a 25% primary win margin, and refuses to select a winner when analytics are pending
or the secondary engagement signal collapses.  The next ``--format auto`` run can then use the
winner stored in ``state/format_experiment.json``.
"""
import datetime
import json
import subprocess
import sys
from pathlib import Path

from _common import REPO_ROOT, emit

TOOLS = Path(__file__).resolve().parent
LOG_PATH = REPO_ROOT / "state" / "ig_post_log.json"
STATE_PATH = REPO_ROOT / "state" / "format_experiment.json"
FORMATS = ("standalone", "ranking")
MIN_SAMPLES = 3
MIN_AGE_DAYS = 4.0
WIN_MARGIN = 0.25
SECONDARY_FLOOR = -0.10
RETENTION_FLOOR = -0.15


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def age_days(value):
    try:
        posted = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if posted.tzinfo is None:
            posted = posted.replace(tzinfo=datetime.timezone.utc)
        return (datetime.datetime.now(datetime.timezone.utc) - posted).total_seconds() / 86400
    except (TypeError, ValueError):
        return 0.0


def fetch(post_id):
    proc = subprocess.run([sys.executable, str(TOOLS / "ig_fetch_analytics.py"),
                           "--post-id", str(post_id)], cwd=str(REPO_ROOT),
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=60)
    text = (proc.stdout or "").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        i, j = text.find("{"), text.rfind("}")
        data = json.loads(text[i:j + 1]) if i >= 0 and j > i else {}
    if proc.returncode != 0 or data.get("error"):
        raise RuntimeError(data.get("error") or "analytics lookup failed")
    return data


def avg(values):
    values = [float(v) for v in values if v is not None]
    return sum(values) / len(values) if values else None


def decide(stats):
    """Return (winner, reason) using views with engagement and retention guardrails."""
    if any(len(stats.get(fmt, [])) < MIN_SAMPLES for fmt in FORMATS):
        return None, f"need at least {MIN_SAMPLES} mature posts per format"
    standalone = stats["standalone"]
    ranking = stats["ranking"]
    standalone_views, ranking_views = avg([p.get("views") for p in standalone]), avg([p.get("views") for p in ranking])
    standalone_eng, ranking_eng = avg([p.get("engagement_rate") for p in standalone]), avg([p.get("engagement_rate") for p in ranking])
    if not standalone_views or not ranking_views or standalone_eng is None or ranking_eng is None:
        return None, "views and engagement analytics are required for both cohorts"
    view_delta = standalone_views / ranking_views - 1
    eng_delta = standalone_eng / ranking_eng - 1 if ranking_eng else 0
    standalone_watch = avg([p.get("watch_completion_ratio") for p in standalone])
    ranking_watch = avg([p.get("watch_completion_ratio") for p in ranking])
    watch_delta = None
    if standalone_watch is not None and ranking_watch is not None and ranking_watch:
        watch_delta = standalone_watch / ranking_watch - 1
    guardrail_ok = watch_delta is None or watch_delta >= RETENTION_FLOOR
    if view_delta >= WIN_MARGIN and eng_delta >= SECONDARY_FLOOR and guardrail_ok:
        suffix = f"; watch completion {watch_delta:+.0%}" if watch_delta is not None else ""
        return "standalone", f"views {view_delta:+.0%}; engagement {eng_delta:+.0%}{suffix}"
    if view_delta <= -WIN_MARGIN and eng_delta <= SECONDARY_FLOOR and (
            watch_delta is None or watch_delta <= -RETENTION_FLOOR):
        suffix = f"; watch completion {watch_delta:+.0%}" if watch_delta is not None else ""
        return "ranking", f"standalone vs ranking: views {view_delta:+.0%}; engagement {eng_delta:+.0%}{suffix}"
    watch_text = f", watch completion {watch_delta:+.0%}" if watch_delta is not None else ""
    return None, f"no clear winner: standalone views {view_delta:+.0%}, engagement {eng_delta:+.0%}{watch_text}"


def main():
    log = load_json(LOG_PATH, {"posts": []})
    stats = {fmt: [] for fmt in FORMATS}
    pending, errors = [], []
    for entry in log.get("posts", []):
        context = entry.get("context") or {}
        fmt = context.get("format")
        if fmt not in FORMATS or not entry.get("post_id"):
            continue
        if age_days(entry.get("posted_at")) < MIN_AGE_DAYS:
            pending.append(entry.get("post_id"))
            continue
        try:
            analytics = fetch(entry["post_id"])
            if analytics.get("sync_status") == "pending":
                pending.append(entry["post_id"])
                continue
            stats[fmt].append({"post_id": entry["post_id"], **analytics})
        except Exception as exc:
            errors.append({"post_id": entry["post_id"], "error": str(exc)[:240]})

    winner, reason = decide(stats)
    state = load_json(STATE_PATH, {"run_index": 0, "runs": []})
    if not isinstance(state, dict):
        state = {"run_index": 0, "runs": []}
    # Do not erase a previous winner on a temporary analytics outage or inconclusive cohort.
    if winner:
        state["winner"] = winner
        state["winner_reason"] = reason
    state["last_comparison"] = {
        "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "samples": {fmt: len(stats[fmt]) for fmt in FORMATS},
        "winner": winner,
        "reason": reason,
        "pending": len(pending),
        "errors": len(errors),
    }
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=True), encoding="utf-8")
    emit({"status": "compared", "winner": winner, "reason": reason,
          "samples": {fmt: len(stats[fmt]) for fmt in FORMATS},
          "pending": pending, "errors": errors,
          "policy": {"min_samples": MIN_SAMPLES, "min_age_days": MIN_AGE_DAYS,
                     "win_margin": WIN_MARGIN, "secondary_floor": SECONDARY_FLOOR,
                     "retention_floor": RETENTION_FLOOR,
                     "live_delete": False}})


if __name__ == "__main__":
    main()
