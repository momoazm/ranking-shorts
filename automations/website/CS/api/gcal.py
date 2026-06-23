"""
Vercel Python serverless function: private Google Calendar create/edit tool.

POST /api/gcal  with a JSON body:
  { "password": "...", "action": "list" }
  { "password": "...", "action": "create",
    "summary": "Title", "start": "2026-06-23T15:00", "end": "2026-06-23T16:00",
    "timeZone": "Africa/Cairo", "location": "...", "description": "..." }
  { "password": "...", "action": "update", "id": "<eventId>", ...same optional fields... }

The function acts as the site owner via a CALENDAR-ONLY OAuth refresh token, gated by a
shared admin password. Every secret comes from environment variables set in Vercel —
never the repo:
  GOOGLE_CAL_CLIENT_ID, GOOGLE_CAL_CLIENT_SECRET, GOOGLE_CAL_REFRESH_TOKEN, CAL_ADMIN_PASSWORD

Standard library only — no third-party dependencies.
"""
from http.server import BaseHTTPRequestHandler
from datetime import datetime, timezone
import json
import os
import hmac
import urllib.request
import urllib.parse
import urllib.error

TOKEN_URL = "https://oauth2.googleapis.com/token"
EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
REQUIRED_ENV = ("GOOGLE_CAL_CLIENT_ID", "GOOGLE_CAL_CLIENT_SECRET",
                "GOOGLE_CAL_REFRESH_TOKEN", "CAL_ADMIN_PASSWORD")


def _missing_env():
    return [k for k in REQUIRED_ENV if not os.environ.get(k)]


def _access_token():
    """Exchange the long-lived refresh token for a short-lived access token."""
    body = urllib.parse.urlencode({
        "client_id": os.environ["GOOGLE_CAL_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_CAL_CLIENT_SECRET"],
        "refresh_token": os.environ["GOOGLE_CAL_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request(
        TOKEN_URL, data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())["access_token"]


def _calendar(url, method="GET", token=None, body=None, query=None):
    if query:
        url = url + "?" + urllib.parse.urlencode(query)
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + token}
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode() or "{}")


def _rfc3339(s):
    """datetime-local gives 'YYYY-MM-DDTHH:MM' (no seconds); Google wants seconds."""
    s = (s or "").strip()
    return s + ":00" if len(s) == 16 else s


def _event_body(p):
    ev = {}
    if p.get("summary") is not None:
        ev["summary"] = p["summary"]
    if p.get("description") is not None:
        ev["description"] = p["description"]
    if p.get("location") is not None:
        ev["location"] = p["location"]
    tz = p.get("timeZone") or "UTC"
    if p.get("start"):
        ev["start"] = {"dateTime": _rfc3339(p["start"]), "timeZone": tz}
    if p.get("end"):
        ev["end"] = {"dateTime": _rfc3339(p["end"]), "timeZone": tz}
    return ev


class handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        payload = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        # Harmless health ping: reveals only whether env vars are present, no secrets.
        self._send(200, {"ok": True, "service": "calendar", "configured": not _missing_env()})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
            p = json.loads((self.rfile.read(length) if length else b"{}").decode() or "{}")
        except Exception:
            return self._send(400, {"error": "Invalid JSON body."})

        missing = _missing_env()
        if missing:
            return self._send(500, {"error": "Server not configured. Missing env vars: " + ", ".join(missing)})

        # Constant-time password check (the only gate on this endpoint).
        if not hmac.compare_digest((p.get("password") or "").encode(),
                                   os.environ["CAL_ADMIN_PASSWORD"].encode()):
            return self._send(401, {"error": "Wrong password."})

        action = p.get("action")
        try:
            token = _access_token()

            if action == "list":
                data = _calendar(EVENTS_URL, "GET", token, query={
                    "timeMin": datetime.now(timezone.utc).isoformat(),
                    "maxResults": 15, "singleEvents": "true", "orderBy": "startTime"})
                events = [{
                    "id": e.get("id"), "summary": e.get("summary"),
                    "start": e.get("start"), "end": e.get("end"),
                    "location": e.get("location"), "description": e.get("description"),
                    "htmlLink": e.get("htmlLink"),
                } for e in data.get("items", [])]
                return self._send(200, {"events": events})

            if action == "create":
                if not (p.get("summary") and p.get("start") and p.get("end")):
                    return self._send(400, {"error": "summary, start and end are required."})
                data = _calendar(EVENTS_URL, "POST", token, body=_event_body(p))
                return self._send(200, {"message": "Event created.",
                                        "event": {"id": data.get("id"), "htmlLink": data.get("htmlLink")}})

            if action == "update":
                if not p.get("id"):
                    return self._send(400, {"error": "id is required to update an event."})
                url = EVENTS_URL + "/" + urllib.parse.quote(p["id"])
                data = _calendar(url, "PATCH", token, body=_event_body(p))
                return self._send(200, {"message": "Event updated.",
                                        "event": {"id": data.get("id"), "htmlLink": data.get("htmlLink")}})

            return self._send(400, {"error": "Unknown action: " + str(action)})

        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            try:
                detail = json.loads(detail).get("error", {}).get("message", detail)
            except Exception:
                pass
            return self._send(502, {"error": "Google Calendar API error: " + detail})
        except Exception as e:
            return self._send(500, {"error": "Server error: " + str(e)})
