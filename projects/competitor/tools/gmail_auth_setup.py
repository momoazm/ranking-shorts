"""One-time OAuth consent flow: turns credentials.json into a usable token.json.

Run this once, standalone, after creating an OAuth Client ID (type "Desktop app")
in Google Cloud Console and downloading it as credentials.json in the repo root.
Opens a browser for consent; only requests the minimal gmail.send scope.

Usage:
    python tools/gmail_auth_setup.py

Prints JSON: {"status": "ok", "token_path": "..."}
"""
import os

from _common import load_env, emit, fail

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def main():
    load_env()
    creds_path = os.environ.get("GMAIL_CREDENTIALS_PATH", "credentials.json")
    token_path = os.environ.get("GMAIL_TOKEN_PATH", "token.json")

    if not os.path.isfile(creds_path):
        fail(
            f"{creds_path} not found. Create an OAuth Client ID (type 'Desktop app') in Google "
            "Cloud Console, enable the Gmail API, and download it to this path before running this script."
        )
        return

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
    creds = flow.run_local_server(port=0)

    with open(token_path, "w", encoding="utf-8") as f:
        f.write(creds.to_json())

    emit({"status": "ok", "token_path": token_path})


if __name__ == "__main__":
    main()
