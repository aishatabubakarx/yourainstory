"""Upload to YouTube with the Data API (resumable), set thumbnail, optional playlist."""
from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path


SCOPES = ["https://www.googleapis.com/auth/youtube", "https://www.googleapis.com/auth/youtube.upload"]


def _service():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    names = ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN")
    # .strip() removes the stray space or newline that often comes with pasting a secret
    cid, secret, refresh = ((os.environ.get(k) or "").strip() for k in names)
    missing = [k for k, v in zip(names, (cid, secret, refresh)) if not v]
    if missing:
        raise SystemExit("Missing GitHub secret(s): " + ", ".join(missing) + " (see README step 3)")
    creds = Credentials(None, refresh_token=refresh, token_uri="https://oauth2.googleapis.com/token",
                        client_id=cid, client_secret=secret)  # no scopes: use what the token was granted
    return build("youtube", "v3", http=_make_http(creds), cache_discovery=False)


def _make_http(creds):
    """HTTP client for big uploads.

    Must come from googleapiclient's own build_http(): it tells httplib2 that status 308 is NOT a redirect.
    Google uses 308 to say 'chunk received, send the next one' during a resumable upload. A plain
    httplib2.Http() treats it as a redirect and crashes with RedirectMissingLocation.
    """
    import google_auth_httplib2
    from googleapiclient.http import build_http

    http = build_http()
    http.timeout = 600  # default 60s is too short for a big chunk on a slow moment
    http.redirect_codes = http.redirect_codes - {308}
    return google_auth_httplib2.AuthorizedHttp(creds, http=http)


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
                        client_id=cid, client_secret=secret)
    try:
        creds.refresh(Request())
    except RefreshError as e:
        raise SystemExit(
            f"YouTube login FAILED: {e}\n"
            "Usual causes: the three secrets are not from the SAME run of connect.py (paste all three again), "
            "the consent screen is still on 'Testing' (token expires after 7 days; click Publish app), "
            "or access was removed at myaccount.google.com/permissions.")
    granted = set(requests.get("https://oauth2.googleapis.com/tokeninfo", params={"access_token": creds.token},
                               timeout=30).json().get("scope", "").split())
    if SCOPES[1] not in granted:
        raise SystemExit("YouTube login works but the upload permission (youtube.upload) is missing. "
                         "Run connect.py again and tick every permission box.")
    if SCOPES[0] not in granted:
        print("WARNING: only the upload permission was granted. Uploads and thumbnails will work; "
              "playlists and editing old videos will not.")
    yt = _service()
    items = yt.channels().list(part="snippet", mine=True).execute().get("items", [])
    if not items:
        print("Login OK and upload permission present. (Channel lookup needs the wider permission, skipped.)")
        return
    print(f"YouTube login OK. Channel: {items[0]['snippet']['title']}. Permissions OK.")


def _insert(yt, body, video: Path):
    import socket
    import ssl

    import httplib2
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    media = MediaFileUpload(str(video), chunksize=128 * 1024 * 1024, resumable=True, mimetype="video/mp4")
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


def run_test():
    """Uploads a ~225 MB private test video (several chunks, same path as the real upload). Takes about 5 minutes."""
    import subprocess
    import tempfile

    d = Path(tempfile.mkdtemp())
    video, thumb = d / "test.mp4", d / "thumb.jpg"
    src = "testsrc2=size=1920x1080:rate=30"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", src, "-f", "lavfi", "-i",
                    "anullsrc=r=44100:cl=stereo", "-t", "30", "-vf", "noise=alls=60:allf=t+u",
                    "-c:v", "libx264", "-preset", "ultrafast", "-b:v", "60M", "-maxrate", "60M", "-bufsize", "120M",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(video)], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", src, "-frames:v", "1",
                    "-q:v", "4", str(thumb)], check=True)
    mb = video.stat().st_size / 1e6
    print(f"test video {mb:.0f} MB (upload chunks are 128 MB, so this takes 2 chunks)")
    meta = {"title": "Upload test - safe to delete", "description": "Automated upload test. Safe to delete.",
            "tags": ["test"], "category_id": "22", "language": "en", "privacy": "private",
            "made_for_kids": False, "embeddable": True, "public_stats_viewable": True, "license": "youtube",
            "contains_synthetic_media": False}
    res = upload(meta, video, thumb, d / "result.json")
    try:
        _service().videos().delete(id=res["video_id"]).execute()
        print("Test video deleted again.")
    except Exception:
        print("Test video stays on your channel as PRIVATE. Delete it in YouTube Studio (Content).")
    print("UPLOAD TEST PASSED. A full upload will work.")
