"""Stitch intro + looping scenes + transitions + outro with stream copy (no re-encode of the long parts)."""
from __future__ import annotations

import math
from pathlib import Path

from .common import Settings, run

XFADE = "A*(P*P*(3-2*P))+B*(1-(P*P*(3-2*P)))"  # smoothstep dissolve


def _cut(src: Path, start: float, length: float, out: Path):
    run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.3f}", "-i", src, "-t", f"{length:.3f}",
         "-c", "copy", "-avoid_negative_ts", "make_zero", "-f", "mpegts", out])
    return out


def _xfade(S: Settings, a: Path, a_start: float, b: Path, length: float, out: Path):
    run(["ffmpeg", "-y", "-loglevel", "error",
         "-ss", f"{a_start:.3f}", "-t", f"{length:.3f}", "-i", a,
         "-t", f"{length:.3f}", "-i", b,
         "-filter_complex",
         f"[0:v][1:v]xfade=transition=custom:duration={length}:offset=0:expr='{XFADE}',format=yuv420p[v]",
         "-map", "[v]", *S.x264_args(), "-an", "-f", "mpegts", out])
    return out


def assemble(S: Settings, plan, loops: list[Path], intro_ts: Path, outro_ts: Path, audio: Path, out_mp4: Path,
             work: Path, intro_len: float):
    pieces_dir = work / "pieces"
    pieces_dir.mkdir(parents=True, exist_ok=True)
    L, Lo = S.loop_seconds, S.outro_loop_seconds
    seq: list[Path] = []

    # intro (copied) -> dissolve into scene 1
    td0 = plan.scenes[0].td_in
    seq.append(_cut(intro_ts, 0, intro_len - td0, pieces_dir / "intro_main.ts"))
    seq.append(_xfade(S, intro_ts, intro_len - td0, loops[0], td0, pieces_dir / "t_intro.ts"))

    for i, sp in enumerate(plan.scenes):
        loop = loops[i]
        seq.append(_cut(loop, sp.td_in, L - sp.td_in, pieces_dir / f"s{i}_first.ts"))
        seq.extend([loop] * (sp.loops - 1))
        nxt = loops[i + 1] if i + 1 < len(plan.scenes) else outro_ts
        seq.append(_xfade(S, loop, 0, nxt, sp.td_out, pieces_dir / f"t_{i}.ts"))

    remaining = plan.total - plan.outro_start
    first = Lo - plan.outro_td
    seq.append(_cut(outro_ts, plan.outro_td, first, pieces_dir / "outro_first.ts"))
    extra = max(0, math.ceil((remaining - first) / Lo)) + 1
    seq.extend([outro_ts] * extra)

    lst = work / "concat.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in seq), encoding="utf-8")
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-i", audio,
         "-map", "0:v:0", "-map", "1:a:0", "-c", "copy", "-t", f"{plan.total:.3f}",
         out_mp4])
    return out_mp4
