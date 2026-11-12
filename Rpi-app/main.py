"""Suction Trainer — Raspberry Pi app entry point.

Run on the Pi:            python3 main.py
Run without hardware:     SUCTION_SIM=1 python3 main.py
Force a faulted sensor:   SUCTION_SIM=1 SUCTION_SIM_FAULT=2 python3 main.py
Fake ESP over TCP:        python3 tools/fake_esp.py  &  SUCTION_PORT=socket://127.0.0.1:7777 python3 main.py
UI version:               app_settings.ini → [ui] version = v2 | legacy (switchable in the app)
"""
import os
import sys

# On the Pi, force the local screen. Skip on macOS/Windows (Tk uses its own
# display there) and never override a DISPLAY the user already set (e.g. SSH X11).
if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
    os.environ["DISPLAY"] = ":0"


def _single_instance():
    """Return a held lock, or None if another copy is already running.

    Two copies (autostart + a tap on the desktop icon) both open the ESP's
    serial port and each receives only part of the stream, so live values
    go stale and blink.
    """
    try:
        import fcntl
    except ImportError:          # Windows: no lock, dev use only
        return True
    lock_dir = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    fh = open(os.path.join(lock_dir, "suction-trainer.lock"), "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


def main():
    lock = _single_instance()
    if lock is None:
        print("Suction Trainer is already running.", file=sys.stderr)
        sys.exit(0)
    # UI version is remembered in app_settings.ini (v2 = new default, legacy = old UI)
    from app.settings import get_ui_version
    if get_ui_version() == "legacy":
        from app.ui.app import SuctionApp as App
    else:
        from app.ui2.app import App2 as App
    App().mainloop()


if __name__ == "__main__":
    main()
