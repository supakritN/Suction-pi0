"""Scoring settings — instructor-facing weight editor, PIN-gated.
Weights are normalized to 100 at scoring time, so any positive values work.
"""
import tkinter as tk

from ... import config as cfg_store
from .. import theme
from .. import widgets as w

KEYS = ["depth", "duration", "pressure", "contact"]


def render(app, parent, **kw):
    cfg = cfg_store.load_config()
    if cfg.get("settings", {}).get("pin_required", True):
        _pin_gate(app, parent, cfg)
    else:
        _weights(app, parent, cfg, "")


def _pin_gate(app, parent, cfg):
    frame = tk.Frame(parent, bg=theme.BG)
    frame.pack(fill="both", expand=True, padx=48, pady=36)
    w.title(frame, "Instructor settings").pack(anchor="w")
    w.subtitle(frame, "Enter the PIN to edit scoring.").pack(anchor="w", pady=(6, 20))

    card = w.card(frame)
    card.pack(fill="x")
    inner = tk.Frame(card, bg=theme.SURFACE)
    inner.pack(fill="x", padx=22, pady=22)
    entry = tk.Entry(inner, font=theme.font(20), show="•", bg=theme.SURFACE2, fg=theme.TEXT,
                     insertbackground=theme.TEXT, relief="flat")
    entry.pack(fill="x", ipady=12, pady=(0, 10))
    entry.focus_set()
    err = tk.Label(inner, text="", bg=theme.SURFACE, fg=theme.BAD, font=theme.SMALL)
    err.pack(anchor="w")

    def unlock(*_):
        pin = entry.get().strip()
        if cfg_store.check_pin(pin):
            _weights(app, parent, cfg, pin)
        else:
            err.config(text="Wrong PIN.")

    row = tk.Frame(inner, bg=theme.SURFACE)
    row.pack(fill="x", pady=(10, 0))
    w.primary_button(row, "Unlock", unlock).pack(side="left")
    w.ghost_button(row, "Back", lambda: app.show("mode_select")).pack(side="left", padx=(12, 0))
    entry.bind("<Return>", unlock)


def _weights(app, parent, cfg, pin):
    for child in parent.winfo_children():
        child.destroy()
    frame = tk.Frame(parent, bg=theme.BG)
    frame.pack(fill="both", expand=True, padx=48, pady=30)
    w.title(frame, "Scoring weights").pack(anchor="w")
    w.subtitle(frame, "Adjust each category's weight. The total is normalized to 100.").pack(anchor="w", pady=(6, 18))

    card = w.card(frame)
    card.pack(fill="x")
    body = tk.Frame(card, bg=theme.SURFACE)
    body.pack(fill="x", padx=22, pady=18)

    scales = {}
    sum_lbl = tk.Label(body, text="", bg=theme.SURFACE, fg=theme.MUTED, font=theme.BODY)

    def on_change(_=None):
        total = sum(int(s.get()) for s in scales.values())
        sum_lbl.config(text=f"Sum: {total}  (normalized to 100)")

    for key in KEYS:
        row = tk.Frame(body, bg=theme.SURFACE)
        row.pack(fill="x", pady=8)
        tk.Label(row, text=key.capitalize(), bg=theme.SURFACE, fg=theme.TEXT, font=theme.BODY,
                 width=10, anchor="w").pack(side="left")
        scale = tk.Scale(row, from_=0, to=60, orient="horizontal", command=on_change,
                         bg=theme.SURFACE, fg=theme.TEXT, troughcolor=theme.SURFACE2,
                         highlightthickness=0, bd=0, length=520, font=theme.SMALL)
        scale.set(int(cfg["weights"][key]))
        scale.pack(side="left", fill="x", expand=True)
        scales[key] = scale

    sum_lbl.pack(anchor="w", pady=(8, 0))
    on_change()

    status = tk.Label(frame, text="", bg=theme.BG, fg=theme.OK, font=theme.BODY)
    status.pack(anchor="w", pady=12)

    def save():
        weights = {k: int(s.get()) for k, s in scales.items()}
        cfg_store.update_weights(weights)
        status.config(text="Saved.", fg=theme.OK)

    btns = tk.Frame(frame, bg=theme.BG)
    btns.pack(anchor="w")
    w.primary_button(btns, "Save", save).pack(side="left")
    w.ghost_button(btns, "Back", lambda: app.show("mode_select")).pack(side="left", padx=(12, 0))
