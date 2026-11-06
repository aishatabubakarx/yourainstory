"""Download the narration audio and the reusable brand assets from GitHub Releases (works for draft releases)."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import requests

API = "https://api.github.com"


def _headers(accept="application/vnd.github+json"):
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not tok:
        raise SystemExit("GITHUB_TOKEN is not set (it is provided automatically inside GitHub Actions)")
    return {"Authorization": f"Bearer {tok}", "Accept": accept, "X-GitHub-Api-Version": "2022-11-28"}


def _find_release(repo: str, name: str):
    page = 1
    while True:
        r = requests.get(f"{API}/repos/{repo}/releases", params={"per_page": 100, "page": page}, headers=_headers())
        r.raise_for_status()
        items = r.json()
        for rel in items:
            if rel.get("name") == name or rel.get("tag_name") == name:
                return rel
        if len(items) < 100:
            return None
        page += 1


def download_asset(repo: str, release_name: str, file_name: str, dest: Path) -> Path:
    rel = _find_release(repo, release_name)
    if rel is None:
        raise SystemExit(f"No release named '{release_name}' found in {repo}. Create it (a draft is fine) "
                         f"and attach {file_name}.")
    asset = next((a for a in rel["assets"] if a["name"] == file_name), None)
    if asset is None:
        names = ", ".join(a["name"] for a in rel["assets"]) or "none"
        raise SystemExit(f"Release '{release_name}' has no file '{file_name}' (it has: {names})")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(f"{API}/repos/{repo}/releases/assets/{asset['id']}",
                      headers=_headers("application/octet-stream"), stream=True) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            shutil.copyfileobj(r.raw, f, length=1 << 24)
    print(f"downloaded {file_name} ({dest.stat().st_size / 1e6:.0f} MB)")
    return dest


def get_voice(job: dict, job_dir: Path, work: Path) -> Path:
    a = job["audio"]
    kind = a.get("source", "file")
    dest = work / "voice.wav"
    work.mkdir(parents=True, exist_ok=True)
    if kind == "file":
        src = job_dir / a["path"]
        if not src.exists():
            raise SystemExit(f"audio file not found: {src}")
        return src
    if kind == "release":
        repo = os.environ.get("GITHUB_REPOSITORY")
        if not repo:
            raise SystemExit("GITHUB_REPOSITORY not set; run inside GitHub Actions or set audio.source to 'file'")
        if dest.exists():
            return dest
        return download_asset(repo, a.get("release", job["slug"]), a["file"], dest)
    if kind == "url":
        with requests.get(a["url"], stream=True) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                shutil.copyfileobj(r.raw, f, length=1 << 24)
        return dest
    raise SystemExit(f"unknown audio.source '{kind}' (use file, release or url)")
