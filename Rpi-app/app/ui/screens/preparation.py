"""3.1 Preparation — sensor self-check. Ready appears only when all pass.
4.1 A quick tutorial pops up before the run starts.
"""
import tkinter as tk

from .. import theme
from .. import widgets as w


def render(app, parent, **kw):
    frame = tk.Frame(parent, bg=theme.BG)
    frame.pack(fill="both", expand=True, padx=48, pady=30)

    w.title(frame, "Preparing sensors").pack(anchor="w")
    w.subtitle(frame, "Checking the rig. Fix any faulted sensor and re-check.").pack(anchor="w", pady=(6, 18))

    card = w.card(frame)
    card.pack(fill="x")
    rows = tk.Frame(card, bg=theme.SURFACE)
    rows.pack(fill="x", padx=20, pady=12)

    status = tk.Label(frame, text="", bg=theme.BG, fg=theme.MUTED, font=theme.BODY, wraplength=820, justify="left")
    status.pack(anchor="w", pady=14)

    btns = tk.Frame(frame, bg=theme.BG)
    btns.pack(anchor="w")
    ready_btn = w.primary_button(btns, "Ready", lambda: _start(app))
    recheck_btn = w.button(btns, "Re-check", lambda: refresh())
    recheck_btn.pack(side="left")
    w.ghost_button(btns, "Back", lambda: _back(app)).pack(side="left", padx=(12, 0))

    def refresh():
        statuses = app.node.self_check()
        for child in rows.winfo_children():
            child.destroy()
        if not statuses:
            status.config(text="Waiting for sensor data from the ESP…", fg=theme.WARN)
            ready_btn.pack_forget()
            return
        for s in statuses:
            _sensor_row(rows, s)
        if all(s.ok for s in statuses):
            status.config(text="All sensors ready.", fg=theme.OK)
            ready_btn.pack(side="left", padx=(0, 12), before=recheck_btn)
        else:
            bad = ", ".join(s.label for s in statuses if not s.ok)
            status.config(text=f"Fault: {bad}. Re-seat and re-check.", fg=theme.BAD)
            ready_btn.pack_forget()

    app.set_poll(700, refresh)
    refresh()


def _sensor_row(parent, s):
    row = tk.Frame(parent, bg=theme.SURFACE)
    row.pack(fill="x", pady=8)
    tk.Label(row, text=s.label, bg=theme.SURFACE, fg=theme.TEXT, font=theme.BODY).pack(side="left")
    color = theme.OK if s.ok else theme.BAD
    tk.Label(row, text=("OK" if s.ok else "FAULT"), bg=theme.SURFACE, fg=color,
             font=theme.font(14, "bold")).pack(side="right")


def _back(app):
    if app.room:
        app.show("room", action="rejoin")
    else:
        app.show("mode_select")


def _start(app):
    app.clear_poll()
    _tutorial(app)


def _tutorial(app):
    top = tk.Toplevel(app, bg=theme.SURFACE)
    top.title("Quick tutorial")
    top.transient(app)
    try:
        top.grab_set()
    except Exception:
        pass
    pad = tk.Frame(top, bg=theme.SURFACE)
    pad.pack(padx=26, pady=22)
    tk.Label(pad, text="Quick tutorial", bg=theme.SURFACE, fg=theme.TEXT, font=theme.H2).pack(anchor="w", pady=(0, 10))
    steps = [
        "1.  Fold the tube before inserting.",
        "2.  Insert until the timer starts at the first marker.",
        "3.  Reach the correct depth — do not over-insert past 6 cm.",
        "4.  Hold suction at the target pressure (80–120 mmHg).",
        "5.  Withdraw smoothly until the tube is fully clear.",
    ]
    for stp in steps:
        tk.Label(pad, text=stp, bg=theme.SURFACE, fg=theme.MUTED, font=theme.BODY,
                 wraplength=460, justify="left").pack(anchor="w", pady=3)

    def ok():
        top.destroy()
        app.show("process")

    w.primary_button(pad, "OK, start", ok).pack(fill="x", pady=(16, 0))
    top.update_idletasks()
    _center(app, top)


def _center(app, top):
    try:
        app.update_idletasks()
        x = app.winfo_rootx() + (app.winfo_width() - top.winfo_width()) // 2
        y = app.winfo_rooty() + (app.winfo_height() - top.winfo_height()) // 2
        top.geometry(f"+{max(x, 0)}+{max(y, 0)}")
    except Exception:
        pass
