"""1. Name entry — just ask for a name, press OK (no login/password)."""
import tkinter as tk

from .. import theme
from .. import widgets as w


def render(app, parent, **kw):
    frame = tk.Frame(parent, bg=theme.BG)
    frame.pack(fill="both", expand=True, padx=48, pady=36)

    w.title(frame, "Enter your name").pack(anchor="w")
    w.subtitle(frame, "This name shows on your results and in the room list.").pack(anchor="w", pady=(6, 22))

    card = w.card(frame)
    card.pack(fill="x")
    inner = tk.Frame(card, bg=theme.SURFACE)
    inner.pack(fill="x", padx=22, pady=22)

    tk.Label(inner, text="Name", bg=theme.SURFACE, fg=theme.MUTED, font=theme.SMALL).pack(anchor="w")
    entry = tk.Entry(inner, font=theme.font(20), bg=theme.SURFACE2, fg=theme.TEXT,
                     insertbackground=theme.TEXT, relief="flat")
    entry.pack(fill="x", ipady=12, pady=(6, 18))
    entry.focus_set()

    def submit(*_):
        value = entry.get().strip()
        if not value:
            entry.focus_set()
            return
        app.username = value
        app.show("mode_select")

    w.primary_button(inner, "OK", submit).pack(fill="x")
    entry.bind("<Return>", submit)
