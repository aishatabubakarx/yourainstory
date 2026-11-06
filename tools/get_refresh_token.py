"""Run ONCE on your own computer to get the YouTube refresh token.

1. In Google Cloud Console create an OAuth client of type "Desktop app" and download it as client_secret.json
2. pip install google-auth-oauthlib
3. python tools/get_refresh_token.py client_secret.json
4. Sign in with the Google account that owns the channel. Copy the three values it prints into GitHub Secrets.
"""
import json
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube", "https://www.googleapis.com/auth/youtube.upload"]

path = sys.argv[1] if len(sys.argv) > 1 else "client_secret.json"
flow = InstalledAppFlow.from_client_secrets_file(path, SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
info = json.load(open(path))
c = info.get("installed") or info.get("web")
print("\nAdd these as GitHub repository secrets:\n")
print("YT_CLIENT_ID      =", c["client_id"])
print("YT_CLIENT_SECRET  =", c["client_secret"])
print("YT_REFRESH_TOKEN  =", creds.refresh_token)
