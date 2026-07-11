"""Suction Trainer — Raspberry Pi app entry point.

Run on the Pi:            python3 main.py
Run without hardware:     SUCTION_SIM=1 python3 main.py
Force a faulted sensor:   SUCTION_SIM=1 SUCTION_SIM_FAULT=2 python3 main.py
"""
import os
import sys

# On the Pi, force the local screen. Skip on macOS/Windows (Tk uses its own
# display there) and never override a DISPLAY the user already set (e.g. SSH X11).
if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
    os.environ["DISPLAY"] = ":0"

from app.ui.app import SuctionApp


def main():
    SuctionApp().mainloop()


if __name__ == "__main__":
    main()
