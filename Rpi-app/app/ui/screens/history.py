"""History — every past practice run from results.csv.

Each row:  timestamp · name · total/available · (depth · duration · pressure · contact)
Pressure (or any category) that wasn't scored shows as "—", and both its
points and its max are removed from the total ratio.
"""
from __future__ import annotations

import csv
import tkinter as tk
from pathlib import Path

from .. import theme
from .. import widgets as w
from ... import results_log


# Weight-per-category defaults; the actual weights live in scoring_config.json
# but the CSV only stores points, so we read weights from the current config.
def _max_from_config(key):
    try:
        from ... import config as cfg_store
        cfg = cfg_store.load_config()
        return int(round(float(cfg["weights"].get(key, 0))))
    except Exception:
        defaults = {"depth": 30, "duration": 20, "pressure": 20, "contact": 30}
        return defaults.get(key, 0)


def _read_rows(limit=200):
    path = Path(results_log.RESULTS_PATH)
    if not path.exists():
        return []
    try:
        with path.open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    except Exception:
        return []
    return rows[-limit:][::-1]   # newest first


def render(app, parent, **kw):
    frame = tk.Frame(parent, bg=theme.BG)
    frame.pack(fill="both", expand=True, padx=22, pady=10)

    # Footer first (pinned)
    btns = tk.Frame(frame, bg=theme.BG)
    btns.pack(side="bottom", anchor="w", pady=(6, 0))
    w.button(btns, "Refresh", lambda: _rebuild(body, info)).pack(side="left")
    w.ghost_button(btns, "Back", lambda: _back(app)).pack(side="left", padx=(10, 0))

    w.title(frame, "Practice history").pack(anchor="w")

    info = tk.Label(frame, text="", bg=theme.BG, fg=theme.MUTED,
                    font=theme.SMALL)
    info.pack(anchor="w", pady=(2, 8))

    body_wrap, body = _scrollable(frame)
    body_wrap.pack(fill="both", expand=True)

    _rebuild(body, info)


def _back(app):
    # go back to the sensible place depending on where the user came from
    if app.last_score is not None:
        app.show("results")
    else:
        app.show("mode_select")


def _rebuild(body, info):
    for c in body.winfo_children():
        c.destroy()

    rows = _read_rows()
    if not rows:
        tk.Label(body, text="No practice runs yet.", bg=theme.SURFACE,
                 fg=theme.MUTED, font=theme.BODY).pack(anchor="w", padx=16, pady=16)
        info.config(text="")
        return

    info.config(text=f"{len(rows)} run(s), newest first")

    # header
    hdr = tk.Frame(body, bg=theme.SURFACE)
    hdr.pack(fill="x", padx=14, pady=(10, 4))
    for text, wd, anchor in [
        ("When",     16, "w"),
        ("Name",     14, "w"),
        ("Total",    10, "w"),
        ("Depth",     8, "w"),
        ("Duration",  9, "w"),
        ("Pressure",  9, "w"),
        ("Contact",   8, "w"),
        ("Time",      8, "w"),
    ]:
        tk.Label(hdr, text=text, bg=theme.SURFACE, fg=theme.MUTED,
                 font=theme.font(10, "bold"), width=wd, anchor=anchor
                 ).pack(side="left")

    # weights (max per category)
    maxes = {k: _max_from_config(k) for k in ("depth", "duration", "pressure", "contact")}

    for r in rows:
        row = tk.Frame(body, bg=theme.SURFACE)
        row.pack(fill="x", padx=14, pady=2)

        ts = (r.get("timestamp") or "").replace("T", " ")[:16]
        name = (r.get("name") or "")[:14]

        cat_pts = {k: r.get(f"{k}_pts", "") for k in maxes}
        available = sum(maxes[k] for k, v in cat_pts.items() if str(v) != "")
        raw = sum(int(float(v)) for v in cat_pts.values() if str(v) != "")
        total_txt = f"{raw}/{available}" if available else "—"

        def cell(text, wd, fg=theme.TEXT, font=None, anchor="w"):
            l = tk.Label(row, text=text, bg=theme.SURFACE, fg=fg,
                         font=font or theme.font(11), width=wd, anchor=anchor)
            l.pack(side="left")
            return l

        cell(ts,                            16, theme.MUTED)
        cell(name,                          14, theme.TEXT, theme.font(11, "bold"))
        cell(total_txt,                     10, theme.ACCENT, theme.font(12, "bold"))
        cell(_slash(cat_pts["depth"],    maxes["depth"]),    8)
        cell(_slash(cat_pts["duration"], maxes["duration"]), 9)
        cell(_slash(cat_pts["pressure"], maxes["pressure"]), 9)
        cell(_slash(cat_pts["contact"],  maxes["contact"]),  8)
        cell(r.get("total_time_s", ""),      8, theme.MUTED)


def _slash(points, maximum):
    if str(points) == "" or points is None:
        return "—"
    try:
        return f"{int(float(points))}/{int(maximum)}"
    except Exception:
        return f"{points}/{maximum}"


# ── scrollable container (same pattern as results/preparation) ──
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
