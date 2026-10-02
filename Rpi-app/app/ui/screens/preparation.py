"""3.1 Preparation — physical sensor map (simple) or scrollable debug detail.

Buttons stay pinned to the bottom; sensor list in the middle scrolls (touch-drag
or mousewheel) when it overflows the screen.
"""
import tkinter as tk

from .. import theme
from .. import widgets as w


_DEBUG = [False]
_SHORT = {"Top-Left": "TL", "Top-Right": "TR",
          "Bottom-Left": "BL", "Bottom-Right": "BR"}


def render(app, parent, **kw):
    frame = tk.Frame(parent, bg=theme.BG)
    frame.pack(fill="both", expand=True, padx=24, pady=10)

    # ── Pack footer FIRST so it stays pinned at the bottom ────
    btns = tk.Frame(frame, bg=theme.BG)
    btns.pack(side="bottom", anchor="w", pady=(6, 0))

    status_lbl = tk.Label(frame, text="", bg=theme.BG, fg=theme.MUTED,
                          font=theme.BODY, wraplength=800, justify="left")
    status_lbl.pack(side="bottom", anchor="w", pady=(4, 4))

    ready_btn   = w.primary_button(btns, "Ready",    lambda: _start(app))
    recheck_btn = w.button(btns,         "Re-check", lambda: refresh())
    cal_btn     = w.button(btns,         "Calibrate", lambda: app.show("calibrate"))
    debug_btn   = w.ghost_button(btns, _toggle_label(), lambda: None)
    back_btn    = w.ghost_button(btns, "Back",      lambda: _back(app))

    recheck_btn.pack(side="left")
    cal_btn.pack(side="left", padx=(8, 0))
    debug_btn.pack(side="left", padx=(8, 0))
    back_btn.pack(side="left", padx=(8, 0))

    # ── Header + scrollable body fill remaining space ─────────
    w.title(frame, "Preparing sensors").pack(anchor="w")
    sub_lbl = w.subtitle(frame, "")
    sub_lbl.pack(anchor="w", pady=(2, 6))

    body_wrap, body = _scrollable(frame)
    body_wrap.pack(fill="both", expand=True)

    def refresh():
        statuses = app.node.self_check()
        connected = app.node.is_connected()
        for child in body.winfo_children():
            child.destroy()

        if not connected or not statuses:
            tk.Label(body, text="⚠  Waiting for ESP32 over USB…",
                     bg=theme.BG, fg=theme.WARN, font=theme.font(18, "bold")).pack(
                anchor="nw", pady=12)
            sub_lbl.config(text="Plug the ESP32 into any USB port.")
            status_lbl.config(text="No data on serial. The app auto-connects when the ESP is detected.",
                              fg=theme.WARN)
            ready_btn.pack_forget()
            debug_btn.config(text=_toggle_label())
            return

        # "Enabled" pins = those we actually require. Disabled pins are red
        # markers but do NOT block Ready.
        enabled   = [s for s in statuses if not s.disabled]
        installed = [s for s in enabled if s.present]
        all_ok    = installed and all(s.ok for s in installed)

        if _DEBUG[0]:
            _render_debug(body, statuses)
            sub_lbl.config(text="Debug view — pin + raw ADC per sensor (scroll if needed).")
        else:
            _render_simple(body, statuses)
            sub_lbl.config(text="Green = ready · Red = fault · Gray = not installed.")

        n_ok = sum(1 for s in installed if s.ok)
        n_disabled = sum(1 for s in statuses if s.disabled)
        tail = f" ({n_disabled} disabled)" if n_disabled else ""
        if all_ok:
            status_lbl.config(text=f"All {n_ok} enabled sensors ready.{tail}", fg=theme.OK)
            ready_btn.pack(side="left", padx=(0, 8), before=recheck_btn)
        else:
            bad_names = [f"{s.label} ({s.detail.split(' · ')[0]})"
                         for s in installed if not s.ok]
            if bad_names:
                status_lbl.config(text=f"Fault: {', '.join(bad_names)}", fg=theme.BAD)
            else:
                status_lbl.config(text=f"Waiting for enabled sensors…{tail}", fg=theme.WARN)
            ready_btn.pack_forget()
        debug_btn.config(text=_toggle_label())

    def toggle_debug():
        _DEBUG[0] = not _DEBUG[0]
        refresh()

    debug_btn.config(command=toggle_debug)

    app.set_poll(600, refresh)
    refresh()


# ── scrollable container ────────────────────────────────────
def _scrollable(parent):
    """Return (outer_frame, inner_scrollable_frame).
    Inner frame grows naturally; outer provides canvas + scrollbar + drag/wheel.
    """
    wrap = tk.Frame(parent, bg=theme.BG)
    canvas = tk.Canvas(wrap, bg=theme.BG, highlightthickness=0, bd=0)
    sb = tk.Scrollbar(wrap, orient="vertical", command=canvas.yview, width=14)
    inner = tk.Frame(canvas, bg=theme.BG)

    canvas.configure(yscrollcommand=sb.set)
    win = canvas.create_window((0, 0), window=inner, anchor="nw")

    def _on_inner_config(_e):
        canvas.configure(scrollregion=canvas.bbox("all"))
    inner.bind("<Configure>", _on_inner_config)

    def _on_canvas_config(e):
        canvas.itemconfigure(win, width=e.width)
    canvas.bind("<Configure>", _on_canvas_config)

    # Mouse-wheel scrolling (Linux uses Button-4/5)
    def _wheel(e):
        canvas.yview_scroll(-1 if e.num == 4 else 1, "units")
    canvas.bind_all("<Button-4>", _wheel)
    canvas.bind_all("<Button-5>", _wheel)

    # Touch / click-drag scrolling
    drag = {"y": 0}
    def _press(e):   drag["y"] = e.y
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


# ── simple view ─────────────────────────────────────────────
def _render_simple(parent, statuses):
    cols = tk.Frame(parent, bg=theme.BG)
    cols.pack(anchor="nw", fill="x")

    throat_statuses = [s for s in statuses if s.side == "throat"]
    mouth_statuses  = [s for s in statuses if s.side == "mouth"]

    _side_card(cols, "Throat", throat_statuses).pack(side="left", padx=(0, 8), anchor="nw")
    _side_card(cols, "Mouth",  mouth_statuses).pack(side="left", padx=(0, 0), anchor="nw")

    pressures = [s for s in statuses if s.side == "pressure"]
    if pressures:
        prow = tk.Frame(parent, bg=theme.SURFACE)
        prow.pack(anchor="nw", fill="x", pady=(8, 0), ipadx=10, ipady=6)
        tk.Label(prow, text="Pressure", bg=theme.SURFACE, fg=theme.MUTED,
                 font=theme.font(12, "bold")).pack(side="left", padx=(8, 14))
        for p in pressures:
            cell = tk.Frame(prow, bg=theme.SURFACE)
            cell.pack(side="left", padx=10)
            _dot(cell, p).pack(side="left", padx=(0, 5))
            tk.Label(cell, text=p.label, bg=theme.SURFACE, fg=theme.TEXT,
                     font=theme.font(12)).pack(side="left")


def _side_card(parent, title, side_statuses):
    card = tk.Frame(parent, bg=theme.SURFACE)

    tk.Label(card, text=title, bg=theme.SURFACE, fg=theme.MUTED,
             font=theme.font(12, "bold")).pack(anchor="nw", padx=10, pady=(8, 2))

    cap = next((s for s in side_statuses if s.id.endswith("_cap")), None)
    if cap:
        row = tk.Frame(card, bg=theme.SURFACE)
        row.pack(anchor="nw", padx=10, pady=(0, 4))
        _dot(row, cap).pack(side="left", padx=(0, 5))
        tk.Label(row, text=cap.label, bg=theme.SURFACE, fg=theme.TEXT,
                 font=theme.font(12, "bold")).pack(side="left")

    grid = tk.Frame(card, bg=theme.SURFACE)
    grid.pack(anchor="nw", padx=10, pady=(0, 10))
    coords = {"_tl": (0, 0), "_tr": (0, 1), "_bl": (1, 0), "_br": (1, 1)}
    for s in side_statuses:
        suffix = s.id[s.id.rfind("_"):]
        if suffix not in coords:
            continue
        r, c = coords[suffix]
        cell = tk.Frame(grid, bg=theme.SURFACE)
        cell.grid(row=r, column=c, padx=5, pady=2, sticky="w")
        _dot(cell, s).pack(side="left", padx=(0, 4))
        tk.Label(cell, text=_SHORT.get(s.label, s.label), bg=theme.SURFACE, fg=theme.TEXT,
                 font=theme.font(11)).pack(side="left")

    return card


# ── debug view ──────────────────────────────────────────────
def _render_debug(parent, statuses):
    rows = tk.Frame(parent, bg=theme.SURFACE)
    rows.pack(anchor="nw", fill="x")

    header = tk.Frame(rows, bg=theme.SURFACE)
    header.pack(fill="x", padx=10, pady=(8, 2))
    for text, w_, anchor in [("Sensor", 24, "w"), ("Pin / value", 24, "w"), ("State", 12, "e")]:
        tk.Label(header, text=text, bg=theme.SURFACE, fg=theme.MUTED,
                 font=theme.font(10, "bold"), width=w_, anchor=anchor).pack(side="left")

    for s in statuses:
        row = tk.Frame(rows, bg=theme.SURFACE)
        row.pack(fill="x", padx=10, pady=1)
        prefix = {"throat": "[T]", "mouth": "[M]", "pressure": "[P]"}.get(s.side, "")
        tk.Label(row, text=f"{prefix} {s.label}", bg=theme.SURFACE, fg=theme.TEXT,
                 font=theme.font(11), width=24, anchor="w").pack(side="left")
        tk.Label(row, text=s.detail, bg=theme.SURFACE, fg=theme.MUTED,
                 font=theme.font(10), width=24, anchor="w").pack(side="left")
        tk.Label(row, text=_tag(s), bg=theme.SURFACE,
                 fg=_tag_color(s), font=theme.font(10, "bold"),
                 width=12, anchor="e").pack(side="left")


# ── bits ────────────────────────────────────────────────────
def _dot(parent, s):
    color = _tag_color(s)
    c = tk.Canvas(parent, width=16, height=16, bg=parent["bg"], highlightthickness=0)
    c.create_oval(2, 2, 14, 14, fill=color, outline="")
    return c


def _tag(s):
    if s.disabled:
        return "DISABLED"
    if not s.present:
        return "NOT INST"
    return "READY" if s.ok else "FAULT"


def _tag_color(s):
    if s.disabled:
        return theme.BAD           # red for disabled, per user request
    if not s.present:
        return theme.MUTED
    return theme.OK if s.ok else theme.BAD


def _toggle_label():
    return "Simple view" if _DEBUG[0] else "Debug view"


def _back(app):
    app.clear_poll()
    if app.room:
        app.show("room", action="rejoin")
    else:
        app.show("mode_select")


def _start(app):
    app.clear_poll()
    app.show("process")
