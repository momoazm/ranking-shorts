"""Pull YouTube Analytics (retention, watch time, CTR, subs, traffic) for the last N days.

Read-only. Uses the YouTube Analytics API v2 -- needs the yt-analytics.readonly scope AND the
YouTube Analytics API enabled in the channel's Cloud project. Degrades gracefully: each report
runs independently, and any unsupported metric/dimension (some vary for Shorts) is recorded
under "errors" instead of aborting the whole run.

Usage:
    python tools/yt_fetch_analytics.py --token token.json --days 7 --out .tmp/analytics_momo.json

Prints JSON: {"window":{...}, "totals":{...}, "per_video":[...], "traffic_sources":[...], "errors":[...]}
"""
import argparse
import datetime as dt
import os

from _common import emit, fail

CORE_METRICS = (
    "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,"
    "subscribersGained,subscribersLost,likes,comments,shares"
)


def load_creds(token_path):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_file(token_path)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    return creds


def rows_to_dicts(resp):
    if not resp:
        return []
    cols = [h["name"] for h in resp.get("columnHeaders", [])]
    return [dict(zip(cols, row)) for row in resp.get("rows", [])]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--token", required=True, help="Path to this channel's OAuth token.json")
    p.add_argument("--days", type=int, default=7)
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

    ya = build("youtubeAnalytics", "v2", credentials=creds)

    end = dt.date.today()
    start = end - dt.timedelta(days=args.days)
    s, e = start.isoformat(), end.isoformat()
    errors = []

    def query(label, **kw):
        try:
            return ya.reports().query(ids="channel==MINE", startDate=s, endDate=e, **kw).execute()
        except Exception as ex:
            errors.append({"report": label, "error": str(ex)})
            return None

    totals_resp = query("totals", metrics=CORE_METRICS)
    totals = rows_to_dicts(totals_resp)[0] if rows_to_dicts(totals_resp) else {}

    # Impressions + CTR are a separate metric family and aren't always available for Shorts;
    # fetch them on their own so a failure here doesn't lose the core totals.
    imp_resp = query("impressions", metrics="impressions,impressionsClickThroughRate")
    imp = rows_to_dicts(imp_resp)
    if imp:
        totals.update(imp[0])

    per_video_resp = query("per_video", dimensions="video", metrics=CORE_METRICS, sort="-views", maxResults=50)
    per_video = rows_to_dicts(per_video_resp)

    traffic_resp = query(
        "traffic_sources", dimensions="insightTrafficSourceType",
        metrics="views,estimatedMinutesWatched", sort="-views",
    )
    traffic = rows_to_dicts(traffic_resp)

    emit({
        "window": {"days": args.days, "startDate": s, "endDate": e},
        "totals": totals,
        "per_video": per_video,
        "traffic_sources": traffic,
        "errors": errors,
    })


if __name__ == "__main__":
    main()
