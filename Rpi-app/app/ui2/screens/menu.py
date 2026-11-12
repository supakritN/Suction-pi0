"""☰ menu overlay: calibration, factory defaults, switch to the legacy UI."""
import tkinter as tk

from .. import style as S
from ...serial_node import apply_default_calibration, calibration_summary


def open_menu(app):
    if getattr(app, "_menu", None) is not None and app._menu.winfo_exists():
        app._menu.destroy()
        app._menu = None
        return
    # Tk has no translucent overlays: show just the panel over the screen.
    panel = tk.Frame(app, bg=S.BG, highlightthickness=1, highlightbackground=S.ACCENT)
    panel.place(relx=1, rely=0, x=-12, y=40, anchor="ne", width=360)
    panel.lift()
    app._menu = panel

    def close():
        panel.destroy()
        app._menu = None

    def go(fn):
        close()
        fn()

    S.tag(panel, "Menu").pack(anchor="w", padx=16, pady=(12, 2))
    S.label(panel, f"Calibration: {calibration_summary()}", 11, fg=S.MUTED,
            wraplength=320, justify="left").pack(anchor="w", padx=16, pady=(0, 8))

    def item(text, fn, kind="secondary"):
        S.button(panel, text, lambda: go(fn), kind=kind, size=13, pady=8).pack(
            fill="x", padx=16, pady=3)

    item("Auto calibrate (factory + regression)", lambda: app.show("calibrate"))
    item("Use factory defaults", lambda: (apply_default_calibration(), app.show("name")))
    item("Switch to legacy UI", app.switch_to_legacy)
    item("Exit app", app.quit_app, kind="ghost")
    S.button(panel, "Close", close, kind="ghost", size=11, pady=4).pack(pady=(0, 10))
