"""Upload to YouTube with the Data API (resumable), set thumbnail, optional playlist."""
from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path


def _service():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    cid, secret, refresh = (os.environ.get(k) for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"))
    if not (cid and secret and refresh):
        raise SystemExit("Missing YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN secrets (see README step 3)")
    creds = Credentials(None, refresh_token=refresh, token_uri="https://oauth2.googleapis.com/token",
                        client_id=cid, client_secret=secret,
                        scopes=["https://www.googleapis.com/auth/youtube",
                                "https://www.googleapis.com/auth/youtube.upload"])
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def _insert(yt, body, video: Path):
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    media = MediaFileUpload(str(video), chunksize=128 * 1024 * 1024, resumable=True, mimetype="video/mp4")
    notify = body.pop("_notify", False)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media, notifySubscribers=notify)
    resp, retry = None, 0
    while resp is None:
        try:
            status, resp = req.next_chunk()
            if status:
                print(f"  uploaded {int(status.progress() * 100)}%", flush=True)
        except HttpError as e:
            if e.resp.status in (500, 502, 503, 504) and retry < 10:
                retry += 1
                wait = min(120, 2 ** retry + random.random())
                print(f"  server error {e.resp.status}, retrying in {wait:.0f}s")
                time.sleep(wait)
            else:
                raise
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
