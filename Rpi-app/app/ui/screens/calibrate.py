"""Calibrate — interactive two-point capture.

Live ADC values are always shown. The user runs two captures:
  Step 1: tube is OUT     → baseline  (2 s mean)
  Step 2: tube is INSERTED → triggered (2 s mean)

Per-pin threshold = |triggered − baseline| ÷ 2, floored at a few times the
noise measured during the captures (not a fixed number: since the re-wiring
the sensors' noise is ~0.5 ADC, so even a clean 10-ADC signal is usable).
The trigger line sits halfway between the idle and the in-tube readings.

The result is written to pins_config.json under trigger_delta_overrides.
"Factory defaults" loads calibration_default.json (recorded on the trainer)
instead; capturing again overrides it.
"""
import statistics
import tkinter as tk

from .. import theme
from .. import widgets as w
from ...serial_node import (
    SENSOR_LAYOUT,
    apply_default_calibration,
    calibration_summary,
    load_calibrated_at,
    load_default_calibration,
    load_enabled_pins,
    load_roles,
    save_calibration,
)


_SAMPLES       = 40     # 50 ms × 40 ≈ 2 s per capture
_SAMPLE_PERIOD = 50
_NOISE_K       = 4      # threshold ≥ 4 × noise sd
_MIN_THR       = 3      # ADC
_WEAK_SNR      = 8      # signal < 8 × noise (or < _MIN_SIGNAL) → flagged weak
_MIN_SIGNAL    = 5      # ADC
_ROLE_NAMES    = {"entry": "Entry", "9cm": "9 cm", "11cm": "11 cm"}


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
    dflt_btn = w.button(btns, "Use factory defaults", lambda: _load_defaults())
    step_btn.pack(side="left")
    if load_default_calibration():
        dflt_btn.pack(side="left", padx=(10, 0))
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
        "noise": {},         # pin → max sd seen in either capture
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
        # median, so one stray reading can't skew the threshold
        means = {p: (sorted(xs)[len(xs) // 2] if xs else -1)
                 for p, xs in st["accum"].items()}
        for p, xs in st["accum"].items():
            if len(xs) > 1:
                st["noise"][p] = max(st["noise"].get(p, 0.0), statistics.pstdev(xs))
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
                noise = st["noise"].get(p, 0.0)
                thr = int(round(max(delta / 2, _NOISE_K * noise, _MIN_THR)))
                thresholds[p] = thr
                is_weak = delta < max(_WEAK_SNR * noise, _MIN_SIGNAL)
                if is_weak:
                    weak.append(p)
                if p in labels:
                    labels[p]["triggered"].config(text=str(t) if t >= 0 else "—",
                                                  fg=theme.TEXT)
                    labels[p]["threshold"].config(
                        text=f"{thr}  (Δ {delta})",
                        fg=theme.BAD if is_weak else theme.OK,
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
                    f"Weak signal on pins {weak} (too close to the noise). "
                    "Insert deeper or re-seat, then Redo.", theme.BAD)
            else:
                _show_status("Capture complete ✓", theme.OK)
            bar_fill.place_configure(relwidth=0.0)

    def _load_defaults():
        if apply_default_calibration():
            app.show("calibrate", loaded_defaults=True)   # rebuild rows for its pins
        else:
            _show_status("No calibration_default.json found.", theme.BAD)

    def _save():
        if not st["thresholds"]:
            _show_status("Nothing to save.", theme.BAD)
            return
        save_calibration(st["thresholds"], st["baseline"], st["triggered"])
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
    live_cache: dict = {}

    def live_tick():
        pv = app.node.get_pin_values()
        for pin, cols in labels.items():
            val = (str(pv[pin]), theme.TEXT) if pin in pv else ("—", theme.MUTED)
            if live_cache.get(pin) != val:      # only touch widgets that changed
                live_cache[pin] = val
                cols["live"].config(text=val[0], fg=val[1])

    last = load_calibrated_at()
    if kw.get("loaded_defaults"):
        _show_status("✓ Factory defaults loaded — ready to practice "
                     "(or capture to calibrate your own).", theme.OK)
    elif last:
        _show_status(f"In use: {calibration_summary()}", theme.MUTED)
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
    roles = load_roles()
    layout = {}
    for (_, lbl, pin, side) in SENSOR_LAYOUT:
        role = _ROLE_NAMES.get(roles.role_of(pin))
        layout[pin] = f"{role} · {lbl}" if role else f"[{side[0].upper()}] {lbl}"
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
        cell(layout.get(pin, "?"), 22)
        live  = cell("—", 12, theme.MUTED)
        base_ = cell("—", 12, theme.MUTED)
        trig  = cell("—", 12, theme.MUTED)
        thr   = cell("—", 12, theme.MUTED, theme.font(11, "bold"))
        labels[pin] = {"live": live, "baseline": base_, "triggered": trig, "threshold": thr}
