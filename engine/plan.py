"""Timeline planning: how many loops per scene, where transitions fall, chapters."""
from __future__ import annotations

from dataclasses import dataclass, field

from .common import Settings, fmt_ts


@dataclass
class ScenePlan:
    index: int
    name: str
    loops: int
    td_in: int
    td_out: int
    start: float      # fully visible from here
    end: float        # outgoing transition starts here
    center: float     # centre of outgoing transition (ambience crossfades here)


@dataclass
class Plan:
    intro: float
    voice: float
    total: float
    scenes: list = field(default_factory=list)
    outro_start: float = 0.0
    outro_td: int = 0
    chapters: list = field(default_factory=list)


def make_plan(S: Settings, job: dict, intro_len: float, voice_len: float) -> Plan:
    I, A = float(intro_len), float(voice_len)
    L = S.loop_seconds
    scenes = job["scenes"]
    n = len(scenes)
    plan = Plan(intro=I, voice=A, total=0.0)
    s = I
    for i, sc in enumerate(scenes):
        td_in = S.t_intro if i == 0 else S.t_scene
        td_out = S.t_scene if i < n - 1 else S.t_outro
        ideal_center = I + A * (i + 1) / n
        loops = max(1, round((ideal_center - td_out / 2 - s + td_in) / L))
        e = s + loops * L - td_in
        plan.scenes.append(ScenePlan(i, sc.get("chapter") or sc.get("name", f"Scene {i + 1}"), loops, td_in, td_out,
                                     s, e, e + td_out / 2))
        s = e + td_out
    plan.outro_start = s
    plan.outro_td = S.t_outro
    if S.preview:
        plan.total = I + A + S.outro_seconds
    else:
        target = float(job.get("total_hours", 4.0)) * 3600
        plan.total = max(target, plan.outro_start + 600)
    plan.total = max(plan.total, plan.outro_start + 20)
    first = plan.scenes[0]
    plan.chapters = [(0.0, first.name)] + [(p.start, p.name) for p in plan.scenes[1:]]
    plan.chapters.append((plan.outro_start, job.get("outro_chapter", "Sleep soundscape (no narration)")))
    return plan


def chapter_lines(plan: Plan) -> list[str]:
    return [f"{fmt_ts(t)} {name}" for t, name in plan.chapters]
