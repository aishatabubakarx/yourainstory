"""Procedural starry-night base image for the reusable outro (no stock image needed)."""
from __future__ import annotations

import cv2
import numpy as np

from .common import Settings


def _fbm(h, w, rng, octaves=5, base=6):
    out = np.zeros((h, w), np.float32)
    amp, tot = 1.0, 0.0
    for o in range(octaves):
        s = base * (2 ** o)
        small = rng.normal(0, 1, (max(2, h * s // max(h, w)), max(2, w * s // max(h, w)))).astype(np.float32)
        out += amp * cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC)
        tot += amp
        amp *= 0.55
    return out / tot


def make_sky(S: Settings, seed=42, sky: dict | None = None) -> np.ndarray:
    sky = sky or {}
    W, H = S.W, S.H
    rng = np.random.default_rng(seed)
    ys = np.linspace(0, 1, H, dtype=np.float32)[:, None]
    xs = np.linspace(0, 1, W, dtype=np.float32)[None, :]
    top = np.array(sky.get('top', [26, 12, 8]), np.float32)  # BGR
    bot = np.array(sky.get('bottom', [62, 34, 20]), np.float32)
    img = (top[None, None] * (1 - ys[..., None]) + bot[None, None] * ys[..., None]) * np.ones((1, W, 1), np.float32)
    # milky way band (diagonal), mottled, with dust lanes
    ang = np.deg2rad(-24)
    d = (xs - 0.5) * np.sin(ang) * (W / H) + (ys - 0.5) * np.cos(ang)
    band = np.exp(-(d / 0.13) ** 2)
    n1 = _fbm(H, W, rng)
    n2 = _fbm(H, W, rng, base=14)
    glow = np.clip(band * (0.55 + 0.6 * n1), 0, 1.5) * (1 - 0.45 * np.clip(n2 + 0.2, 0, 1) * band)
    col = np.array(sky.get('band', [205, 160, 150]), np.float32)  # BGR
    img += glow[..., None] * col[None, None] * float(sky.get('band_strength', 0.22))
    # stars
    n_stars = int(sky.get('stars', 4200) * (W * H) / (3840 * 2160))
    canvas = np.zeros((H, W, 3), np.float32)
    sx = max(0.8, S.scale * 1.0)
    for _ in range(n_stars):
        x, y = rng.uniform(0, W), rng.uniform(0, H)
        dd = (((x / W) - 0.5) * np.sin(ang) * (W / H) + ((y / H) - 0.5) * np.cos(ang))
        if rng.uniform() > 0.55 + 0.45 * np.exp(-(dd / 0.2) ** 2):
            continue
        mag = rng.uniform() ** 5
        br = 0.38 + 0.62 * mag
        r = sx * (0.55 + 2.6 * mag)
        warm = rng.uniform()
        c = (np.array([255, 215, 190]) * (1 - warm) + np.array([205, 235, 255]) * warm) / 255.0
        xi, yi = int(x), int(y)
        rr = int(np.ceil(r * 3)) + 1
        xa, xb, ya, yb = max(0, xi - rr), min(W, xi + rr + 1), max(0, yi - rr), min(H, yi + rr + 1)
        if xb <= xa or yb <= ya:
            continue
        gy, gx = np.mgrid[ya:yb, xa:xb].astype(np.float32)
        g = np.exp(-(((gx - x) ** 2 + (gy - y) ** 2) / (2 * (r * 0.5) ** 2)))
        g += 0.12 * mag * np.exp(-(((gx - x) ** 2 + (gy - y) ** 2) / (2 * (r * 2.2) ** 2)))
        canvas[ya:yb, xa:xb] += g[..., None] * c[::-1][None, None] * br
    img = img + canvas * 255 * 0.9
    return np.clip(img, 0, 255).astype(np.uint8)
