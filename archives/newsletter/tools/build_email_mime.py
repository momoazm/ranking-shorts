"""Assemble the final MIME email: HTML body + inline CID-attached images + file attachments.

Kept separate from sending so the exact bytes that would be sent can be inspected
(as a .eml file) at the human-confirmation gate before anything irreversible happens.

Usage:
    python tools/build_email_mime.py --html .tmp/newsletter.html --subject "..." --to someone@example.com \\
        --images '[{"cid":"logo","path":"brand/logo.png"},{"cid":"chart1","path":".tmp/chart1.png"}]' \\
        --attachments '[{"path":".tmp/newsletter.pdf","filename":"newsletter.pdf"}]' \\
        --out .tmp/newsletter.eml

Prints JSON: {"path": "<out>", "to": ..., "subject": ..., "image_count": N, "attachment_count": N}
"""
import argparse
import json
import os
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from _common import emit, fail


def build_message(html, subject, sender, to, images, attachments):
    root = MIMEMultipart("mixed")
    root["Subject"] = subject
    if sender:
        root["From"] = sender
    root["To"] = to

    related = MIMEMultipart("related")
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(html, "html", "utf-8"))
    related.attach(alt)

    for image in images:
        with open(image["path"], "rb") as f:
            mime_img = MIMEImage(f.read())
        mime_img.add_header("Content-ID", f"<{image['cid']}>")
        mime_img.add_header("Content-Disposition", "inline", filename=os.path.basename(image["path"]))
        related.attach(mime_img)

    root.attach(related)

    for attachment in attachments:
        with open(attachment["path"], "rb") as f:
            data = f.read()
        filename = attachment.get("filename") or os.path.basename(attachment["path"])
        mime_att = MIMEApplication(data, _subtype=attachment.get("subtype", "octet-stream"))
        mime_att.add_header("Content-Disposition", "attachment", filename=filename)
        root.attach(mime_att)

    return root


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", required=True, help="Path to rendered HTML file")
    parser.add_argument("--subject", required=True)
    parser.add_argument("--to", required=True)
    parser.add_argument("--sender", default=None, help="From address; defaults to GMAIL_SENDER_EMAIL at send time")
    parser.add_argument("--images", default="[]", help='JSON list of {"cid": "...", "path": "..."}')
    parser.add_argument("--attachments", default="[]", help='JSON list of {"path": "...", "filename": "..." (optional)}')
    parser.add_argument("--out", required=True, help="Output .eml path")
    args = parser.parse_args()

    try:
        with open(args.html, "r", encoding="utf-8") as f:
            html = f.read()
    except OSError as e:
        fail(f"Could not read --html: {e}")
        return

    try:
        images = json.loads(args.images)
    except json.JSONDecodeError as e:
        fail(f"Invalid --images JSON: {e}")
        return

    try:
        attachments = json.loads(args.attachments)
    except json.JSONDecodeError as e:
        fail(f"Invalid --attachments JSON: {e}")
        return

    for image in images:
        if not os.path.isfile(image["path"]):
            fail(f"Image file not found: {image['path']} (cid: {image['cid']})")
            return

    for attachment in attachments:
        if not os.path.isfile(attachment["path"]):
            fail(f"Attachment file not found: {attachment['path']}")
            return

    msg = build_message(html, args.subject, args.sender, args.to, images, attachments)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "wb") as f:
        f.write(msg.as_bytes())

    emit({
        "path": args.out, "to": args.to, "subject": args.subject,
        "image_count": len(images), "attachment_count": len(attachments),
    })


if __name__ == "__main__":
    main()
