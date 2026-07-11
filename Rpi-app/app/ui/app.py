"""Main application window and screen manager.

A single Tk root hosts a container frame; ``show(name, **kw)`` swaps the
screen inside it. Shared session state (username, mode, room, last result,
the sensor node) lives on the app instance so screens stay stateless.
"""
from __future__ import annotations

import tkinter as tk

from ..serial_node import SensorNode
from . import theme
from .screens import (
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
    "process": process.render,
    "results": results.render,
    "room": room.render,
    "settings": settings.render,
}


class SuctionApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Suction Trainer")
        try:
            self.attributes("-fullscreen", True)
        except Exception:
            self.geometry("1024x600")
        self.configure(bg=theme.BG)
        self.bind("<Escape>", lambda e: self.quit_app())

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

    def quit_app(self):
        self.clear_poll()
        self.node.stop()
        self.destroy()
