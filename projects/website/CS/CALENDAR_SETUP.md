# My Calendar — private create/edit tool

Adds a password-gated "My Calendar" panel to the CS site (`index.html`) backed by a Vercel
serverless function (`api/gcal.py`). It can **list, create, and edit** events on your Google
Calendar's `primary` calendar. It acts as you via a **Calendar-only** OAuth token and is gated
by a single admin password — no one but you can use it.

```
index.html  (My Calendar panel, password box)
   │ POST /api/gcal  { password, action, ... }
   ▼
api/gcal.py  → checks password → refresh-token → Google Calendar API
```

## 1. Set the environment variables in Vercel
Project → **Settings → Environment Variables** (Production). Names below; the **values** are in
`C:\Users\monar\.config\gws-website-calendar\vercel-env.txt` (kept outside the repo on purpose —
never commit them).

| Variable | What it is |
|---|---|
| `GOOGLE_CAL_CLIENT_ID` | OAuth client id (Claude GWS project) |
| `GOOGLE_CAL_CLIENT_SECRET` | OAuth client secret |
| `GOOGLE_CAL_REFRESH_TOKEN` | Calendar-only refresh token (secret) |
| `CAL_ADMIN_PASSWORD` | The password you type to unlock the panel |

## 2. Publish the OAuth app (important)
The OAuth app must be in **Production**, not Testing — otherwise Google expires the refresh
token after ~7 days and the panel stops working. Cloud Console →
`https://console.cloud.google.com/auth/audience?project=claude-gws-500214` → **Publish app**.

## 3. Deploy
Push the `CS/` contents to the **momoazm/CS** GitHub repo (same as you deploy the site now).
Vercel auto-detects `api/gcal.py` and serves it at `/api/gcal`. `api/requirements.txt` is empty
on purpose so the function stays standard-library-only (it does **not** pull in pinecone/
google-genai from the project-root `requirements.txt`).

## 4. Use it
Open the site → scroll to **My Calendar** → type your admin password → **Unlock**. Then create
events or click **Edit** on an upcoming one. Times use your browser's time zone.

## Security notes
- The admin password is the only gate. Use the strong one generated for you; rotate it by
  changing `CAL_ADMIN_PASSWORD` in Vercel.
- The function holds a **Calendar-only** scope — even if the token leaked it cannot touch Gmail,
  Drive, etc.
- Secrets live only in Vercel env vars, never in the repo or the page. Don't paste them into
  `index.html`.
- The endpoint can only `list`, `create`, and `update` events on `primary`. It cannot delete.

## Local testing (optional)
```bash
# from CS/, with the four vars exported into your shell:
python -c "import http.server,sys; sys.path.insert(0,'api'); import gcal; \
  http.server.HTTPServer(('127.0.0.1',8801), gcal.handler).serve_forever()"
# then POST {"password":"...","action":"list"} to http://127.0.0.1:8801/
```

## Endpoint reference (`POST /api/gcal`)
```jsonc
{ "password": "...", "action": "list" }
{ "password": "...", "action": "create",
  "summary": "Title", "start": "2026-06-23T15:00", "end": "2026-06-23T16:00",
  "timeZone": "Africa/Cairo", "location": "(optional)", "description": "(optional)" }
{ "password": "...", "action": "update", "id": "<eventId>", "summary": "...", "start": "...", "end": "..." }
```
Responses are JSON: `{ "events": [...] }` for list, `{ "message": "...", "event": {...} }` for
create/update, or `{ "error": "..." }` with a 4xx/5xx status on failure.
