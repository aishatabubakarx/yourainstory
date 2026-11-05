"""Quick check that the YouTube secrets work. Takes a few seconds, uploads nothing.

Reads YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN from the environment
(the GitHub workflow "Check YouTube connection" sets them from your Secrets).
"""
import os
import sys

import requests

ok = True


def say(good, text):
    global ok
    ok = ok and good
    print(("PASS  " if good else "FAIL  ") + text, flush=True)


cid, secret, refresh = (os.environ.get(k, "").strip() for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"))
for name, val in (("YT_CLIENT_ID", cid), ("YT_CLIENT_SECRET", secret), ("YT_REFRESH_TOKEN", refresh)):
    say(bool(val), f"secret {name} is {'filled in' if val else 'EMPTY or missing'}")
if not ok:
    sys.exit(1)

# 1. Can the refresh token be exchanged for an access token?
r = requests.post("https://oauth2.googleapis.com/token", data={
    "client_id": cid, "client_secret": secret, "refresh_token": refresh, "grant_type": "refresh_token"}, timeout=30)
if r.status_code != 200:
    err = r.json().get("error", r.text)
    hints = {
        "invalid_grant": "token expired or revoked. Publish the OAuth app (not 'Testing') and run tools/get_refresh_token.py again.",
        "invalid_client": "client ID / secret do not match the OAuth client that made the token.",
        "invalid_scope": "token was made with other scopes. Run tools/get_refresh_token.py again.",
    }
    say(False, f"Google refused the token: {err}. {hints.get(err, '')}")
    sys.exit(1)
access = r.json()["access_token"]
say(True, "Google accepted the refresh token")

# 2. Which permissions does the token really have?
info = requests.get("https://oauth2.googleapis.com/tokeninfo", params={"access_token": access}, timeout=30).json()
scopes = info.get("scope", "").split()
print("      permissions granted:", *[s.rsplit("/", 1)[-1] for s in scopes])
say("https://www.googleapis.com/auth/youtube.upload" in scopes, "permission to UPLOAD videos")
say("https://www.googleapis.com/auth/youtube" in scopes, "permission to manage the channel (thumbnails, playlists)")

# 3. Does it reach the right channel?
h = {"Authorization": f"Bearer {access}"}
c = requests.get("https://www.googleapis.com/youtube/v3/channels", headers=h,
                 params={"part": "snippet,status", "mine": "true"}, timeout=30)
if c.status_code != 200:
    say(False, f"could not read your channel ({c.status_code}): {c.json().get('error', {}).get('message', c.text)}")
    sys.exit(1)
items = c.json().get("items", [])
say(bool(items), "a YouTube channel is attached to this login" + ("" if items else " (log in with the account that owns the channel)"))
if items:
    ch = items[0]
    print(f"      channel: {ch['snippet']['title']}")
    long_ok = ch.get("status", {}).get("longUploadsStatus")
    if long_ok:
        say(long_ok == "allowed", f"uploads longer than 15 minutes: {long_ok} (verify your channel by phone if not 'allowed'; your video is hours long)")

print()
print("ALL GOOD: the connection is open." if ok else "SOMETHING IS WRONG: fix the FAIL lines above.")
sys.exit(0 if ok else 1)
