"""v2 UI root window: name → practice (offline, factory calibration) → results.

Same SensorNode / detector / scoring as the legacy UI; only the screens differ.
Settings live behind the ☰ menu (auto-calibrate, factory defaults, switch UI).
"""
from __future__ import annotations

import os
import tkinter as tk
import traceback

from ..serial_node import SensorNode
from .. import display, settings
from . import style as S
from .screens import calibrate, menu, name, practice, results

SCREENS = {
    "name": name.render,
    "practice": practice.render,
    "results": results.render,
    "calibrate": calibrate.render,
}


class App2(tk.Tk):
    def __init__(self):
        super().__init__()
        try:
            self.wm_class("SuctionTrainer", "SuctionTrainer")
        except Exception:
            pass
        self.title("Suction Trainer")
        self.configure(bg=S.BG)
        self.bind("<Escape>", lambda e: self.quit_app())

        self.update_idletasks()
        test_geom = os.environ.get("SUCTION_GEOMETRY")
        if test_geom:
            self.geometry(test_geom)
        else:
            self.geometry(f"{self.winfo_screenwidth()}x{self.winfo_screenheight()}+0+0")
            self._go_fullscreen()
            self.after(200, self._go_fullscreen)

        # per-screen sizing: Touch Display 2 (5") is the 1.0 baseline; other
        # screens (e.g. EDATEC 7") pick their own profile automatically
        self.update_idletasks()
        self.display = display.detect_from_settings(self.winfo_screenwidth(), self.winfo_screenheight())
        S.set_scale(self.display.scale)
        print(f"[display] {self.display.label} -> scale {self.display.scale}")

        # session state (offline only)
        self.username = None
        self.mode = "offline"
        self.room = None
        self.last_metrics = None
        self.last_score = None
        self.last_csv = None
        self._poll_id = None

        self.node = SensorNode()
        self.node.start()

        header = tk.Frame(self, bg=S.BG, height=S.px(34))
        header.pack(fill="x")
        header.pack_propagate(False)
        S.tag(header, "LARICE / PRESS-04 · Suction trainer").pack(side="left", padx=S.px(14))
        tk.Button(header, text="✕", command=self.quit_app, bg=S.BG, fg=S.MUTED, bd=0,
                  relief="flat", activebackground=S.BG, font=S.f(13),
                  cursor="hand2").pack(side="right", padx=(4, 10))
        tk.Button(header, text="☰ MENU", command=lambda: menu.open_menu(self), bg=S.BG,
                  fg=S.ACCENT, bd=0, relief="flat", activebackground=S.BG, activeforeground=S.INK,
                  font=S.f(11, "bold"), cursor="hand2").pack(side="right", padx=6)
        self.meta = S.tag(header, "")
        self.meta.pack(side="right", padx=10)
        tk.Frame(self, bg=S.LINE, height=1).pack(fill="x")

        self.container = tk.Frame(self, bg=S.BG)
        self.container.pack(fill="both", expand=True)
        self.show("name")

    # ── navigation ──
    def show(self, screen, **kw):
        self.clear_poll()
        for w in self.container.winfo_children():
            w.destroy()
        self.meta.config(text=(self.username or "").upper())
        SCREENS[screen](self, self.container, **kw)

    def set_poll(self, ms, fn):
        self.clear_poll()

        def tick():
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

    def switch_to_legacy(self):
        settings.switch_ui("legacy", self)

    def _go_fullscreen(self):
        try:
            self.attributes("-fullscreen", True)
        except tk.TclError:
            self.overrideredirect(True)
            self.geometry(f"{self.winfo_screenwidth()}x{self.winfo_screenheight()}+0+0")

    def quit_app(self):
        self.clear_poll()
        self.node.stop()
        self.destroy()
