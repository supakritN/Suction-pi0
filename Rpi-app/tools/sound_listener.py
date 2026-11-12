"""Play the trainer's alert sounds on the machine you watch it from (VNC has no audio).

1. Forward the port through the same tunnel you use for VNC/SSH:
       ssh -N -L 8766:localhost:8766 pi0
2. Run this on the viewing machine (stdlib only; macOS, Windows, Linux):
       python3 sound_listener.py            # connects to localhost:8766
       python3 sound_listener.py HOST PORT

It reconnects on its own if the trainer restarts or the tunnel drops.
"""
from __future__ import annotations

import os
import platform
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import cough_wav  # noqa: E402  (stdlib-only module, imported standalone)

WAV = Path(tempfile.gettempdir()) / "suction_cough.wav"


def play(path: Path) -> None:
    system = platform.system()
    if system == "Windows":
        import winsound
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
        return
    for cmd in (["afplay"], ["pw-play"], ["paplay"], ["aplay", "-q"]):
        try:
            subprocess.Popen(cmd + [str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except FileNotFoundError:
            continue
    print("\a", end="", flush=True)   # last resort: terminal bell


def main() -> None:
    host = sys.argv[1] if len(sys.argv) > 1 else "localhost"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8766
    cough_wav.ensure(WAV)
    print(f"listening for trainer sounds on {host}:{port} (Ctrl+C to stop)")
    while True:
        try:
            with socket.create_connection((host, port), timeout=5) as s:
                s.settimeout(None)
                print("connected")
                buf = b""
                while True:
                    chunk = s.recv(256)
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        if line.strip() == b"cough":
                            print(time.strftime("%H:%M:%S"), "cough")
                            play(WAV)
        except OSError:
            pass
        print("waiting for trainer…")
        time.sleep(3)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
