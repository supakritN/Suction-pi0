"""5.1 / 5.2 Results — show the score. In a room the result was already sent
to the host from the process screen; here we offer to return to the room.
"""
import os
import tkinter as tk

from .. import theme
from .. import widgets as w


def render(app, parent, **kw):
    score = app.last_score
    metrics = app.last_metrics
    frame = tk.Frame(parent, bg=theme.BG)
    frame.pack(fill="both", expand=True, padx=48, pady=24)

    if not score:
        w.subtitle(frame, "No result yet.").pack(anchor="w")
        return

    w.title(frame, "Practice score").pack(anchor="w")

    hero = w.card(frame)
    hero.pack(fill="x", pady=(14, 14))
    inner = tk.Frame(hero, bg=theme.SURFACE)
    inner.pack(pady=22)
    tk.Label(inner, text=str(score.total), bg=theme.SURFACE, fg=theme.TEXT, font=theme.BIG).pack()
    tk.Label(inner, text=score.level, bg=theme.SURFACE, fg=theme.ACCENT, font=theme.H2).pack(pady=(6, 2))
    tk.Label(inner, text=score.note, bg=theme.SURFACE, fg=theme.MUTED, font=theme.BODY).pack()

    card = w.card(frame)
    card.pack(fill="x")
    body = tk.Frame(card, bg=theme.SURFACE)
    body.pack(fill="x", padx=20, pady=14)
    tk.Label(body, text="Breakdown", bg=theme.SURFACE, fg=theme.TEXT, font=theme.font(18, "bold")).pack(anchor="w", pady=(0, 8))

    for c in score.categories:
        pts = f"{round(c.points)} / {round(c.max_points)}" if c.available else "—"
        _row(body, f"{c.key.capitalize()} · {c.label}", pts)
    _row(body, "Measured", f"{score.raw_score} / {score.available_score}")
    _row(body, "Total time", f"{metrics.total_time_ms / 1000:.2f} s")
    _row(body, "Max depth", f"{metrics.max_depth_cm} cm")

    if getattr(app, "last_csv", None):
        tk.Label(frame, text=f"Saved to {os.path.basename(str(app.last_csv))}",
                 bg=theme.BG, fg=theme.MUTED, font=theme.SMALL).pack(anchor="w", pady=(10, 0))

    in_room = bool(app.room)
    btns = tk.Frame(frame, bg=theme.BG)
    btns.pack(anchor="w", pady=(18, 0))
    w.primary_button(btns, "New practice",
                     lambda: app.show("process" if in_room else "preparation")).pack(side="left")
    if in_room:
        w.button(btns, "Back to room", lambda: app.show("room", action="rejoin")).pack(side="left", padx=(12, 0))
    w.ghost_button(btns, "Home", lambda: app.show("mode_select")).pack(side="left", padx=(12, 0))


def _row(parent, label, value):
    row = tk.Frame(parent, bg=theme.SURFACE)
    row.pack(fill="x", pady=6)
    tk.Label(row, text=label, bg=theme.SURFACE, fg=theme.MUTED, font=theme.BODY).pack(side="left")
    tk.Label(row, text=value, bg=theme.SURFACE, fg=theme.TEXT, font=theme.font(16, "bold")).pack(side="right")
