"""Fetch top comment threads for a set of videos (read-only).

Given an OAuth token and a list of video IDs, pulls the most-relevant top-level comments per
video so the weekly-roundup skill can theme them and read sentiment. Handles
comments-disabled videos gracefully (recorded under "errors", empty list returned).

Usage:
    python tools/yt_fetch_comments.py --token token.json --video-ids ID1,ID2 --max 20 --out .tmp/comments_momo.json

Prints JSON: {"per_video": {videoId: [ {author,text,likeCount,publishedAt} ]}, "total": N, "errors": [...]}
"""
import argparse
import os

from _common import emit, fail


def load_creds(token_path):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_file(token_path)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    return creds


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--token", required=True, help="Path to this channel's OAuth token.json")
    p.add_argument("--video-ids", required=True, help="Comma-separated video IDs")
    p.add_argument("--max", type=int, default=20, help="Top comments per video (<=100)")
    p.add_argument("--out", required=True)
    args = p.parse_args()

    if not os.path.isfile(args.token):
        fail(f"Token not found: {args.token}. Run youtube_auth_setup.py for this channel first.")
        return
    try:
        creds = load_creds(args.token)
    except Exception as e:
        fail(f"Could not load/refresh credentials from {args.token}: {e}")
        return

    from googleapiclient.discovery import build

    yt = build("youtube", "v3", credentials=creds)

    ids = [v.strip() for v in args.video_ids.split(",") if v.strip()]
    per_video, errors, total = {}, [], 0
    for vid in ids:
        try:
            resp = yt.commentThreads().list(
                part="snippet", videoId=vid, order="relevance",
                maxResults=min(args.max, 100), textFormat="plainText",
            ).execute()
        except Exception as ex:
            errors.append({"videoId": vid, "error": str(ex)})  # e.g. comments disabled (403)
            per_video[vid] = []
            continue
        comments = []
        for it in resp.get("items", []):
            top = it["snippet"]["topLevelComment"]["snippet"]
            comments.append({
                "author": top.get("authorDisplayName"),
                "text": top.get("textDisplay"),
                "likeCount": top.get("likeCount", 0),
                "publishedAt": top.get("publishedAt"),
            })
        per_video[vid] = comments
        total += len(comments)

    emit({"per_video": per_video, "total": total, "errors": errors})


if __name__ == "__main__":
    main()
