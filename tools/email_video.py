"""Email a finished Short to yourself via Gmail, with the ready-to-paste captions in the body and
the mp4 attached — so you grab it on your phone and post to TikTok/Instagram by hand.

This is the delivery step for the semi-manual workflow (no IG/TikTok API needed). It reuses the
same Gmail OAuth as the newsletter project.

AUTH: a Gmail OAuth token with the gmail.send scope. Point GMAIL_TOKEN_PATH at it (default
"gmail_token.json"); locally you can reuse newsletter/token.json. Sender = GMAIL_SENDER_EMAIL,
recipient defaults to GMAIL_TO or the sender (i.e. emails it to yourself).

Gmail caps a message at ~25 MB; our Shorts are well under that. If a clip is bigger it still tries,
and reports the size so you can re-encode.

Usage:
    python tools/email_video.py --video .tmp/final.mp4 --captions-meta .tmp/captions_meta.json \
        [--to you@gmail.com] [--subject "..."]

Prints JSON: {"status": "sent", "message_id": ..., "to": ..., "size_bytes": N}
"""
import argparse
import base64
import json
import os
import socket
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import encoders

from _common import load_env, emit, fail

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
GMAIL_LIMIT = 25 * 1024 * 1024
# Above this, attaching/sending over a slow link reliably times out — re-encode a smaller copy first.
COMPRESS_OVER = 12 * 1024 * 1024


def reencode_small(src, dst):
    """720x1280 / CRF 30 / 96k audio — a few MB, plenty for phone playback & manual posting."""
    from _media import run_ffmpeg
    run_ffmpeg(["-i", src, "-vf", "scale=-2:1280", "-c:v", "libx264", "-crf", "30",
                "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
                "-movflags", "+faststart", dst])


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def load_credentials(token_path):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    return creds


def body_text(title, meta):
    ig = (meta.get("instagram", {}) or {}).get("caption", "")
    tt = (meta.get("tiktok", {}) or {}).get("caption", "")
    yt = meta.get("youtube", {}) or {}
    return (
        f"New brainrot Short ready to post: {title}\n\n"
        f"Attached: video.mp4 (1080x1920, Shorts/Reels/TikTok ready).\n\n"
        f"------------------------------------------------------------\n"
        f"INSTAGRAM caption:\n{ig}\n\n"
        f"------------------------------------------------------------\n"
        f"TIKTOK caption:\n{tt}\n\n"
        f"------------------------------------------------------------\n"
        f"YOUTUBE title:\n{yt.get('title', title)}\n\n"
        f"YOUTUBE description:\n{yt.get('description', '')}\n"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--captions-meta", default=".tmp/captions_meta.json")
    parser.add_argument("--to", help="Recipient (default: GMAIL_TO or GMAIL_SENDER_EMAIL)")
    parser.add_argument("--subject", help="Email subject (default from the video title)")
    args = parser.parse_args()

    load_env()
    if not os.path.isfile(args.video):
        fail(f"Video not found: {args.video}")
        return

    token_path = os.environ.get("GMAIL_TOKEN_PATH", "gmail_token.json")
    sender = os.environ.get("GMAIL_SENDER_EMAIL", "")
    to = args.to or os.environ.get("GMAIL_TO") or sender
    if not os.path.isfile(token_path):
        fail(f"Gmail token not found at {token_path}. Set GMAIL_TOKEN_PATH (e.g. to "
             "newsletter/token.json) or run a Gmail OAuth setup. Needs the gmail.send scope.")
        return
    if not to:
        fail("No recipient. Set GMAIL_TO or GMAIL_SENDER_EMAIL in API.env, or pass --to.")
        return

    meta = load_json(args.captions_meta) or {}
    title = meta.get("title") or "brainrot short"
    subject = args.subject or f"New brainrot Short: {title}"

    # Big files time out / bounce — re-encode a smaller copy for reliable delivery.
    video_path = args.video
    size = os.path.getsize(video_path)
    if size > COMPRESS_OVER:
        small = os.path.join(os.path.dirname(args.video) or ".", "email_small.mp4")
        try:
            reencode_small(args.video, small)
            video_path, size = small, os.path.getsize(small)
        except Exception:
            pass  # fall back to the original; the send may still work

    # Assemble MIME: text body (captions) + the mp4 attachment.
    root = MIMEMultipart("mixed")
    root["Subject"] = subject
    root["To"] = to
    if sender:
        root["From"] = sender
    root.attach(MIMEText(body_text(title, meta), "plain", "utf-8"))

    with open(video_path, "rb") as f:
        part = MIMEBase("video", "mp4")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename="video.mp4")
    root.attach(part)

    try:
        creds = load_credentials(token_path)
    except Exception as e:
        fail(f"Could not load/refresh Gmail credentials: {e}")
        return

    from googleapiclient.discovery import build

    socket.setdefaulttimeout(300)   # large attachments need more than the ~60s default write window
    service = build("gmail", "v1", credentials=creds)
    raw = base64.urlsafe_b64encode(root.as_bytes()).decode("utf-8")
    try:
        sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    except Exception as e:
        hint = " (video may exceed Gmail's 25 MB limit; re-encode smaller)" if size > GMAIL_LIMIT else ""
        fail(f"Gmail send failed: {e}{hint}", size_bytes=size)
        return

    emit({"status": "sent", "message_id": sent.get("id"), "to": to,
          "size_bytes": size, "over_gmail_limit": size > GMAIL_LIMIT})


if __name__ == "__main__":
    main()
