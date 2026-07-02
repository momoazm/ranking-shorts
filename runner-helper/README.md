# MOMO runner-helper

The tiny always-on watcher that lets the **"Run" buttons on the MOMO site** start your
self-hosted pipelines on demand — and makes the runner close itself after each job.

## The flow
```
Site button ──POST──▶ Vercel /api/runner ──workflow_dispatch──▶ GitHub: run "queued"
                                                                      │
runner_helper.py polls GitHub every ~20s ◀────────────────────────────┘
        │  sees a queued run
        ▼
  launches  <runner folder>\run.cmd --once   ──▶ runner takes ONE job, runs it, EXITS
```
The runner is only alive while a job runs. `--once` handles the "close the runner" step — the
helper never has to stop anything.

## One-time setup
1. **Token** — create a fine-grained GitHub PAT (github.com → Settings → Developer settings →
   Fine-grained tokens): repo access = `clipping-auto` + `ranking-shorts`; Permissions →
   **Actions: Read and write** (read is enough for the helper; the same token goes in Vercel where
   write is needed to dispatch).
2. **Config** — copy `helper.env.example` → `helper.env`, paste the token into `GH_DISPATCH_TOKEN`.
   The default runner folders (`C:\actions-runner`, `C:\actions-runner-ranking`) already match
   this PC; change them only if yours differ.
3. **Stop running `run.cmd` by hand.** Let the helper own launching the runners — otherwise you'd
   get two runners fighting for the same job.

## Run it
- **Test (foreground, see output):** `python runner_helper.py`  (Ctrl-C to stop)
- **Background (hidden):** `powershell -ExecutionPolicy Bypass -File start-helper.ps1`

## Auto-start at logon (so it's always ready)
Register a Task Scheduler job that launches it hidden every time you log in:
```powershell
$ps = "powershell -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$PWD\start-helper.ps1`""
schtasks /create /tn "MOMO Runner Helper" /tr $ps /sc onlogon /rl highest /f
```
Remove it later with: `schtasks /delete /tn "MOMO Runner Helper" /f`

## Notes
- The PC must be **on and logged in** for a button press to run. If it's off, the run just stays
  `queued` on GitHub and fires the moment the helper comes online.
- Logs: `helper.log` (next to this file). Both `helper.env` and `helper.log` are gitignored.
- This helper only manages **clipping** and **ranking** — your `actions-runner-followers` runner is
  untouched.
