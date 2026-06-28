"""One-time OAuth consent for YouTube uploads: turns an OAuth client into youtube_token.json.

The OAuth client (a Desktop "installed" app) can come from EITHER:
  - the shared API.env: set YOUTUBE_CLIENT_ID + YOUTUBE_CLIENT_SECRET (preferred), or
  - a credentials.json file (reused from the Gmail setup, or YOUTUBE_CREDENTIALS_PATH).

Prereqs in the SAME Google Cloud project:
  - Enable the **YouTube Data API v3**.
  - OAuth consent screen: add the channel's Google account as a **Test user** (else access_denied).

Run once, standalone; opens a browser for consent. Requests upload + read scopes
(read needed by the weekly-roundup skill: list uploads, stats, comments, analytics) —
kept in a SEPARATE token file from the Gmail token because the scopes differ.

Prereq for analytics: enable the **YouTube Analytics API** in the same Cloud project.

Usage:
    python tools/youtube_auth_setup.py

Prints JSON: {"status": "ok", "token_path": "...", "source": "env|file"}
"""
import os

from _common import load_env, emit, fail

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",        # publish videos
    "https://www.googleapis.com/auth/youtube.readonly",      # list uploads, stats, comments
    "https://www.googleapis.com/auth/yt-analytics.readonly",  # retention, CTR, watch time, subs
]


def client_config_from_env():
    """Build an InstalledAppFlow client config from API.env, or None if not fully set."""
    cid = os.environ.get("YOUTUBE_CLIENT_ID", "").strip()
    secret = os.environ.get("YOUTUBE_CLIENT_SECRET", "").strip()
    if not cid or not secret:
        return None
    return {
        "installed": {
            "client_id": cid,
            "client_secret": secret,
            "project_id": os.environ.get("YOUTUBE_PROJECT_ID", "").strip(),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "redirect_uris": ["http://localhost"],
        }
    }


def main():
    load_env()
    token_path = os.environ.get("YOUTUBE_TOKEN_PATH", "youtube_token.json")

    from google_auth_oauthlib.flow import InstalledAppFlow

    config = client_config_from_env()
    if config:
        flow = InstalledAppFlow.from_client_config(config, SCOPES)
        source = "env"
    else:
        creds_path = os.environ.get("YOUTUBE_CREDENTIALS_PATH") or os.environ.get("GMAIL_CREDENTIALS_PATH", "credentials.json")
        if not os.path.isfile(creds_path):
            fail(
                "No OAuth client found. Either set YOUTUBE_CLIENT_ID + YOUTUBE_CLIENT_SECRET in API.env, "
                f"or provide {creds_path} (the Desktop OAuth client). Also enable the YouTube Data API v3."
            )
            return
        flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
        source = "file"

    creds = flow.run_local_server(port=0)

    with open(token_path, "w", encoding="utf-8") as f:
        f.write(creds.to_json())

    emit({"status": "ok", "token_path": token_path, "source": source})


if __name__ == "__main__":
    main()
