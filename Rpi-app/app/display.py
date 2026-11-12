"""Display profiles: pick per-screen settings automatically from the screen size.

The UI was laid out for the Raspberry Pi Touch Display 2 (5", used at 853×480).
Other screens get the same layout scaled up or down. Known screens have a
profile with their own values; anything else gets a scale derived from its size.

Override in app_settings.ini:

    [display]
    profile = auto          ; auto | touch2-5in | edatec-7in
    scale =                 ; optional number, e.g. 1.15, wins over the profile

or with the environment variable SUCTION_DISPLAY=<profile name>.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

BASE_W, BASE_H = 853, 480   # size the v2 layout was designed for


@dataclass(frozen=True)
class DisplayProfile:
    name: str
    label: str
    size: tuple[int, int] | None   # logical screen size (w, h) seen by Tk; None = any
    scale: float                   # multiplier for fonts and fixed pixel sizes
    has_speaker: bool = False      # built-in speaker available for alert sounds
    has_buzzer: bool = False


PROFILES = {
    "touch2-5in": DisplayProfile(
        "touch2-5in", 'Raspberry Pi Touch Display 2 (5")', (853, 480), 1.0),
    "edatec-7in": DisplayProfile(
        "edatec-7in", 'EDATEC ED-HMI3020-070C (7")', (1024, 600), 1.2,
        has_speaker=True, has_buzzer=True),
}

_TOLERANCE = 0.04   # 4 % size tolerance when matching a known screen
MIN_SCALE, MAX_SCALE = 0.75, 2.5


def _matches(size: tuple[int, int], w: int, h: int) -> bool:
    pw, ph = size
    for a, b in ((w, h), (h, w)):   # accept either orientation
        if abs(a - pw) <= pw * _TOLERANCE and abs(b - ph) <= ph * _TOLERANCE:
            return True
    return False


def fit_scale(w: int, h: int) -> float:
    """Scale that fits the base layout into a w×h landscape screen."""
    lw, lh = max(w, h), min(w, h)
    s = min(lw / BASE_W, lh / BASE_H)
    return round(max(MIN_SCALE, min(MAX_SCALE, s)), 2)


def detect(w: int, h: int, profile: str = "auto", scale_override: float | None = None) -> DisplayProfile:
    """Return the profile for a w×h screen.

    profile: "auto" or a key of PROFILES (forced). scale_override replaces the
    profile's scale when given.
    """
    chosen = None
    if profile and profile != "auto":
        chosen = PROFILES.get(profile)
    if chosen is None:
        chosen = next((p for p in PROFILES.values() if p.size and _matches(p.size, w, h)), None)
    if chosen is None:
        chosen = DisplayProfile("generic", f"Generic {w}x{h}", (w, h), fit_scale(w, h))
    if scale_override:
        s = max(MIN_SCALE, min(MAX_SCALE, float(scale_override)))
        chosen = DisplayProfile(chosen.name, chosen.label, chosen.size, s, chosen.has_speaker, chosen.has_buzzer)
    return chosen


def detect_from_settings(w: int, h: int) -> DisplayProfile:
    """detect() using SUCTION_DISPLAY / app_settings.ini [display]."""
    from . import settings
    profile = os.environ.get("SUCTION_DISPLAY") or settings.get_display_profile()
    return detect(w, h, profile, settings.get_display_scale())
