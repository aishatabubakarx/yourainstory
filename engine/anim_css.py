"""Evaluate real animate.css entrance keyframes (vendor/animate.css) frame by frame.

Supports any keyframe set made of opacity, translate3d/translate and scale3d/scale
(fadeIn*, zoomIn*, slideIn*, bounceIn* ... ), with per-keyframe timing functions.
"""
from __future__ import annotations

import re
from functools import lru_cache

from .common import ROOT

_NAMED = {
    "ease": (0.25, 0.1, 0.25, 1.0), "ease-in": (0.42, 0, 1, 1), "ease-out": (0, 0, 0.58, 1),
    "ease-in-out": (0.42, 0, 0.58, 1), "linear": None,
}


def _bezier(p, x1, y1, x2, y2):
    if p <= 0:
        return 0.0
    if p >= 1:
        return 1.0

    def bx(t):
        return 3 * (1 - t) ** 2 * t * x1 + 3 * (1 - t) * t ** 2 * x2 + t ** 3

    def by(t):
        return 3 * (1 - t) ** 2 * t * y1 + 3 * (1 - t) * t ** 2 * y2 + t ** 3

    lo, hi = 0.0, 1.0
    for _ in range(40):
        mid = (lo + hi) / 2
        if bx(mid) < p:
            lo = mid
        else:
            hi = mid
    return by((lo + hi) / 2)


def _timing(spec, p):
    if spec is None:
        spec = "ease"
    spec = spec.strip()
    if spec in _NAMED:
        c = _NAMED[spec]
        return p if c is None else _bezier(p, *c)
    m = re.match(r"cubic-bezier\(([^)]*)\)", spec)
    if m:
        v = [float(x) for x in m.group(1).split(",")]
        return _bezier(p, *v)
    return p


def _num_unit(tok):
    tok = tok.strip()
    m = re.match(r"(-?[\d.]+)(%|px)?", tok)
    return float(m.group(1)), (m.group(2) or "px")


def _parse_decl(decl: str) -> dict:
    d = {}
    for part in decl.split(";"):
        if ":" not in part:
            continue
        k, v = [s.strip() for s in part.split(":", 1)]
        if k == "opacity":
            d["opacity"] = float(v)
        elif k == "transform":
            for fn, args in re.findall(r"(translate3d|translate|scale3d|scale)\(([^)]*)\)", v):
                a = [x for x in args.split(",")]
                if fn.startswith("translate"):
                    d["tx"] = _num_unit(a[0])
                    d["ty"] = _num_unit(a[1]) if len(a) > 1 else (0.0, "px")
                else:
                    sx = float(a[0])
                    sy = float(a[1]) if len(a) > 1 else sx
                    d["sx"], d["sy"] = sx, sy
        elif k == "animation-timing-function":
            d["timing"] = v
    return d


@lru_cache(maxsize=1)
def _all_keyframes() -> dict:
    css = (ROOT / "vendor" / "animate.css").read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r"@keyframes\s+([A-Za-z0-9_-]+)\s*\{", css):
        i = m.end()
        depth, j = 1, i
        while depth:
            c = css[j]
            depth += (c == "{") - (c == "}")
            j += 1
        body = css[i:j - 1]
        frames = []
        for sel, decl in re.findall(r"([\w%,.\s]+?)\s*\{([^}]*)\}", body):
            for s in sel.split(","):
                s = s.strip()
                if not s:
                    continue
                off = 0.0 if s == "from" else 1.0 if s == "to" else float(s.rstrip("%")) / 100.0
                frames.append((off, _parse_decl(decl)))
        frames.sort(key=lambda f: f[0])
        out[m.group(1)] = frames
    return out


def available() -> list[str]:
    return sorted(_all_keyframes())


def evaluate(name: str, p: float, w: float, h: float) -> dict:
    """State of animate.css animation `name` at progress p (0..1) for an element of size w x h."""
    frames = _all_keyframes().get(name)
    if frames is None:
        raise KeyError(f"unknown animate.css animation '{name}'")
    defaults = {"opacity": 1.0, "tx": (0.0, "px"), "ty": (0.0, "px"), "sx": 1.0, "sy": 1.0}
    res = {}
    for prop, dflt in defaults.items():
        pts = [(off, d[prop], d.get("timing")) for off, d in frames if prop in d]
        if not pts:
            res[prop] = 0.0 if prop in ("tx", "ty") else dflt
            continue
        if pts[0][0] > 0:
            pts.insert(0, (0.0, dflt, None))
        if pts[-1][0] < 1:
            pts.append((1.0, dflt, None))

        def val(v, axis):
            if isinstance(v, tuple):
                n, u = v
                return n / 100.0 * (w if axis == "tx" else h) if u == "%" else n
            return v

        axis = prop
        seg = next(((a, b) for a, b in zip(pts, pts[1:]) if a[0] <= p <= b[0]), (pts[-2], pts[-1]))
        a, b = seg
        span = (b[0] - a[0]) or 1.0
        q = _timing(a[2], (p - a[0]) / span)
        va, vb = val(a[1], axis), val(b[1], axis)
        res[prop] = va + (vb - va) * q
    return {"opacity": res["opacity"], "tx": res["tx"], "ty": res["ty"], "sx": res["sx"], "sy": res["sy"]}
