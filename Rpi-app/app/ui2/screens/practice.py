"""Practice — countdown, live mannequin, timer, then Done → results.

Detection is the shared ThroatDetector with the configured roles / factory
calibration; this screen only renders. Widgets are built once and updated in
place only when a value changes (cheap on the Pi).
"""
import math
import time as _time
import tkinter as tk

from .. import style as S
from ..mannequin import Mannequin
from ...detector import DEPTH_CM, Injection, ThroatDetector
from ...serial_node import load_calibrated_levels, load_roles, load_trigger_deltas

COUNTDOWN_S = 5
START_SHOW_S = 0.8
POLL_MS = 50
THR_REFRESH_S = 1.0
FLASH_S = 1.5
STAGE = {0: ("OUT", S.MUTED), 1: ("ENTRY", S.ACCENT2), 2: ("9 CM", S.OK),
         3: ("11 CM · TOO DEEP", S.BAD)}


def render(app, parent, **kw):
    body = tk.Frame(parent, bg=S.BG)
    body.pack(fill="both", expand=True)

    # ── right panel ──
    side = tk.Frame(body, bg=S.BG, width=S.px(250))
    side.pack(side="right", fill="y", padx=(0, 18), pady=10)
    side.pack_propagate(False)
    tk.Frame(body, bg=S.LINE, width=1).pack(side="right", fill="y", pady=12)

    status = S.tag(side, "")
    status.pack(anchor="w")
    S.tag(side, "Time").pack(anchor="w", pady=(10, 0))
    time_lbl = S.label(side, "0.0", 42, "bold", fg=S.ACCENT, mono=True)
    time_lbl.pack(anchor="w")
    S.tag(side, "Depth").pack(anchor="w", pady=(4, 0))
    stage_lbl = S.label(side, "OUT", 17, "bold", fg=S.MUTED, mono=True)
    stage_lbl.pack(anchor="w")
    flash_lbl = S.label(side, "", 12, "bold", fg=S.ACCENT)
    flash_lbl.pack(anchor="w", pady=(2, 0))

    stats = tk.Frame(side, bg=S.BG)
    stats.pack(fill="x", pady=(8, 0))
    cells = {}
    for i, (k, t) in enumerate((("n", "Passes"), ("max", "Max depth"), ("last", "Last"))):
        c = tk.Frame(stats, bg=S.BG)
        c.grid(row=0, column=i, sticky="w", padx=(0, 14))
        S.tag(c, t).pack(anchor="w")
        cells[k] = S.label(c, "0" if k == "n" else "—", 15, "bold", mono=True)
        cells[k].pack(anchor="w")

    btns = tk.Frame(side, bg=S.BG)
    btns.pack(side="bottom", fill="x")
    S.button(btns, "Done", lambda: _finish(app, det)).pack(fill="x")
    row2 = tk.Frame(btns, bg=S.BG)
    row2.pack(fill="x", pady=(6, 0))
    S.button(row2, "Re-zero", lambda: _rezero(), kind="ghost", size=11, pady=4).pack(side="left")
    S.button(row2, "Cancel", lambda: app.show("name"), kind="ghost", size=11, pady=4).pack(side="right")

    # ── mannequin ──
    man = Mannequin(body)
    man.canvas.pack(side="left", fill="both", expand=True, padx=(4, 4), pady=4)

    # ── countdown overlay ──
    overlay = tk.Frame(body, bg=S.BG)
    overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
    mid = tk.Frame(overlay, bg=S.BG)
    mid.place(relx=0.5, rely=0.46, anchor="center")
    S.tag(mid, f"Get ready · {app.username or ''}").pack()
    cd_num = S.label(mid, str(COUNTDOWN_S), 110, "bold", fg=S.ACCENT, mono=True)
    cd_num.pack()
    cd_hint = S.label(mid, "Keep the tube OUT — zeroing sensors", 13, fg=S.MUTED)
    cd_hint.pack()
    S.button(overlay, "Cancel", lambda: app.show("name"), kind="ghost", size=11).place(
        relx=0, rely=1, x=14, y=-10, anchor="sw")

    # ── detection ──
    roles = load_roles()
    thr = {"default": 120, "over": {}, "at": 0.0}
    det = ThroatDetector(lambda p: thr["over"].get(p, thr["default"]),
                         load_calibrated_levels(), roles)
    ui = {"start_at": _time.monotonic() + COUNTDOWN_S, "started": False,
          "hide_at": 0.0, "flash_at": 0.0, "blink": 0}
    prime = []
    cache = {}

    def put(widget, text, fg=None):
        key = id(widget)
        if cache.get(key) != (text, fg):
            cache[key] = (text, fg)
            widget.config(text=text, **({"fg": fg} if fg else {}))

    def _rezero():
        det.reset_baseline()

    def flash(text):
        put(flash_lbl, text)
        ui["flash_at"] = _time.monotonic() + FLASH_S

    def tick():
        now = _time.monotonic()
        if now - thr["at"] > THR_REFRESH_S:
            thr["default"], thr["over"] = load_trigger_deltas()
            thr["at"] = now
        pv = app.node.get_pin_values()

        if not ui["started"]:
            left = ui["start_at"] - now
            if left > 0:
                put(cd_num, str(math.ceil(left)))
                if pv:
                    prime.append(pv)
                    del prime[:-16]
                    put(cd_hint, "Keep the tube OUT — zeroing sensors", S.MUTED)
                else:
                    put(cd_hint, "Waiting for the sensor board…", S.ACCENT2)
                return
            ui["started"] = True
            det.prime(prime)
            put(cd_num, "GO", S.OK)
            put(cd_hint, "")
            ui["hide_at"] = now + START_SHOW_S
        if ui["hide_at"] and now > ui["hide_at"]:
            ui["hide_at"] = 0.0
            overlay.destroy()
        if ui["flash_at"] and now > ui["flash_at"]:
            ui["flash_at"] = 0.0
            put(flash_lbl, "")

        man.tick()
        if not pv:
            put(status, "● Waiting for sensor board", S.ACCENT2)
            return
        s = det.feed(pv, now)
        if not s.ready:
            put(status, "● Zeroing…", S.ACCENT2)
            return
        put(status, "● Live (tube was in at start)" if det.recovered else "● Live",
            S.ACCENT2 if det.recovered else S.OK)

        man.set_state(s.level, s.entry, s.d9, s.d11)
        name_, col = STAGE[s.level]
        if s.level >= 3:                       # blink the depth label while too deep
            ui["blink"] = (ui["blink"] + 1) % 12
            col = S.BAD if ui["blink"] < 6 else S.FAINT
        put(stage_lbl, name_, col)

        for ev in s.events:
            if ev == "touch9":
                flash("✓ reached 9 cm")
            elif ev == "touch11":
                flash("⚠ too deep — pull back")
            elif ev == "healed":
                flash("↺ sensor auto-cleared")
            elif isinstance(ev, Injection):
                put(cells["n"], str(det.injections))
                put(cells["last"], f"{ev.duration_s:.1f}s")
                put(cells["max"], f"{DEPTH_CM[det.max_level]}cm",
                    S.BAD if det.max_level >= 3 else S.INK)

        if s.in_start is not None:
            put(time_lbl, f"{now - s.in_start:.1f}", S.ACCENT if s.level < 3 else S.BAD)
        else:
            put(time_lbl, f"{det.last_time_s:.1f}" if det.last_time_s else "0.0", S.MUTED)

    app.set_poll(POLL_MS, tick)


def _finish(app, det):
    app.clear_poll()
    from ...models import SessionMetrics
    from ... import config as cfg_store, scoring, results_log
    metrics = SessionMetrics(
        max_depth_cm=DEPTH_CM[det.max_level],
        total_time_ms=det.total_time_ms,
        pressure_mmhg=None,
        pressure_available=False,
        contact_events=0,
        contact_band_count=det.injections,
    )
    result = scoring.score_session(metrics, cfg_store.load_config())
    app.last_metrics, app.last_score = metrics, result
    try:
        app.last_csv = results_log.log_result(app.username, "offline", None, metrics, result)
    except Exception:
        app.last_csv = None
    app.show("results")
