"""Publish a finished Short to Instagram via Zernio social media integration platform.

Zernio is an external API that connects workflows to social media platforms, allowing automated
posting to Instagram, TikTok, and other social platforms without directly managing each platform's
complex authentication.

AUTH/SETUP:
  * ZERNIO_API_KEY: Your Zernio API key (obtain from Zernio dashboard)
  * ZERNIO_API_URL: Your Zernio API endpoint (typically https://api.zernio.com/v1 or similar)
  * The video must be hosted at a PUBLIC url (use host_public.py to get one)

Flow: POST to Zernio API with video URL + caption -> Zernio handles Instagram authentication
and posting -> returns post_id on success.

SAFETY GATE: refuses to publish without --confirm (dry-run preview otherwise). Irreversible.

Usage:
    python tools/upload_zernio.py --video-url https://... --caption "..." \\
        --api-key YOUR_KEY --api-url https://api.zernio.com/v1 [--confirm]

Prints JSON: dry run -> {"status":"preview",...}; real -> {"status":"uploaded","post_id",...}.
"""
import argparse
import json
import os
import time

from _common import load_env, emit, fail


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-url", required=True, help="PUBLIC https url to the mp4 (host_public.py)")
    parser.add_argument("--caption", default="", help="Caption incl. hashtags")
    parser.add_argument("--api-key", required=True, help="Zernio API key")
    parser.add_argument("--api-url", required=True, help="Zernio API endpoint")
    parser.add_argument("--confirm", action="store_true", help="Required to actually publish.")
    parser.add_argument("--poll-timeout", type=int, default=180)
    args = parser.parse_args()

    load_env()
    
    api_key = args.api_key.strip()
    api_url = args.api_url.strip().rstrip("/")
    
    if not api_key or not api_url:
        fail("--api-key and --api-url are required. Ensure ZERNIO_API_KEY and ZERNIO_API_URL "
             "are set in API.env or passed as arguments.")
        return

    if not args.confirm:
        emit({
            "status": "preview",
            "would_upload": True,
            "platform": "instagram_via_zernio",
            "api_url": api_url,
            "video_url": args.video_url,
            "caption": args.caption,
            "note": "DRY RUN. Re-run with --confirm to publish via Zernio.",
        })
        return

    import httpx

    # Post to Zernio API to publish to Instagram
    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "platform": "instagram",
            "content": {
                "type": "video",
                "video_url": args.video_url,
                "caption": args.caption,
                "media_type": "reel"  # Instagram Reels format
            }
        }
        
        response = httpx.post(
            f"{api_url}/publish",
            json=payload,
            headers=headers,
            timeout=60
        )
        
        response.raise_for_status()
        result = response.json()
        
        post_id = result.get("id") or result.get("post_id") or result.get("media_id")
        if not post_id:
            fail(f"Zernio publish returned no post id: {result}")
            return
            
        emit({
            "status": "uploaded",
            "platform": "instagram_via_zernio",
            "post_id": post_id,
            "zernio_response": result
        })
        
    except httpx.HTTPStatusError as e:
        try:
            error_detail = e.response.json()
        except:
            error_detail = str(e)
        fail(f"Zernio API error ({e.response.status_code}): {error_detail}")
        return
    except Exception as e:
        fail(f"Zernio publish failed: {e}")
        return


if __name__ == "__main__":
    main()
