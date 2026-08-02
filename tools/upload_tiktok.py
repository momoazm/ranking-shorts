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

Flow: POST .../publish/video/init/ (reserve + get upload_url) -> PUT the mp4 bytes in retryable
chunks -> poll .../publish/status/fetch/ until done. A timed-out status is reported as an
ambiguous failure, never as a successful upload, so callers do not consume their no-repeat
source state on an unconfirmed post.

Usage:
    python tools/upload_tiktok.py --video .tmp/final.mp4 --title "..." [--privacy SELF_ONLY] [--confirm]

Prints JSON: dry run -> {"status":"preview",...}; real -> {"status":"uploaded","publish_id",...}.
"""
import argparse
import math
import os
import time

from _common import load_env, emit, fail

API = "https://open.tiktokapis.com/v2"
PRIVACY = ["SELF_ONLY", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "PUBLIC_TO_EVERYONE"]
MAX_CHUNK_BYTES = 64 * 1024 * 1024


def _retry_delay(attempt, response=None):
    """Bounded exponential delay, honoring TikTok's Retry-After when it is usable."""
    if response is not None:
        value = (response.headers.get("Retry-After") or "").strip()
        if value.isdigit():
            return min(60, max(1, int(value)))
    return min(30, 2 ** attempt)


def _response_error(response):
    """Return a short API error without echoing credentials or the upload URL."""
    try:
        data = response.json()
        error = data.get("error") if isinstance(data, dict) else None
        if isinstance(error, dict):
            code = error.get("code") or "api_error"
            message = error.get("message") or ""
            return f"{code}: {message}".strip(": ")
        if isinstance(data, dict) and data.get("message"):
            return str(data["message"])
    except Exception:
        pass
    return response.text[:240].strip()


def get_access_token():
    """Return a usable access token, refreshing via the refresh token if creds allow."""
    import httpx

    token = os.environ.get("TIKTOK_ACCESS_TOKEN", "").strip()
    refresh = os.environ.get("TIKTOK_REFRESH_TOKEN", "").strip()
    client_key = os.environ.get("TIKTOK_CLIENT_KEY", "").strip()
    client_secret = os.environ.get("TIKTOK_CLIENT_SECRET", "").strip()
    refresh_error = None
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
            payload = resp.json()
            new = payload.get("access_token")
            if new:
                return new
            refresh_error = "refresh response did not contain an access token"
        except Exception as exc:
            refresh_error = str(exc)
    # Keep the static token fallback for local/manual runs. The caller emits a precise missing
    # credential error when neither route is available; refresh failures never expose secrets.
    return token


def put_chunk(client, upload_url, data, start, total):
    """Upload one FILE_UPLOAD chunk with bounded retries."""
    end = start + len(data) - 1
    headers = {
        "Content-Type": "video/mp4",
        "Content-Length": str(len(data)),
        "Content-Range": f"bytes {start}-{end}/{total}",
    }
    last = None
    for attempt in range(4):
        try:
            response = client.put(upload_url, content=data, headers=headers, timeout=300)
            if 200 <= response.status_code < 300:
                return
            last = f"HTTP {response.status_code}: {_response_error(response)}"
            retryable = response.status_code == 429 or response.status_code >= 500
            if not retryable or attempt == 3:
                raise RuntimeError(last)
            time.sleep(_retry_delay(attempt, response))
        except RuntimeError:
            raise
        except Exception as exc:
            last = str(exc)
            if attempt == 3:
                raise RuntimeError(last) from exc
            time.sleep(_retry_delay(attempt))
    raise RuntimeError(last or "unknown TikTok chunk upload error")


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
    if size <= 0:
        fail("TikTok video is empty.")
        return

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
    # 1) init: reserve the post + get an upload URL. TikTok caps a FILE_UPLOAD chunk at 64 MiB;
    # using a bounded count also keeps the workflow from reading a large MP4 into RAM.
    chunk_size = min(MAX_CHUNK_BYTES, size)
    total_chunks = max(1, math.ceil(size / chunk_size))
    init_body = {
        "post_info": {"title": args.title[:2200], "privacy_level": args.privacy,
                      "disable_comment": False, "disable_duet": False, "disable_stitch": False},
        "source_info": {"source": "FILE_UPLOAD", "video_size": size,
                        "chunk_size": chunk_size, "total_chunk_count": total_chunks},
    }
    publish_id = upload_url = None
    last_init = None
    with httpx.Client() as client:
        for attempt in range(4):
            try:
                r = client.post(f"{API}/post/publish/video/init/", headers=headers,
                                json=init_body, timeout=60)
                if r.status_code == 429 or r.status_code >= 500:
                    last_init = f"HTTP {r.status_code}: {_response_error(r)}"
                    if attempt < 3:
                        time.sleep(_retry_delay(attempt, r))
                        continue
                r.raise_for_status()
                body = r.json()
                data = body.get("data", {}) if isinstance(body, dict) else {}
                publish_id, upload_url = data.get("publish_id"), data.get("upload_url")
                if not publish_id or not upload_url:
                    last_init = _response_error(r) or f"unexpected response: {body}"
                    if attempt < 3:
                        time.sleep(_retry_delay(attempt))
                        continue
                    break
                break
            except Exception as exc:
                last_init = str(exc)
                if attempt < 3:
                    time.sleep(_retry_delay(attempt))
        if not publish_id or not upload_url:
            fail(f"TikTok init failed after retries: {last_init or 'no upload URL'}")
            return

        # 2) upload the bytes without loading the full MP4 into memory. FILE_UPLOAD uses an
        # inclusive byte range, so the final chunk ends at size-1.
        try:
            with open(args.video, "rb") as f:
                offset = 0
                while offset < size:
                    data = f.read(min(chunk_size, size - offset))
                    if not data:
                        raise RuntimeError(f"unexpected EOF at byte {offset} of {size}")
                    put_chunk(client, upload_url, data, offset, size)
                    offset += len(data)
        except Exception as exc:
            fail(f"TikTok byte upload failed: {exc}", publish_id=publish_id)
            return

        # 3) poll publish status. A timeout is not success: TikTok may still finish in the
        # background, so callers must treat it as ambiguous and avoid an automatic duplicate.
        status, deadline, poll_error = None, time.time() + args.poll_timeout, None
        while time.time() < deadline:
            try:
                s = client.post(f"{API}/post/publish/status/fetch/", headers=headers,
                                json={"publish_id": publish_id}, timeout=30)
                s.raise_for_status()
                body = s.json()
                status = (body.get("data", {}) or {}).get("status")
                if status in ("PUBLISH_COMPLETE", "FAILED"):
                    break
                poll_error = None
            except Exception as exc:
                poll_error = str(exc)
            time.sleep(5)

        if status == "PUBLISH_COMPLETE":
            emit({
                "status": "uploaded", "platform": "tiktok", "publish_id": publish_id,
                "tiktok_status": status, "privacy": args.privacy,
            })
        elif status == "FAILED":
            fail("TikTok rejected the video during processing.", publish_id=publish_id,
                 tiktok_status=status)
        else:
            fail("TikTok publish status timed out; the post may still be processing. "
                 "Do not immediately retry with the same video.", publish_id=publish_id,
                 tiktok_status=status, poll_error=poll_error, ambiguous=True)


if __name__ == "__main__":
    main()
