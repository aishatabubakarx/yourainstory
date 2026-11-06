"""Command line: brand | render | upload | upload-test | check-auth | check | new"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from .common import ROOT, Settings, duration, load_json, run


def brand_dir(S):
    return ROOT / "build" / f"brand_{S.tag}"


def build_outro(S, out: Path):
    from .render import render_loop
    from .skygen import make_sky
    spec = load_json(ROOT / "brand" / "outro.json")
    render_loop(spec, make_sky(S, seed=int(spec.get("seed", 42)), sky=spec.get("sky")), out, S, S.outro_loop_seconds)


def ensure_brand(S, force=False):
    from .intro import build_intro
    d = brand_dir(S)
    intro, outro = d / "intro.ts", d / "outro_loop.ts"
    built = False
    if force or not intro.exists():
        print("building intro ...", flush=True)
        build_intro(S, intro, debug_dir=d / "debug")
        built = True
    if force or not outro.exists():
        print("building outro loop ...", flush=True)
        build_outro(S, outro)
        built = True
    if built:
        (d / "BUILT").write_text("1")
    return intro, outro


def _render_one(args):
    idx, image, scene, out, preview, threads = args
    from .render import load_image, render_loop
    S = Settings(preview=preview)
    S.threads = threads
    render_loop(scene, load_image(image), out, S, S.loop_seconds, debug_dir=Path(out).parent / f"debug_scene{idx}")
    return idx


def load_job(slug):
    jd = ROOT / "jobs" / slug
    if not (jd / "job.json").exists():
        raise SystemExit(f"jobs/{slug}/job.json not found")
    return jd, load_json(jd / "job.json")


def check_job(jd: Path, job: dict):
    problems = []
    for sc in job["scenes"]:
        if not (jd / sc["image"]).exists():
            problems.append(f"missing image {sc['image']}")
    if len(job["metadata"]["title"]) > 100:
        problems.append("title longer than 100 characters")
    if problems:
        raise SystemExit("job check failed:\n  - " + "\n  - ".join(problems))


def cmd_render(a):
    from .assemble import assemble
    from .audio import build_audio
    from .fetch import get_voice
    from .metadata import build_metadata
    from .plan import make_plan
    from .thumbnail import make_thumbnail

    S = Settings(preview=a.preview)
    jd, job = load_job(a.job)
    check_job(jd, job)
    tag = S.tag
    work = ROOT / "build" / "work" / f"{a.job}_{tag}"
    out = ROOT / "out" / f"{a.job}{'_preview' if a.preview else ''}"
    work.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)

    voice = get_voice(job, jd, work)
    voice_len = duration(voice)
    if S.voice_limit:
        voice_len = min(voice_len, S.voice_limit)
    intro_ts, outro_ts = ensure_brand(S)
    intro_len = duration(intro_ts)
    plan = make_plan(S, job, intro_len, voice_len)
    print(f"timeline: total {plan.total / 60:.1f} min, scenes {[p.loops for p in plan.scenes]} loops each, "
          f"outro from {plan.outro_start / 60:.1f} min", flush=True)

    # scene loops (parallel)
    loops = [work / f"scene{i}.ts" for i in range(len(job["scenes"]))]
    jobs = []
    cpu = os.cpu_count() or 1
    workers = max(1, min(len(loops), cpu // 2 if cpu > 2 else 1))
    for i, sc in enumerate(job["scenes"]):
        if a.reuse and loops[i].exists():
            continue
        jobs.append((i, jd / sc["image"], sc, loops[i], a.preview, max(1, cpu // workers)))
    if jobs:
        print(f"rendering {len(jobs)} scene loop(s) with {workers} worker(s) ...", flush=True)
        if workers == 1:
            for j in jobs:
                _render_one(j)
        else:
            with ProcessPoolExecutor(max_workers=workers) as ex:
                list(ex.map(_render_one, jobs))
        for i in range(len(loops)):
            d = work / f"debug_scene{i}"
            if d.exists():
                shutil.copytree(d, out / "debug" / f"scene{i}", dirs_exist_ok=True)

    audio = work / "audio.m4a"
    print("mixing audio ...", flush=True)
    build_audio(S, job, plan, voice, audio, work)

    print("assembling video ...", flush=True)
    video = out / "video.mp4"
    assemble(S, plan, loops, intro_ts, outro_ts, audio, video, work, intro_len)

    make_thumbnail(jd, job, S.channel, out / "thumbnail.jpg")
    meta = build_metadata(job, S.channel, plan, out / "metadata.json")
    (out / "timeline.json").write_text(json.dumps({
        "total_seconds": plan.total, "intro": plan.intro, "voice": plan.voice, "outro_start": plan.outro_start,
        "scenes": [vars(p) for p in plan.scenes], "chapters": plan.chapters}, indent=2))
    contact_sheet(video, plan, out / "contact_sheet.jpg")
    print(f"\nDONE  {video}  ({video.stat().st_size / 1e9:.2f} GB)   duration {duration(video) / 60:.1f} min")
    print(f"title: {meta['title']}")
    return out


def contact_sheet(video: Path, plan, out: Path):
    import cv2
    import numpy as np
    times = [3, *[p.start + 20 for p in plan.scenes[1:]], plan.outro_start + 30]
    times = [min(t, plan.total - 2) for t in times]
    tiles = []
    for k, t in enumerate(times):
        f = out.parent / f"_cs{k}.jpg"
        run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", video, "-frames:v", "1",
             "-vf", "scale=640:-2", f])
        tiles.append(cv2.imread(str(f)))
        f.unlink()
    rows = []
    for r in range(0, len(tiles), 2):
        row = tiles[r:r + 2]
        if len(row) < 2:
            row.append(np.zeros_like(row[0]))
        rows.append(np.hstack(row))
    cv2.imwrite(str(out), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 88])


def cmd_upload(a):
    from .upload import upload
    out = ROOT / "out" / a.job
    meta = load_json(out / "metadata.json")
    upload(meta, out / "video.mp4", out / "thumbnail.jpg", out / "upload_result.json")


def cmd_new(a):
    dst = ROOT / "jobs" / a.slug
    if dst.exists():
        raise SystemExit(f"{dst} already exists")
    shutil.copytree(ROOT / "jobs" / "_template", dst)
    print(f"created jobs/{a.slug}/  -> add your images, edit job.json")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="indream")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("brand")
    b.add_argument("--force", action="store_true")
    b.add_argument("--preview", action="store_true")
    r = sub.add_parser("render")
    r.add_argument("--job", required=True)
    r.add_argument("--preview", action="store_true")
    r.add_argument("--reuse", action="store_true", help="reuse already-rendered scene loops")
    u = sub.add_parser("upload")
    u.add_argument("--job", required=True)
    sub.add_parser("check-auth")
    sub.add_parser("upload-test")
    c = sub.add_parser("check")
    c.add_argument("--job", required=True)
    n = sub.add_parser("new")
    n.add_argument("--slug", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "brand":
        ensure_brand(Settings(preview=a.preview), force=a.force)
    elif a.cmd == "render":
        cmd_render(a)
    elif a.cmd == "upload":
        cmd_upload(a)
    elif a.cmd == "upload-test":
        from .upload import run_test
        run_test()
    elif a.cmd == "check-auth":
        from .upload import check_auth
        check_auth()
    elif a.cmd == "check":
        jd, job = load_job(a.job)
        check_job(jd, job)
        print("job OK")
    elif a.cmd == "new":
        cmd_new(a)


if __name__ == "__main__":
    main()
