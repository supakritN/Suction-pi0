"""Append each finished run to a CSV the instructor can open in Excel.

Two files, both next to main.py:
  * ``results.csv``      — every run made on this device (offline or in a room)
  * ``room_results.csv`` — on a host, every attendee's result received in rooms

One row per run, with the total, the per-category points, and the raw metrics.
"""
from __future__ import annotations

import csv
import datetime
from pathlib import Path

from .models import ScoreResult, SessionMetrics

_BASE = Path(__file__).resolve().parent.parent
RESULTS_PATH = _BASE / "results.csv"
ROOM_RESULTS_PATH = _BASE / "room_results.csv"

FIELDS = [
    "timestamp", "name", "mode", "room", "total", "level",
    "depth_pts", "duration_pts", "pressure_pts", "contact_pts",
    "max_depth_cm", "total_time_s", "pressure_mmhg", "contact_events",
]


def log_result(name: str, mode, room, metrics: SessionMetrics,
               score: ScoreResult, path: Path = RESULTS_PATH) -> Path:
    cats = {c.key: c for c in score.categories}

    def pts(key):
        c = cats.get(key)
        if c is None or not c.available:
            return ""
        return round(c.points)

    row = {
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "name": name,
        "mode": mode or "offline",
        "room": room or "",
        "total": score.total,
        "level": score.level,
        "depth_pts": pts("depth"),
        "duration_pts": pts("duration"),
        "pressure_pts": pts("pressure"),
        "contact_pts": pts("contact"),
        "max_depth_cm": metrics.max_depth_cm,
        "total_time_s": round(metrics.total_time_ms / 1000, 2),
        "pressure_mmhg": "" if metrics.pressure_mmhg is None else metrics.pressure_mmhg,
        "contact_events": metrics.contact_events,
    }

    path = Path(path)
    is_new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow(row)
    return path
