"""
MOMO runner-helper  —  the tiny always-on piece that makes the website's "Run" buttons work.

Why this exists
---------------
The clipping + ranking pipelines run on SELF-HOSTED runners (this PC). A button on the Vercel
site can't reach into a home PC (NAT), so something here has to watch for work and start the
runner. This script is that watcher. GitHub itself is the queue:

  site button -> Vercel /api/runner -> workflow_dispatch -> GitHub shows the run "queued"
  THIS helper polls GitHub -> sees a queued run -> launches `run.cmd --once` in the right folder
  the runner takes that ONE job, runs it, and EXITS on its own (--once) -> "closed"

So the runner is only alive while a job is running. The helper does NOT need to stop anything.

What it needs
-------------
A GitHub token with **Actions: Read** on both repos (the same fine-grained PAT used by the
Vercel function works — read is all the helper needs). Put it in `helper.env` next to this file.

Stdlib only. Run with:  python runner_helper.py        (Ctrl-C to stop)
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
GITHUB_API = "https://api.github.com"
ACTIVE_STATES = {"queued", "in_progress", "requested", "pending", "waiting"}

# repo key -> GitHub slug, workflow file, env var holding the runner folder, and a sane default.
REPOS = {
    "clipping": {"slug": "momoazm/clipping-auto", "workflow": "clipping_daily.yml",
                 "dir_env": "RUNNER_DIR_CLIPPING", "default_dir": r"C:\actions-runner"},
    "ranking":  {"slug": "momoazm/ranking-shorts", "workflow": "autopost.yml",
                 "dir_env": "RUNNER_DIR_RANKING", "default_dir": r"C:\actions-runner-ranking"},
}

# CREATE_NO_WINDOW so the runner runs hidden (its logs still go to GitHub Actions).
CREATE_NO_WINDOW = 0x08000000


def log(msg):
    line = "[%s] %s" % (datetime.now().strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    try:
        with open(HERE / "helper.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_env():
    """Load KEY=VALUE lines from helper.env into os.environ (without overriding real env vars)."""
    env_file = HERE / "helper.env"
    if env_file.exists():
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def gh_get(path):
    req = urllib.request.Request(GITHUB_API + path, headers={
        "Authorization": "Bearer " + os.environ["GH_DISPATCH_TOKEN"],
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "momo-runner-helper",
    })
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode() or "{}")


def has_active_run(cfg):
    data = gh_get("/repos/%s/actions/workflows/%s/runs?per_page=5" % (cfg["slug"], cfg["workflow"]))
    return any(run.get("status") in ACTIVE_STATES for run in data.get("workflow_runs", []))


def runner_dir(cfg):
    return os.environ.get(cfg["dir_env"]) or cfg["default_dir"]


def launch_runner(cfg):
    rdir = runner_dir(cfg)
    run_cmd = os.path.join(rdir, "run.cmd")
    if not os.path.exists(run_cmd):
        log("  !! run.cmd not found at %s — skipping (check %s)" % (run_cmd, cfg["dir_env"]))
        return None
    # `cmd /c run.cmd --once` -> runner processes exactly one job, then exits.
    return subprocess.Popen(["cmd", "/c", run_cmd, "--once"], cwd=rdir,
                            creationflags=CREATE_NO_WINDOW)


def main():
    load_env()
    if not os.environ.get("GH_DISPATCH_TOKEN"):
        log("FATAL: GH_DISPATCH_TOKEN not set (put it in runner-helper/helper.env). Exiting.")
        sys.exit(1)

    poll = int(os.environ.get("POLL_SECONDS") or 20)
    procs = {}  # repo -> live Popen of the runner we launched (None when idle)
    log("MOMO runner-helper started. Polling every %ss. Repos: %s" % (poll, ", ".join(REPOS)))

    while True:
        for repo, cfg in REPOS.items():
            # Reap a finished runner so the next queued job can launch a fresh one.
            p = procs.get(repo)
            if p is not None and p.poll() is not None:
                log("%-9s runner exited (job done)." % repo)
                procs[repo] = None
                p = None
            try:
                active = has_active_run(cfg)
            except urllib.error.HTTPError as e:
                log("%-9s GitHub error %s — will retry next poll." % (repo, getattr(e, "code", "?")))
                continue
            except Exception as e:
                log("%-9s poll error: %s — will retry next poll." % (repo, e))
                continue

            if active and procs.get(repo) is None:
                log("%-9s job queued/active -> starting runner (run.cmd --once)" % repo)
                procs[repo] = launch_runner(cfg)
            # If active and a runner is already running, do nothing (it's handling the job).
            # If not active and a runner is somehow still alive, leave it: --once exits itself.

        time.sleep(poll)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Stopped (Ctrl-C).")
