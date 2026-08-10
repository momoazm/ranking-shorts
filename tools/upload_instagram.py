"""Publish a finished Short to Instagram as a Reel -- via Zernio (zernio.com), not Meta's Graph
API directly.

Why Zernio instead of our own Meta app: posting through your OWN Facebook App requires either
(a) Advanced Access via Meta App Review + Business Verification (real registered-business
documents), or (b) staying in Development Mode with the posting account added as an App
Tester/Admin -- and even then a System User token (Business Manager construct) still hits the same
Advanced Access wall. Zernio already completed App Review and Business Verification under THEIR
app; you authorize via a normal "Continue with Facebook" OAuth consent screen on zernio.com, and
Zernio's API takes it from there. Free tier covers this project's volume (first 2 connected
accounts, unlimited posts).

SAFETY GATE: refuses to publish without --confirm (dry-run preview otherwise). Irreversible.

AUTH/SETUP:
  * ZERNIO_API_KEY in API.env (the GitHub secret name already wired into this repo's workflow).
  * ZERNIO_INSTAGRAM_ID -- the Zernio-internal id for the connected Instagram account (NOT the
    same as a Meta IG user id; fetched once via GET /v1/accounts after connecting in Zernio's
    dashboard).

Instagram still fetches the video from a PUBLIC url (Zernio just proxies the same Graph API
container-create/poll/publish flow under the hood) -- pass --video-url (host_public.py).

Usage:
    python tools/upload_instagram.py --video-url https://... --caption "..." [--confirm]

Prints JSON: dry run -> {"status":"preview",...}; real -> {"status":"uploaded","post_id",...}.
"""
import argparse
import json
import os
import time

from _common import load_env, emit, fail, zernio_create_post, zernio_retry_post

ZERNIO_API = "https://zernio.com/api/v1"


def _platform_entry(post):
    for entry in (post or {}).get("platforms", []):
        if entry.get("platform") == "instagram":
            return entry
    return {}


def _platform_detail(entry):
    """Keep provider diagnostics useful without dumping unrelated account metadata."""
    details = {key: entry.get(key) for key in ("error", "code", "message", "platformError")
               if entry.get(key) not in (None, "", {})}
    if not details:
        return "provider returned no Instagram error detail"
    return json.dumps(details, ensure_ascii=True, separators=(",", ":"))[:600]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-url", required=True, help="PUBLIC https url to the mp4 (host_public.py)")
    parser.add_argument("--caption", default="", help="Caption incl. hashtags")
    parser.add_argument("--confirm", action="store_true", help="Required to actually publish.")
    parser.add_argument("--poll-timeout", type=int, default=180)
    args = parser.parse_args()

    load_env()
    api_key = os.environ.get("ZERNIO_API_KEY", "").strip()
    account_id = os.environ.get("ZERNIO_INSTAGRAM_ID", "").strip()
    if not api_key:
        fail("ZERNIO_API_KEY not set in API.env. Sign up free at zernio.com and grab it from "
             "Settings -> API Keys.")
        return
    if not account_id:
        fail("ZERNIO_INSTAGRAM_ID not set in API.env. After connecting the Instagram account "
             "in Zernio's dashboard, fetch it via GET /v1/accounts.")
        return

    payload = {
        "content": args.caption,
        "mediaItems": [{"type": "video", "url": args.video_url}],
        "platforms": [{
            "platform": "instagram",
            "accountId": account_id,
            "platformSpecificData": {"contentType": "reels", "shareToFeed": True},
        }],
        "publishNow": True,
    }

    if not args.confirm:
        emit({
            "status": "preview", "would_upload": True, "platform": "instagram",
            "via": "zernio", "account_id": account_id,
            "video_url": args.video_url, "caption": args.caption,
            "note": "DRY RUN. Re-run with --confirm to publish.",
        })
        return

    import httpx

    post, cerr = zernio_create_post(f"{ZERNIO_API}/posts", payload, api_key)
    if cerr:
        fail(cerr)
        return

    post_id = post.get("_id")
    if not post_id:
        fail(f"Zernio post create returned no post id: {post}")
        return

    entry = _platform_entry(post)
    status = entry.get("status") or post.get("status")

    poll_error = None
    retry_attempted = False
    retry_error = None

    def poll_until_terminal():
        nonlocal post, entry, status, poll_error
        deadline = time.time() + args.poll_timeout
        while status not in ("published", "failed", "error", "partial") and time.time() < deadline:
            time.sleep(5)
            try:
                s = httpx.get(f"{ZERNIO_API}/posts/{post_id}",
                              headers={"Authorization": f"Bearer {api_key}"}, timeout=30)
                s.raise_for_status()
                body = s.json()
                post = body.get("post", post) if isinstance(body, dict) else post
                entry = _platform_entry(post)
                status = entry.get("status") or post.get("status")
            except Exception as exc:
                poll_error = str(exc)

    poll_until_terminal()

    # Zernio retries only failed platforms. Use its supported retry endpoint once instead of
    # creating a second post or silently giving up after a transient Instagram processing error.
    if status in ("failed", "error", "partial"):
        retry_attempted = True
        retried, retry_error = zernio_retry_post(ZERNIO_API, post_id, api_key)
        if retried:
            post = retried
            entry = _platform_entry(post)
            status = entry.get("status") or post.get("status")
            poll_until_terminal()

    if status not in ("published",):
        detail = f"Zernio publish did not complete (status={status}; {_platform_detail(entry)})."
        if retry_error:
            detail += f" Retry attempt: {retry_error}"
        fail(detail, post_id=post_id, platform_status=entry,
             retry_attempted=retry_attempted, poll_error=poll_error,
             ambiguous=status not in ("failed", "error", "partial"))
        return

    emit({"status": "uploaded", "platform": "instagram", "via": "zernio",
          "post_id": post_id, "media_url": entry.get("platformPostUrl")})


if __name__ == "__main__":
    main()
