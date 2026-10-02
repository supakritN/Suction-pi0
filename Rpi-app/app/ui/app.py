"""Main application window and screen manager.

A single Tk root hosts a container frame; ``show(name, **kw)`` swaps the
screen inside it. Shared session state (username, mode, room, last result,
the sensor node) lives on the app instance so screens stay stateless.
"""
from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path

from ..serial_node import SensorNode
from . import theme

_ICON_CANDIDATES = [
    "/home/local/.local/share/icons/suction-trainer.png",
    str(Path(__file__).resolve().parent.parent.parent / "assets" / "icon.png"),
]
from .screens import (
    calibrate,
    history,
    mode_select,
    name as name_screen,
    preparation,
    process,
    results,
    room,
    settings,
)

SCREENS = {
    "name": name_screen.render,
    "mode_select": mode_select.render,
    "preparation": preparation.render,
    "calibrate": calibrate.render,
    "process": process.render,
    "results": results.render,
    "history": history.render,
    "room": room.render,
    "settings": settings.render,
}


class SuctionApp(tk.Tk):
    def __init__(self):
        super().__init__()
        # WM class — taskbars match this against the .desktop file's
        # StartupWMClass to show the correct icon.
        try:
            self.wm_class("SuctionTrainer", "SuctionTrainer")
        except Exception:
            pass
        self.title("Suction Trainer")
        self.configure(bg=theme.BG)
        self.bind("<Escape>", lambda e: self.quit_app())
        # Window icon (keep PhotoImage ref so it isn't GC'd)
        for p in _ICON_CANDIDATES:
            if not os.path.exists(p):
                continue
            try:
                self._icon_img = tk.PhotoImage(file=p)
                self.wm_iconphoto(True, self._icon_img)
                break
            except Exception:
                continue

        # Force the window to the real screen size, then assert fullscreen.
        # On the Pi's window manager (and over VNC) a fullscreen request made
        # before the window is mapped is silently ignored, so we also re-assert
        # it once the event loop has realized the window.
        self.update_idletasks()
        geom = self._preferred_geometry()
        self.geometry(geom)
        self._go_fullscreen()
        self.after(200, self._go_fullscreen)

        # shared session state
        self.username = None
        self.mode = None                 # offline | create | join
        self.room = None                 # {"role":"host","server":..} / {"role":"client","client":..,"host":ip}
        self.last_metrics = None
        self.last_score = None
        self.last_csv = None
        self._poll_id = None

        self.node = SensorNode()
        self.node.start()

        # header bar
        header = tk.Frame(self, bg=theme.SURFACE, height=54)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="Suction Trainer", bg=theme.SURFACE, fg=theme.TEXT,
                 font=theme.font(16, "bold")).pack(side="left", padx=18)
        tk.Button(header, text="✕ Exit", command=self.quit_app, bg=theme.SURFACE,
                  fg=theme.MUTED, activebackground=theme.SURFACE, activeforeground=theme.TEXT,
                  relief="flat", bd=0, font=theme.SMALL, cursor="hand2").pack(side="right", padx=12)
        self.meta = tk.Label(header, text="", bg=theme.SURFACE, fg=theme.MUTED, font=theme.SMALL)
        self.meta.pack(side="right", padx=8)

        # screen container
        self.container = tk.Frame(self, bg=theme.BG)
        self.container.pack(fill="both", expand=True)

        self.show("name")

    # -- navigation ----------------------------------------------------
    def show(self, name, **kw):
        self.clear_poll()
        for w in self.container.winfo_children():
            w.destroy()
        self._update_meta()
        SCREENS[name](self, self.container, **kw)

    def _update_meta(self):
        bits = []
        if self.username:
            bits.append(self.username)
        if self.room:
            role = "host" if self.room.get("role") == "host" else "room"
            addr = self.room.get("host") or (self.room.get("server").ip if self.room.get("server") else "")
            bits.append(f"{role} {addr}")
        self.meta.config(text="    ·    ".join(bits))

    # -- single repeating poll (used by live screens) ------------------
    def set_poll(self, ms, fn):
        self.clear_poll()

        def tick():
            fn()
            self._poll_id = self.after(ms, tick)

        self._poll_id = self.after(ms, tick)

    def clear_poll(self):
        if self._poll_id is not None:
            try:
                self.after_cancel(self._poll_id)
            except Exception:
                pass
            self._poll_id = None

    def _preferred_geometry(self) -> str:
        """
        Prefer the HDMI output when it's connected (wireless HDMI, external
        monitor, etc.). If only the built-in DSI touchscreen is present,
        fall back to the primary display.

        Honors SUCTION_OUTPUT=<name> to force a specific output.
        """
        import subprocess, re, os
        prefer = os.environ.get("SUCTION_OUTPUT")  # e.g. "HDMI-A-1" or "DSI-1"
        try:
            txt = subprocess.check_output(["wlr-randr"], text=True,
                                          stderr=subprocess.DEVNULL, timeout=1.5)
        except Exception:
            txt = ""
        outputs = []
        cur = None
        for line in txt.splitlines():
            m = re.match(r"^(\S+)\s+\"", line)
            if m:
                cur = {"name": m.group(1)}
                outputs.append(cur)
                continue
            if cur is None:
                continue
            m = re.match(r"\s+Position:\s+(\d+),(\d+)", line)
            if m:
                cur["x"] = int(m.group(1)); cur["y"] = int(m.group(2))
            m = re.match(r"\s+([\d]+)x([\d]+)\s+px.*\(preferred, current\)", line)
            if m:
                cur["w"] = int(m.group(1)); cur["h"] = int(m.group(2))

        chosen = None
        if prefer:
            chosen = next((o for o in outputs if o.get("name") == prefer), None)
        if not chosen:
            # Prefer HDMI if present, else first output
            chosen = next((o for o in outputs if "HDMI" in o.get("name", "")), None)
            if not chosen and outputs:
                chosen = outputs[0]

        if chosen and {"x", "y", "w", "h"} <= chosen.keys():
            return f"{chosen['w']}x{chosen['h']}+{chosen['x']}+{chosen['y']}"
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        return f"{sw}x{sh}+0+0"

    def _go_fullscreen(self):
        """Assert true fullscreen; ignore WMs that don't support the attribute."""
        try:
            self.attributes("-fullscreen", True)
        except tk.TclError:
            # Fallback for window managers without -fullscreen support.
            self.overrideredirect(True)
            self.geometry(self._preferred_geometry())

    def quit_app(self):
        self.clear_poll()
        self.node.stop()
        self.destroy()
