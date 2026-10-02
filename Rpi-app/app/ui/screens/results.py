"""5.1 / 5.2 Results — compact layout so the full breakdown fits on 480 px.

Buttons are pinned to the bottom; the breakdown table scrolls if the content
exceeds the screen.
"""
import os
import tkinter as tk

from .. import theme
from .. import widgets as w


def render(app, parent, **kw):
    score = app.last_score
    metrics = app.last_metrics
    frame = tk.Frame(parent, bg=theme.BG)
    frame.pack(fill="both", expand=True, padx=28, pady=12)

    if not score:
        w.subtitle(frame, "No result yet.").pack(anchor="w")
        return

    # ── Footer pinned to bottom first ──
    btns = tk.Frame(frame, bg=theme.BG)
    btns.pack(side="bottom", anchor="w", pady=(8, 0))
    in_room = bool(app.room)
    w.primary_button(btns, "New practice",
                     lambda: app.show("process" if in_room else "preparation")
                     ).pack(side="left")
    if in_room:
        w.button(btns, "Back to room",
                 lambda: app.show("room", action="rejoin")
                 ).pack(side="left", padx=(10, 0))
    w.button(btns, "History", lambda: app.show("history")
             ).pack(side="left", padx=(10, 0))
    w.ghost_button(btns, "Home", lambda: app.show("mode_select")
                   ).pack(side="left", padx=(10, 0))

    if getattr(app, "last_csv", None):
        tk.Label(frame, text=f"Saved to {os.path.basename(str(app.last_csv))}",
                 bg=theme.BG, fg=theme.MUTED, font=theme.SMALL
                 ).pack(side="bottom", anchor="w", pady=(6, 2))

    # ── Header + compact hero ──
    tk.Label(frame, text="Practice score", bg=theme.BG, fg=theme.TEXT,
             font=theme.H2).pack(anchor="w")

    hero = w.card(frame)
    hero.pack(fill="x", pady=(6, 8))
    hrow = tk.Frame(hero, bg=theme.SURFACE)
    hrow.pack(fill="x", padx=18, pady=10)

    # Show raw / available (NOT normalized to 100) so a missing pressure
    # sensor shrinks the maximum instead of inflating the score.
    big = tk.Frame(hrow, bg=theme.SURFACE)
    big.pack(side="left")
    tk.Label(big, text=f"{int(round(score.raw_score))}",
             bg=theme.SURFACE, fg=theme.ACCENT,
             font=theme.font(42, "bold")).pack(side="left")
    tk.Label(big, text=f" / {int(round(score.available_score))}",
             bg=theme.SURFACE, fg=theme.MUTED,
             font=theme.font(22, "bold")).pack(side="left", anchor="s", pady=(0, 8))

    txt = tk.Frame(hrow, bg=theme.SURFACE)
    txt.pack(side="left", padx=(16, 0), anchor="s", pady=(0, 4))
    tk.Label(txt, text=score.level, bg=theme.SURFACE, fg=theme.TEXT,
             font=theme.font(18, "bold")).pack(anchor="w")
    tk.Label(txt, text=score.note, bg=theme.SURFACE, fg=theme.MUTED,
             font=theme.SMALL, wraplength=520, justify="left").pack(anchor="w")

    # ── Breakdown (scrollable) ──
    body_wrap, body = _scrollable(frame)
    body_wrap.pack(fill="both", expand=True)

    heading = tk.Frame(body, bg=theme.SURFACE)
    heading.pack(fill="x")
    tk.Label(heading, text="Breakdown", bg=theme.SURFACE, fg=theme.TEXT,
             font=theme.font(16, "bold")).pack(anchor="w", padx=16, pady=(10, 4))

    rows = tk.Frame(body, bg=theme.SURFACE)
    rows.pack(fill="x")

    for c in score.categories:
        pts = f"{round(c.points)} / {round(c.max_points)}" if c.available else "—"
        _row(rows, f"{c.key.capitalize()} · {c.label}", pts)
    _row(rows, "Measured",   f"{score.raw_score} / {score.available_score}")
    _row(rows, "Total time", f"{metrics.total_time_ms / 1000:.2f} s")
    _row(rows, "Max depth",  f"{metrics.max_depth_cm} cm")
    _row(rows, "Injections", f"{metrics.contact_band_count}")


def _row(parent, label, value):
    row = tk.Frame(parent, bg=theme.SURFACE)
    row.pack(fill="x", padx=16, pady=3)
    tk.Label(row, text=label, bg=theme.SURFACE, fg=theme.MUTED,
             font=theme.BODY).pack(side="left")
    tk.Label(row, text=value, bg=theme.SURFACE, fg=theme.TEXT,
             font=theme.font(15, "bold")).pack(side="right")


# ── scrollable container ─────────────────────────────────
def _scrollable(parent):
    wrap = tk.Frame(parent, bg=theme.BG)
    canvas = tk.Canvas(wrap, bg=theme.SURFACE, highlightthickness=0, bd=0)
    sb = tk.Scrollbar(wrap, orient="vertical", command=canvas.yview, width=14)
    inner = tk.Frame(canvas, bg=theme.SURFACE)

    canvas.configure(yscrollcommand=sb.set)
    win = canvas.create_window((0, 0), window=inner, anchor="nw")
    inner.bind("<Configure>",
               lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>",
                lambda e: canvas.itemconfigure(win, width=e.width))

    def _wheel(e):
        canvas.yview_scroll(-1 if e.num == 4 else 1, "units")
    canvas.bind_all("<Button-4>", _wheel)
    canvas.bind_all("<Button-5>", _wheel)

    drag = {"y": 0}
    def _press(e): drag["y"] = e.y
    def _drag(e):
        dy = drag["y"] - e.y
        if abs(dy) > 1:
            canvas.yview_scroll(int(dy / 10) or (1 if dy > 0 else -1), "units")
            drag["y"] = e.y
    canvas.bind("<ButtonPress-1>", _press)
    canvas.bind("<B1-Motion>", _drag)
    inner.bind("<ButtonPress-1>", _press)
    inner.bind("<B1-Motion>", _drag)

    canvas.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    return wrap, inner
