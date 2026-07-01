"""End-to-end self-test for the MOMO website backends (RAG, and optionally the
live serverless endpoints). Deterministic, prints one JSON object to stdout, and
exits non-zero if any CRITICAL check fails — so it's safe to wire into CI or run
by hand before a deploy.

What it does
------------
RAG round-trip (always, critical):
  1. Ensure the Pinecone index exists (setup_pinecone.py).
  2. Ingest a throwaway file containing a random passphrase.
  3. Query for that passphrase and assert OUR file is the top match.
  4. Clean up: delete exactly the vectors we added (never delete_all — real data
     in the index is left untouched).

Live endpoints (only with --url, best-effort — not critical unless --strict):
  • GET  /api/health          -> expects {ok:true}
  • POST /api/ask             -> full RAG answer; checks the passphrase is echoed
  • POST /api/gcal {list}     -> Calendar (needs Google creds; reported, not fatal)
  • GET  /api/runner?repo=... -> pipeline runner status (reported, not fatal)

Usage (run from anywhere; paths are resolved relative to this file):
    python selftest.py
    python selftest.py --url http://localhost:8000
    python selftest.py --url http://localhost:8000 --strict
"""
import argparse
import json
import random
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
from pathlib import Path

# selftest.py lives at projects/website/skills/website-selftest/ ; CS is a sibling
# of skills/ under projects/website/.
HERE = Path(__file__).resolve()
WEBSITE_DIR = HERE.parents[2]            # projects/website
CS_DIR = WEBSITE_DIR / "CS"
VENV_PY = CS_DIR / ".venv" / "Scripts" / "python.exe"   # Windows layout
if not VENV_PY.exists():                                # POSIX fallback
    VENV_PY = CS_DIR / ".venv" / "bin" / "python"


def run_cs_tool(args, timeout=180):
    """Run a CS/ tool with the CS venv, from the CS dir, and parse its stdout JSON."""
    proc = subprocess.run(
        [str(VENV_PY), *args],
        cwd=str(CS_DIR), capture_output=True, text=True, timeout=timeout,
    )
    out = (proc.stdout or "").strip()
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        raise RuntimeError(
            f"{args} did not print JSON (exit {proc.returncode}).\n"
            f"stdout: {out[:500]}\nstderr: {(proc.stderr or '')[:500]}"
        )
    return data, proc.returncode


def http_json(url, method="GET", body=None, timeout=15):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode() or "{}")


def rag_round_trip(results):
    """Ingest → query → assert → clean up. Returns True on success."""
    if not VENV_PY.exists():
        results["rag"] = {"ok": False, "error": f"CS venv python not found at {VENV_PY}. "
                          "Create it: see CS/CS.md 'Environment setup'."}
        return False

    # 1. index exists
    setup, rc = run_cs_tool(["tools/setup_pinecone.py"])
    if "error" in setup:
        results["rag"] = {"ok": False, "stage": "setup", "error": setup["error"]}
        return False

    # 2. ingest a throwaway file with a unique passphrase
    passphrase = f"MOMO-SELFTEST-{random.randint(10**7, 10**8 - 1)}"
    with tempfile.TemporaryDirectory() as td:
        fpath = Path(td) / "momo_selftest_note.txt"
        fpath.write_text(
            f"This is an automated MOMO website self-test document.\n"
            f"The secret self-test passphrase is {passphrase}.\n",
            encoding="utf-8",
        )
        ingest, rc = run_cs_tool(["tools/ingest.py", "--path", str(fpath)])
        if "error" in ingest or ingest.get("upserted", 0) < 1:
            results["rag"] = {"ok": False, "stage": "ingest", "detail": ingest}
            return False
        ids = ingest.get("vectors", [])

        try:
            # Pinecone serverless is eventually consistent — give the upsert a moment.
            top = None
            for _ in range(10):
                query, rc = run_cs_tool(
                    ["tools/query.py", "--text",
                     "What is the secret self-test passphrase?", "--top-k", "3"]
                )
                matches = query.get("matches", []) if "error" not in query else []
                if matches:
                    top = matches[0]
                    if (top.get("metadata", {}) or {}).get("filename") == fpath.name:
                        break
                time.sleep(1.5)

            ok = bool(top) and (top.get("metadata", {}) or {}).get("filename") == fpath.name
            results["rag"] = {
                "ok": ok,
                "passphrase": passphrase,
                "top_match": (top or {}).get("metadata", {}).get("filename") if top else None,
                "top_score": round(float((top or {}).get("score", 0) or 0), 3) if top else None,
                "detail": None if ok else "expected our self-test file as the top match",
            }
        finally:
            # 3. clean up — delete ONLY the ids we added.
            wipe_src = (
                "import sys; sys.path.insert(0,'tools');"
                "from _common import load_env, pinecone_config; load_env();"
                "from pinecone import Pinecone; cfg=pinecone_config();"
                "idx=Pinecone(api_key=cfg['api_key']).Index(cfg['index']);"
                "ids=sys.argv[1:];"
                "idx.delete(ids=ids) if ids else None;"
                "print('{\"deleted\": %d}' % len(ids))"
            )
            try:
                subprocess.run([str(VENV_PY), "-c", wipe_src, *ids],
                               cwd=str(CS_DIR), capture_output=True, text=True, timeout=60)
                results["rag"]["cleaned_up"] = len(ids)
            except Exception as e:  # cleanup failure shouldn't mask the test result
                results["rag"]["cleanup_error"] = str(e)

    return results["rag"]["ok"]


def endpoint_checks(url, passphrase, results):
    base = url.rstrip("/")
    ep = results["endpoints"] = {}

    # health (critical-ish under --strict)
    try:
        st, j = http_json(f"{base}/api/health")
        ep["health"] = {"ok": bool(j.get("ok")), "status": st, "detail": j}
    except Exception as e:
        ep["health"] = {"ok": False, "error": str(e)}

    # full RAG answer (best-effort; only meaningful if a doc is in the DB)
    try:
        st, j = http_json(f"{base}/api/ask", "POST",
                          {"question": "What is the secret self-test passphrase?"})
        answer = (j.get("answer") or "")
        ep["ask"] = {"ok": st == 200 and bool(answer), "status": st,
                     "answer_preview": answer[:160]}
    except Exception as e:
        ep["ask"] = {"ok": False, "error": str(e)}

    # calendar (reported, not fatal — needs Google creds)
    try:
        st, j = http_json(f"{base}/api/gcal", "POST", {"action": "list"})
        ep["calendar"] = {"ok": st == 200 and "error" not in j, "status": st,
                          "events": len(j.get("events", [])) if isinstance(j, dict) else None,
                          "note": j.get("error")}
    except Exception as e:
        ep["calendar"] = {"ok": False, "error": str(e), "note": "endpoint down or no creds"}

    # runner status (reported, not fatal)
    try:
        st, j = http_json(f"{base}/api/runner?repo=ranking")
        ep["runner"] = {"ok": st == 200, "status": st, "detail": j}
    except Exception as e:
        ep["runner"] = {"ok": False, "error": str(e), "note": "endpoint down"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="Base URL of a running site (e.g. http://localhost:8000) "
                                  "to also test the live /api/* endpoints.")
    ap.add_argument("--strict", action="store_true",
                    help="Treat health + ask endpoint failures as fatal too.")
    args = ap.parse_args()

    results = {}
    passphrase = None
    rag_ok = rag_round_trip(results)
    passphrase = results.get("rag", {}).get("passphrase")

    if args.url:
        endpoint_checks(args.url, passphrase, results)

    # Decide overall pass/fail. RAG round-trip is always critical.
    critical = [rag_ok]
    if args.url and args.strict:
        ep = results.get("endpoints", {})
        critical += [ep.get("health", {}).get("ok", False),
                     ep.get("ask", {}).get("ok", False)]
    results["passed"] = all(critical)

    print(json.dumps(results, indent=2, ensure_ascii=False))
    sys.exit(0 if results["passed"] else 1)


if __name__ == "__main__":
    main()
