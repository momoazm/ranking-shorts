"""
Vercel Python serverless function: trigger the self-hosted GitHub Actions pipelines
(clipping-auto + ranking-shorts) on demand from the MOMO site, and report their status.

GET  /api/runner?repo=ranking|clipping
  -> { ok, repo, running, can_run, last: {status, conclusion, created_at, html_url, event} }

POST /api/runner   with JSON body:
  { "repo": "ranking" }
  { "repo": "clipping", "dry_run": true }   # clipping supports a dry run
  -> dispatches the workflow (workflow_dispatch). Rejected 409 if a run is already active.

The function holds a fine-grained GitHub PAT (Actions: read+write on both repos) so the token
NEVER touches the static page. No password gate — the endpoint is intentionally open (Moemen's
call); the only server-side guard is "blocked while a run is already active". Every secret comes
from Vercel environment variables — never the repo:
  GH_DISPATCH_TOKEN

Standard library only — no third-party dependencies.
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import urllib.request
import urllib.parse
import urllib.error

GITHUB_API = "https://api.github.com"

# repo key -> (owner/repo, workflow file). The runner that serves each repo lives on Moemen's PC
# (C:\actions-runner for clipping, C:\actions-runner-ranking for ranking); the local helper starts
# them on demand. This function only talks to GitHub.
REPOS = {
    "ranking":  {"slug": "momoazm/ranking-shorts", "workflow": "autopost.yml"},
    "clipping": {"slug": "momoazm/clipping-auto",  "workflow": "clipping_daily.yml"},
}

# A run in any of these states means "busy" -> the gate blocks a new dispatch.
ACTIVE_STATES = {"queued", "in_progress", "requested", "pending", "waiting"}


def _missing_env():
    missing = []
    if not os.environ.get("GH_DISPATCH_TOKEN"):
        missing.append("GH_DISPATCH_TOKEN")
    return missing


def _gh(path, method="GET", body=None):
    """Call the GitHub REST API with the PAT. Returns (status_code, parsed_json_or_None)."""
    url = GITHUB_API + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + os.environ["GH_DISPATCH_TOKEN"],
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "momo-runner-button",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read().decode() or ""
        return r.status, (json.loads(raw) if raw.strip() else None)


def _latest_runs(slug, workflow):
    _, data = _gh("/repos/%s/actions/workflows/%s/runs?per_page=5" % (slug, workflow))
    return (data or {}).get("workflow_runs", [])


def _status(repo):
    """Build the status object the frontend uses to enable/disable the button."""
    cfg = REPOS[repo]
    runs = _latest_runs(cfg["slug"], cfg["workflow"])
    running = any((run.get("status") in ACTIVE_STATES) for run in runs)
    last = runs[0] if runs else None
    return {
        "ok": True,
        "repo": repo,
        "running": running,
        "can_run": not running,
        "last": ({
            "status": last.get("status"),
            "conclusion": last.get("conclusion"),
            "created_at": last.get("created_at"),
            "html_url": last.get("html_url"),
            "event": last.get("event"),
        } if last else None),
    }


def _default_branch(slug):
    _, data = _gh("/repos/%s" % slug)
    return (data or {}).get("default_branch") or "main"


class handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        payload = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _repo_param(self):
        qs = urllib.parse.urlparse(self.path).query
        return (urllib.parse.parse_qs(qs).get("repo") or [None])[0]

    def do_GET(self):
        missing = _missing_env()
        if missing:
            return self._send(500, {"error": "Server not configured. Missing env vars: " + ", ".join(missing)})
        repo = self._repo_param()
        if repo not in REPOS:
            # No/unknown repo -> harmless health ping (no secrets revealed).
            return self._send(200, {"ok": True, "service": "runner", "repos": list(REPOS)})
        try:
            return self._send(200, _status(repo))
        except urllib.error.HTTPError as e:
            return self._send(502, {"error": _gh_err(e)})
        except Exception as e:
            return self._send(500, {"error": "Server error: " + str(e)})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
            p = json.loads((self.rfile.read(length) if length else b"{}").decode() or "{}")
        except Exception:
            return self._send(400, {"error": "Invalid JSON body."})

        missing = _missing_env()
        if missing:
            return self._send(500, {"error": "Server not configured. Missing env vars: " + ", ".join(missing)})

        repo = p.get("repo")
        if repo not in REPOS:
            return self._send(400, {"error": "Unknown repo: " + str(repo)})
        cfg = REPOS[repo]

        try:
            # Server-side gate: never dispatch while a run is already active.
            status = _status(repo)
            if status["running"]:
                return self._send(409, {"error": "A run is already in progress.", **status})

            inputs = {}
            if repo == "clipping" and p.get("dry_run"):
                inputs["dry_run"] = "true"   # build clips but DON'T upload (safe test)

            branch = _default_branch(cfg["slug"])
            body = {"ref": branch}
            if inputs:
                body["inputs"] = inputs
            code, _ = _gh("/repos/%s/actions/workflows/%s/dispatches" % (cfg["slug"], cfg["workflow"]),
                          method="POST", body=body)
            # GitHub returns 204 No Content on a successful dispatch.
            return self._send(200, {"ok": True, "message": "Dispatched.", "repo": repo,
                                    "dry_run": bool(inputs), "running": True, "can_run": False})
        except urllib.error.HTTPError as e:
            return self._send(502, {"error": _gh_err(e)})
        except Exception as e:
            return self._send(500, {"error": "Server error: " + str(e)})


def _gh_err(e):
    detail = ""
    try:
        detail = e.read().decode(errors="replace")
        detail = json.loads(detail).get("message", detail)
    except Exception:
        pass
    return "GitHub API error (%s): %s" % (getattr(e, "code", "?"), detail or str(e))
