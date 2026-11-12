#!/bin/sh
# Boot launcher for Suction Trainer (called from ~/.config/autostart/Suction.desktop).
# Runs on top of the normal desktop: Exit / Esc closes the app and leaves the
# desktop, panel and file manager usable. main.py's lock stops double launches.
HERE="$(cd "$(dirname "$0")" && pwd)"
LOG="${XDG_CACHE_HOME:-$HOME/.cache}/suction-trainer.log"
mkdir -p "$(dirname "$LOG")"

export DISPLAY="${DISPLAY:-:0}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

# Let labwc's own autostart (wlr-randr output scaling at +2 s) settle first,
# so the window is sized for the final screen geometry.
sleep "${SUCTION_START_DELAY:-4}"

cd "$HERE" || exit 1
echo "=== $(date '+%F %T') start" >> "$LOG"
exec "$HERE/../venv/bin/python" "$HERE/main.py" >> "$LOG" 2>&1
