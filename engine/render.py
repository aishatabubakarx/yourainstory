"""Render one seamless looping scene clip (video only) from a still image + effects."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from . import fx
from .common import ROOT, Settings, VideoWriter


def load_image(path) -> np.ndarray:
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit(f"cannot read image {path}")
    return img


def render_loop(scene: dict, image, out: Path, S: Settings, loop_seconds: int, debug_dir: Path | None = None):
    """scene: {effects:[...], style:{dim,vignette,paper,grain}}. image: BGR array."""
    N = loop_seconds * S.fps
    style = scene.get("style", {})
    base = fx.prep_base(image, S, style)
    ctx = fx.Ctx(base, S, N, loop_seconds, seed=int(scene.get("seed", 5)))
    effects = fx.build_effects(scene.get("effects", []), ctx)
    grain = fx.Grain(S, amount=float(style.get("grain", 2.4)))
    if debug_dir is not None:
        debug_dir.mkdir(parents=True, exist_ok=True)
        for name, m in ctx.debug_masks:
            cv2.imwrite(str(debug_dir / f"{name}.png"), (m * 255).astype(np.uint8))
        cv2.imwrite(str(debug_dir / "base.jpg"), base, [cv2.IMWRITE_JPEG_QUALITY, 85])
    w = VideoWriter(S, out)
    frame = np.empty_like(base)
    for i in range(N):
        np.copyto(frame, base)
        for e in effects:
            e.apply(frame, i)
        grain.apply(frame, i)
        w.write(frame)
        if i % (S.fps * 5) == 0:
            print(f"  {Path(out).name}: frame {i}/{N}", flush=True)
    w.close()
    return N
