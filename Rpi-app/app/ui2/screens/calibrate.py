"""Auto calibrate = factory calibration + per-sensor linear regression.

Three guided 2-second captures (tube OUT, at 9 cm, at 11 cm). For each sensor
ADC_now = a·ADC_factory + b is fitted over those points (app/regression.py),
which maps every factory level onto today's sensor scale and rebuilds the
triggers. Not needed for normal use — the factory defaults are the default.
"""
import statistics
import tkinter as tk

from .. import style as S
from ... import regression
from ...serial_node import (apply_default_calibration, calibration_summary,
                            load_default_calibration, save_regression_calibration)

STEPS = [("out", "Tube OUT", "Pull the tube fully out, then capture."),
         ("9cm", "Tube at 9 cm", "Insert to 9 cm and hold still, then capture."),
         ("11cm", "Tube at 11 cm", "Insert to 11 cm and hold still, then capture.")]
SAMPLES, PERIOD_MS = 40, 50       # 2 s per capture
ROLE = {"entry": "Entry", "d9": "9 cm", "d11": "11 cm"}


def render(app, parent, **kw):
    factory = load_default_calibration()
    pins = sorted(int(p) for p in factory.get("report", {}))
    frame = tk.Frame(parent, bg=S.BG)
    frame.pack(fill="both", expand=True, padx=26, pady=(10, 10))

    top = tk.Frame(frame, bg=S.BG)
    top.pack(fill="x")
    S.label(top, "Auto calibrate", 22, "bold").pack(side="left")
    S.tag(top, "factory + linear regression").pack(side="left", padx=10, anchor="s", pady=(0, 6))
    S.tag(top, f"in use · {calibration_summary()}").pack(side="right", anchor="s", pady=(0, 6))

    step_lbl = S.label(frame, "", 15, "bold", fg=S.ACCENT)
    step_lbl.pack(anchor="w", pady=(6, 0))
    hint_lbl = S.label(frame, "", 12, fg=S.MUTED, wraplength=S.px(780), justify="left")
    hint_lbl.pack(anchor="w")

    bar = tk.Frame(frame, bg=S.LINE, height=6)
    bar.pack(fill="x", pady=(6, 6))
    fill = tk.Frame(bar, bg=S.ACCENT)
    fill.place(x=0, y=0, relheight=1, relwidth=0)

    table = tk.Frame(frame, bg=S.PANEL, highlightthickness=1, highlightbackground=S.LINE)
    table.pack(fill="both", expand=True)
    hdr = ("GPIO", "Role", "Live", "Out", "9 cm", "11 cm", "Fit  (F = factory ADC)", "Trigger")
    widths = (5, 6, 6, 6, 6, 6, 30, 10)
    for c, (t, wd) in enumerate(zip(hdr, widths)):
        tk.Label(table, text=t, bg=S.PANEL, fg=S.MUTED, font=S.f(9, "bold", True), width=wd,
                 anchor="w").grid(row=0, column=c, sticky="w", padx=(8 if c == 0 else 2, 2), pady=(6, 2))
    cells = {}
    for r, pin in enumerate(pins, start=1):
        role = factory["report"][str(pin)]["role"]
        vals = (f"{pin}", ROLE.get(role, role), "—", "—", "—", "—", "—",
                f"±{factory['trigger_delta_overrides'][str(pin)]}")
        row = {}
        for c, (v, wd) in enumerate(zip(vals, widths)):
            l = tk.Label(table, text=v, bg=S.PANEL, fg=S.INK if c != 1 else S.MUTED,
                         font=S.f(10, "normal", True), width=wd, anchor="w")
            l.grid(row=r, column=c, sticky="w", padx=(8 if c == 0 else 2, 2), pady=1)
            row[c] = l
        cells[pin] = row

    btns = tk.Frame(frame, bg=S.BG)
    btns.pack(fill="x", pady=(8, 0))
    cap_btn = S.button(btns, "Capture", lambda: begin())
    save_btn = S.button(btns, "Save calibration", lambda: save())
    redo_btn = S.button(btns, "Redo", lambda: reset(), kind="secondary")
    S.button(btns, "Back", lambda: app.show("name"), kind="ghost").pack(side="right")
    S.button(btns, "Use factory defaults", lambda: use_factory(), kind="secondary").pack(
        side="right", padx=6)

    st = {"step": 0, "left": 0, "acc": {}, "captures": {}, "result": None}

    def show_step():
        if st["step"] < len(STEPS):
            _, title, hint = STEPS[st["step"]]
            step_lbl.config(text=f"Step {st['step'] + 1}/3 · {title}", fg=S.ACCENT)
            hint_lbl.config(text=hint)
            save_btn.pack_forget()
            redo_btn.pack_forget()
            cap_btn.pack(side="left")
            cap_btn.config(state="normal")

    def reset():
        st.update(step=0, captures={}, result=None)
        for pin in pins:
            for c in (3, 4, 5, 6):
                cells[pin][c].config(text="—", fg=S.INK)
            cells[pin][7].config(text=f"±{factory['trigger_delta_overrides'][str(pin)]}", fg=S.INK)
        show_step()

    def begin():
        cap_btn.config(state="disabled")
        st["acc"] = {p: [] for p in pins}
        st["left"] = SAMPLES
        hint_lbl.config(text="Sampling… hold still.")
        app.after(0, sample)

    def sample():
        pv = app.node.get_pin_values()
        for p in pins:
            if p in pv:
                st["acc"][p].append(pv[p])
        st["left"] -= 1
        fill.place_configure(relwidth=(SAMPLES - st["left"]) / SAMPLES)
        if st["left"] > 0:
            app.after(PERIOD_MS, sample)
            return
        fill.place_configure(relwidth=0)
        pos = STEPS[st["step"]][0]
        cap = {p: (statistics.fmean(v), statistics.pstdev(v)) for p, v in st["acc"].items() if len(v) > 5}
        if len(cap) < len(pins):
            hint_lbl.config(text="No data from the sensor board — check the USB cable, then capture again.")
            cap_btn.config(state="normal")
            return
        st["captures"][pos] = cap
        col = {"out": 3, "9cm": 4, "11cm": 5}[pos]
        for p, (m, _) in cap.items():
            cells[p][col].config(text=f"{m:.0f}")
        st["step"] += 1
        if st["step"] < len(STEPS):
            show_step()
        else:
            finish()

    def finish():
        res = regression.calibrate(factory, st["captures"])
        st["result"] = res
        for pin, p in res["pins"].items():
            cells[pin][6].config(text=regression.formula(p),
                                 fg=S.OK if p["mode"] == "regression" else S.ACCENT2)
            f_thr = factory["trigger_delta_overrides"][str(pin)]
            cells[pin][7].config(text=f"±{f_thr}→±{p['threshold']}")
        n_reg = sum(1 for p in res["pins"].values() if p["mode"] == "regression")
        cap_btn.pack_forget()
        if res["suspect"]:
            for pin in res["suspect"]:
                cells[pin][3].config(fg=S.BAD)
            step_lbl.config(text="Check the tube-OUT step", fg=S.BAD)
            hint_lbl.config(text=f"GPIO {', '.join(map(str, res['suspect']))} read far from its "
                                 "factory out level — the tube was probably inside. Redo.")
            redo_btn.pack(side="left")
            return
        step_lbl.config(text=f"Fitted · {n_reg}/{len(res['pins'])} sensors by regression", fg=S.OK)
        hint_lbl.config(text="Green = linear fit used · orange = poor fit, offset-only shift. "
                             "Save to use it, or keep the factory defaults.")
        save_btn.pack(side="left")
        redo_btn.pack(side="left", padx=(8, 0))

    def save():
        if st["result"]:
            save_regression_calibration(st["result"])
            app.show("name")

    def use_factory():
        apply_default_calibration()
        app.show("name")

    def live():
        pv = app.node.get_pin_values()
        for p in pins:
            txt = str(pv[p]) if p in pv else "—"
            if cells[p][2].cget("text") != txt:
                cells[p][2].config(text=txt)

    reset()
    app.set_poll(150, live)
