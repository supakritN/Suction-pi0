"""Process — depth + duration + attempt count, computed on the Pi.

Normal view:
  Big Time, Depth gauge, TOUCH banner, Cap/9/11 checkpoints, injections summary.

Debug view (toggle):
  Live ADC graphs per throat pin — baseline, ±threshold, current value — so
  you can see whether a trigger is set too high / too low for the cloudy tube.

A 5-4-3-2-1-Start! countdown runs first; the sensors are zeroed from the
readings taken during it (tube OUT), then the session timer starts.

Detection (baseline, hysteresis, debounce) lives in app/detector.py. This
screen only renders, and it does so without flicker: widgets and canvas
items are created once and then updated in place, only when a value changes.
"""
import math
import time as _time
import tkinter as tk
from collections import deque

from .. import theme
from .. import widgets as w
from ...detector import DEPTH_CM, Injection, ThroatDetector
from ...serial_node import load_calibrated_levels, load_roles, load_trigger_deltas
from ... import sound


COUNTDOWN_S    = 5
START_SHOW_S   = 0.8      # how long "Start!" stays up
POLL_MS        = 50
GRAPH_EVERY_MS = 100
THR_REFRESH_S  = 1.0
TOUCH_FLASH_MS = 1500
_HIST_LEN      = 150      # ≈ 7.5 s at 50 ms poll

_ROLE_NAMES = {"entry": "Entry", "9cm": "9 cm", "11cm": "11 cm"}
_DEBUG = [False]          # module-level, remembered across screen opens

_DEPTH_NAME = {0: "Out", 1: "Entry", 2: "9 cm", 3: "11 cm"}
_DEPTH_LEVEL_CM = {0: 0, 1: 0.5, 2: 9, 3: 11}    # cm shown on the bar
_DEPTH_SCALE_MAX = 12                             # cm — bar range
_DEPTH_MARKERS   = [(0, "0"), (9, "9 cm"), (11, "11 cm")]


def render(app, parent, **kw):
    frame = tk.Frame(parent, bg=theme.BG)
    frame.pack(fill="both", expand=True, padx=22, pady=10)

    # Layout is sized for the Pi's HDMI at 2.25× scale (≈ 853×480 usable).
    top = tk.Frame(frame, bg=theme.BG)
    top.pack(fill="x")
    tk.Label(top, text="Practice", bg=theme.BG, fg=theme.TEXT,
             font=theme.H2).pack(side="left", anchor="w")
    touch_banner = tk.Label(top, text="", bg=theme.BG, fg=theme.ACCENT,
                            font=theme.font(16, "bold"))
    touch_banner.pack(side="left", padx=(18, 0))
    status_lbl = tk.Label(top, text="", bg=theme.BG, fg=theme.MUTED, font=theme.SMALL)
    status_lbl.pack(side="right", anchor="e")

    # ── buttons pinned to bottom so they stay visible in both views ──
    btn_row = tk.Frame(frame, bg=theme.BG)
    btn_row.pack(side="bottom", anchor="w", pady=(6, 0))
    w.primary_button(btn_row, "Done", lambda: _finish(app, det)).pack(side="left")
    debug_btn = w.ghost_button(btn_row, _dbg_label(), lambda: None)
    debug_btn.pack(side="left", padx=(10, 0))
    w.ghost_button(btn_row, "Re-zero", lambda: _rezero()).pack(side="left", padx=(10, 0))
    w.ghost_button(btn_row, "Back", lambda: _abort_back(app)).pack(side="left", padx=(10, 0))

    # ── Time cell + Depth gauge side by side ──
    main = tk.Frame(frame, bg=theme.BG)
    main.pack(fill="x", pady=(4, 0))
    main.columnconfigure(0, weight=1, uniform="m")
    main.columnconfigure(1, weight=3, uniform="m")
    time_cell = tk.Frame(main, bg=theme.SURFACE,
                         highlightbackground=theme.BORDER, highlightthickness=1)
    time_cell.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
    tk.Label(time_cell, text="Time", bg=theme.SURFACE, fg=theme.MUTED,
             font=theme.SMALL).pack(pady=(8, 0))
    time_val = tk.Label(time_cell, text="0.0 s", bg=theme.SURFACE, fg=theme.TEXT,
                        font=theme.font(26, "bold"))
    time_val.pack(expand=True)
    depth_card = tk.Frame(main, bg=theme.SURFACE,
                          highlightbackground=theme.BORDER, highlightthickness=1)
    depth_card.grid(row=0, column=1, sticky="nsew")
    tk.Label(depth_card, text="Depth", bg=theme.SURFACE, fg=theme.MUTED,
             font=theme.SMALL).pack(anchor="w", padx=12, pady=(6, 0))
    gauge = _DepthGauge(depth_card)

    # ── normal (simple) view: checkpoints + session summary in one row ──
    simple_wrap = tk.Frame(frame, bg=theme.SURFACE)
    cks = [_checkpoint(simple_wrap, "Entry"), _checkpoint(simple_wrap, "9 cm"),
           _checkpoint(simple_wrap, "11 cm")]
    tk.Frame(simple_wrap, bg=theme.BORDER, width=1).pack(side="left", fill="y", padx=8, pady=6)
    inj_val       = _summary(simple_wrap, "Injections", "0")
    max_depth_val = _summary(simple_wrap, "Max depth",  "—")
    last_time_val = _summary(simple_wrap, "Last time",  "—")

    # ── debug (graphs) view: rows share the remaining height ──
    debug_wrap = tk.Frame(frame, bg=theme.BG)
    roles = load_roles()        # which GPIO is entry / 9 cm / 11 cm (pins_config)
    graphs = [_PinGraph(debug_wrap, pin, _pin_name(roles, pin)) for pin in roles.all_pins]

    def _mount_view():
        simple_wrap.pack_forget()
        debug_wrap.pack_forget()
        if _DEBUG[0]:
            debug_wrap.pack(fill="both", expand=True, pady=(4, 0))
        else:
            simple_wrap.pack(fill="x", pady=(6, 0), ipady=4)
        debug_btn.config(text=_dbg_label())
        ck_state[0] = None                    # re-push checkpoint colours

    def _toggle_debug():
        _DEBUG[0] = not _DEBUG[0]
        _mount_view()

    debug_btn.config(command=_toggle_debug)

    # ── session state ──────────────────────────────────────
    thr = {"default": 120, "over": {}, "at": 0.0}

    def _thr(pin):
        return thr["over"].get(pin, thr["default"])

    det = ThroatDetector(_thr, load_calibrated_levels(), roles)
    history = {pin: deque(maxlen=_HIST_LEN) for pin in roles.all_pins}
    ui = {"touch_hide_at": 0.0, "graph_at": 0.0,
          "start_at": _time.monotonic() + COUNTDOWN_S, "started": False, "cd_hide_at": 0.0}
    prime_buf = deque(maxlen=16)        # last ~0.8 s of countdown readings

    overlay = tk.Frame(frame.master, bg=theme.BG)
    overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
    cd_mid = tk.Frame(overlay, bg=theme.BG)
    cd_mid.place(relx=0.5, rely=0.45, anchor="center")
    tk.Label(cd_mid, text="Get ready", bg=theme.BG, fg=theme.MUTED,
             font=theme.font(22, "bold")).pack()
    cd_num = tk.Label(cd_mid, text=str(COUNTDOWN_S), bg=theme.BG, fg=theme.ACCENT,
                      font=theme.font(140, "bold"))
    cd_num.pack()
    cd_hint = tk.Label(cd_mid, text="Keep the tube OUT — zeroing sensors",
                       bg=theme.BG, fg=theme.MUTED, font=theme.BODY)
    cd_hint.pack()
    w.ghost_button(overlay, "Cancel", lambda: _abort_back(app)).place(
        relx=0, rely=1, x=22, y=-10, anchor="sw")
    ck_state = [None]

    def _rezero():
        det.reset_baseline()
        for h in history.values():
            h.clear()

    lbl_cache: dict = {}

    def _text(widget, text, fg=None):
        """Configure a label only when its text/colour actually changes."""
        key = id(widget)
        val = (text, fg)
        if lbl_cache.get(key) != val:
            lbl_cache[key] = val
            widget.config(text=text, **({"fg": fg} if fg else {}))

    def tick():
        now = _time.monotonic()
        if now - thr["at"] > THR_REFRESH_S:
            thr["default"], thr["over"] = load_trigger_deltas()
            thr["at"] = now

        if ui["touch_hide_at"] and now > ui["touch_hide_at"]:
            ui["touch_hide_at"] = 0.0
            _text(touch_banner, "")

        pv = app.node.get_pin_values()

        if not ui["started"]:
            left = ui["start_at"] - now
            if left > 0:
                _text(cd_num, str(math.ceil(left)))
                if pv:
                    prime_buf.append(pv)
                    _text(cd_hint, "Keep the tube OUT — zeroing sensors", theme.MUTED)
                else:
                    _text(cd_hint, "⚠ Waiting for ESP…", theme.WARN)
                return
            ui["started"] = True
            det.prime(list(prime_buf))
            _text(cd_num, "Start!", theme.OK)
            _text(cd_hint, "")
            ui["cd_hide_at"] = now + START_SHOW_S
        if ui["cd_hide_at"] and now > ui["cd_hide_at"]:
            ui["cd_hide_at"] = 0.0
            overlay.destroy()

        if not pv:
            _text(status_lbl, "⚠ Waiting for ESP…", theme.WARN)
            _text(time_val, "—", theme.MUTED)
            return

        s = det.feed(pv, now)
        if not s.ready:
            _text(status_lbl, "Zeroing sensors — keep the tube OUT…", theme.WARN)
            return
        if det.recovered:
            _text(status_lbl, "● Live (tube was in at start — using calibrated zero)", theme.WARN)
        else:
            _text(status_lbl, "● Live", theme.OK)

        for pin in roles.all_pins:
            if pin in pv:
                history[pin].append(pv[pin])

        for ev in s.events:
            if ev == "touch9":
                _flash("✓ TOUCH 9 cm")
            elif ev == "touch11":
                _flash("✓ TOUCH 11 cm")
                sound.get().cough()
            elif ev == "healed":
                _flash("↺ Entry auto-cleared")
            elif isinstance(ev, Injection):
                _text(inj_val, str(det.injections))
                _text(last_time_val, f"{ev.duration_s:.1f} s")
                _text(max_depth_val, f"{DEPTH_CM[det.max_level]} cm")

        if _DEBUG[0]:
            if now - ui["graph_at"] >= GRAPH_EVERY_MS / 1000.0:
                ui["graph_at"] = now
                for g in graphs:
                    g.update(history[g.pin], det.baseline.get(g.pin),
                             det.thr_pair(g.pin), pv.get(g.pin))
        else:
            states = (s.level >= 1, s.level >= 2, s.level >= 3)
            if states != ck_state[0]:
                ck_state[0] = states
                for ck, on in zip(cks, states):
                    _light(ck, on)

        if s.in_start is not None:
            t_txt, t_col = f"{now - s.in_start:.1f} s", theme.ACCENT
        else:
            last = det.last_time_s
            t_txt, t_col = (f"{last:.1f} s" if last else "0.0 s"), theme.TEXT
        _text(time_val, t_txt, t_col)

        gauge.set_level(s.level)

    def _flash(text):
        _text(touch_banner, text)
        ui["touch_hide_at"] = _time.monotonic() + TOUCH_FLASH_MS / 1000.0

    _mount_view()
    app.set_poll(POLL_MS, tick)


# ── depth gauge (persistent canvas items) ───────────────────────
class _DepthGauge:
    H = 80

    def __init__(self, parent):
        self.can = tk.Canvas(parent, bg=theme.SURFACE, height=self.H, highlightthickness=0)
        self.can.pack(fill="x", padx=10, pady=(0, 6))
        self.level = None
        self.width = 0
        self.can.bind("<Configure>", self._on_resize)

    def _on_resize(self, e):
        if e.width != self.width:
            self.width = e.width
            self._build()

    def _build(self):
        c = self.can
        c.delete("all")
        w_ = max(self.width, 100)
        self.left, self.right = 48, w_ - 48
        self.bar_y, bh = self.H // 2, 10
        c.create_rectangle(self.left, self.bar_y - bh / 2, self.right, self.bar_y + bh / 2,
                           fill=theme.SURFACE2, outline=theme.BORDER)
        self.fill = c.create_rectangle(self.left, self.bar_y - bh / 2, self.left,
                                       self.bar_y + bh / 2, fill=theme.MUTED, outline="")
        for cm_val, text in _DEPTH_MARKERS:
            x = self._x(cm_val)
            c.create_line(x, self.bar_y - bh - 6, x, self.bar_y + bh + 6, fill=theme.MUTED)
            c.create_text(x, self.bar_y + bh + 10, text=text, fill=theme.TEXT,
                          font=theme.font(11, "bold"), anchor="n")
        self.dot = c.create_oval(0, 0, 0, 0, fill=theme.MUTED, outline="white", width=2)
        self.name = c.create_text(0, 0, text="", fill=theme.MUTED,
                                  font=theme.font(12, "bold"), anchor="s")
        lvl, self.level = self.level, None
        self.set_level(lvl or 0)

    def _x(self, cm):
        return self.left + int((cm / _DEPTH_SCALE_MAX) * max(self.right - self.left, 10))

    def set_level(self, level):
        if level == self.level or not self.width:
            return
        self.level = level
        c, r, bh = self.can, 11, 10
        x = self._x(_DEPTH_LEVEL_CM[level])
        col = (theme.OK if level == 3 else theme.ACCENT if level == 2 else
               theme.WARN if level == 1 else theme.MUTED)
        c.coords(self.fill, self.left, self.bar_y - bh / 2, x, self.bar_y + bh / 2)
        c.itemconfig(self.fill, fill=col)
        c.coords(self.dot, x - r, self.bar_y - r, x + r, self.bar_y + r)
        c.itemconfig(self.dot, fill=col)
        c.coords(self.name, x, self.bar_y - r - 4)
        c.itemconfig(self.name, text=_DEPTH_NAME[level], fill=col)


# ── debug graph row (persistent canvas items) ───────────────────
def _pin_name(roles, pin):
    return f"{_ROLE_NAMES.get(roles.role_of(pin), '')} · GPIO {pin}".lstrip(" ·")


class _PinGraph:
    def __init__(self, parent, pin, name):
        self.pin = pin
        row = tk.Frame(parent, bg=theme.SURFACE)
        row.pack(fill="both", expand=True, pady=1)
        box = tk.Frame(row, bg=theme.SURFACE, width=150)
        box.pack(side="left", padx=(6, 4), fill="y")
        box.pack_propagate(False)
        tk.Label(box, text=name, bg=theme.SURFACE,
                 fg=theme.TEXT, font=theme.font(9, "bold")).pack(anchor="w")
        self.val = tk.Label(box, text="—", bg=theme.SURFACE, fg=theme.MUTED,
                            font=theme.font(8), justify="left")
        self.val.pack(anchor="w")
        self.can = tk.Canvas(row, bg=theme.SURFACE, highlightthickness=0, height=24)
        self.can.pack(side="left", fill="both", expand=True, padx=(0, 8), pady=2)
        c = self.can
        self.mid  = c.create_line(0, 0, 0, 0, fill=theme.MUTED)
        self.hi   = c.create_line(0, 0, 0, 0, fill=theme.BAD, dash=(3, 3))
        self.lo   = c.create_line(0, 0, 0, 0, fill=theme.BAD, dash=(3, 3))
        self.rhi  = c.create_line(0, 0, 0, 0, fill=theme.BORDER, dash=(2, 4))
        self.rlo  = c.create_line(0, 0, 0, 0, fill=theme.BORDER, dash=(2, 4))
        self.trace = c.create_line(0, 0, 0, 0, fill=theme.ACCENT, width=2)
        self.span = 0.0
        self.last_text = None

    def update(self, samples, base, thr_pair, cur):
        if base is None or cur is None:
            return
        thr, rel = thr_pair
        c = self.can
        w_ = c.winfo_width()
        h_ = c.winfo_height()
        if w_ <= 1 or h_ <= 1:
            return
        # Sticky vertical scale: grows at once, shrinks slowly — no jumpy rescale.
        need = max([thr * 2, 40] + [abs(s - base) for s in samples])
        self.span = need if need > self.span else max(need, self.span * 0.97)
        y_mid, half = h_ // 2, h_ // 2 - 3

        def y_of(v):
            return y_mid - int(((v - base) / self.span) * half)

        c.coords(self.mid, 0, y_mid, w_, y_mid)
        c.coords(self.hi, 0, y_of(base + thr), w_, y_of(base + thr))
        c.coords(self.lo, 0, y_of(base - thr), w_, y_of(base - thr))
        c.coords(self.rhi, 0, y_of(base + rel), w_, y_of(base + rel))
        c.coords(self.rlo, 0, y_of(base - rel), w_, y_of(base - rel))
        n = len(samples)
        if n >= 2:
            step = w_ / (_HIST_LEN - 1)
            x0 = w_ - (n - 1) * step          # newest sample pinned to the right edge
            pts = []
            for i, s in enumerate(samples):
                pts.append(x0 + i * step)
                pts.append(y_of(s))
            c.coords(self.trace, *pts)

        dev = int(cur - base)
        hit = abs(dev) > thr
        text = (f"{cur}  Δ{dev:+d}  ±{thr:.0f}", hit)
        if text != self.last_text:
            self.last_text = text
            self.val.config(text=text[0], fg=theme.OK if hit else theme.MUTED)


# ── misc helpers ─────────────────────────────────────────────
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


def _finish(app, det):
    app.clear_poll()
    from ...models import SessionMetrics
    metrics = SessionMetrics(
        max_depth_cm=DEPTH_CM[det.max_level],
        total_time_ms=det.total_time_ms,
        pressure_mmhg=None,
        pressure_available=False,
        contact_events=0,
        contact_band_count=det.injections,
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
