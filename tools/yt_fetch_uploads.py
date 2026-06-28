"""Fetch a channel's uploads from the last N days + their Data API statistics.

Read-only. Given an OAuth token.json (with youtube.readonly), lists the videos the
authenticated channel published within the window and pulls views/likes/comment-count for
each, plus channel-level totals. Feeds the weekly-roundup skill.

Pass --token explicitly so the same script runs against any channel's token (MOMO Shorts'
token.json here, or ../clipping-auto/token.json for the clipping channel).

Usage:
    python tools/yt_fetch_uploads.py --token token.json --days 7 --out .tmp/uploads_momo.json

Prints JSON: {"channel": {...}, "window": {...}, "videos": [ {...} ]}
"""
import argparse
import datetime as dt
import os
import re

from _common import emit, fail


def load_creds(token_path):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    # scopes=None -> use whatever the token was granted (robust across channels/scope sets).
    creds = Credentials.from_authorized_user_file(token_path)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    return creds


def parse_duration(iso):
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return None
    h, mn, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mn * 60 + s


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--token", required=True, help="Path to this channel's OAuth token.json")
    p.add_argument("--days", type=int, default=7, help="Look-back window in days")
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

    try:
        ch = yt.channels().list(part="snippet,contentDetails,statistics", mine=True).execute()
    except Exception as e:
        fail(f"channels().list failed: {e}")
        return
    items = ch.get("items", [])
    if not items:
        fail("No channel found for this token.")
        return
    c = items[0]
    uploads_playlist = c["contentDetails"]["relatedPlaylists"]["uploads"]
    channel = {
        "id": c["id"],
        "title": c["snippet"]["title"],
        "subscriberCount": c["statistics"].get("subscriberCount"),
        "viewCount": c["statistics"].get("viewCount"),
        "videoCount": c["statistics"].get("videoCount"),
    }

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.days)
    recent_ids, page, stop = [], None, False
    while not stop:
        pl = yt.playlistItems().list(
            part="contentDetails", playlistId=uploads_playlist, maxResults=50, pageToken=page
        ).execute()
        for it in pl.get("items", []):
            published = it["contentDetails"].get("videoPublishedAt")
            if not published:
                continue
            ts = dt.datetime.strptime(published, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
            if ts >= cutoff:
                recent_ids.append(it["contentDetails"]["videoId"])
            else:
                stop = True  # uploads come newest-first; once we pass the window we can stop
        page = pl.get("nextPageToken")
        if not page:
            break

    videos = []
    for i in range(0, len(recent_ids), 50):
        batch = recent_ids[i:i + 50]
        vr = yt.videos().list(part="snippet,statistics,contentDetails", id=",".join(batch)).execute()
        for v in vr.get("items", []):
            st = v.get("statistics", {})
            sn = v["snippet"]
            dur = parse_duration(v.get("contentDetails", {}).get("duration"))
            videos.append({
                "id": v["id"],
                "title": sn["title"],
                "publishedAt": sn["publishedAt"],
                "url": f"https://youtube.com/watch?v={v['id']}",
                "duration_sec": dur,
                "is_short": dur is not None and dur <= 60,
                "thumbnail": sn.get("thumbnails", {}).get("medium", {}).get("url"),
                "views": int(st.get("viewCount", 0)),
                "likes": int(st["likeCount"]) if "likeCount" in st else None,
                "comments": int(st["commentCount"]) if "commentCount" in st else None,
            })
    videos.sort(key=lambda x: x["views"], reverse=True)

    emit({
        "channel": channel,
        "window": {
            "days": args.days,
            "since": cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "video_count": len(videos),
        },
        "videos": videos,
    })


if __name__ == "__main__":
    main()
