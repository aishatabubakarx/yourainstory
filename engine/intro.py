"""Build the 10-second 4K intro: animated background, animate.css title entrance, glow, shimmer, grain."""
from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np

from . import anim_css, fx
from .common import ROOT, Settings, VideoWriter, load_json, smoothstep
from .render import load_image


def _logo():
    im = cv2.imread(str(ROOT / "brand" / "logo_gold.png"), cv2.IMREAD_UNCHANGED)
    return im


def build_intro(S: Settings, out: Path, spec_path=None, debug_dir: Path | None = None):
    spec = load_json(spec_path or ROOT / "brand" / "intro.json")
    seconds = int(spec["seconds"])
    N = seconds * S.fps
    bg = load_image(ROOT / spec["background"])
    style = spec.get("style", {})
    base = fx.prep_base(bg, S, style)
    ctx = fx.Ctx(base, S, N, seconds, seed=9)
    effects = fx.build_effects(spec["effects"], ctx)
    grain = fx.Grain(S, amount=float(style.get("grain", 2.6)))

    L = spec["logo"]
    logo = _logo()
    lw = int(L["width"] * S.W)
    lh = int(logo.shape[0] * lw / logo.shape[1])
    cx, cy = L["center"][0] * S.W, L["center"][1] * S.H
    glow_col = np.array([70, 175, 255], np.float32)  # BGR warm gold
    cache = {}

    def scaled(sx, sy):
        key = (round(sx, 3), round(sy, 3))
        if key not in cache:
            if len(cache) > 6:
                cache.clear()
            w, h = max(2, int(lw * sx)), max(2, int(lh * sy))
            interp = cv2.INTER_AREA if w < logo.shape[1] else cv2.INTER_CUBIC
            im = cv2.resize(logo, (w, h), interpolation=interp).astype(np.float32) / 255
            a = im[..., 3]
            glow = cv2.GaussianBlur(a, (0, 0), max(3.0, 0.012 * S.W))
            glow2 = cv2.GaussianBlur(a, (0, 0), max(8.0, 0.04 * S.W))
            cache[key] = (im[..., :3], a, glow * 0.8 + glow2 * 0.7)
        return cache[key]

    w = VideoWriter(S, out)
    frame = np.empty_like(base)
    fi = float(spec.get("fade_in_seconds", 1.2)) * S.fps
    zoom = float(spec.get("zoom", 0.04))
    for i in range(N):
        t = i / S.fps
        np.copyto(frame, base)
        for e in effects:
            e.apply(frame, i)
        # slow push-in (Ken Burns) on the background
        z = 1.0 + zoom * (i / N)
        M = cv2.getRotationMatrix2D((S.W / 2, S.H * 0.46), 0, z)
        frame = cv2.warpAffine(frame, M, (S.W, S.H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

        # title: real animate.css keyframes, evaluated per frame
        p = (t - L["delay"]) / L["duration"]
        if p > 0:
            st = anim_css.evaluate(L["animation"], min(1.0, p), lw, lh)
            op, sx, sy = st["opacity"], st["sx"], st["sy"]
            tx, ty = st["tx"] * S.scale if False else st["tx"], st["ty"]
            if p > 1:  # gentle idle float once settled
                ty += 5 * S.scale * math.sin(2 * math.pi * (t - L["delay"] - L["duration"]) / 6.0)
            lcol, la, lglow = scaled(sx, sy)
            h2, w2 = la.shape
            x0, y0 = int(cx + tx - w2 / 2), int(cy + ty - h2 / 2)
            pad = int(0.1 * S.W)
            xa, ya = max(0, x0 - pad), max(0, y0 - pad)
            xb, yb = min(S.W, x0 + w2 + pad), min(S.H, y0 + h2 + pad)
            reg = frame[ya:yb, xa:xb].astype(np.float32)
            # embed logo layers in the padded region
            A = np.zeros(reg.shape[:2], np.float32)
            G = np.zeros_like(A)
            C = np.zeros_like(reg)
            lx0, ly0 = max(0, xa - x0), max(0, ya - y0)
            rx0, ry0 = max(0, x0 - xa), max(0, y0 - ya)
            ww, hh = min(w2 - lx0, reg.shape[1] - rx0), min(h2 - ly0, reg.shape[0] - ry0)
            if ww > 0 and hh > 0:
                A[ry0:ry0 + hh, rx0:rx0 + ww] = la[ly0:ly0 + hh, lx0:lx0 + ww]
                C[ry0:ry0 + hh, rx0:rx0 + ww] = lcol[ly0:ly0 + hh, lx0:lx0 + ww] * 255
                # glow is wider than the logo: pad it
                gl = np.zeros_like(A)
                gl[ry0:ry0 + hh, rx0:rx0 + ww] = lglow[ly0:ly0 + hh, lx0:lx0 + ww]
                G = gl
            pulse = 0.88 + 0.12 * math.sin(2 * math.pi * t / 4.0)
            reg += G[..., None] * glow_col * (L["glow"] * op * pulse * 0.45)
            a = (A * op)[..., None]
            reg = reg * (1 - a) + C * a
            ts = t - L.get("shimmer_at", 99)
            if 0 <= ts < 1.6:  # a soft light sweep across the letters
                xs = np.arange(reg.shape[1], dtype=np.float32)[None, :]
                centre = rx0 + (-0.1 + 1.2 * smoothstep(ts / 1.6)) * w2
                band = np.exp(-((xs - centre) / (0.07 * w2)) ** 2)
                reg += (A * band * 120 * op)[..., None]
            frame[ya:yb, xa:xb] = np.clip(reg, 0, 255).astype(np.uint8)
        grain.apply(frame, i)
        if i < fi:
            frame = (frame.astype(np.float32) * smoothstep(i / fi)).astype(np.uint8)
        w.write(frame)
        if i % (S.fps * 2) == 0:
            print(f"  intro: frame {i}/{N}", flush=True)
        if debug_dir is not None and i in (int(1.8 * S.fps), int(4 * S.fps), int(7.5 * S.fps)):
            debug_dir.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(debug_dir / f"intro_{i:03d}.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
    w.close()
    return seconds
