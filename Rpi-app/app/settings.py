"""App-level settings in app_settings.ini (next to main.py).

    [ui]
    version = v2        ; v2 (new, default) | legacy

The chosen UI is remembered across restarts and reboots.
"""
from __future__ import annotations

import configparser
import os
import sys
from pathlib import Path

_PATH = Path(__file__).resolve().parent.parent / "app_settings.ini"
UI_VERSIONS = ("v2", "legacy")
DEFAULT_UI = "v2"


def settings_path() -> Path:
    return _PATH


def _read() -> configparser.ConfigParser:
    cp = configparser.ConfigParser()
    try:
        cp.read(_PATH, encoding="utf-8")
    except configparser.Error:
        pass
    return cp


def get_ui_version() -> str:
    v = _read().get("ui", "version", fallback=DEFAULT_UI).strip().lower()
    return v if v in UI_VERSIONS else DEFAULT_UI


def get_display_profile() -> str:
    return _read().get("display", "profile", fallback="auto").strip().lower() or "auto"


def get_display_scale() -> float | None:
    raw = _read().get("display", "scale", fallback="").strip()
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def set_ui_version(version: str) -> None:
    if version not in UI_VERSIONS:
        raise ValueError(version)
    cp = _read()
    if not cp.has_section("ui"):
        cp.add_section("ui")
    cp.set("ui", "version", version)
    tmp = _PATH.with_suffix(".ini.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write("; Suction Trainer settings — ui version: v2 (new) | legacy\n")
        cp.write(fh)
    tmp.replace(_PATH)


def restart_app() -> None:
    """Re-exec main.py so the other UI starts with a clean process (serial
    port, single-instance lock and Tk are all released by the exec)."""
    main_py = Path(__file__).resolve().parent.parent / "main.py"
    os.execv(sys.executable, [sys.executable, str(main_py)])


def switch_ui(version: str, root=None) -> None:
    set_ui_version(version)
    if root is not None:
        try:
            root.node.stop()
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass
    restart_app()
