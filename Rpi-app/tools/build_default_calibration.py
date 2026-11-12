"""Build calibration_default.json from position recordings on the trainer.

    python tools/build_default_calibration.py

Inputs (calib_samples/, recorded with the tube held still at each position):
    pos1_out.csv  pos2_entry.csv  pos3_9cm.csv  pos4_11cm.csv

For every role pin the trigger is 40 % of its *smallest* change over the
positions where it should read "tube" (so a shallow / off-centre tube still
clears it early), floored at a few times the measured noise.
"""
from __future__ import annotations

import csv
import json
import statistics as st
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SAMPLES = HERE / "calib_samples"
OUT = HERE / "calibration_default.json"

# Mapping found from the recordings on 2026-10-03 (see calib_samples/):
#   GPIO 17, 18 drop 3000+ at the entry and stay low while the tube is inside;
#   GPIO 6 is the only pin that moves at 9 cm (small, −8);
#   GPIO 7, 15 move only at 11 cm. GPIO 4 (Cap) is unconnected, GPIO 5 saturated.
ROLES = {"entry": [17, 18], "d9": [6], "d11": [7, 15]}
POSITIONS = {"out": "pos1_out.csv", "entry": "pos2_entry.csv",
             "9cm": "pos3_9cm.csv", "11cm": "pos4_11cm.csv"}
# positions where a pin of each role must read "tube"
ACTIVE_AT = {"entry": ["entry", "9cm", "11cm"], "d9": ["9cm", "11cm"], "d11": ["11cm"]}
TRIGGER_FRAC = 0.4   # trigger at 40 % of the smallest tube change
NOISE_K = 4          # trigger ≥ NOISE_K × noise sd
MIN_THR = 3          # ADC


def _load(name: str) -> list[dict]:
    with (SAMPLES / name).open() as fh:
        return list(csv.DictReader(fh))


def build() -> dict:
    data = {pos: _load(f) for pos, f in POSITIONS.items()}
    thresholds, levels, report = {}, {}, {}
    for role, pins in ROLES.items():
        for pin in pins:
            col = f"pin{pin}"
            lvl = {pos: st.mean(int(r[col]) for r in rows) for pos, rows in data.items()}
            noise = max(st.pstdev(int(r[col]) for r in rows) for rows in data.values())
            active = ACTIVE_AT[role]
            weakest = min(active, key=lambda pos: abs(lvl[pos] - lvl["out"]))
            delta = lvl[weakest] - lvl["out"]
            thr = max(abs(delta) * TRIGGER_FRAC, NOISE_K * noise, MIN_THR)
            # tube-in levels: weakest first (sets Δ / direction), then the others
            ins = [weakest] + [p for p in active if p != weakest]
            thresholds[str(pin)] = int(round(thr))
            levels[str(pin)] = [int(round(lvl["out"]))] + [int(round(lvl[p])) for p in ins]
            report[str(pin)] = {
                "role": role,
                "levels": {k: int(round(v)) for k, v in lvl.items()},
                "smallest_change": int(round(delta)),
                "noise_sd": round(noise, 2),
                "signal_to_noise": round(abs(delta) / max(noise, 0.5), 1),
            }
    return {
        "_comment": "Factory calibration from position recordings (tools/build_default_calibration.py). "
                    "Loaded from the Calibrate screen ('Load factory defaults'); auto-calibrate overrides it.",
        "recorded_at": "2026-10-03",
        "enabled_pins": sorted({p for pins in ROLES.values() for p in pins}),
        "roles": ROLES,
        "trigger_delta_overrides": thresholds,
        "calibrated_levels": levels,
        "report": report,
    }


if __name__ == "__main__":
    cfg = build()
    OUT.write_text(json.dumps(cfg, indent=2) + "\n")
    print(f"wrote {OUT.name}")
    for pin, r in cfg["report"].items():
        print(f"  GPIO {pin:>2} {r['role']:<5}  levels {r['levels']}  "
              f"Δmin {r['smallest_change']:+5d}  noise {r['noise_sd']:4.1f}  "
              f"S/N {r['signal_to_noise']:6.1f}  trigger ±{cfg['trigger_delta_overrides'][pin]}")
