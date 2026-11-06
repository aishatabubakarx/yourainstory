"""Branded thumbnail, one fixed look for the whole channel (config/channel.json -> thumbnail.style):
scene crop, warm bloom, small gold logo top-right, big lowercase white title with ONE gold word and an amber glow,
italic gold subtitle "sleep story · N hours". A job only supplies its picture, title and gold word."""
from __future__ import annotations

import textwrap
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .common import ROOT, load_json


def _font(path, size, weight=None):
    f = ImageFont.truetype(str(ROOT / path), size)
    if weight:
        try:
            f.set_variation_by_axes([weight])
        except Exception:
            pass
    return f


def _tracked(draw, xy, text, font, fill, tracking):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking
    return x


DEFAULT_STYLE = {
    "title": {"size": 0.17, "wrap": 12, "weight": 700, "x": 0.045, "y": 0.045, "max_width": 0.50,
              "case": "title", "color": [255, 255, 255], "accent_color": [255, 196, 48], "outline_color": [30, 12, 4],
              "glow_color": [255, 170, 60], "glow_soft_color": [255, 215, 150]},
    "subtitle": {"size": 0.058, "weight": 600, "tracking": 0.004, "color": [255, 226, 160],
                 "case": "title", "kind": "sleep story", "separator": " · "},
    "logo": {"pos": "top-right", "width": 0.13},
    "grade": {"bloom": 0.75, "contrast": 1.06, "title_shade": True},
}


def brand_style(channel: dict, th: dict) -> dict:
    """Channel style, plus an explicit per-job `thumbnail.override` escape hatch (use rarely: it breaks the family look)."""
    st = {k: dict(v) for k, v in DEFAULT_STYLE.items()}
    for src in (channel.get("thumbnail", {}).get("style", {}), th.get("override", {})):
        for k, v in src.items():
            if k.startswith("_"):
                continue
            if isinstance(v, dict) and k in st:
                st[k].update(v)
    return st


SMALL_WORDS = {"a", "an", "the", "and", "but", "or", "of", "in", "on", "at", "to", "by", "for", "with", "as"}


def apply_case(text: str, mode: str) -> str:
    """mode: lower | title (Fall Asleep by the Fire) | words (Fall Asleep By The Fire) | upper"""
    words = text.split()
    if mode == "upper":
        return text.upper()
    if mode == "words":
        return " ".join(w[:1].upper() + w[1:].lower() for w in words)
    if mode == "title":
        return " ".join(w.lower() if (0 < i < len(words) - 1 and w.lower() in SMALL_WORDS) else w[:1].upper() + w[1:].lower()
                        for i, w in enumerate(words))
    return text.lower()


def _hours_text(h: float) -> str:
    h = float(h)
    n = int(h) if h == int(h) else round(h, 1)
    return f"{n} hour" if n == 1 else f"{n} hours"


def make_thumbnail(job_dir: Path, job: dict, channel: dict, out: Path, W=1920, H=1080):
    th = job.get("thumbnail", {})
    st = brand_style(channel, th)
    T, SB, LG, GR = st["title"], st["subtitle"], st["logo"], st["grade"]
    scene = job["scenes"][int(th.get("scene", 0))]
    img = cv2.imread(str(job_dir / scene["image"]), cv2.IMREAD_COLOR)
    h, w = img.shape[:2]
    fx, fy = th.get("focus", [0.5, 0.5])
    zoom = float(th.get("zoom", 1.0))
    cw, ch = w / zoom, w / zoom * 9 / 16
    if ch > h:
        ch = h
        cw = h * 16 / 9
    x0 = int(np.clip(fx * w - cw / 2, 0, w - cw))
    y0 = int(np.clip(fy * h - ch / 2, 0, h - ch))
    crop = img[y0:y0 + int(ch), x0:x0 + int(cw)]
    base = cv2.resize(crop, (W, H), interpolation=cv2.INTER_AREA).astype(np.float32) / 255

    # dreamy bloom on highlights + gentle grade
    lum = base.mean(2, keepdims=True)
    bloom = cv2.GaussianBlur(np.clip(base - 0.55, 0, 1) * (lum > 0.5), (0, 0), W * 0.012)
    base = 1 - (1 - base) * (1 - bloom * float(GR["bloom"]))
    base = np.clip((base - 0.5) * float(GR["contrast"]) + 0.5, 0, 1)
    ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)
    title_top = bool(GR.get("title_shade", True))
    left = np.clip(1 - xs / (W * 0.75), 0, 1) ** 1.5
    bottom = np.clip((ys / H - 0.45) / 0.55, 0, 1) ** 1.3
    top = np.clip(1 - ys / (H * 0.55), 0, 1) ** 1.4
    if title_top:   # darken behind the title so it stays readable
        shade = 1 - (0.30 * left * (0.5 + 0.5 * top) + 0.50 * top * np.clip(1 - xs / (W * 0.85), 0.25, 1) + 0.20 * bottom)
    else:
        shade = 1 - (0.50 * left * (0.4 + 0.6 * bottom) + 0.35 * bottom)
    d = np.sqrt(((xs - W / 2) / (W / 2)) ** 2 + ((ys - H / 2) / (H / 2)) ** 2)
    shade *= 1 - 0.28 * np.clip(d - 0.55, 0, 1)
    base = np.clip(base * shade[..., None], 0, 1)
    pil = Image.fromarray(cv2.cvtColor((base * 255).astype(np.uint8), cv2.COLOR_BGR2RGB)).convert("RGBA")

    # logo: small, in a corner (th.logo_pos: top-right, top-left, bottom-left, bottom-right)
    logo = Image.open(ROOT / channel["thumbnail"]["logo"]).convert("RGBA")
    lw = int(W * float(LG["width"]))
    logo = logo.resize((lw, int(logo.height * lw / logo.width)), Image.LANCZOS)
    pos = LG["pos"]
    mx, my = int(W * 0.035), int(H * 0.05)
    lx = W - lw - mx if "right" in pos else mx
    ly = H - logo.height - my if "bottom" in pos else my
    shadow = Image.new("RGBA", pil.size, (0, 0, 0, 0))
    sh = Image.new("RGBA", logo.size, (0, 0, 0, 255))
    sh.putalpha(logo.getchannel("A").point(lambda v: int(v * 0.65)))
    shadow.paste(sh, (lx + 2, ly + 3), sh)
    shadow = shadow.filter(ImageFilter.GaussianBlur(8))
    pil = Image.alpha_composite(pil, shadow)
    pil.alpha_composite(logo, (lx, ly))

    # title: lowercase, fixed size/position; shrinks only if a line would run into the picture's focus area
    raw_title = th.get("title", job.get("title_short", "")).strip()
    title = apply_case(raw_title, T["case"])
    sub = th.get("subtitle") or (SB["kind"] + SB["separator"] + _hours_text(job.get("total_hours", 4.0)))
    size = float(T["size"])
    wrap = int(th.get("wrap", T["wrap"]))
    lines = textwrap.wrap(title, width=wrap)
    if len(lines) > 3:
        print(f"thumbnail: title wraps to {len(lines)} lines, showing the first 3. Shorten it ({title!r}).")
    lines = lines[:3]
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    while True:
        font = _font(channel["thumbnail"]["font"], int(H * size), int(T["weight"]))
        widest = max(probe.textlength(l, font=font) for l in lines) if lines else 0
        if widest <= W * float(T["max_width"]) or size <= 0.10:
            break
        size *= 0.96
    tx = int(W * float(T["x"]))
    line_h = int(H * size * 0.96)
    block_h = line_h * len(lines)
    ty = int(H * float(T["y"]))
    # words to colour in vivid gold (th.accent: "fire" or ["fall asleep"]); everything else is bright white
    acc = th.get("accent") or (raw_title.split()[-1:] if raw_title else [])   # default: the last word
    acc = {w.lower() for w in ([acc] if isinstance(acc, str) else acc)}
    acc_words = {w for a in acc for w in a.split()}
    WHITE, GOLD = tuple(T["color"]) + (255,), tuple(T["accent_color"]) + (255,)
    stroke = max(3, int(H * 0.008))

    def words(draw, y, line, fill_for, **kw):
        x = tx
        for wd in line.split(" "):
            draw.text((x, y), wd, font=font, fill=fill_for(wd), **kw)
            x += draw.textlength(wd + " ", font=font)

    halo = Image.new("RGBA", pil.size, (0, 0, 0, 0))          # dark cushion behind the letters for contrast
    glow = Image.new("RGBA", pil.size, (0, 0, 0, 0))          # amber light around the letters
    hd, gd = ImageDraw.Draw(halo), ImageDraw.Draw(glow)
    for k, line in enumerate(lines):
        words(hd, ty + k * line_h, line, lambda w: (0, 0, 0, 255), stroke_width=stroke * 3, stroke_fill=(0, 0, 0, 255))
        words(gd, ty + k * line_h, line, lambda w: tuple(T["glow_color"]) + (255,) if (w.lower() in acc_words or not acc_words) else tuple(T["glow_soft_color"]) + (255,))
    halo = halo.filter(ImageFilter.GaussianBlur(W * 0.014))
    halo.putalpha(halo.getchannel("A").point(lambda v: int(v * 0.75)))
    glow = glow.filter(ImageFilter.GaussianBlur(W * 0.010))
    pil = Image.alpha_composite(pil, halo)
    pil = Image.alpha_composite(pil, glow)
    text = Image.new("RGBA", pil.size, (0, 0, 0, 0))
    td = ImageDraw.Draw(text)
    for k, line in enumerate(lines):
        y = ty + k * line_h
        words(td, y, line, lambda w: GOLD if w.lower() in acc_words else WHITE, stroke_width=stroke, stroke_fill=tuple(T["outline_color"]) + (255,))
    if sub:
        sfont = _font(channel["thumbnail"]["font_italic"], int(H * float(SB["size"])), int(SB["weight"]))
        _tracked(td, (tx + 4, ty + block_h + int(H * 0.012)), apply_case(sub, SB["case"]), sfont, tuple(SB["color"]) + (255,), W * float(SB["tracking"]))
    pil = Image.alpha_composite(pil, text).convert("RGB")
    out.parent.mkdir(parents=True, exist_ok=True)
    q = 92
    while True:
        pil.save(out, "JPEG", quality=q, optimize=True, progressive=True)
        if out.stat().st_size < 1_900_000 or q <= 70:
            break
        q -= 4
    return out
