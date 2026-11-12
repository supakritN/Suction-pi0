"""Fake ESP32 sensor node — streams the real firmware line format over TCP.

    python tools/fake_esp.py [--port 7777] [--noise 0.35] [--spikes 0.01]
    python tools/fake_esp.py --replay      # loop the real recordings in calib_samples/
    SUCTION_PORT=socket://127.0.0.1:7777 python main.py

Each 10 ms it sends:
    pin4:v,pin5:v,pin6:v,pin7:v,pin15:v,pin17:v,pin1:v,pin2:v,pin18:v,pin8:v,pin3:v,pin9:v

Scenario (loops): tube out → cap → 9 cm → 11 cm → back out, with Gaussian
noise (as a fraction of each pin's threshold) plus random single-sample
spikes — the conditions that made the live ADC blink.
"""
from __future__ import annotations

import argparse
import json
import random
import socket
import threading
import time
from pathlib import Path

PIN_ORDER = [4, 5, 6, 7, 15, 17, 1, 2, 18, 8, 3, 9]
BASE = {4: 2000, 5: 1800, 6: 2200, 7: 1900, 15: 2100,
        17: 2050, 1: 1950, 2: 2150, 18: 1850, 8: 2000, 3: 1500, 9: 1500}

# (seconds, pins covered by the tube)
SCENARIO = [
    (2.0, set()),
    (1.0, {4}),
    (1.5, {4, 5, 6}),
    (1.2, {4, 5, 6, 7, 15}),
    (0.8, {4, 5, 6}),
    (0.6, {4}),
    (2.5, set()),
    (1.5, {4, 5}),          # shallow attempt, 9 cm only on one side
    (2.0, set()),
]


def _thresholds() -> dict[int, int]:
    cfg_path = Path(__file__).resolve().parent.parent / "pins_config.json"
    try:
        cfg = json.loads(cfg_path.read_text())
    except Exception:
        cfg = {}
    d = int(cfg.get("trigger_delta_default", 120))
    over = {int(k): int(v) for k, v in cfg.get("trigger_delta_overrides", {}).items()}
    return {p: over.get(p, d) for p in PIN_ORDER}


def covered_at(t: float) -> set:
    total = sum(d for d, _ in SCENARIO)
    t %= total
    for dur, pins in SCENARIO:
        if t < dur:
            return pins
        t -= dur
    return set()


def frame(t: float, thr: dict, noise: float, spikes: float, rng: random.Random) -> str:
    cov = covered_at(t)
    out = []
    for pin in PIN_ORDER:
        v = BASE[pin]
        if pin in cov:
            v -= int(thr[pin] * 2.2)            # tube shadows the IR beam
        v += int(rng.gauss(0, thr[pin] * noise))
        if rng.random() < spikes:
            v += rng.choice((-1, 1)) * rng.randint(200, 600)
        out.append(f"pin{pin}:{max(0, min(4095, v))}")
    return ",".join(out)


# --replay: real frames recorded on the trainer, (file, seconds) per step
REPLAY = [("pos1_out", 3.0), ("pos2_entry", 1.5), ("pos3_9cm", 1.5), ("pos4_11cm", 2.0),
          ("pos3_9cm", 1.0), ("pos2_entry", 0.5), ("pos1_out", 3.0)]


def _replay_frames():
    import csv
    base = Path(__file__).resolve().parent.parent / "calib_samples"
    segs = []
    for name, secs in REPLAY:
        with (base / f"{name}.csv").open() as fh:
            rows = list(csv.DictReader(fh))
        segs.append((rows, secs))
    while True:
        for rows, secs in segs:
            for i in range(int(secs * 50)):
                r = rows[i % len(rows)]
                yield ",".join(f"pin{p}:{r[f'pin{p}']}" for p in PIN_ORDER)


def serve(port: int, noise: float, spikes: float, hz: int, seed: int | None,
          replay: bool = False) -> None:
    rng = random.Random(seed)
    thr = _thresholds()
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(1)
    print(f"fake ESP on socket://127.0.0.1:{port}  thr={thr}  noise={noise} spikes={spikes}")
    while True:
        conn, _ = srv.accept()
        print("client connected")
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        threading.Thread(target=_drain, args=(conn,), daemon=True).start()
        t0 = time.monotonic()
        period = 1.0 / (50 if replay else hz)
        nxt = t0
        frames = _replay_frames() if replay else None
        try:
            while True:
                now = time.monotonic()
                line = next(frames) if replay else frame(now - t0, thr, noise, spikes, rng)
                conn.sendall((line + "\r\n").encode())
                nxt += period
                time.sleep(max(0.0, nxt - time.monotonic()))
        except OSError:
            print("client gone")


def _drain(conn):
    try:
        while True:
            data = conn.recv(256)
            if not data:
                return
            print("rx:", data.decode(errors="replace").strip())
    except OSError:
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=7777)
    ap.add_argument("--noise", type=float, default=0.35, help="σ as fraction of threshold")
    ap.add_argument("--spikes", type=float, default=0.01, help="per-sample spike probability")
    ap.add_argument("--hz", type=int, default=100)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--replay", action="store_true", help="loop calib_samples/pos*.csv")
    a = ap.parse_args()
    serve(a.port, a.noise, a.spikes, a.hz, a.seed, a.replay)
