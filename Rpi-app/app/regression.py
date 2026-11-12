"""Auto-calibration = factory calibration + per-sensor linear regression.

The factory file (calibration_default.json) holds every role sensor's ADC level
at four tube positions (out / entry / 9 cm / 11 cm) recorded on the trainer.
Sensors drift and re-seating a jumper shifts / scales a sensor's response, so
instead of re-learning everything, the trainee captures a few positions now and
we fit, per sensor:

    ADC_now = a · ADC_factory + b        (least squares over captured positions)

That maps *all* factory levels — including positions not captured — onto today's
scale, and the triggers are rebuilt from the mapped levels exactly like the
factory ones. If a fit is not trustworthy (too few distinct points, gain out of
range, poor R²) the sensor falls back to an offset-only shift (a = 1), and every
trigger stays within ½–2× of its factory value.
"""
from __future__ import annotations

from typing import Iterable

POSITIONS = ("out", "entry", "9cm", "11cm")
ACTIVE_AT = {"entry": ("entry", "9cm", "11cm"), "d9": ("9cm", "11cm"), "d11": ("11cm",)}
TRIGGER_FRAC = 0.4
NOISE_K = 4
MIN_THR = 3
GAIN_RANGE = (0.3, 3.0)
MIN_R2 = 0.8
MIN_SPREAD = 5          # ADC — factory levels must differ this much to fit a gain
SUSPECT_ABS = 30        # an "out" capture this far (and > ½ the factory signal) from
                        # factory out → the tube was probably inside during the capture


def fit_line(points: Iterable[tuple[float, float]]) -> tuple[float, float, float]:
    """Least-squares y = a·x + b. Returns (a, b, r²); r² = 1 for 2 points."""
    pts = list(points)
    n = len(pts)
    if n < 2:
        raise ValueError("need ≥ 2 points")
    mx = sum(x for x, _ in pts) / n
    my = sum(y for _, y in pts) / n
    sxx = sum((x - mx) ** 2 for x, _ in pts)
    if sxx == 0:
        raise ValueError("x values identical")
    sxy = sum((x - mx) * (y - my) for x, y in pts)
    a = sxy / sxx
    b = my - a * mx
    syy = sum((y - my) ** 2 for _, y in pts)
    ss_res = sum((y - (a * x + b)) ** 2 for x, y in pts)
    r2 = 1.0 if syy == 0 else max(0.0, 1.0 - ss_res / syy)
    return a, b, r2


def _role_key(role: str) -> str:
    return {"9cm": "d9", "11cm": "d11"}.get(role, role)


def calibrate(factory: dict, captures: dict) -> dict:
    """factory: calibration_default.json content.
    captures: {position: {pin: (mean, sd)}} for the positions captured now
              (must include "out").
    Returns {"pins": {pin: {...}}, "trigger_delta_overrides", "calibrated_levels"}.
    """
    report = factory.get("report", {})
    fthr = {int(k): float(v) for k, v in factory.get("trigger_delta_overrides", {}).items()}
    pins_out, thresholds, levels = {}, {}, {}
    for pin_s, rep in report.items():
        pin = int(pin_s)
        role = _role_key(rep["role"])
        F = {p: float(v) for p, v in rep["levels"].items()}
        caps = {pos: c[pin] for pos, c in captures.items() if pin in c and pos in F}
        if "out" not in caps:
            continue
        noise = max(sd for _, sd in caps.values())
        pts = [(F[pos], m) for pos, (m, _) in caps.items()]
        mode, a, b, r2 = "offset", 1.0, caps["out"][0] - F["out"], None
        xs = [x for x, _ in pts]
        if len(pts) >= 2 and max(xs) - min(xs) >= MIN_SPREAD:
            fa, fb, fr2 = fit_line(pts)
            if GAIN_RANGE[0] <= fa <= GAIN_RANGE[1] and (len(pts) == 2 or fr2 >= MIN_R2):
                mode, a, b, r2 = "regression", fa, fb, fr2
            else:
                r2 = fr2
        L = {pos: a * F[pos] + b for pos in POSITIONS if pos in F}
        f_active = [p for p in ACTIVE_AT[role] if p in F]
        f_sig = min(abs(F[p] - F["out"]) for p in f_active) if f_active else 0
        shift = abs(caps["out"][0] - F["out"])
        suspect = shift > SUSPECT_ABS and shift > 0.5 * f_sig
        active = [p for p in ACTIVE_AT[role] if p in L]
        weakest = min(active, key=lambda p: abs(L[p] - L["out"]))
        dmin = abs(L[weakest] - L["out"])
        thr = max(TRIGGER_FRAC * dmin, NOISE_K * noise, MIN_THR)
        f = fthr.get(pin)
        if f:
            thr = min(max(thr, 0.5 * f), 2.0 * f)
        thr = int(round(thr))
        thresholds[pin_s] = thr
        levels[pin_s] = [int(round(L["out"]))] + [int(round(L[p]))
                                                   for p in [weakest] + [q for q in active if q != weakest]]
        pins_out[pin] = {"role": role, "mode": mode, "a": a, "b": b, "r2": r2,
                         "points": len(pts), "levels": {k: int(round(v)) for k, v in L.items()},
                         "threshold": thr, "factory_threshold": f, "noise": noise,
                         "suspect": suspect}
    return {"pins": pins_out, "trigger_delta_overrides": thresholds,
            "calibrated_levels": levels,
            "suspect": sorted(p for p, v in pins_out.items() if v["suspect"])}


def formula(p: dict) -> str:
    """Human-readable fit, e.g. 'ADC = 0.98·F + 12  (R² 0.99)'."""
    sign = "+" if p["b"] >= 0 else "−"
    txt = f"ADC = {p['a']:.2f}·F {sign} {abs(p['b']):.0f}"
    if p["mode"] == "regression" and p["r2"] is not None and p["points"] > 2:
        txt += f"  (R² {p['r2']:.2f})"
    elif p["mode"] == "offset":
        txt += "  (offset only)"
    return txt
