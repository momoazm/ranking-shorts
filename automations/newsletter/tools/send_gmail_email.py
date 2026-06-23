"""Send a pre-built MIME message via the Gmail API. The only step with an
externally-visible, hard-to-reverse side effect — only call this after the
user has explicitly confirmed the preview.

Usage:
    python tools/send_gmail_email.py --eml .tmp/newsletter.eml

Prints JSON: {"status": "sent", "message_id": "...", "thread_id": "..."}
"""
import argparse
import base64
import os

from _common import load_env, emit, fail

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def load_credentials(token_path):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    return creds


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--eml", required=True, help="Path to the .eml file from build_email_mime.py")
    args = parser.parse_args()

    load_env()
    token_path = os.environ.get("GMAIL_TOKEN_PATH", "token.json")

    if not os.path.isfile(token_path):
        fail(f"{token_path} not found. Run: python tools/gmail_auth_setup.py")
        return

    try:
        with open(args.eml, "rb") as f:
            raw_bytes = f.read()
    except OSError as e:
        fail(f"Could not read --eml: {e}")
        return

    try:
        creds = load_credentials(token_path)
    except Exception as e:
        fail(
            f"Could not load/refresh Gmail credentials: {e}. "
            "If the refresh token was revoked, re-run: python tools/gmail_auth_setup.py"
        )
        return

    from googleapiclient.discovery import build

    service = build("gmail", "v1", credentials=creds)
    raw = base64.urlsafe_b64encode(raw_bytes).decode("utf-8")

    try:
        sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    except Exception as e:
        fail(f"Gmail send failed: {e}")
        return

    emit({"status": "sent", "message_id": sent.get("id"), "thread_id": sent.get("threadId")})


if __name__ == "__main__":
    main()
