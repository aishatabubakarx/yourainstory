"""Upload to YouTube with the Data API (resumable), set thumbnail, optional playlist."""
from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path


SCOPES = ["https://www.googleapis.com/auth/youtube", "https://www.googleapis.com/auth/youtube.upload"]


def _service():
    import google_auth_httplib2
    import httplib2
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    names = ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN")
    # .strip() removes the stray space or newline that often comes with pasting a secret
    cid, secret, refresh = ((os.environ.get(k) or "").strip() for k in names)
    missing = [k for k, v in zip(names, (cid, secret, refresh)) if not v]
    if missing:
        raise SystemExit("Missing GitHub secret(s): " + ", ".join(missing) + " (see README step 3)")
    creds = Credentials(None, refresh_token=refresh, token_uri="https://oauth2.googleapis.com/token",
                        client_id=cid, client_secret=secret, scopes=SCOPES)
    # default timeout is 60s, too short for a big upload chunk on a slow moment
    http = google_auth_httplib2.AuthorizedHttp(creds, http=httplib2.Http(timeout=600))
    return build("youtube", "v3", http=http, cache_discovery=False)


def check_auth():
    """Fast login test. Run BEFORE a multi-hour render so a bad secret fails in seconds."""
    from google.auth.transport.requests import Request
    from google.auth.exceptions import RefreshError
    from google.oauth2.credentials import Credentials
    import requests

    names = ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN")
    cid, secret, refresh = ((os.environ.get(k) or "").strip() for k in names)
    missing = [k for k, v in zip(names, (cid, secret, refresh)) if not v]
    if missing:
        raise SystemExit("Missing GitHub secret(s): " + ", ".join(missing))
    creds = Credentials(None, refresh_token=refresh, token_uri="https://oauth2.googleapis.com/token",
                        client_id=cid, client_secret=secret, scopes=SCOPES)
    try:
        creds.refresh(Request())
    except RefreshError as e:
        raise SystemExit(
            f"YouTube login FAILED: {e}\n"
            "Usual causes: the three secrets are not from the SAME client (re-run connect.py and paste all three "
            "again), the consent screen is still on 'Testing' (token expires after 7 days; click Publish app), "
            "or access was removed at myaccount.google.com/permissions.")
    granted = set(requests.get("https://oauth2.googleapis.com/tokeninfo", params={"access_token": creds.token},
                               timeout=30).json().get("scope", "").split())
    lacking = [x for x in SCOPES if x not in granted]
    if lacking:
        raise SystemExit("YouTube login works but these permissions are missing: " + ", ".join(lacking))
    yt = _service()
    items = yt.channels().list(part="snippet", mine=True).execute().get("items", [])
    if not items:
        raise SystemExit("Signed in, but this Google account has no YouTube channel.")
    print(f"YouTube login OK. Channel: {items[0]['snippet']['title']}. Permissions OK.")


def _insert(yt, body, video: Path):
    import socket
    import ssl

    import httplib2
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    media = MediaFileUpload(str(video), chunksize=32 * 1024 * 1024, resumable=True, mimetype="video/mp4")
    notify = body.pop("_notify", False)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media, notifySubscribers=notify)
    resp, retry = None, 0
    net_errors = (ConnectionError, TimeoutError, socket.timeout, socket.gaierror, ssl.SSLError,
                  httplib2.HttpLib2Error, OSError)
    while resp is None:
        try:
            status, resp = req.next_chunk()
            retry = 0  # a chunk went through, so the connection is healthy again
            if status:
                print(f"  uploaded {int(status.progress() * 100)}%", flush=True)
        except HttpError as e:
            if e.resp.status in (500, 502, 503, 504) and retry < 12:
                retry += 1
                wait = min(120, 2 ** retry + random.random())
                print(f"  server error {e.resp.status}, retrying in {wait:.0f}s", flush=True)
                time.sleep(wait)
            else:
                raise
        except net_errors as e:
            if retry >= 12:
                raise
            retry += 1
            wait = min(120, 2 ** retry + random.random())
            print(f"  network hiccup ({type(e).__name__}), retrying in {wait:.0f}s", flush=True)
            time.sleep(wait)
    return resp


def upload(meta: dict, video: Path, thumbnail: Path, result_path: Path) -> dict:
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    yt = _service()
    status = {
        "privacyStatus": meta["privacy"],
        "selfDeclaredMadeForKids": bool(meta["made_for_kids"]),
        "embeddable": bool(meta["embeddable"]),
        "publicStatsViewable": bool(meta["public_stats_viewable"]),
        "license": meta["license"],
        "containsSyntheticMedia": bool(meta["contains_synthetic_media"]),
    }
    if meta.get("publish_at"):
        status["privacyStatus"] = "private"       # YouTube requires private + publishAt for scheduling
        status["publishAt"] = meta["publish_at"]
    body = {
        "snippet": {"title": meta["title"], "description": meta["description"], "tags": meta["tags"],
                    "categoryId": meta["category_id"], "defaultLanguage": meta["language"],
                    "defaultAudioLanguage": meta["language"]},
        "status": status,
        "_notify": bool(meta.get("notify_subscribers")),
    }
    try:
        resp = _insert(yt, dict(body, status=dict(status)), video)
    except HttpError as e:
        if "publishAt" in status and e.resp.status == 400:
            print("YouTube rejected the schedule; uploading as private without it (you can schedule it in Studio).")
            status.pop("publishAt")
            resp = _insert(yt, dict(body, status=status), video)
        else:
            raise
    vid = resp["id"]
    result = {"video_id": vid, "url": f"https://youtu.be/{vid}", "privacy": resp.get("status", {}).get("privacyStatus"),
              "publish_at": status.get("publishAt")}
    try:
        yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumbnail), mimetype="image/jpeg")).execute()
        result["thumbnail"] = "set"
    except HttpError as e:
        result["thumbnail"] = f"failed ({e.resp.status}); your channel may need phone verification for custom thumbnails"
    if meta.get("playlist_id"):
        try:
            yt.playlistItems().insert(part="snippet", body={"snippet": {
                "playlistId": meta["playlist_id"], "resourceId": {"kind": "youtube#video", "videoId": vid}}}).execute()
            result["playlist"] = "added"
        except HttpError as e:
            result["playlist"] = f"failed ({e.resp.status})"
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return result
