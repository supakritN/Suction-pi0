"""Main application window and screen manager.

A single Tk root hosts a container frame; ``show(name, **kw)`` swaps the
screen inside it. Shared session state (username, mode, room, last result,
the sensor node) lives on the app instance so screens stay stateless.
"""
from __future__ import annotations

import os
import tkinter as tk
import traceback
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
        test_geom = os.environ.get("SUCTION_GEOMETRY")   # e.g. 1280x720 for desktop testing
        if test_geom:
            self.geometry(test_geom)
        else:
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            self.geometry(f"{sw}x{sh}+0+0")
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
        tk.Button(header, text="New UI ↗", command=self.switch_to_new_ui, bg=theme.SURFACE,
                  fg=theme.ACCENT, activebackground=theme.SURFACE, activeforeground=theme.TEXT,
                  relief="flat", bd=0, font=theme.SMALL, cursor="hand2").pack(side="right", padx=4)
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
            # Reschedule first: an exception in fn() used to silently kill
            # the loop and freeze the live screen.
            self._poll_id = self.after(ms, tick)
            try:
                fn()
            except Exception:
                traceback.print_exc()

        self._poll_id = self.after(ms, tick)

    def clear_poll(self):
        if self._poll_id is not None:
            try:
                self.after_cancel(self._poll_id)
            except Exception:
                pass
            self._poll_id = None

    def _go_fullscreen(self):
        """Assert true fullscreen; ignore WMs that don't support the attribute."""
        try:
            self.attributes("-fullscreen", True)
        except tk.TclError:
            # Fallback for window managers without -fullscreen support.
            self.overrideredirect(True)
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            self.geometry(f"{sw}x{sh}+0+0")

    def switch_to_new_ui(self):
        from ..settings import switch_ui
        switch_ui("v2", self)

    def quit_app(self):
        self.clear_poll()
        self.node.stop()
        self.destroy()
