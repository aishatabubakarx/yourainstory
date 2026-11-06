"""Mix the final audio track: intro swell, narration, per-scene ambience (crossfading with the visuals), outro bed."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, sosfilt

from .common import ROOT, Settings, duration, run

SR = 48000


def make_fire_wav(path: Path, seconds: int = 90, seed: int = 3):
    """Synthetic fire crackle, circularly built so it loops without a seam."""
    rng = np.random.default_rng(seed)
    n = SR * seconds
    out = np.zeros((2, n), np.float64)
    freqs = np.fft.rfftfreq(n, 1 / SR)
    for ch in range(2):
        # low warm rumble of the flames
        spec = np.fft.rfft(rng.normal(0, 1, n))
        shape = 1.0 / (1.0 + (freqs / 140.0) ** 2) * (freqs > 25)
        out[ch] += np.fft.irfft(spec * shape, n) * 0.08
    # crackles and pops
    for kernel_tau, rate, level in ((0.0015, 5.0, 1.0), (0.005, 2.2, 0.8), (0.012, 0.5, 0.9)):
        klen = int(kernel_tau * 9 * SR)
        k = rng.normal(0, 1, klen) * np.exp(-np.arange(klen) / (kernel_tau * SR))
        kpad = np.zeros(n)
        kpad[:klen] = k
        kf = np.fft.rfft(kpad)
        for ch in range(2):
            imp = np.zeros(n)
            idx = rng.integers(0, n, int(rate * seconds))
            imp[idx] = rng.lognormal(0, 0.9, len(idx)) * rng.choice([-1, 1], len(idx))
            out[ch] += np.fft.irfft(np.fft.rfft(imp) * kf, n) * level
    sos = butter(2, [500, 9000], btype="band", fs=SR, output="sos")
    for ch in range(2):
        out[ch] = sosfilt(sos, out[ch]) + out[ch] * 0.0
    # tame the pops: raw crackle has a ~39 dB peak-to-average ratio, so single pops would be as loud as speech.
    # A soft limiter (applied sample by sample, so the loop stays seamless) keeps them natural but gentle.
    knee = np.sqrt((out ** 2).mean()) * 3.5
    out = knee * np.tanh(out / knee)
    out /= np.abs(out).max() * 2.0
    wavfile.write(str(path), SR, (out.T * 32767).astype(np.int16))


def _swell(spec):  # slow, non-repeating-feeling gain wobble as an ffmpeg expression
    a, b, c = spec
    return (f"volume='{a[0]}+{a[1]}*sin(2*PI*t/{a[2]}+{a[3]})+{b[1]}*sin(2*PI*t/{b[2]}+{b[3]})"
            f"+{c[1]}*sin(2*PI*t/{c[2]}+{c[3]})':eval=frame")


LAYERS = {
    # kind: (noise colour, filter chain, swell(a,b,c) each (base/amp, amp, period, phase))
    "wind": ("brown", "highpass=f=35,lowpass=f=520", ((0.62, 0.25, 57, 0.7), (0, 0.13, 23, 2.1), (0, 0.06, 11, 4.0))),
    "hush": ("pink", "highpass=f=900,lowpass=f=6500", ((0.7, 0.2, 71, 1.3), (0, 0.1, 29, 0.2), (0, 0.04, 13, 5.1))),
    "rain": ("white", "highpass=f=1400,lowpass=f=9500", ((0.85, 0.08, 83, 0.4), (0, 0.04, 31, 1.7), (0, 0.02, 9, 3.3))),
}


def _layer_graph(kind: str, dur: float, label: str, seed: int, fire_input_index: int | None) -> str:
    """ffmpeg filter-graph text producing a stereo, un-levelled layer on [label]."""
    if kind == "fire":
        return (f"[{fire_input_index}:a]atrim=duration={dur:.3f},asetpts=PTS-STARTPTS,aresample={SR},"
                f"aformat=channel_layouts=stereo[{label}]")
    color, chain, sw = LAYERS[kind]
    return (f"anoisesrc=d={dur:.3f}:c={color}:r={SR}:a=0.7:s={seed}[{label}l];"
            f"anoisesrc=d={dur:.3f}:c={color}:r={SR}:a=0.7:s={seed + 101}[{label}r];"
            f"[{label}l][{label}r]amerge=inputs=2,{chain},{_swell(sw)},aformat=channel_layouts=stereo[{label}]")


def _measure_lufs(graph_with_out: str, extra_inputs: list) -> float:
    p = run(["ffmpeg", "-hide_banner", "-nostats", *extra_inputs, "-filter_complex", graph_with_out,
             "-map", "[m]", "-f", "null", "-"])
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", p.stderr)
    return float(m[-1]) if m else -40.0


def _gain_expr(levels: list[float], centers: list[float], tds: list[float], start_gain_scale: float) -> str:
    """Linear gain over time: levels[0] at the start, ramping to levels[i+1] across each transition."""
    expr = f"{levels[0] * start_gain_scale:.6f}"
    for i, c in enumerate(centers):
        d = (levels[i + 1] - levels[i]) * start_gain_scale
        if abs(d) < 1e-9:
            continue
        expr += f"+({d:.6f})*clip((t-{c - tds[i] / 2:.2f})/{tds[i]:.2f},0,1)"
    return expr


def build_audio(S: Settings, job: dict, plan, voice_path: Path, out_path: Path, work: Path):
    work.mkdir(parents=True, exist_ok=True)
    cfg = job.get("ambience", {})
    under_db = float(cfg.get("under_voice_db", -9))
    outro_db = float(cfg.get("outro_db", -2))
    ref_lufs = float(S.channel["audio"]["ambience_reference_lufs"])
    total, I, A = plan.total, plan.intro, plan.voice

    # per-scene layer levels (scenes..., outro)
    scene_amb = [sc.get("ambience", {}) for sc in job["scenes"]] + [job.get("outro", {}).get("ambience", {})]
    kinds = [k for k in ("wind", "hush", "rain", "fire") if any(a.get(k, 0) > 0 for a in scene_amb)]

    fire_wav = work / "fire_crackle.wav"
    if "fire" in kinds and not fire_wav.exists():
        make_fire_wav(fire_wav)

    centers = [p.center for p in plan.scenes]
    tds = [p.td_out for p in plan.scenes]

    inputs = ["-i", str(voice_path)]
    n_in = 1
    fire_idx = None
    if "fire" in kinds:
        inputs += ["-stream_loop", "-1", "-i", str(fire_wav)]
        fire_idx = n_in
        n_in += 1
    custom_intro = ROOT / "brand" / "intro_audio.wav"
    intro_idx = None
    if custom_intro.exists():
        inputs += ["-i", str(custom_intro)]
        intro_idx = n_in
        n_in += 1

    parts = []
    vl = S.voice_limit
    vtrim = f"atrim=0:{vl},asetpts=PTS-STARTPTS," if vl else ""
    parts.append(f"[0:a]{vtrim}aresample={SR},pan=stereo|c0=c0|c1=c0,adelay={int(I * 1000)}|{int(I * 1000)},"
                 f"apad=whole_dur={total:.3f}[voice]")
    mix_labels = ["voice"]

    # level calibration so scene numbers mean the same thing for every layer
    under = 10 ** (under_db / 20)
    outro_lin = 10 ** (outro_db / 20)
    ramp_start = I + A - 20
    level_expr = f"{under:.6f}+({outro_lin - under:.6f})*clip((t-{ramp_start:.2f})/90,0,1)"
    for ki, kind in enumerate(kinds):
        lab = f"L{kind}"
        graph = _layer_graph(kind, total, lab + "raw", 11 + ki * 7, fire_idx)
        measure_graph = _layer_graph(kind, 40, "x", 11 + ki * 7, 0 if kind == "fire" else None)
        measure_in = ["-stream_loop", "-1", "-i", str(fire_wav)] if kind == "fire" else []
        if kind == "fire":
            measure_graph += ";[x]atrim=duration=40,ebur128=peak=true[m]"
        else:
            measure_graph += ";[x]ebur128=peak=true[m]"
        mg = measure_graph.replace("ebur128=peak=true[m]", "ebur128=peak=true,aformat=channel_layouts=stereo[m]")
        measured = _measure_lufs(mg, measure_in)
        norm = 10 ** ((ref_lufs - measured) / 20)
        levels = [a.get(kind, 0.0) for a in scene_amb]
        gexpr = _gain_expr(levels, centers, tds, norm)
        parts.append(graph)
        parts.append(f"[{lab}raw]volume='({gexpr})*({level_expr})':eval=frame[{lab}]")
        mix_labels.append(lab)

    # intro audio: custom file (loudness-matched to the narration) or a soft synthesised swell
    if intro_idx is not None:
        parts.append(f"[{intro_idx}:a]atrim=duration={I},loudnorm=I=-26:TP=-3:LRA=7,aresample={SR},"
                     f"aformat=channel_layouts=stereo,afade=t=out:st={I - 1.5}:d=1.5,apad=whole_dur={total:.3f}[intro]")
    else:
        sw = min(7.5, I - 1)
        parts.append(f"anoisesrc=d={I}:c=pink:r={SR}:a=0.6:s=5[iw];"
                     f"[iw]highpass=f=900,lowpass=f=5200,aformat=channel_layouts=stereo,"
                     f"volume='0.055*pow(sin(PI*clip((t-0.8)/{sw - 0.8:.2f},0,1)),2)':eval=frame,"
                     f"apad=whole_dur={total:.3f}[intro]")
    mix_labels.append("intro")

    parts.append("".join(f"[{l}]" for l in mix_labels) +
                 f"amix=inputs={len(mix_labels)}:normalize=0:duration=longest,atrim=0:{total:.3f},"
                 f"alimiter=limit=0.92,aformat=sample_rates={SR}:channel_layouts=stereo[out]")
    script = work / "audio_graph.txt"
    script.write_text(";\n".join(parts), encoding="utf-8")
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *inputs, "-filter_complex_script", script,
         "-map", "[out]", "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.3f}", out_path])
    return out_path
