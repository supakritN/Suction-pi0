"""Process — depth + duration + attempt count, computed on the Pi.

Normal view:
  Big Time, big Depth, TOUCH banner, Cap/9/11 checkpoints, injections summary,
  live sensor-dot row.

Debug view (toggle):
  Live ADC graphs per enabled pin — baseline, ±threshold, current value — so
  you can see whether a trigger is set too high / too low for the cloudy tube.
"""
import time as _time
import tkinter as tk
from collections import deque

from .. import theme
from .. import widgets as w
from ...serial_node import load_trigger_deltas


CAP_PIN   = 4
TOP_PINS  = (5, 6)       # 9 cm depth
BOT_PINS  = (7, 15)      # 11 cm depth

TOUCH_FLASH_MS = 1500
_HIST_LEN = 120           # ≈ 12 s at 100 ms poll

_PIN_NAMES = {4: "Cap", 5: "TL (9cm)", 6: "TR (9cm)", 7: "BL (11cm)", 15: "BR (11cm)"}
_DEBUG = [False]          # module-level, remembered across screen opens


_DEPTH_TEXT = {
    0: ("Out",   "0 cm"),
    1: ("Entry", "0 cm"),
    2: ("9 cm",  "9 cm"),
    3: ("11 cm", "11 cm"),
}
_DEPTH_LEVEL_CM = {0: 0, 1: 0.5, 2: 9, 3: 11}   # cm shown on the bar
_DEPTH_SCALE_MAX = 12                            # cm — bar range
_DEPTH_MARKERS   = [(0, "0"), (9, "9 cm"), (11, "11 cm")]


def render(app, parent, **kw):
    frame = tk.Frame(parent, bg=theme.BG)
    frame.pack(fill="both", expand=True, padx=22, pady=10)

    w.title(frame, "Practice in progress").pack(anchor="w")

    # ── buttons pinned to bottom so they stay visible in both views ──
    btn_row = tk.Frame(frame, bg=theme.BG)
    btn_row.pack(side="bottom", anchor="w", pady=(6, 0))
    w.primary_button(btn_row, "Done", lambda: _finish(app, st)).pack(side="left")
    debug_btn = w.ghost_button(btn_row, _dbg_label(), lambda: None)
    debug_btn.pack(side="left", padx=(10, 0))
    w.ghost_button(btn_row, "Back", lambda: _abort_back(app)).pack(side="left", padx=(10, 0))

    # ── Time cell ──
    header = tk.Frame(frame, bg=theme.BG)
    header.pack(fill="x")
    time_val, _ = _bigcell(header, 0, "Time", "0.0 s", width_cols=1)
    header.columnconfigure(0, weight=1)

    # ── Depth bar (visual) ──
    depth_card = tk.Frame(frame, bg=theme.SURFACE,
                          highlightbackground=theme.BORDER, highlightthickness=1)
    depth_card.pack(fill="x", pady=(6, 2))
    tk.Label(depth_card, text="Depth", bg=theme.SURFACE, fg=theme.MUTED,
             font=theme.SMALL).pack(anchor="w", padx=14, pady=(8, 0))
    depth_canvas = tk.Canvas(depth_card, bg=theme.SURFACE, height=90,
                             highlightthickness=0)
    depth_canvas.pack(fill="x", padx=10, pady=(0, 6))

    touch_banner = tk.Label(frame, text="", bg=theme.BG, fg=theme.ACCENT,
                            font=theme.font(18, "bold"))
    touch_banner.pack(anchor="w", pady=(4, 0))

    # ── normal (simple) view container ──
    simple_wrap = tk.Frame(frame, bg=theme.BG)
    ck_row = tk.Frame(simple_wrap, bg=theme.SURFACE)
    ck_row.pack(fill="x", pady=(6, 4), ipadx=10, ipady=6)
    cap_ck = _checkpoint(ck_row, "Cap")
    d9_ck  = _checkpoint(ck_row, "9 cm")
    d11_ck = _checkpoint(ck_row, "11 cm")

    sumrow = tk.Frame(simple_wrap, bg=theme.SURFACE)
    sumrow.pack(fill="x", pady=(0, 6), ipadx=10, ipady=6)
    inj_val       = _summary(sumrow, "Injections", "0")
    max_depth_val = _summary(sumrow, "Max depth",  "—")
    last_time_val = _summary(sumrow, "Last time",  "—")

    # ── debug (graphs) view container ──
    debug_wrap = tk.Frame(frame, bg=theme.BG)
    graphs: dict[int, tuple] = {}   # pin → (canvas, text_label)

    def _mount_view():
        simple_wrap.pack_forget()
        debug_wrap.pack_forget()
        for c in debug_wrap.winfo_children():
            c.destroy()
        graphs.clear()
        if _DEBUG[0]:
            debug_wrap.pack(fill="both", expand=True, pady=(4, 0))
            _build_graphs(debug_wrap, graphs)
        else:
            simple_wrap.pack(fill="x")
        debug_btn.config(text=_dbg_label())

    def _toggle_debug():
        _DEBUG[0] = not _DEBUG[0]
        _mount_view()

    debug_btn.config(command=_toggle_debug)
    _mount_view()

    # ── session state ──────────────────────────────────────
    st = {
        "baseline": {},
        "cap_prev": False,
        "in_start": None,
        "cur_max_depth": 0,
        "touched_9_now": False,
        "touched_11_now": False,
        "injections": 0,
        "max_depth_overall": 0,
        "last_time_s": None,
        "total_time_ms": 0,
        "touch_hide_at": 0.0,
        "history": {pin: deque(maxlen=_HIST_LEN) for pin in (CAP_PIN, *TOP_PINS, *BOT_PINS)},
    }

    def _capture_baseline():
        pv = app.node.get_pin_values()
        if pv:
            st["baseline"] = dict(pv)

    def _flash(text):
        touch_banner.config(text=text)
        st["touch_hide_at"] = _time.monotonic() + TOUCH_FLASH_MS / 1000.0

    def tick():
        now = _time.monotonic()
        if touch_banner.cget("text") and now > st["touch_hide_at"]:
            touch_banner.config(text="")

        pv = app.node.get_pin_values()
        if not pv:
            time_val.config(text="—")
            depth_val.config(text="Waiting ESP", fg=theme.WARN)
            return

        if not st["baseline"]:
            _capture_baseline()
            return

        # push samples into per-pin history (for the debug graph)
        for pin in st["history"]:
            if pin in pv:
                st["history"][pin].append(pv[pin])

        tdef, tover = load_trigger_deltas()
        def _thr(pin): return tover.get(pin, tdef)

        triggered = {pin: abs(pv.get(pin, base) - base) > _thr(pin)
                     for pin, base in st["baseline"].items()}

        cap_now = triggered.get(CAP_PIN, False)
        d9  = any(triggered.get(p, False) for p in TOP_PINS)
        d11 = any(triggered.get(p, False) for p in BOT_PINS)

        if   d11: depth_level = 3
        elif d9:  depth_level = 2
        elif cap_now: depth_level = 1
        else:     depth_level = 0

        if not _DEBUG[0]:
            _light(cap_ck, cap_now or depth_level >= 1)
            _light(d9_ck,  d9 or depth_level >= 2)
            _light(d11_ck, d11 or depth_level >= 3)
        else:
            _redraw_graphs(graphs, st["history"], st["baseline"], _thr, pv)

        if cap_now and not st["cap_prev"]:
            st["in_start"] = now
            st["cur_max_depth"] = depth_level
            st["touched_9_now"] = False
            st["touched_11_now"] = False
        if cap_now:
            st["cur_max_depth"] = max(st["cur_max_depth"], depth_level)
            if d9 and not st["touched_9_now"]:
                st["touched_9_now"] = True
                _flash("✓ TOUCH 9 cm")
            if d11 and not st["touched_11_now"]:
                st["touched_11_now"] = True
                _flash("✓ TOUCH 11 cm")

        if st["cap_prev"] and not cap_now and st["in_start"] is not None:
            dur = now - st["in_start"]
            st["injections"] += 1
            st["total_time_ms"] += int(dur * 1000)
            st["last_time_s"] = dur
            st["max_depth_overall"] = max(st["max_depth_overall"], st["cur_max_depth"])
            if not _DEBUG[0]:
                inj_val.config(text=str(st["injections"]))
                last_time_val.config(text=f"{dur:.1f} s")
                _, cm = _DEPTH_TEXT[st["max_depth_overall"]]
                max_depth_val.config(text=cm)
            st["in_start"] = None
            st["cur_max_depth"] = 0

        st["cap_prev"] = cap_now

        if st["in_start"] is not None:
            t = now - st["in_start"]
            time_val.config(text=f"{t:.1f} s", fg=theme.ACCENT)
        else:
            time_val.config(text=f"{(st['last_time_s'] or 0):.1f} s" if st["last_time_s"] else "0.0 s",
                            fg=theme.TEXT)

        cm_now = _DEPTH_LEVEL_CM[depth_level]
        _draw_depth_bar(depth_canvas, cm_now, depth_level)

    app.after(400, _capture_baseline)
    app.set_poll(80, tick)


# ── debug graphs ─────────────────────────────────────────────
def _build_graphs(parent, graphs):
    """One row per enabled throat pin (fixed set here)."""
    pins = [CAP_PIN, *TOP_PINS, *BOT_PINS]
    for pin in pins:
        row = tk.Frame(parent, bg=theme.SURFACE)
        row.pack(fill="x", pady=2)
        label_box = tk.Frame(row, bg=theme.SURFACE, width=100)
        label_box.pack(side="left", padx=(6, 4))
        label_box.pack_propagate(False)
        tk.Label(label_box, text=_PIN_NAMES.get(pin, f"GPIO {pin}"),
                 bg=theme.SURFACE, fg=theme.TEXT,
                 font=theme.font(11, "bold")).pack(anchor="w", pady=(6, 0))
        val_lbl = tk.Label(label_box, text="—", bg=theme.SURFACE, fg=theme.MUTED,
                           font=theme.font(10))
        val_lbl.pack(anchor="w")
        can = tk.Canvas(row, bg=theme.SURFACE, highlightthickness=0, height=48)
        can.pack(side="left", fill="x", expand=True, padx=(0, 8), pady=4)
        graphs[pin] = (can, val_lbl)


def _redraw_graphs(graphs, history, baselines, thr_fn, pv):
    for pin, (can, val_lbl) in graphs.items():
        can.delete("all")
        w_ = can.winfo_width() or 400
        h_ = can.winfo_height() or 48
        base = baselines.get(pin, 2048)
        thr  = thr_fn(pin)
        samples = list(history.get(pin, []))
        cur = pv.get(pin, base)

        # auto range: fit baseline ± max(threshold*2, observed deviation)
        max_dev = max([thr * 2] + [abs(s - base) for s in samples] + [abs(cur - base)])
        max_dev = max(max_dev, 40)
        y_mid = h_ // 2

        def y_of(v):
            # center = baseline, span = max_dev above/below
            off = v - base
            return y_mid - int((off / max_dev) * (h_ // 2 - 3))

        # background baseline line
        can.create_line(0, y_mid, w_, y_mid, fill=theme.MUTED, width=1)
        # threshold band
        can.create_rectangle(0, y_of(base + thr), w_, y_of(base - thr),
                             fill="", outline=theme.BORDER)
        can.create_line(0, y_of(base + thr), w_, y_of(base + thr),
                        fill=theme.BAD, dash=(3, 3), width=1)
        can.create_line(0, y_of(base - thr), w_, y_of(base - thr),
                        fill=theme.BAD, dash=(3, 3), width=1)

        # trace
        if len(samples) >= 2:
            n = len(samples)
            pts = []
            for i, s in enumerate(samples):
                x = int(i * w_ / max(n - 1, 1))
                pts.extend([x, y_of(s)])
            can.create_line(*pts, fill=theme.ACCENT, width=2)

        # value tag
        dev = cur - base
        hit = abs(dev) > thr
        val_lbl.config(
            text=f"ADC {cur}  Δ{dev:+d}  thr±{thr}",
            fg=theme.OK if hit else theme.MUTED,
        )


# ── misc helpers ─────────────────────────────────────────────
def _bigcell(parent, col, label, value, width_cols=2):
    cell = tk.Frame(parent, bg=theme.SURFACE,
                    highlightbackground=theme.BORDER, highlightthickness=1)
    cell.grid(row=0, column=col, columnspan=width_cols,
              sticky="nsew", padx=5, ipady=6)
    tk.Label(cell, text=label, bg=theme.SURFACE, fg=theme.MUTED,
             font=theme.SMALL).pack(pady=(6, 0))
    val = tk.Label(cell, text=value, bg=theme.SURFACE, fg=theme.TEXT,
                   font=theme.font(28, "bold"))
    val.pack(pady=(0, 8))
    return val, cell


def _draw_depth_bar(can, cm, level):
    """Horizontal clinical depth gauge: 0cm ── 9cm ── 11cm with current marker."""
    can.delete("all")
    try:
        w_ = can.winfo_width()
    except Exception:
        w_ = 600
    if w_ <= 1:
        w_ = 600
    h_ = 90
    margin_x = 48
    track_left = margin_x
    track_right = w_ - margin_x
    track_w = max(track_right - track_left, 10)
    bar_y = h_ // 2 + 8
    bar_h = 10

    def _x(cm_val):
        return track_left + int((cm_val / _DEPTH_SCALE_MAX) * track_w)

    # Track background
    can.create_rectangle(track_left, bar_y - bar_h / 2,
                         track_right, bar_y + bar_h / 2,
                         fill=theme.SURFACE2, outline=theme.BORDER)

    # Progress fill — color by depth level
    progress_x = _x(cm)
    fill_col = (theme.OK   if level == 3 else
                theme.ACCENT if level == 2 else
                theme.WARN if level == 1 else theme.MUTED)
    if cm > 0:
        can.create_rectangle(track_left, bar_y - bar_h / 2,
                             progress_x, bar_y + bar_h / 2,
                             fill=fill_col, outline="")

    # Depth markers + labels
    for cm_val, text in _DEPTH_MARKERS:
        x = _x(cm_val)
        can.create_line(x, bar_y - bar_h - 6, x, bar_y + bar_h + 6,
                        fill=theme.MUTED, width=1)
        can.create_text(x, bar_y + bar_h + 16, text=text,
                        fill=theme.TEXT, font=theme.font(11, "bold"), anchor="n")

    # Current depth marker (large dot above bar)
    r = 11
    can.create_oval(progress_x - r, bar_y - r,
                    progress_x + r, bar_y + r,
                    fill=fill_col, outline="white", width=2)
    # Numeric readout above the dot
    name, _ = _DEPTH_TEXT[level]
    can.create_text(progress_x, bar_y - r - 10, text=name,
                    fill=fill_col, font=theme.font(13, "bold"), anchor="s")


def _summary(parent, label, value):
    cell = tk.Frame(parent, bg=theme.SURFACE)
    cell.pack(side="left", padx=10)
    tk.Label(cell, text=label, bg=theme.SURFACE, fg=theme.MUTED,
             font=theme.font(10, "bold")).pack(anchor="w")
    val = tk.Label(cell, text=value, bg=theme.SURFACE, fg=theme.TEXT,
                   font=theme.font(16, "bold"))
    val.pack(anchor="w")
    return val


def _checkpoint(parent, label):
    cell = tk.Frame(parent, bg=theme.SURFACE)
    cell.pack(side="left", padx=12)
    can = tk.Canvas(cell, width=18, height=18, bg=theme.SURFACE, highlightthickness=0)
    oid = can.create_oval(2, 2, 16, 16, fill=theme.MUTED, outline="")
    can.pack(side="left", padx=(0, 5))
    tk.Label(cell, text=label, bg=theme.SURFACE, fg=theme.TEXT,
             font=theme.font(13, "bold")).pack(side="left")
    return (can, oid)


def _light(ck, on):
    can, oid = ck
    can.itemconfig(oid, fill=theme.OK if on else theme.MUTED)


def _dbg_label():
    return "Hide ADC graph" if _DEBUG[0] else "ADC graph"


def _abort_back(app):
    app.clear_poll()
    try:
        app.node.abort()
    except Exception:
        pass
    app.show("preparation")


def _finish(app, st):
    app.clear_poll()
    from ...models import SessionMetrics
    cm_by_level = {0: 0, 1: 0, 2: 9, 3: 11}
    metrics = SessionMetrics(
        max_depth_cm=cm_by_level[st["max_depth_overall"]],
        total_time_ms=st["total_time_ms"],
        pressure_mmhg=None,
        pressure_available=False,
        contact_events=0,
        contact_band_count=st["injections"],
    )
    from ... import config as cfg_store, scoring, results_log
    result = scoring.score_session(metrics, cfg_store.load_config())
    app.last_metrics = metrics
    app.last_score = result
    try:
        room_addr = app.room.get("host") if app.room else None
        app.last_csv = results_log.log_result(app.username, app.mode, room_addr, metrics, result)
    except Exception:
        app.last_csv = None
    if app.room:
        try:
            if app.room.get("role") == "host":
                app.room["server"].record(app.username, metrics.to_dict())
            else:
                app.room["client"].send_result(app.username, metrics.to_dict())
        except Exception:
            pass
    app.show("results")
