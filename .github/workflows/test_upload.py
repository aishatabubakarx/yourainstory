"""Upload a 10 second TEST video (private) with the real thumbnail code and a test title.

Uses the same upload code as the real pipeline, so if this works, the real upload will work.
The video is PRIVATE and titled "indream TEST ... delete me". Delete it afterwards in YouTube Studio.
"""
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.common import Settings, load_json  # noqa: E402
from engine.thumbnail import make_thumbnail  # noqa: E402
from engine.upload import upload  # noqa: E402

job_name = sys.argv[1] if len(sys.argv) > 1 else "cabin-snow-001"
out = ROOT / "out" / "_test_upload"
out.mkdir(parents=True, exist_ok=True)
video, thumb = out / "video.mp4", out / "thumbnail.jpg"

print("1/3 making a 10 second test video ...", flush=True)
subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=0x14213d:s=1280x720:d=10:r=30",
                "-f", "lavfi", "-i", "sine=frequency=180:duration=10",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(video)], check=True)

print("2/3 making the thumbnail with the real thumbnail code ...", flush=True)
jd = ROOT / "jobs" / job_name
job = load_json(jd / "job.json")
make_thumbnail(jd, job, Settings(preview=True).channel, thumb)
print(f"    thumbnail {thumb.stat().st_size / 1e6:.2f} MB (YouTube limit 2 MB)")

stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
meta = {
    "title": f"indream TEST upload {stamp} (delete me)",
    "description": "Test upload from the indream pipeline. Private. Safe to delete.\n\n#indream #test",
    "tags": ["indream", "test"],
    "category_id": "22", "language": "en",
    "made_for_kids": False, "contains_synthetic_media": True, "embeddable": True,
    "public_stats_viewable": True, "license": "youtube", "notify_subscribers": False,
    "privacy": "private", "publish_at": None, "playlist_id": None,
}

print("3/3 uploading to YouTube (private) ...", flush=True)
res = upload(meta, video, thumb, out / "upload_result.json")

print("\n==== RESULT ====")
print("video   :", res["url"])
print("privacy :", res.get("privacy"))
print("thumbnail:", res.get("thumbnail"))
if res.get("thumbnail") != "set":
    print("-> thumbnail was NOT set. Most likely the channel is not phone-verified: youtube.com/verify")
print("Open the link, check the title and thumbnail, then delete the video in YouTube Studio.")
