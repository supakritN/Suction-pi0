"""Throat tube detector — pure logic, no Tk, so it can be unit-tested.

Turns per-pin ADC readings into a stable depth level + injection events.
Raw IR readings through a translucent tube are noisy and hover near the
threshold, which made the old "single sample vs threshold" check blink.
This adds:

  * baseline   = mean of the first BASELINE_SAMPLES readings, then a very
                 slow drift-follow while the pin is idle and quiet;
  * hysteresis = trigger at |Δ| > thr, release only once |Δ| < thr·RELEASE;
  * debounce   = a pin must hold its new state for ON_MS / OFF_MS before
                 it flips, so one noisy sample can't end an injection;
  * tube-in-at-start recovery: if the warm-up reading sits near one of the
                 calibrated tube-IN levels, the calibrated tube-OUT level
                 becomes the baseline instead.

Which GPIO plays which role (entry / 9 cm / 11 cm) comes from Roles, loaded
from pins_config.json, so re-wiring a sensor is a config change.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

CAP_PIN  = 4             # legacy layout (used when pins_config has no "roles")
TOP_PINS = (5, 6)        # 9 cm depth
BOT_PINS = (7, 15)       # 11 cm depth
ALL_PINS = (CAP_PIN, *TOP_PINS, *BOT_PINS)

BASELINE_SAMPLES = 8
RELEASE_RATIO    = 0.8   # release threshold = thr * RELEASE_RATIO (narrow band; debounce does the rest)
ON_MS            = 60
OFF_MS           = 150
DRIFT_ALPHA      = 0.01  # per-sample baseline follow while idle & quiet
CAL_ON_FRAC      = 0.6   # with calibration: trigger by 60 % of the measured tube signal
CAL_MIN_DELTA    = 5     # below this the calibrated signal is noise — not used
RECOVER_MIN_DELTA = 30   # "tube in at start" zero swap only for strong pins: a weak
                         # pin's day-to-day level shift (±10) exceeds its whole signal
STUCK_S          = 6.0   # weak entry-only + flat this long → tube is out, sensor didn't return
FLAT_FRAC        = 0.3   # "flat" = stays within ±max(thr·FLAT_FRAC, FLAT_MIN) of where it settled
FLAT_MIN         = 12    # ADC — floor so a weak pin's noise still counts as flat
MIN_INJECTION_S  = 0.3   # shorter cap blips are not counted as an injection
INSIDE_RELEASE_S = 0.4   # "tube out" only after nothing is on this long (one hold
                         # at a shallow depth must not split into several injections)
DEPTH_STUCK_S    = 10.0  # weak depth pin alone + flat this long → muted (stuck guard)

DEPTH_CM = {0: 0, 1: 0, 2: 9, 3: 11}


@dataclass(frozen=True)
class Roles:
    entry: tuple = (CAP_PIN,)    # any of these on → tube is inside
    d9: tuple = TOP_PINS
    d11: tuple = BOT_PINS

    @property
    def all_pins(self) -> tuple:
        return tuple(dict.fromkeys((*self.entry, *self.d9, *self.d11)))

    def role_of(self, pin: int) -> str:
        if pin in self.entry:
            return "entry"
        if pin in self.d9:
            return "9cm"
        return "11cm" if pin in self.d11 else ""


@dataclass
class _Pin:
    state: bool = False
    cand: bool = False
    cand_since: float = 0.0
    sign: int = 0          # learned direction the tube moves this pin's reading (+1 / -1)
    flat_ref: float = 0.0  # value the reading settled at…
    flat_since: float = 0.0  # …and since when
    muted_at: Optional[float] = None   # healed: ignore until reading moves from here


@dataclass
class Injection:
    duration_s: float
    max_level: int


@dataclass
class DetectorState:
    ready: bool = False              # baseline captured
    level: int = 0                   # 0 out · 1 entry · 2 9cm · 3 11cm
    cap: bool = False                # tube inside (latched)
    entry: bool = False              # an entry sensor is on right now
    d9: bool = False
    d11: bool = False
    in_start: Optional[float] = None
    events: list = field(default_factory=list)   # "touch9" | "touch11" | Injection


class ThroatDetector:
    def __init__(self, thr_fn: Callable[[int], int],
                 calibrated: Optional[dict[int, tuple]] = None,
                 roles: Optional[Roles] = None) -> None:
        self.thr_fn = thr_fn
        # pin → (tube_out, tube_in[, more tube-in levels at other depths…])
        self.calibrated = calibrated or {}
        self.roles = roles or Roles()
        self.all_pins = self.roles.all_pins
        self.recovered: set[int] = set()       # pins that fell back to calibration
        self.baseline: dict[int, float] = {}
        self._warm: dict[int, list[int]] = {}
        self._pins: dict[int, _Pin] = {p: _Pin() for p in self.all_pins}
        self._cap_prev = False
        self._off_since: Optional[float] = None   # inside → nothing on, since when
        self._in_start: Optional[float] = None
        self._cur_max = 0
        self._t9 = False
        self._t11 = False
        # session totals
        self.injections = 0
        self.total_time_ms = 0
        self.max_level = 0
        self.last_time_s: Optional[float] = None

    def reset_baseline(self) -> None:
        self.baseline.clear()
        self._warm.clear()
        self.recovered.clear()
        for p in self._pins.values():
            p.state = p.cand = False
            p.sign = 0
            p.muted_at = None

    def prime(self, samples: list) -> None:
        """Set the baseline from readings taken just before the session starts
        (the countdown, when the trainee is told to keep the tube out)."""
        self.reset_baseline()
        recent = samples[-BASELINE_SAMPLES * 2:]
        for pin in self.all_pins:
            vals = [pv[pin] for pv in recent if pin in pv]
            if len(vals) >= BASELINE_SAMPLES // 2:
                self.baseline[pin] = self._pick_baseline(pin, float(sorted(vals)[len(vals) // 2]))

    def _pick_baseline(self, pin: int, warm: float) -> float:
        cal = self.calibrated.get(pin)
        if cal is not None and len(cal) >= 2:
            out_lvl = cal[0]
            # Only when the reading actually looks like "tube in": near one of
            # the calibrated tube-in levels. A sensor that drifted far from all
            # of them (seen on the old Cap: 2621/2664 calibrated, 3000 live) is
            # not a tube — keep the live zero.
            for in_lvl in cal[1:]:
                delta = abs(in_lvl - out_lvl)
                if delta >= RECOVER_MIN_DELTA and abs(warm - in_lvl) <= delta / 2:
                    self.recovered.add(pin)
                    return float(out_lvl)
        return warm

    def deviation(self, pin: int, value: int) -> int:
        base = self.baseline.get(pin)
        return 0 if base is None else int(value - base)

    def _cal_delta(self, pin: int) -> int:
        """Signed calibrated tube signal (tube_in − tube_out), 0 if unusable."""
        cal = self.calibrated.get(pin)
        if cal is None or len(cal) < 2 or abs(cal[1] - cal[0]) < CAL_MIN_DELTA:
            return 0
        return cal[1] - cal[0]

    def _tube_sign(self, pin: int) -> int:
        """+1/-1 if calibration says which way the tube moves the reading, else 0."""
        d = self._cal_delta(pin)
        return (d > 0) - (d < 0)

    def thr_pair(self, pin: int) -> tuple[float, float]:
        """(trigger, release) deviation from baseline for this pin.

        A weak sensor (e.g. Cap: tube signal 43 vs the 40 floor) would trigger
        only at 93 % of its signal; with calibration the trigger is capped to
        60 % of the measured signal.
        """
        on = float(self.thr_fn(pin))
        d = abs(self._cal_delta(pin))
        if d:
            on = min(on, d * CAL_ON_FRAC)
        return on, on * RELEASE_RATIO

    def _stuck(self, pin: int, pv: dict, now: float, after_s: float) -> bool:
        """Pin on, barely past its trigger, reading flat for after_s → mute it."""
        ps = self._pins[pin]
        thr, _ = self.thr_pair(pin)
        weak = abs(pv[pin] - self.baseline[pin]) < 2 * thr
        if weak and now - ps.flat_since >= after_s and ps.flat_since > (self._in_start or 0):
            ps.muted_at = float(pv[pin])
            ps.state = ps.cand = False
            return True
        return False

    def _update_pin(self, pin: int, value: int, now: float) -> bool:
        ps = self._pins[pin]
        thr, rel = self.thr_pair(pin)
        dev = value - self.baseline[pin]
        band = max(thr * FLAT_FRAC, FLAT_MIN)
        if abs(value - ps.flat_ref) > band:
            ps.flat_ref, ps.flat_since = value, now
        if ps.muted_at is not None:
            if abs(value - ps.muted_at) <= band * 1.5:
                return False
            ps.muted_at = None      # reading moved (tube back in, or sensor recovered)
        # Tube direction: from calibration, else learned from this pin's first
        # trigger and kept. Readings moving the other way never trigger.
        sign = self._tube_sign(pin) or ps.sign
        if ps.state:
            # Release is measured in the tube's direction, so an overshoot the
            # other way (IR sensors do this as the tube leaves) counts as "gone"
            # instead of leaving Entry stuck on / re-triggering.
            raw = dev * sign > rel
        else:
            raw = (dev * sign > thr) if sign else (abs(dev) > thr)
            if raw and not ps.sign:
                ps.sign = 1 if dev > 0 else -1
            # follow slow drift (temperature, ambient light) while idle — including
            # a lasting shift in the non-tube direction. Paused while the tube is
            # inside, so a slow approach to 9 / 11 cm is never "absorbed".
            if not self._cap_prev and (dev * sign if sign else abs(dev)) < thr * 0.5:
                self.baseline[pin] += DRIFT_ALPHA * (value - self.baseline[pin])
        if raw == ps.state:
            ps.cand = ps.state
            return ps.state
        if raw != ps.cand:
            ps.cand, ps.cand_since = raw, now
        hold = (ON_MS if raw else OFF_MS) / 1000.0
        if now - ps.cand_since >= hold:
            ps.state = raw
        return ps.state

    def feed(self, pv: dict[int, int], now: float) -> DetectorState:
        out = DetectorState()
        if not pv:
            return out
        pins = self.all_pins

        if len(self.baseline) < len([p for p in pins if p in pv]):
            for pin in pins:
                if pin in pv and pin not in self.baseline:
                    w = self._warm.setdefault(pin, [])
                    w.append(pv[pin])
                    if len(w) >= BASELINE_SAMPLES:
                        # median: one spike during warm-up can't skew the zero
                        self.baseline[pin] = self._pick_baseline(pin, float(sorted(w)[len(w) // 2]))
            if len(self.baseline) < len([p for p in pins if p in pv]):
                return out
        out.ready = True

        trig = {pin: self._update_pin(pin, pv[pin], now)
                for pin in pins if pin in pv and pin in self.baseline}
        r = self.roles
        entry_on = [p for p in r.entry if trig.get(p, False)]
        d9_on  = [p for p in r.d9 if trig.get(p, False)]
        d11_on = [p for p in r.d11 if trig.get(p, False)]

        heal_at = None
        # Stuck-Entry heal (weak entry sensors only): entry on alone, reading
        # flat for STUCK_S and barely past its threshold → the tube left but the
        # sensor settled off its old zero. Mute it until its reading moves again
        # (keeps the true zero for the next insertion) and end the injection when
        # the reading went flat (≈ tube removal). A strong entry signal (e.g.
        # −3000 ADC) is never "stuck", so it is never healed.
        if entry_on and not (d9_on or d11_on):
            for p in list(entry_on):
                if self._stuck(p, pv, now, STUCK_S):
                    heal_at = self._pins[p].flat_since
                    entry_on.remove(p)
                    out.events.append("healed")
        # Same guard for a weak depth pin holding "inside" on its own.
        if not entry_on:
            for group in (d9_on, d11_on):
                for p in list(group):
                    if self._stuck(p, pv, now, DEPTH_STUCK_S):
                        heal_at = self._pins[p].flat_since
                        group.remove(p)
                        out.events.append("healed")
        d9, d11 = bool(d9_on), bool(d11_on)

        # Tube inside = any role sensor on. The entry pair alone is not enough:
        # recorded on the trainer, while the tube is *held* at 9 / 11 cm the
        # translucent body at the entry often changes it by only 20–300 ADC
        # (below its trigger), so 9 cm used to wait for Entry → "lag".
        raw_inside = bool(entry_on) or d9 or d11
        if raw_inside:
            self._off_since = None
            cap = True
        elif self._cap_prev:
            if self._off_since is None:
                self._off_since = heal_at or now
            cap = (now - self._off_since) < INSIDE_RELEASE_S and heal_at is None
        else:
            cap = False
        level = 3 if d11 else 2 if d9 else 1 if cap else 0
        out.cap, out.d9, out.d11, out.level = cap, d9, d11, level
        out.entry = bool(entry_on)

        if cap and not self._cap_prev:
            self._in_start = now
            self._cur_max = level
            self._t9 = self._t11 = False
        if cap:
            self._cur_max = max(self._cur_max, level)
            if d9 and not self._t9:
                self._t9 = True
                out.events.append("touch9")
            if d11 and not self._t11:
                self._t11 = True
                out.events.append("touch11")
        if self._cap_prev and not cap and self._in_start is not None:
            # ends when the tube actually left, not after the release delay
            dur = (self._off_since or heal_at or now) - self._in_start
            if dur >= MIN_INJECTION_S:
                self.injections += 1
                self.total_time_ms += int(dur * 1000)
                self.last_time_s = dur
                self.max_level = max(self.max_level, self._cur_max)
                out.events.append(Injection(dur, self._cur_max))
            self._in_start = None
            self._cur_max = 0
            self._off_since = None
        self._cap_prev = cap
        out.in_start = self._in_start
        return out
