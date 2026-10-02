"""Calibrate — interactive two-point capture.

Live ADC values are always shown. The user runs two captures:
  Step 1: tube is OUT     → baseline  (2 s mean)
  Step 2: tube is INSERTED → triggered (2 s mean)

Per-pin threshold = max(_MIN_THRESHOLD, |triggered − baseline| ÷ 2).
That is, the trigger line is set exactly halfway between the measured idle
and the measured in-tube readings — so inserting the tube reliably crosses
it while idle noise does not.

The result is written to pins_config.json under trigger_delta_overrides.
"""
import tkinter as tk

from .. import theme
from .. import widgets as w
from ...serial_node import (
    SENSOR_LAYOUT,
    load_enabled_pins,
    load_calibrated_at,
    save_calibration,
)


_SAMPLES       = 40     # 50 ms × 40 ≈ 2 s per capture
_SAMPLE_PERIOD = 50
_MIN_THRESHOLD = 40     # floor
_MIN_DELTA     = 30     # below this we can't tell signal from noise


def render(app, parent, **kw):
    frame = tk.Frame(parent, bg=theme.BG)
    frame.pack(fill="both", expand=True, padx=22, pady=10)

    w.title(frame, "Calibrate sensors").pack(anchor="w")

    sub_txt = tk.StringVar(value=_subtext_initial())
    tk.Label(frame, textvariable=sub_txt, bg=theme.BG, fg=theme.MUTED,
             font=theme.BODY, wraplength=780, justify="left"
             ).pack(anchor="w", pady=(2, 8))

    # ── buttons pinned at bottom so they stay visible ──
    btns = tk.Frame(frame, bg=theme.BG)
    btns.pack(side="bottom", anchor="w", pady=(6, 0))
    step_btn = w.primary_button(btns, "Capture baseline (tube OUT)", lambda: _begin_capture())
    save_btn = w.primary_button(btns, "Save & continue", lambda: _save())
    redo_btn = w.ghost_button(btns, "Redo", lambda: _reset())
    back_btn = w.ghost_button(btns, "Back", lambda: app.show("preparation"))
    step_btn.pack(side="left")
    back_btn.pack(side="left", padx=(10, 0))

    status = tk.Label(frame, text="", bg=theme.BG, fg=theme.MUTED,
                      font=theme.font(13, "bold"), wraplength=780, justify="left")
    status.pack(side="bottom", anchor="w", pady=(6, 2))

    # progress bar for current capture
    bar = tk.Frame(frame, bg=theme.SURFACE, height=10)
    bar.pack(side="bottom", fill="x", pady=(0, 4))
    bar.pack_propagate(False)
    bar_fill = tk.Frame(bar, bg=theme.ACCENT)
    bar_fill.place(x=0, y=0, relheight=1, relwidth=0.0)

    # ── live ADC table (always visible) ──
    table = tk.Frame(frame, bg=theme.SURFACE)
    table.pack(fill="both", expand=True)

    hdr = tk.Frame(table, bg=theme.SURFACE)
    hdr.pack(fill="x", padx=10, pady=(10, 2))
    for text, wd in [("Pin", 8), ("Location", 20), ("Live ADC", 12),
                     ("Baseline", 12), ("Triggered", 12), ("Threshold", 12)]:
        tk.Label(hdr, text=text, bg=theme.SURFACE, fg=theme.MUTED,
                 font=theme.font(10, "bold"), width=wd, anchor="w").pack(side="left")

    labels: dict[int, dict] = {}        # pin → {live, baseline, triggered, threshold}
    _build_rows(table, labels)

    # ── state ──
    st = {
        "phase": "idle",     # idle | capturing_baseline | capturing_triggered | ready_to_save
        "left": 0,
        "accum": {},         # pin → list[int]
        "baseline": {},      # pin → int
        "triggered": {},     # pin → int
        "thresholds": {},    # pin → int
    }

    def _show_status(msg, color=theme.MUTED):
        status.config(text=msg, fg=color)

    def _reset():
        st.update({"phase": "idle", "left": 0, "accum": {},
                   "baseline": {}, "triggered": {}, "thresholds": {}})
        bar_fill.place_configure(relwidth=0.0)
        step_btn.config(text="Capture baseline (tube OUT)")
        step_btn.pack(side="left", before=back_btn)
        save_btn.pack_forget()
        redo_btn.pack_forget()
        sub_txt.set(_subtext_initial())
        _show_status("Live ADC values update continuously below.", theme.MUTED)
        # Clear table cols
        for pin, cols in labels.items():
            for key in ("baseline", "triggered", "threshold"):
                cols[key].config(text="—", fg=theme.MUTED)

    def _begin_capture():
        enabled = load_enabled_pins()
        if not enabled:
            _show_status("No enabled pins — nothing to calibrate.", theme.BAD)
            return
        if st["phase"] == "idle" or st["phase"] == "ready_to_save" and not st["baseline"]:
            st["phase"] = "capturing_baseline"
            sub_txt.set("Capturing BASELINE — keep the tube OUT. Hold still…")
        elif st["phase"] == "idle" and st["baseline"]:  # defensive
            pass
        else:
            # baseline already present → this press is for the triggered capture
            st["phase"] = "capturing_triggered"
            sub_txt.set("Capturing TRIGGERED — hold the tube fully INSERTED. Hold still…")
        st["accum"] = {p: [] for p in enabled}
        st["left"] = _SAMPLES
        step_btn.pack_forget()
        _show_status("Sampling…", theme.WARN)
        app.after(0, _step)

    def _step():
        if st["phase"] not in ("capturing_baseline", "capturing_triggered"):
            return
        pv = app.node.get_pin_values()
        for p in st["accum"]:
            if p in pv:
                st["accum"][p].append(pv[p])
        st["left"] -= 1
        bar_fill.place_configure(relwidth=(_SAMPLES - st["left"]) / _SAMPLES)
        if st["left"] > 0:
            app.after(_SAMPLE_PERIOD, _step)
        else:
            _finish_capture()

    def _finish_capture():
        means = {p: (sum(xs) // len(xs) if xs else -1)
                 for p, xs in st["accum"].items()}
        if st["phase"] == "capturing_baseline":
            st["baseline"] = means
            for pin, v in means.items():
                if pin in labels:
                    labels[pin]["baseline"].config(text=str(v) if v >= 0 else "—",
                                                   fg=theme.TEXT)
            st["phase"] = "idle"
            step_btn.config(text="Capture triggered (tube IN)")
            step_btn.pack(side="left", before=back_btn)
            sub_txt.set("Baseline captured ✓.  Now INSERT the tube fully and press "
                        "“Capture triggered”.")
            _show_status("Insert the tube to its deepest point, then capture.", theme.ACCENT)
            bar_fill.place_configure(relwidth=0.0)
            # arm the next capture
            st["phase"] = "await_triggered"
        elif st["phase"] == "capturing_triggered":
            st["triggered"] = means
            thresholds = {}
            weak = []
            for p, b in st["baseline"].items():
                t = means.get(p, b)
                delta = abs(t - b) if (t >= 0 and b >= 0) else 0
                thr = max(_MIN_THRESHOLD, delta // 2)
                thresholds[p] = thr
                if delta < _MIN_DELTA:
                    weak.append(p)
                if p in labels:
                    labels[p]["triggered"].config(text=str(t) if t >= 0 else "—",
                                                  fg=theme.TEXT)
                    labels[p]["threshold"].config(
                        text=f"{thr}  (Δ {delta})",
                        fg=theme.OK if delta >= _MIN_DELTA else theme.BAD,
                    )
            st["thresholds"] = thresholds
            st["phase"] = "ready_to_save"
            step_btn.pack_forget()
            save_btn.pack(side="left", before=back_btn)
            redo_btn.pack(side="left", before=back_btn, padx=(10, 0))
            sub_txt.set("Threshold is set to half the measured difference. "
                        "Review the table, then Save & continue.")
            if weak:
                _show_status(
                    f"Weak signal on pins {weak} (Δ < {_MIN_DELTA}). "
                    "Insert deeper or re-seat, then Redo.", theme.BAD)
            else:
                _show_status("Capture complete ✓", theme.OK)
            bar_fill.place_configure(relwidth=0.0)

    def _save():
        if not st["thresholds"]:
            _show_status("Nothing to save.", theme.BAD)
            return
        save_calibration(st["thresholds"])
        app.show("preparation")

    # intercept the step button: it does different things in different phases
    def _step_pressed():
        if st["phase"] == "idle":
            # start baseline
            st["phase"] = "idle"   # placeholder, _begin_capture handles
            st["baseline"] = {}
            _begin_capture()
        elif st["phase"] == "await_triggered":
            st["phase"] = "capturing_triggered"
            _begin_capture_triggered()
        else:
            _begin_capture()

    def _begin_capture_triggered():
        enabled = load_enabled_pins()
        st["phase"] = "capturing_triggered"
        st["accum"] = {p: [] for p in enabled}
        st["left"] = _SAMPLES
        step_btn.pack_forget()
        sub_txt.set("Capturing TRIGGERED — hold the tube fully INSERTED. Hold still…")
        _show_status("Sampling…", theme.WARN)
        app.after(0, _step)

    step_btn.config(command=_step_pressed)

    # ── live ADC refresh loop ──
    def live_tick():
        pv = app.node.get_pin_values()
        for pin, cols in labels.items():
            if pin in pv:
                cols["live"].config(text=str(pv[pin]), fg=theme.TEXT)
            else:
                cols["live"].config(text="—", fg=theme.MUTED)

    last = load_calibrated_at()
    if last:
        _show_status(f"Last calibration: {last}", theme.MUTED)
    else:
        _show_status("Never calibrated. Press ‘Capture baseline’ to begin.", theme.MUTED)

    app.set_poll(120, live_tick)


# ── UI helpers ─────────────────────────────────────────────
def _subtext_initial():
    return ("Keep the tube OUT of the throat for the baseline. Then insert it "
            "fully for the triggered capture. The app sets each pin’s threshold "
            "to half the measured change.")


def _build_rows(parent, labels):
    enabled = load_enabled_pins()
    layout = {pin: (f"[{side[0].upper()}] {lbl}") for (_, lbl, pin, side) in SENSOR_LAYOUT}
    for sid, lbl, pin, side in SENSOR_LAYOUT:
        if pin not in enabled:
            continue
        row = tk.Frame(parent, bg=theme.SURFACE)
        row.pack(fill="x", padx=10, pady=2)

        def cell(text, w_, fg=theme.TEXT, font=None):
            l = tk.Label(row, text=text, bg=theme.SURFACE, fg=fg,
                         font=font or theme.font(11), width=w_, anchor="w")
            l.pack(side="left")
            return l

        cell(f"GPIO {pin}", 8, theme.MUTED)
        cell(layout.get(pin, "?"), 20)
        live  = cell("—", 12, theme.MUTED)
        base_ = cell("—", 12, theme.MUTED)
        trig  = cell("—", 12, theme.MUTED)
        thr   = cell("—", 12, theme.MUTED, theme.font(11, "bold"))
        labels[pin] = {"live": live, "baseline": base_, "triggered": trig, "threshold": thr}
