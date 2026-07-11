"""Data-driven scoring engine.

Reads weights + bands from scoring_config.json (via config.py) and turns a
SessionMetrics into a ScoreResult. Editing weights/thresholds in the UI
changes scoring here with no code edit.

Model (matches the accepted rubric):
  * each category earns ``weight * fraction`` where ``fraction`` comes from
    the band the metric falls into (1.0 / 0.5 / 0.0 today);
  * the total is ``raw / available * 100``;
  * an ``optional`` category (pressure) drops out of ``available`` when its
    metric is missing, so a missing pressure reading neither helps nor hurts.
"""
from __future__ import annotations

from typing import Optional

from .models import CategoryScore, ScoreResult, SessionMetrics


def _metric_value(metrics: SessionMetrics, name: str) -> Optional[float]:
    return {
        "maxDepthCm": float(metrics.max_depth_cm),
        "durationSec": metrics.duration_sec,
        "pressureMmHg": metrics.pressure_mmhg,
        "contactEvents": float(metrics.contact_events),
    }.get(name)


def _fraction_bands(value: float, bands: list) -> tuple:
    for band in bands:
        upper = band.get("max")
        if upper is None or value <= upper:
            return float(band["fraction"]), band.get("label", "")
    return 0.0, ""


def _fraction_range_bands(value: float, bands: list) -> tuple:
    for band in bands:
        lo, hi = band.get("min"), band.get("max")
        if (lo is None or value >= lo) and (hi is None or value <= hi):
            return float(band["fraction"]), band.get("label", "")
    return 0.0, ""


def _level_for(total: int, levels: list) -> tuple:
    for level in sorted(levels, key=lambda x: x["min"], reverse=True):
        if total >= level["min"]:
            return level["label"], level.get("note", "")
    return "", ""


def score_session(metrics: SessionMetrics, cfg: dict) -> ScoreResult:
    weights = cfg["weights"]
    categories = cfg["categories"]

    results = []
    raw = 0.0
    available = 0.0

    for key, spec in categories.items():
        weight = float(weights.get(key, 0))
        value = _metric_value(metrics, spec["metric"])
        optional = spec.get("optional", False)
        not_measured = value is None or (key == "duration" and value == 0)

        if optional and (metrics.pressure_available is False or value is None):
            results.append(CategoryScore(key, 0.0, weight, "Not scored", available=False))
            continue
        if not_measured:
            results.append(CategoryScore(key, 0.0, weight, "Not measured", available=True))
            available += weight
            continue

        if "range_bands" in spec:
            fraction, label = _fraction_range_bands(value, spec["range_bands"])
        else:
            fraction, label = _fraction_bands(value, spec["bands"])

        points = weight * fraction
        raw += points
        available += weight
        results.append(CategoryScore(key, points, weight, label, available=True))

    total = round(raw / available * 100) if available > 0 else 0
    level, note = _level_for(total, cfg["levels"])

    return ScoreResult(
        total=total,
        level=level,
        note=note,
        categories=results,
        raw_score=round(raw, 1),
        available_score=round(available, 1),
    )
