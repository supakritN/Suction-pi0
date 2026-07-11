"""Typed data models shared across the app.

These are the shapes that cross module boundaries: the serial node parses
frames into SensorStatus / LiveSample / SessionMetrics; scoring turns
metrics into a ScoreResult; rooms track an Attendee per participant.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SensorStatus:
    id: str
    ok: bool
    label: str = ""


@dataclass
class LiveSample:
    depth_cm: int = 0
    pressure_mmhg: Optional[float] = None
    elapsed_ms: int = 0
    contact_events: int = 0
    phase: str = "idle"      # idle | insert | suction | done


@dataclass
class SessionMetrics:
    max_depth_cm: int = 0
    total_time_ms: int = 0
    pressure_mmhg: Optional[float] = None
    pressure_available: bool = False
    contact_events: int = 0
    contact_band_count: int = 0

    @property
    def duration_sec(self) -> float:
        return self.total_time_ms / 1000.0

    def to_dict(self) -> dict:
        return {
            "maxDepthCm": self.max_depth_cm,
            "totalTimeMs": self.total_time_ms,
            "pressureMmHg": self.pressure_mmhg,
            "pressureAvailable": self.pressure_available,
            "contactEvents": self.contact_events,
            "contactBandCount": self.contact_band_count,
        }

    @staticmethod
    def from_dict(d: dict) -> "SessionMetrics":
        return SessionMetrics(
            max_depth_cm=int(d.get("maxDepthCm", 0)),
            total_time_ms=int(d.get("totalTimeMs", 0)),
            pressure_mmhg=d.get("pressureMmHg"),
            pressure_available=bool(d.get("pressureAvailable", d.get("pressureMmHg") is not None)),
            contact_events=int(d.get("contactEvents", 0)),
            contact_band_count=int(d.get("contactBandCount", 0)),
        )


@dataclass
class CategoryScore:
    key: str
    points: float
    max_points: float
    label: str
    available: bool = True


@dataclass
class ScoreResult:
    total: int
    level: str
    note: str
    categories: list = field(default_factory=list)
    raw_score: float = 0.0
    available_score: float = 0.0


@dataclass
class Attendee:
    username: str
    time_sec: Optional[float] = None
    score: Optional[int] = None
    level: Optional[str] = None
    finished: bool = False

    def to_dict(self) -> dict:
        return {
            "username": self.username,
            "time_sec": self.time_sec,
            "score": self.score,
            "level": self.level,
            "finished": self.finished,
        }
