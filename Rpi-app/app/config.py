"""Load/save the UI-editable scoring configuration.

Everything an instructor can tune (category weights, band thresholds,
level cut-points, the settings PIN) lives in scoring_config.json next to
main.py, so none of it needs a code change or a firmware reflash.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "scoring_config.json"
_lock = threading.Lock()


def config_path() -> Path:
    return _CONFIG_PATH


def load_config() -> dict:
    with _lock:
        with _CONFIG_PATH.open("r", encoding="utf-8") as fh:
            return json.load(fh)


def save_config(cfg: dict) -> None:
    with _lock:
        tmp = _CONFIG_PATH.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
            fh.write("\n")
        tmp.replace(_CONFIG_PATH)


def update_weights(weights: dict) -> dict:
    cfg = load_config()
    for key, value in weights.items():
        if key in cfg["weights"]:
            cfg["weights"][key] = int(value)
    save_config(cfg)
    return cfg


def check_pin(pin: str) -> bool:
    settings = load_config().get("settings", {})
    if not settings.get("pin_required", True):
        return True
    return str(pin) == str(settings.get("instructor_pin", ""))
