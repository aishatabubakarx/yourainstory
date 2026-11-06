"""Frame effects. All motion is periodic over the loop so every loop is seamless.

Coordinates in specs are normalised (0..1 of frame width/height) so one spec works at any resolution.
Effects work on a uint8 BGR frame in place: effect.apply(frame, i) for frame index i of N.
"""
from __future__ import annotations

import math

import cv2
import numpy as np

from .common import periodic_series


def _box(spec_box, W, H):
    x0, y0, x1, y1 = spec_box
    x0, x1 = int(max(0, x0) * W), int(min(1, x1) * W)
    y0, y1 = int(max(0, y0) * H), int(min(1, y1) * H)
    return x0, y0, max(x1, x0 + 2), max(y1, y0 + 2)


def _feather(h, w, frac=0.12):
    ys = np.minimum(np.arange(h), np.arange(h)[::-1]).astype(np.float32)
    xs = np.minimum(np.arange(w), np.arange(w)[::-1]).astype(np.float32)
    fy = np.clip(ys / max(1.0, h * frac), 0, 1)
    fx = np.clip(xs / max(1.0, w * frac), 0, 1)
    f = np.outer(fy, fx)
    return f * f * (3 - 2 * f)


def _gauss_sprite(radius, core=0.35, halo=0.0):
    r = max(1, int(math.ceil(radius * 3.2)))
    ys, xs = np.mgrid[-r:r + 1, -r:r + 1].astype(np.float32)
    d2 = xs * xs + ys * ys
    s = math.exp(0)  # noqa
    sig = max(0.35, radius * core + radius * 0.5)
    a = np.exp(-d2 / (2 * sig * sig))
    if halo:
        a = a + halo * np.exp(-d2 / (2 * (sig * 3) ** 2))
    return np.clip(a, 0, 1).astype(np.float32)


class Ctx:
    def __init__(self, base, S, N, T, seed=1):
        self.base, self.S, self.N, self.T = base, S, N, T
        self.W, self.H = S.W, S.H
        self.rng = np.random.default_rng(seed)


# ----------------------------------------------------------------------------- base prep
def prep_base(img_bgr, S, style):
    """Resize (area filter, so 8K -> 4K is crisp), dim, vignette, paper texture."""
    h, w = img_bgr.shape[:2]
    interp = cv2.INTER_AREA if w >= S.W else cv2.INTER_LANCZOS4
    if abs((w / h) - (S.W / S.H)) > 0.01:  # crop to 16:9
        tw = int(h * S.W / S.H)
        x0 = (w - tw) // 2
        img_bgr = img_bgr[:, x0:x0 + tw] if tw <= w else img_bgr
    img = cv2.resize(img_bgr, (S.W, S.H), interpolation=interp).astype(np.float32) / 255.0
    dim = float(style.get("dim", 0.92))
    img *= dim
    vig = float(style.get("vignette", 0.22))
    if vig > 0:
        ys, xs = np.mgrid[0:S.H, 0:S.W].astype(np.float32)
        d = np.sqrt(((xs - S.W / 2) / (S.W / 2)) ** 2 + ((ys - S.H / 2) / (S.H / 2)) ** 2)
        img *= (1 - vig * np.clip(d - 0.45, 0, 1.2) ** 1.6)[..., None]
    paper = float(style.get("paper", 0.035))
    if paper > 0:
        img *= (1 + paper * paper_texture(S.W, S.H))[..., None]
    return np.clip(img * 255 + 0.5, 0, 255).astype(np.uint8)


def paper_texture(W, H, seed=7):
    """Static, low-contrast paper/fibre texture in roughly [-1, 1]."""
    rng = np.random.default_rng(seed)
    tex = np.zeros((H, W), np.float32)
    for scale, amp in ((6, 0.5), (24, 0.35), (160, 0.35)):
        small = rng.normal(0, 1, (max(2, H // scale), max(2, W // scale))).astype(np.float32)
        tex += amp * cv2.resize(small, (W, H), interpolation=cv2.INTER_CUBIC)
    fib = rng.normal(0, 1, (H // 2 + 1, W // 24 + 1)).astype(np.float32)  # horizontal fibres
    tex += 0.25 * cv2.resize(fib, (W, H), interpolation=cv2.INTER_LINEAR)
    tex /= max(1e-6, float(np.abs(tex).max()))
    return tex


class Grain:
    """Animated film grain, cycling through a small bank so loops stay seamless."""

    def __init__(self, S, amount=2.4, bank=8):
        rng = np.random.default_rng(11)
        self.n = [np.round(rng.normal(0, amount, (S.H, S.W))).astype(np.int16) for _ in range(bank)]
        self.rng = rng
        self.bank = bank

    def apply(self, frame, i):
        g = self.n[i % self.bank]
        sy, sx = (i * 37) % 199, (i * 91) % 257  # deterministic jitter, period divides common loop lengths
        g = np.roll(np.roll(g, sy, 0), sx, 1)
        out = frame.astype(np.int16) + g[..., None]
        np.clip(out, 0, 255, out=out)
        frame[:] = out.astype(np.uint8)


# ----------------------------------------------------------------------------- effects
class Flicker:
    """Warm light flicker (candles, lanterns, fire, lit windows) with optional flame wobble."""

    def __init__(self, spec, ctx: Ctx):
        W, H = ctx.W, ctx.H
        self.x0, self.y0, self.x1, self.y1 = _box(spec["box"], W, H)
        crop = ctx.base[self.y0:self.y1, self.x0:self.x1].astype(np.float32) / 255
        self.crop = crop
        h, w = crop.shape[:2]
        b, g, r = crop[..., 0], crop[..., 1], crop[..., 2]
        lum = 0.114 * b + 0.587 * g + 0.299 * r
        thr = spec.get("threshold", 0.35)
        weight = np.clip((r - b) * 3 + 0.25, 0, 1) * np.clip((lum - thr) / 0.35, 0, 1)
        weight = cv2.GaussianBlur(weight, (0, 0), max(1.0, 0.012 * W * spec.get("blur", 1.0)))
        self.w = weight[..., None]
        self.glow = (spec.get("glow", 0.15) * _feather(h, w, 0.4))[..., None]
        self.amp = spec.get("amp", 0.1)
        self.series = periodic_series(ctx.N, ctx.T, spec.get("rate", 2.2), ctx.rng)
        self.warp = spec.get("warp", 0.0) * w
        if self.warp > 0:
            self.ys, self.xs = np.mgrid[0:h, 0:w].astype(np.float32)
            self.prof = np.clip(1 - self.ys / h, 0, 1) ** 0.8
            self.k = max(1, int(round(spec.get("warp_rate", 1.4) * ctx.T)))
            self.lam = max(8.0, h / 3.5)
            self.wm = np.clip(self.w * 1.6, 0, 1)
        self.N = ctx.N

    def apply(self, frame, i):
        gain = 1 + self.amp * self.series[i]
        out = self.crop * (1 + (self.w + self.glow) * (gain - 1))
        if self.warp > 0:
            ph = 2 * math.pi * self.k * i / self.N
            dx = self.warp * np.sin(2 * math.pi * self.ys / self.lam - ph) * self.prof
            warped = cv2.remap(out, self.xs + dx, self.ys, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
            out = out * (1 - self.wm) + warped * self.wm
        frame[self.y0:self.y1, self.x0:self.x1] = np.clip(out * 255 + 0.5, 0, 255).astype(np.uint8)


class Sway:
    """Gentle wave displacement of a region. anchor: bottom (smoke, steam), top (leaves), none."""

    def __init__(self, spec, ctx: Ctx):
        W, H = ctx.W, ctx.H
        self.x0, self.y0, self.x1, self.y1 = _box(spec["box"], W, H)
        self.crop = ctx.base[self.y0:self.y1, self.x0:self.x1].copy()
        h, w = self.crop.shape[:2]
        self.ys, self.xs = np.mgrid[0:h, 0:w].astype(np.float32)
        anchor = spec.get("anchor", "bottom")
        t = self.ys / h
        self.prof = {"bottom": (1 - t) ** 1.5, "top": t ** 1.2, "none": np.ones_like(t)}[anchor].astype(np.float32)
        self.amp = spec.get("amp", 0.05) * w
        self.k = max(1, int(round(spec.get("rate", 0.12) * ctx.T)))
        self.lam = max(6.0, spec.get("wavelength", 0.5) * h)
        self.feather = _feather(h, w, spec.get("feather", 0.18))[..., None]
        self.N = ctx.N
        self.vert = spec.get("vertical", 0.0) * h

    def apply(self, frame, i):
        ph = 2 * math.pi * self.k * i / self.N
        dx = self.amp * np.sin(2 * math.pi * self.ys / self.lam + ph) * self.prof
        dy = self.vert * np.sin(2 * math.pi * self.xs / self.lam * 1.3 - ph) * self.prof if self.vert else 0 * self.ys
        warped = cv2.remap(self.crop, self.xs + dx, self.ys + dy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        out = self.crop * (1 - self.feather) + warped * self.feather
        frame[self.y0:self.y1, self.x0:self.x1] = np.clip(out + 0.5, 0, 255).astype(np.uint8)


class Ripple(Sway):
    """Water shimmer: horizontal wobble that grows toward the bottom of the box."""

    def __init__(self, spec, ctx):
        spec = dict(spec)
        spec["anchor"] = "none"
        super().__init__(spec, ctx)
        h = self.crop.shape[0]
        self.prof = (0.25 + 0.75 * (self.ys / h)).astype(np.float32)


class Twinkle:
    """Auto-detected stars/lights that softly brighten and dim."""

    def __init__(self, spec, ctx: Ctx):
        W, H = ctx.W, ctx.H
        x0, y0, x1, y1 = _box(spec["box"], W, H)
        crop = ctx.base[y0:y1, x0:x1]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (0, 0), 0.8)
        k = max(3, int(9 * ctx.S.scale) | 1)
        peaks = (blur == cv2.dilate(blur, np.ones((k, k), np.uint8)))
        thr = max(int(spec.get("min_brightness", 120)), int(np.percentile(blur, spec.get("percentile", 99.2))))
        local = cv2.GaussianBlur(blur, (0, 0), max(3.0, 7 * ctx.S.scale * 2)).astype(np.int16)
        contrast = blur.astype(np.int16) - local  # a real star stands out from its surroundings
        ys, xs = np.nonzero(peaks & (blur > thr) & (contrast > spec.get("min_contrast", 22)))
        order = np.argsort(-blur[ys, xs])[: int(spec.get("count", 60))]
        rng = ctx.rng
        self.stars = []
        size = spec.get("size", 1.0) * max(0.8, 2.0 * ctx.S.scale * 1.6)
        for idx in order:
            y, x = int(ys[idx]) + y0, int(xs[idx]) + x0
            col = ctx.base[max(0, y - 1):y + 2, max(0, x - 1):x + 2].reshape(-1, 3).max(0).astype(np.float32) / 255
            col = col / max(float(col.max()), 1e-3)
            strength = max(0.10, float(contrast[y - y0, x - x0]) / 255.0)
            r = size * rng.uniform(0.8, 1.6)
            sp = _gauss_sprite(r, halo=0.25)
            kk = max(1, int(round(rng.uniform(0.04, 0.16) * ctx.T)))  # cycles per loop
            self.stars.append((x, y, sp, col * strength, kk, rng.uniform(0, 2 * math.pi)))
        self.amp = spec.get("amp", 0.55)
        self.N = ctx.N
        self.H, self.W = H, W

    def apply(self, frame, i):
        for x, y, sp, col, kk, ph in self.stars:
            g = self.amp * math.sin(2 * math.pi * kk * i / self.N + ph)
            r = sp.shape[0] // 2
            xa, xb, ya, yb = max(0, x - r), min(self.W, x + r + 1), max(0, y - r), min(self.H, y + r + 1)
            if xb <= xa or yb <= ya:
                continue
            s = sp[ya - (y - r):yb - (y - r), xa - (x - r):xb - (x - r)]
            roi = frame[ya:yb, xa:xb].astype(np.float32)
            roi += g * 255 * s[..., None] * col[None, None, :]
            frame[ya:yb, xa:xb] = np.clip(roi, 0, 255).astype(np.uint8)


def _auto_mask(base, spec, S):
    """Mask of 'sky-blue' pixels (window panes) inside a box."""
    W, H = S.W, S.H
    x0, y0, x1, y1 = _box(spec["box"], W, H)
    m = np.zeros((H, W), np.uint8)
    crop = base[y0:y1, x0:x1].astype(np.int16)
    b, g, r = crop[..., 0], crop[..., 1], crop[..., 2]
    lum = (b + g + r) // 3
    sel = ((b > r + spec.get("blue_margin", 14)) & (lum > spec.get("min_lum", 22))).astype(np.uint8) * 255
    k = max(3, int(9 * S.scale) | 1)
    sel = cv2.morphologyEx(sel, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
    sel = cv2.morphologyEx(sel, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
    sel = cv2.erode(sel, np.ones((3, 3), np.uint8))
    m[y0:y1, x0:x1] = sel
    return cv2.GaussianBlur(m, (0, 0), 1.2).astype(np.float32) / 255


class Snow:
    """Seamless falling snow in three depth layers. Optional mask (e.g. only outside a window)."""

    def __init__(self, spec, ctx: Ctx):
        S, rng = ctx.S, ctx.rng
        self.W, self.H, self.N = ctx.W, ctx.H, ctx.N
        self.mask = None
        if "mask" in spec and spec["mask"]:
            self.mask = _auto_mask(ctx.base, spec["mask"], S)
            ctx.debug_masks.append(("snow_mask", self.mask))
        base_count = int(spec.get("count", 650))
        size = spec.get("size", 1.0) * max(0.7, S.scale)
        wind = spec.get("wind", 0.25)
        speed = max(1, int(round(spec.get("speed", 1))))
        layers = [(0.45, 1.5, 0.55, 1), (0.35, 3.0, 0.8, 1), (0.20, 5.4, 0.95, 2)]
        self.flakes = []
        self.sprites = {}
        margin = 24 * S.scale + 12
        for frac, rad, alpha, cyc in layers:
            n = max(3, int(base_count * frac))
            for _ in range(n):
                r = rad * size * rng.uniform(0.7, 1.35)
                key = round(r * 2) / 2
                if key not in self.sprites:
                    sp = _gauss_sprite(max(0.6, key), core=0.15 + 0.1 * (key > 3))
                    self.sprites[key] = sp
                self.flakes.append((
                    rng.uniform(0, self.W), rng.uniform(0, 1), key, alpha * rng.uniform(0.7, 1.0),
                    cyc * speed, rng.uniform(4, 22) * S.scale * (0.6 + rad / 5.4) * 2.0,
                    rng.integers(1, 4), rng.uniform(0, 2 * math.pi),
                ))
        self.margin, self.wind = margin, wind
        self.color = np.array([238, 232, 222], np.float32)  # BGR, cool white
        self.mask_need = self.mask is not None

    def apply(self, frame, i):
        u = i / self.N
        W, H = self.W, self.H
        span = H + 2 * self.margin
        for x0, y0, key, alpha, cyc, samp, sk, sph in self.flakes:
            age = (y0 + cyc * u) % 1.0
            y = age * span - self.margin
            x = (x0 + self.wind * age * H * 0.35 + samp * math.sin(2 * math.pi * sk * u + sph)) % W
            sp = self.sprites[key]
            r = sp.shape[0] // 2
            xi, yi = int(x), int(y)
            xa, xb, ya, yb = max(0, xi - r), min(W, xi + r + 1), max(0, yi - r), min(H, yi + r + 1)
            if xb <= xa or yb <= ya:
                continue
            a = sp[ya - (yi - r):yb - (yi - r), xa - (xi - r):xb - (xi - r)] * alpha
            if self.mask_need:
                a = a * self.mask[ya:yb, xa:xb]
                if a.max() < 0.01:
                    continue
            roi = frame[ya:yb, xa:xb]
            f = roi.astype(np.float32)
            f += (self.color - f) * a[..., None]
            roi[:] = f.astype(np.uint8)


class Puffs:
    """Rising smoke / steam made of soft overlapping puffs along a swaying path."""

    def __init__(self, spec, ctx: Ctx):
        S, rng = ctx.S, ctx.rng
        self.W, self.H, self.N = ctx.W, ctx.H, ctx.N
        self.ox, self.oy = spec["origin"][0] * self.W, spec["origin"][1] * self.H
        self.rise = spec.get("rise", 0.18) * self.H
        self.drift = spec.get("drift", 0.02) * self.W
        self.sway = spec.get("sway", 0.012) * self.W
        r0 = spec.get("size0", 0.004) * self.W
        r1 = spec.get("size1", 0.012) * self.W
        self.count = int(spec.get("count", 26))
        self.cyc = max(1, int(spec.get("cycles", 2)))
        self.alpha = spec.get("alpha", 0.16)
        self.color = np.array(spec.get("color", [235, 228, 224])[::-1], np.float32)  # RGB -> BGR
        self.buckets = [max(0.8, r0 + (r1 - r0) * k / 11) for k in range(12)]
        self.sprites = [_gauss_sprite(r, core=0.9) for r in self.buckets]
        self.phase = [(k / self.count + rng.uniform(-0.01, 0.01), rng.uniform(0, 6.28)) for k in range(self.count)]

    def apply(self, frame, i):
        u = i / self.N
        for ph, sph in self.phase:
            age = (ph + self.cyc * u) % 1.0
            x = self.ox + self.drift * age + self.sway * math.sin(2 * math.pi * (age * 1.4) + sph) * (0.3 + age)
            y = self.oy - self.rise * age
            fade = min(1.0, age / 0.12) * max(0.0, 1 - age) ** 1.4
            sp = self.sprites[min(11, int(age * 12))]
            r = sp.shape[0] // 2
            xi, yi = int(x), int(y)
            xa, xb, ya, yb = max(0, xi - r), min(self.W, xi + r + 1), max(0, yi - r), min(self.H, yi + r + 1)
            if xb <= xa or yb <= ya:
                continue
            a = sp[ya - (yi - r):yb - (yi - r), xa - (xi - r):xb - (xi - r)] * (self.alpha * fade)
            roi = frame[ya:yb, xa:xb]
            f = roi.astype(np.float32)
            f += (self.color - f) * a[..., None]
            roi[:] = f.astype(np.uint8)


class Fog:
    """Slowly evolving colour mist (nebula / aurora glow). Loops via cos/sin of two noise fields."""

    def __init__(self, spec, ctx: Ctx):
        S, rng = ctx.S, ctx.rng
        self.W, self.H, self.N = ctx.W, ctx.H, ctx.N
        cells = int(spec.get("cells", 9))
        ch, cw = max(3, int(cells * self.H / self.W)), cells
        self.A = cv2.GaussianBlur(rng.normal(0, 1, (ch * 4, cw * 4)).astype(np.float32), (0, 0), 2.2)
        self.B = cv2.GaussianBlur(rng.normal(0, 1, (ch * 4, cw * 4)).astype(np.float32), (0, 0), 2.2)
        self.A /= self.A.std()
        self.B /= self.B.std()
        self.k = max(1, int(spec.get("cycles", 1)))
        self.strength = spec.get("strength", 0.10)
        self.color = np.array(spec.get("color", [90, 60, 160])[::-1], np.float32)
        ys = np.linspace(0, 1, self.H, dtype=np.float32)[:, None]
        xs = np.linspace(0, 1, self.W, dtype=np.float32)[None, :]
        cx, cy = spec.get("center", [0.5, 0.45])
        self.wgt = np.exp(-(((xs - cx) / spec.get("sx", 0.6)) ** 2 + ((ys - cy) / spec.get("sy", 0.5)) ** 2))
        self.sw, self.sh = self.W // 4, self.H // 4
        self.wgt_small = cv2.resize(self.wgt, (self.sw, self.sh))

    def apply(self, frame, i):
        ph = 2 * math.pi * self.k * i / self.N
        f = self.A * math.cos(ph) + self.B * math.sin(ph)
        f = cv2.resize(f, (self.sw, self.sh), interpolation=cv2.INTER_CUBIC)
        m = np.clip(f * 0.55 + 0.25, 0, 1.4) * self.wgt_small * self.strength
        m = cv2.resize(m, (self.W, self.H), interpolation=cv2.INTER_CUBIC)
        f3 = frame.astype(np.float32)
        f3 += m[..., None] * self.color * 1.0
        frame[:] = np.clip(f3, 0, 255).astype(np.uint8)


class Starfield:
    """Fly-through starfield: thousands of stars stream outward from a point, as if gliding forward through space.

    Every star repeats its journey an exact whole number of times per loop, so the loop is seamless.
    """

    def __init__(self, spec, ctx: Ctx):
        W, H, rng = ctx.W, ctx.H, ctx.rng
        self.W, self.H, self.N, self.scale = W, H, ctx.N, ctx.S.scale
        n = max(500, int(spec.get("count", 9000) * (W * H) / (3840 * 2160)))
        aspect = W / H
        self.X = rng.uniform(-1, 1, n) * aspect
        self.Y = rng.uniform(-1, 1, n)
        self.u0 = rng.uniform(0, 1, n)
        self.cycles = max(1, int(spec.get("cycles", 1)))
        self.near = float(spec.get("near", 0.10))
        cx, cy = spec.get("center", [0.5, 0.5])
        self.cx, self.cy = cx * W, cy * H
        self.trail = float(spec.get("trail", 0.010))
        palette = np.array(spec.get("palette", [[255, 236, 214], [255, 220, 180], [255, 246, 236],
                                                 [240, 200, 150], [255, 190, 170]]), np.float32) / 255  # BGR
        self.col = palette[rng.integers(0, len(palette), n)]
        self.mag = rng.uniform(0, 1, n) ** 2.4
        self.gain = float(spec.get("brightness", 1.0))
        self.glow = float(spec.get("glow", 5.0))
        self.layer = np.zeros((H, W, 3), np.uint8)
        self.sw, self.sh = W // 4, H // 4

    def _pos(self, u):
        z = 1 - (1 - self.near) * u
        return self.cx + self.X / z * (self.H / 2), self.cy + self.Y / z * (self.H / 2), z

    def apply(self, frame, i):
        W, H = self.W, self.H
        u = (self.u0 + self.cycles * i / self.N) % 1.0
        x, y, z = self._pos(u)
        up = u - self.trail
        fresh = up < 0
        xp, yp, _ = self._pos(np.maximum(up, 0))
        xp = np.where(fresh, x, xp)
        yp = np.where(fresh, y, yp)
        on = (x >= 0) & (x < W - 1) & (y >= 0) & (y < H - 1)
        fade_in = np.clip(u / 0.10, 0, 1)
        b = np.clip((0.22 + 0.78 * self.mag) * (0.30 + 1.25 * (1 - z)) * fade_in * self.gain, 0, 1.6)
        rgb = np.clip(self.col * b[:, None] * 255, 0, 255).astype(np.uint8)
        seg = np.hypot(x - xp, y - yp)
        thick = 1 + ((1 - z) * 3.2 * self.scale * (0.4 + self.mag)).astype(np.int32)
        small = on & (seg < 1.2) & (thick <= 1)
        L = self.layer
        L.fill(0)
        xi, yi = x.astype(np.int32), y.astype(np.int32)
        L[yi[small], xi[small]] = rgb[small]
        for k in np.nonzero(on & ~small)[0]:
            col = (int(rgb[k, 0]), int(rgb[k, 1]), int(rgb[k, 2]))
            cv2.line(L, (int(xp[k]), int(yp[k])), (int(x[k]), int(y[k])), col, int(thick[k]), cv2.LINE_AA)
        out = cv2.add(frame, L)
        sm = cv2.GaussianBlur(cv2.resize(L, (self.sw, self.sh), interpolation=cv2.INTER_AREA), (0, 0), 1.6)
        out = cv2.addWeighted(out, 1.0, cv2.resize(sm, (W, H), interpolation=cv2.INTER_LINEAR), self.glow, 0)
        frame[:] = out


def _periodic_noise(h, w, rng, sigma):
    """Soft noise that tiles seamlessly in both directions, unit standard deviation."""
    n = rng.normal(0, 1, (h, w)).astype(np.float32)
    spec = np.fft.rfft2(n)
    fy = np.fft.fftfreq(h)[:, None]
    fx = np.fft.rfftfreq(w)[None, :]
    spec *= np.exp(-2 * (math.pi * sigma) ** 2 * (fx * fx + fy * fy))
    out = np.fft.irfft2(spec, s=(h, w)).astype(np.float32)
    return out / max(1e-6, float(out.std()))


class _Drift:
    """A noise field that drifts upward and returns exactly to its start after one loop."""

    def __init__(self, h, w, speed_rows_per_s, T, N, sigma, rng):
        travel = speed_rows_per_s * T                      # rows travelled per loop
        self.m = max(1, int(round(travel / (1.6 * h))))    # whole tile heights per loop
        self.tile = max(int(h * 1.2) + 1, int(round(travel / self.m)))
        self.tex = _periodic_noise(self.tile, w, rng, sigma)
        self.rows = np.arange(h)
        self.N = N

    def get(self, i):
        off = self.m * self.tile * i / self.N
        r0 = int(math.floor(off))
        a = np.float32(off - r0)
        i0 = (self.rows + r0) % self.tile
        i1 = (i0 + 1) % self.tile
        return self.tex[i0] * (1 - a) + self.tex[i1] * a


class Fire:
    """Natural flame (kind=fire) or candle (kind=candle).

    - flames lick upward: the picture is pushed by slow noise that drifts up the flame and grows toward the tips
    - the inside of the flame brightens and dims as that noise travels upward
    - the whole flame leans a little, very slowly, as if in a soft draught
    - the surroundings (stone, wood, floor) breathe with warm light that moves across them, never a strobe
    - a few embers rise and fade (fire only)

    spec: box [l,t,r,b] around the flames, base (y of the flame root, 0..1), height (flame height, fraction of frame height).
    Everything repeats exactly once per loop.
    """

    PRESETS = {
        "fire": dict(lick=0.075, speed=0.30, shimmer=0.20, sway=0.040, light=0.065, light_radius=0.20,
                     embers=7, rate=0.55, breath=0.04),
        "candle": dict(lick=0.14, speed=0.45, shimmer=0.07, sway=0.07, light=0.045, light_radius=0.05,
                       embers=0, rate=0.80, breath=0.05),
    }

    def __init__(self, spec, ctx: Ctx):
        p = dict(self.PRESETS[spec.get("kind", "fire")])
        p.update({k: spec[k] for k in p if k in spec})
        self.p = p
        W, H, T, N, rng = ctx.W, ctx.H, ctx.T, ctx.N, ctx.rng
        self.N, self.W, self.H = N, W, H
        self.x0, self.y0, self.x1, self.y1 = _box(spec["box"], W, H)
        if spec.get("clean", spec.get("kind", "fire") == "fire"):
            self._remove_frozen_streaks(ctx.base, spec)
        crop = ctx.base[self.y0:self.y1, self.x0:self.x1].astype(np.float32) / 255
        h, w = crop.shape[:2]
        self.crop, self.h, self.w = crop, h, w
        b, g, r = crop[..., 0], crop[..., 1], crop[..., 2]
        lum = 0.114 * b + 0.587 * g + 0.299 * r

        base_local = spec.get("base", spec["box"][3]) * H - self.y0
        fh = max(8.0, spec.get("height", 0.2) * H)
        self.fh = fh
        thr = spec.get("threshold", 0.55)
        flame = np.clip((lum - thr) / 0.22, 0, 1) * np.clip((r - b) * 4 + 0.3, 0, 1)
        ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
        hp = np.clip((base_local - ys) / fh, 0, 1) ** 1.1          # 0 at the root, 1 at the tips
        self.hp = hp
        flame *= np.clip((base_local + 0.03 * fh - ys) / (0.06 * fh), 0, 1)   # wax, logs and coals below the root stay still
        grow = max(2, int(fh * 0.05)) | 1
        wm = cv2.dilate(flame, np.ones((grow, grow), np.uint8))
        self.wm = np.clip(cv2.GaussianBlur(wm, (0, 0), max(1.0, fh * 0.03)) * 1.4, 0, 1)[..., None]
        self.flame = cv2.GaussianBlur(flame, (0, 0), max(1.0, fh * 0.012))[..., None]
        self.xs, self.ys = xs, ys
        ctx.debug_masks.append(("fire_flame_mask", np.clip(self.wm[..., 0] * hp, 0, 1)))

        # drifting fields are computed on a coarse grid and enlarged each frame
        self.q = 4
        hs, ws = max(8, h // self.q), max(8, w // self.q)
        self.hs, self.ws = hs, ws
        speed_rows = p["speed"] * fh / self.q
        sig = max(1.5, 0.15 * fh / self.q)
        self.fx = _Drift(hs, ws, speed_rows, T, N, sig, rng)
        self.fy = _Drift(hs, ws, speed_rows * 0.9, T, N, sig * 1.1, rng)
        self.fs = _Drift(hs, ws, speed_rows * 1.25, T, N, sig * 0.8, rng)
        self.A_lick = p["lick"] * fh
        self.A_sway = p["sway"] * fh
        self.sway_t = periodic_series(N, T, 0.20, rng, ncomp=3)
        self.breath_t = periodic_series(N, T, p["rate"] * 0.8, rng)

        # light that the flame throws on its surroundings
        R = p["light_radius"] * W
        cx = (self.x0 + self.x1) / 2
        cy = base_local + self.y0 - 0.35 * fh
        lx0, lx1 = int(max(0, cx - R)), int(min(W, cx + R))
        ly0, ly1 = int(max(0, cy - R)), int(min(H, cy + R))
        self.L = (lx0, ly0, lx1, ly1)
        sub = ctx.base[ly0:ly1, lx0:lx1].astype(np.float32) / 255
        sb, sg, sr = sub[..., 0], sub[..., 1], sub[..., 2]
        slum = 0.114 * sb + 0.587 * sg + 0.299 * sr
        warm = np.clip((sr - sb) * 2.2 + 0.1, 0, 1) * np.clip(slum * 2.2, 0, 1)
        gy, gx = np.mgrid[ly0:ly1, lx0:lx1].astype(np.float32)
        d = np.sqrt((gx - cx) ** 2 + (gy - cy) ** 2) / R
        fall = 1.0 / (1.0 + (d * 1.7) ** 2) * np.clip((1.0 - d) / 0.45, 0, 1)   # reaches 0 before the edge, no seam
        wl = fall * warm
        own = np.zeros_like(wl)
        oy0, ox0 = max(self.y0, ly0), max(self.x0, lx0)
        oy1, ox1 = min(self.y1, ly1), min(self.x1, lx1)
        if oy1 > oy0 and ox1 > ox0:
            own[oy0 - ly0:oy1 - ly0, ox0 - lx0:ox1 - lx0] = self.flame[oy0 - self.y0:oy1 - self.y0, ox0 - self.x0:ox1 - self.x0, 0]
        wl *= 1 - 0.85 * np.clip(own * 1.5, 0, 1)                   # flame pixels do not light themselves
        side = np.clip((gx - (cx - R)) / (2 * R), 0, 1)
        self.G1 = (wl * (1 - side)).astype(np.float32)
        self.G2 = (wl * side).astype(np.float32)
        self.a1 = p["light"] * periodic_series(N, T, p["rate"], rng)
        self.a2 = p["light"] * periodic_series(N, T, p["rate"] * 0.85, rng)

        # embers
        self.embers = []
        size = max(0.9, 2.3 * ctx.S.scale * 1.6)
        for _ in range(int(p["embers"])):
            cyc = int(rng.integers(max(2, round(T / 6.5)), max(3, round(T / 3.8)) + 1))
            self.embers.append(dict(
                ox=self.x0 + w * rng.uniform(0.30, 0.68), oy=self.y0 + base_local - fh * rng.uniform(0.02, 0.18),
                rise=fh * rng.uniform(0.9, 1.5), drift=w * rng.uniform(-0.10, 0.12),
                wob=w * rng.uniform(0.01, 0.035), sph=rng.uniform(0, 6.28), ph=rng.uniform(0, 1), cyc=cyc,
                sprite=_gauss_sprite(size * rng.uniform(0.85, 1.25), core=0.2), peak=rng.uniform(0.55, 0.95)))
        self.ember_col = np.array([0.22, 0.55, 1.0], np.float32)  # BGR, warm orange

    def _remove_frozen_streaks(self, base, spec):
        """Painted fire highlights (thin bright horizontal slivers on the firebox wall) cannot move with the flames,
        so they look like frozen marks. Find them and paint them out with the wall around them."""
        h0 = self.y1 - self.y0
        fh = max(8.0, spec.get("height", 0.2) * self.H)
        base_local = spec.get("base", spec["box"][3]) * self.H - self.y0
        crop = base[self.y0:self.y1, self.x0:self.x1]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        k = int(0.058 * fh) | 1
        top = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
        cand = (top > spec.get("streak_threshold", 28)).astype(np.uint8)
        n, lab, st, _ = cv2.connectedComponentsWithStats(cand, 8)
        kill = np.zeros_like(cand)
        for j in range(1, n):
            x, y, w, h, area = st[j]
            wide = w >= 2.2 * max(h, 1) and w >= 0.005 * self.W
            above_logs = y + h < base_local - 0.12 * fh
            below_lintel = y > 0.06 * h0
            if area >= 20 and wide and above_logs and below_lintel:
                kill[lab == j] = 1
        if kill.any():
            grow = max(3, int(0.012 * fh)) | 1
            kill = cv2.dilate(kill, np.ones((grow, grow), np.uint8)) * 255
            base[self.y0:self.y1, self.x0:self.x1] = cv2.inpaint(crop, kill, 4, cv2.INPAINT_TELEA)

    def apply(self, frame, i):
        N, p = self.N, self.p
        # 1. flame licking
        sc = (self.w, self.h)
        nx = cv2.resize(self.fx.get(i), sc, interpolation=cv2.INTER_CUBIC)
        ny = cv2.resize(self.fy.get(i), sc, interpolation=cv2.INTER_CUBIC)
        ns = cv2.resize(self.fs.get(i), sc, interpolation=cv2.INTER_CUBIC)
        hp = self.hp
        dx = hp * (self.A_lick * nx + self.A_sway * self.sway_t[i] * hp)
        dy = hp * (0.55 * self.A_lick * ny)
        warped = cv2.remap(self.crop, self.xs + dx, self.ys + dy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        out = self.crop + (warped - self.crop) * self.wm
        # 2. brightness moving up inside the flame, plus a slow overall breath
        shim = 1 + p["shimmer"] * ns * (0.35 + 0.65 * hp)
        out = out * (1 + (shim - 1)[..., None] * self.flame) * (1 + p["breath"] * self.breath_t[i] * self.flame)
        # added as a change relative to the still, so several flames and lights can share the picture in any order
        cur = frame[self.y0:self.y1, self.x0:self.x1].astype(np.float32)
        frame[self.y0:self.y1, self.x0:self.x1] = np.clip(cur + (out - self.crop) * 255 + 0.5, 0, 255).astype(np.uint8)
        # 3. soft warm light on everything around
        lx0, ly0, lx1, ly1 = self.L
        roi = frame[ly0:ly1, lx0:lx1].astype(np.float32)
        roi *= (1 + self.a1[i] * self.G1 + self.a2[i] * self.G2)[..., None]
        frame[ly0:ly1, lx0:lx1] = np.clip(roi + 0.5, 0, 255).astype(np.uint8)
        # 4. embers
        u = i / N
        for e in self.embers:
            age = (e["ph"] + e["cyc"] * u) % 1.0
            x = e["ox"] + e["drift"] * age + e["wob"] * math.sin(2 * math.pi * 1.3 * age + e["sph"]) * (0.3 + age)
            y = e["oy"] - e["rise"] * age ** 0.85
            fade = min(1.0, age / 0.10) * max(0.0, 1 - age) ** 1.3
            tw = 0.8 + 0.2 * math.sin(2 * math.pi * e["cyc"] * 3 * u + e["sph"])
            sp = e["sprite"]
            r = sp.shape[0] // 2
            xi, yi = int(x), int(y)
            xa, xb = max(0, xi - r), min(self.W, xi + r + 1)
            ya, yb = max(0, yi - r), min(self.H, yi + r + 1)
            if xb <= xa or yb <= ya:
                continue
            s = sp[ya - (yi - r):yb - (yi - r), xa - (xi - r):xb - (xi - r)]
            roi = frame[ya:yb, xa:xb].astype(np.float32)
            roi += s[..., None] * self.ember_col * 255 * (e["peak"] * fade * tw)
            frame[ya:yb, xa:xb] = np.clip(roi, 0, 255).astype(np.uint8)


EFFECTS = {
    "flicker": Flicker, "sway": Sway, "ripple": Ripple, "twinkle": Twinkle,
    "snow": Snow, "smoke": Puffs, "steam": Puffs, "fog": Fog, "starfield": Starfield, "fire": Fire,
}

# render order: displacement first, light next, particles last
ORDER = ["sway", "ripple", "fog", "flicker", "fire", "twinkle", "starfield", "smoke", "steam", "snow"]


def build_effects(specs, ctx):
    ctx.debug_masks = []
    effs = []
    for spec in sorted(specs, key=lambda s: ORDER.index(s["type"])):
        cls = EFFECTS.get(spec["type"])
        if cls is None:
            raise SystemExit(f"unknown effect type '{spec['type']}' (use: {', '.join(EFFECTS)})")
        effs.append(cls(spec, ctx))
    return effs
