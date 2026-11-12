"""Synthetic cough sound (no third-party audio). Pure stdlib so the remote
listener (tools/sound_listener.py) can build the same file on any machine.

A cough here is two short bursts of band-limited noise with a fast attack and
an exponential decay, plus a little low "chest" thump — enough to read as a
cough on a small speaker.
"""
from __future__ import annotations

import math
import random
import struct
import wave
from pathlib import Path

RATE = 16000


def _burst(dur_s: float, gain: float, rng: random.Random) -> list[float]:
    n = int(dur_s * RATE)
    out, lp, hp_prev, prev_in = [], 0.0, 0.0, 0.0
    for i in range(n):
        t = i / RATE
        env = min(1.0, t / 0.012) * math.exp(-t / (dur_s * 0.32))
        x = rng.uniform(-1.0, 1.0)
        lp += 0.35 * (x - lp)                      # low-pass: take the hiss off
        hp = 0.97 * (hp_prev + lp - prev_in)       # high-pass: no DC rumble
        hp_prev, prev_in = hp, lp
        thump = math.sin(2 * math.pi * 140 * t) * math.exp(-t / 0.03) * 0.5
        out.append(gain * env * (hp * 1.6 + thump))
    return out


def samples(seed: int = 7) -> list[float]:
    rng = random.Random(seed)
    s = _burst(0.28, 0.9, rng)
    s += [0.0] * int(0.09 * RATE)
    s += _burst(0.22, 0.7, rng)
    s += [0.0] * int(0.05 * RATE)
    peak = max(abs(v) for v in s) or 1.0
    return [v / peak * 0.85 for v in s]


def write(path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", int(v * 32767)) for v in samples()))
    return path


def ensure(path: str | Path) -> Path:
    path = Path(path)
    return path if path.exists() else write(path)


if __name__ == "__main__":
    import sys
    print(write(sys.argv[1] if len(sys.argv) > 1 else "cough.wav"))
