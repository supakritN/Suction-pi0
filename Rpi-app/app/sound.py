"""Alert sounds (cough when the catheter hits / goes too deep).

app_settings.ini:

    [sound]
    mode = both        ; local | remote | both | off
    port = 8766        ; TCP port for remote listeners (bound to localhost)

local  : play on this device (3.5 mm jack / built-in speaker) with pw-play or aplay.
remote : VNC carries no audio, so a listener on the viewing machine connects here
         (through the same ssh tunnel: ssh -L 8766:localhost:8766 pi0) and plays
         the sound itself — see tools/sound_listener.py. The Pi only sends one
         short line per event, so it costs nothing.
"""
from __future__ import annotations

import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

from . import cough_wav

WAV = Path(__file__).resolve().parent / "assets" / "cough.wav"
MODES = ("local", "remote", "both", "off")
MIN_INTERVAL_S = 2.0


class SoundOut:
    def __init__(self, mode: str = "both", port: int = 8766, play_cmd: list[str] | None = None):
        self.mode = mode if mode in MODES else "both"
        self.port = port
        self._last: dict[str, float] = {}
        self._clients: list[socket.socket] = []
        self._lock = threading.Lock()
        self._server: socket.socket | None = None
        self._play_cmd = play_cmd if play_cmd is not None else self._find_player()
        if self.mode in ("local", "both"):
            try:
                cough_wav.ensure(WAV)
            except OSError as e:
                print(f"[sound] cannot write {WAV}: {e}")
        if self.mode in ("remote", "both"):
            self._start_server()

    # ── public ──
    def cough(self) -> bool:
        return self.event("cough")

    def event(self, name: str) -> bool:
        """Play / forward one event; repeated events inside MIN_INTERVAL_S are dropped."""
        now = time.monotonic()
        if self.mode == "off" or now - self._last.get(name, -1e9) < MIN_INTERVAL_S:
            return False
        self._last[name] = now
        if self.mode in ("local", "both"):
            self._play_local()
        if self.mode in ("remote", "both"):
            self._broadcast(name)
        return True

    def close(self) -> None:
        with self._lock:
            for c in self._clients:
                try:
                    c.close()
                except OSError:
                    pass
            self._clients.clear()
        if self._server:
            try:
                self._server.close()
            except OSError:
                pass

    # ── local ──
    @staticmethod
    def _find_player() -> list[str]:
        for cmd in (["pw-play"], ["aplay", "-q"], ["paplay"], ["afplay"]):
            if shutil.which(cmd[0]):
                return cmd
        return []

    def _play_local(self) -> None:
        if not self._play_cmd or not WAV.exists():
            return
        try:
            subprocess.Popen(self._play_cmd + [str(WAV)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            print(f"[sound] play failed: {e}")

    # ── remote ──
    def _start_server(self) -> None:
        try:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("127.0.0.1", self.port))
            srv.listen(4)
        except OSError as e:
            print(f"[sound] remote listener port {self.port} unavailable: {e}")
            return
        self._server = srv
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def _accept_loop(self) -> None:
        while self._server:
            try:
                c, _ = self._server.accept()
            except OSError:
                return
            c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            with self._lock:
                self._clients.append(c)

    def _broadcast(self, name: str) -> None:
        data = (name + "\n").encode()
        with self._lock:
            alive = []
            for c in self._clients:
                try:
                    c.sendall(data)
                    alive.append(c)
                except OSError:
                    try:
                        c.close()
                    except OSError:
                        pass
            self._clients = alive


_instance: SoundOut | None = None


def get() -> SoundOut:
    """Process-wide sound output configured from app_settings.ini."""
    global _instance
    if _instance is None:
        from . import settings
        _instance = SoundOut(settings.get_sound_mode(), settings.get_sound_port())
    return _instance
