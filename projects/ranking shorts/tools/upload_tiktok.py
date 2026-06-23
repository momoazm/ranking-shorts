"""Publish a finished Short to TikTok via the Content Posting API (Direct Post, FILE_UPLOAD).

SAFETY GATE: like upload_youtube.py, this refuses to publish without --confirm (dry-run preview
otherwise) — and it is one of the irreversible steps.

AUTH: needs a user access token with the `video.publish` scope in TIKTOK_ACCESS_TOKEN. If
TIKTOK_REFRESH_TOKEN + TIKTOK_CLIENT_KEY + TIKTOK_CLIENT_SECRET are set, an expired access token
is refreshed automatically. Obtaining these requires a TikTok developer app approved for the
Content Posting API (manual review, ~2-6 weeks).

IMPORTANT (the audit gotcha): until your app passes TikTok's content audit, ALL posts are forced
to private regardless of the requested privacy. So this defaults --privacy to SELF_ONLY; switch to
PUBLIC_TO_EVERYONE only once your app is audited.

Flow: POST .../publish/video/init/ (reserve + get upload_url) -> PUT the mp4 bytes (single chunk;
our Shorts are well under 64MB) -> poll .../publish/status/fetch/ until done.

Usage:
    python tools/upload_tiktok.py --video .tmp/final.mp4 --title "..." [--privacy SELF_ONLY] [--confirm]

Prints JSON: dry run -> {"status":"preview",...}; real -> {"status":"uploaded","publish_id",...}.
"""
import argparse
import os
import time

from _common import load_env, emit, fail

API = "https://open.tiktokapis.com/v2"
PRIVACY = ["SELF_ONLY", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "PUBLIC_TO_EVERYONE"]


def get_access_token():
    """Return a usable access token, refreshing via the refresh token if creds allow."""
    import httpx

    token = os.environ.get("TIKTOK_ACCESS_TOKEN", "").strip()
    refresh = os.environ.get("TIKTOK_REFRESH_TOKEN", "").strip()
    client_key = os.environ.get("TIKTOK_CLIENT_KEY", "").strip()
    client_secret = os.environ.get("TIKTOK_CLIENT_SECRET", "").strip()
    if refresh and client_key and client_secret:
        try:
            resp = httpx.post(
                f"{API}/oauth/token/",
                data={"client_key": client_key, "client_secret": client_secret,
                      "grant_type": "refresh_token", "refresh_token": refresh},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30,
            )
            resp.raise_for_status()
            new = resp.json().get("access_token")
            if new:
                return new
        except Exception:
            pass  # fall back to the static token below
    return token


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--title", required=True, help="Caption/title (include hashtags here)")
    parser.add_argument("--privacy", default="SELF_ONLY", choices=PRIVACY)
    parser.add_argument("--confirm", action="store_true", help="Required to actually publish.")
    parser.add_argument("--poll-timeout", type=int, default=120)
    args = parser.parse_args()

    load_env()
    if not os.path.isfile(args.video):
        fail(f"Video not found: {args.video}")
        return
    token = get_access_token()
    if not token:
        fail("No TIKTOK_ACCESS_TOKEN (and no refresh creds) in API.env. "
             "TikTok app must be approved for the Content Posting API (video.publish).")
        return

    size = os.path.getsize(args.video)

    if not args.confirm:
        emit({
            "status": "preview", "would_upload": True, "platform": "tiktok",
            "title": args.title, "privacy": args.privacy,
            "video": args.video, "size_bytes": size,
            "note": "DRY RUN. Re-run with --confirm to publish. Unaudited apps post privately.",
        })
        return

    import httpx

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    # 1) init: reserve the post + get an upload URL (single chunk = whole file).
    init_body = {
        "post_info": {"title": args.title, "privacy_level": args.privacy,
                      "disable_comment": False, "disable_duet": False, "disable_stitch": False},
        "source_info": {"source": "FILE_UPLOAD", "video_size": size,
                        "chunk_size": size, "total_chunk_count": 1},
    }
    try:
        r = httpx.post(f"{API}/post/publish/video/init/", headers=headers, json=init_body, timeout=60)
        r.raise_for_status()
        data = r.json().get("data", {})
        publish_id, upload_url = data.get("publish_id"), data.get("upload_url")
        if not publish_id or not upload_url:
            fail(f"TikTok init returned no upload URL: {r.json()}")
            return
    except Exception as e:
        fail(f"TikTok init failed: {e}")
        return

    # 2) upload the bytes.
    try:
        with open(args.video, "rb") as f:
            put = httpx.put(
                upload_url, content=f.read(),
                headers={"Content-Type": "video/mp4",
                         "Content-Range": f"bytes 0-{size - 1}/{size}"},
                timeout=300,
            )
        put.raise_for_status()
    except Exception as e:
        fail(f"TikTok byte upload failed: {e}", publish_id=publish_id)
        return

    # 3) poll publish status.
    status, deadline = None, time.time() + args.poll_timeout
    while time.time() < deadline:
        try:
            s = httpx.post(f"{API}/post/publish/status/fetch/", headers=headers,
                           json={"publish_id": publish_id}, timeout=30)
            s.raise_for_status()
            status = s.json().get("data", {}).get("status")
            if status in ("PUBLISH_COMPLETE", "FAILED"):
                break
        except Exception:
            pass
        time.sleep(5)

    emit({
        "status": "uploaded" if status == "PUBLISH_COMPLETE" else "processing",
        "platform": "tiktok", "publish_id": publish_id,
        "tiktok_status": status, "privacy": args.privacy,
    })


if __name__ == "__main__":
    main()
