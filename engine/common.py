"""Shared helpers: settings, ffmpeg wrappers, periodic noise."""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def load_json(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


class Settings:
    """Video settings. Preview mode renders a small, short version of the same pipeline."""

    def __init__(self, preview: bool = False):
        cfg = load_json(ROOT / "config" / "channel.json")
        v = cfg["video"]
        self.channel = cfg
        self.preview = preview
        self.fps = int(v["fps"])
        self.gop_seconds = 2
        size_env = os.environ.get("INDREAM_SIZE")  # e.g. "640x360" for quick tests
        if size_env:
            self.W, self.H = [int(x) for x in size_env.lower().split("x")]
        elif preview:
            self.W, self.H = int(v["preview_width"]), int(v["preview_height"])
        else:
            self.W, self.H = int(v["width"]), int(v["height"])
        self.scale = self.W / 3840.0  # sizes are authored at 4K and scaled
        if preview:
            self.loop_seconds = int(v["preview_loop_seconds"])
            self.outro_loop_seconds = int(v["preview_loop_seconds"])
            self.t_intro, self.t_scene, self.t_outro = 2, 4, 4
            self.voice_limit = float(v["preview_voice_seconds"])
            self.outro_seconds = float(v["preview_outro_seconds"])
        else:
            self.loop_seconds = int(v["loop_seconds"])
            self.outro_loop_seconds = int(v["outro_loop_seconds"])
            self.t_intro = int(v["transition_intro_seconds"])
            self.t_scene = int(v["transition_scene_seconds"])
            self.t_outro = int(v["transition_outro_seconds"])
            self.voice_limit = None
            self.outro_seconds = None
        self.crf = str(v["crf"])
        self.maxrate = v["maxrate"]
        self.bufsize = v["bufsize"]
        self.preset = v["preset"] if not preview else "veryfast"
        self.threads = int(os.environ.get("INDREAM_THREADS", "0"))
        for name in ("loop_seconds", "outro_loop_seconds", "t_intro", "t_scene", "t_outro"):
            if getattr(self, name) % self.gop_seconds:
                raise SystemExit(f"{name} must be a multiple of {self.gop_seconds}s (keyframe grid)")

    @property
    def tag(self) -> str:
        return "preview" if self.preview else "full"

    def x264_args(self) -> list[str]:
        keyint = self.fps * self.gop_seconds
        return [
            "-c:v", "libx264", "-preset", self.preset, "-profile:v", "high",
            "-crf", self.crf, "-maxrate", self.maxrate, "-bufsize", self.bufsize,
            "-x264-params", f"keyint={keyint}:min-keyint={keyint}:scenecut=0:open-gop=0",
            "-pix_fmt", "yuv420p", "-threads", str(self.threads),
            "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
            "-color_range", "tv",
        ]


def run(cmd: list, **kw) -> subprocess.CompletedProcess:
    cmd = [str(c) for c in cmd]
    p = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if p.returncode != 0:
        sys.stderr.write(p.stderr[-4000:] + "\n")
        raise RuntimeError(f"command failed ({p.returncode}): {' '.join(cmd[:6])} ...")
    return p


def duration(path) -> float:
    p = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path])
    return float(p.stdout.strip())


class VideoWriter:
    """Pipe raw BGR frames into ffmpeg -> H.264 (BT.709, limited range)."""

    def __init__(self, S: Settings, out: Path):
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
            "-s", f"{S.W}x{S.H}", "-r", str(S.fps), "-i", "-",
            "-vf", "scale=out_color_matrix=bt709:out_range=tv:flags=bicubic,format=yuv420p",
            *S.x264_args(), "-an",
        ]
        if out.suffix == ".ts":
            cmd += ["-f", "mpegts"]
        cmd.append(str(out))
        self.p = subprocess.Popen([str(c) for c in cmd], stdin=subprocess.PIPE)

    def write(self, frame: np.ndarray):
        self.p.stdin.write(np.ascontiguousarray(frame).tobytes())

    def close(self):
        self.p.stdin.close()
        if self.p.wait() != 0:
            raise RuntimeError("ffmpeg encode failed")


def periodic_series(n: int, loop_seconds: float, rate_hz: float, rng, ncomp: int = 4) -> np.ndarray:
    """Smooth pseudo-random series in [-1, 1] that loops perfectly over n frames."""
    i = np.arange(n, dtype=np.float64)
    out = np.zeros(n)
    for j in range(ncomp):
        k = max(1, int(round(rate_hz * loop_seconds * rng.uniform(0.55, 1.6))))
        out += (1.0 / (1 + 0.45 * j)) * np.sin(2 * math.pi * k * i / n + rng.uniform(0, 2 * math.pi))
    m = np.max(np.abs(out)) or 1.0
    return (out / m).astype(np.float32)


def smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


def fmt_ts(sec: float) -> str:
    sec = int(round(sec))
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
