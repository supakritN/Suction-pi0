"""ESP sensor-node interface (USB serial).

Current firmware output (115200 baud), one line per 10 ms:
  pin4:v,pin5:v,pin6:v,pin7:v,pin15:v,pin17:v,pin1:v,pin2:v,pin18:v,pin8:v,pin3:v,pin9:v

Each `pinN:value` carries the GPIO number explicitly, so the Pi can map pin
→ location (SENSOR_LAYOUT below) without caring about field order.

Also accepts legacy forms:
  v1,v2,...,v12            comma-separated raw ADC in firmware pin order
  S1:v,S2:v,...,P:raw      earlier S-tag format
  1,0,1,1                  very old 0/1 flags
  L,...  /  E,...          optional run-event frames
"""
from __future__ import annotations

import json
import os
import queue
import random
import threading
import time
from pathlib import Path
from typing import Optional

from .models import LiveSample, SensorStatus, SessionMetrics


# ── pin enable/disable config ──────────────────────────────
_PINS_CONFIG_PATH = Path(__file__).resolve().parent.parent / "pins_config.json"
# Default: only the 5 throat IR sensors
_DEFAULT_ENABLED_PINS = {4, 5, 6, 7, 15}


def _load_config() -> dict:
    try:
        return json.loads(_PINS_CONFIG_PATH.read_text())
    except Exception:
        return {}


def load_enabled_pins() -> set[int]:
    pins = _load_config().get("enabled_pins")
    if isinstance(pins, list):
        try:
            return {int(p) for p in pins}
        except Exception:
            pass
    return set(_DEFAULT_ENABLED_PINS)


def load_trigger_deltas() -> tuple[int, dict[int, int]]:
    """Return (default_threshold, per_pin_overrides)."""
    cfg = _load_config()
    default = int(cfg.get("trigger_delta_default", 120))
    overrides: dict[int, int] = {}
    raw = cfg.get("trigger_delta_overrides", {})
    if isinstance(raw, dict):
        for k, v in raw.items():
            try:
                overrides[int(k)] = int(v)
            except Exception:
                continue
    return default, overrides


def save_enabled_pins(pins: set[int]) -> None:
    try:
        cfg = _load_config()
        cfg["enabled_pins"] = sorted(pins)
        _PINS_CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    except Exception:
        pass


def save_calibration(thresholds: dict[int, int]) -> None:
    """Persist per-pin trigger_delta_overrides computed from a calibration run."""
    try:
        cfg = _load_config()
        cfg["trigger_delta_overrides"] = {str(pin): int(thr)
                                           for pin, thr in thresholds.items()}
        from datetime import datetime
        cfg["calibrated_at"] = datetime.now().isoformat(timespec="seconds")
        _PINS_CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    except Exception:
        pass


def load_calibrated_at() -> str:
    """Return the ISO timestamp of the last calibration, or empty string."""
    return str(_load_config().get("calibrated_at", ""))

BAUD_RATE = 115200
_ADC_FAULT_LOW   = 20
_ADC_FAULT_HIGH  = 4075
_STALE_SEC       = 2.0
_HISTORY_LEN     = 15      # per-pin rolling window for stability check
_FLOAT_RANGE_MIN = 400     # max-min over window → "pin is floating" (not wired)

# (id, location label, GPIO pin, side)
SENSOR_LAYOUT = [
    ("throat_cap", "Cap (entry)",   4,  "throat"),
    ("throat_tl",  "Top-Left",      5,  "throat"),
    ("throat_tr",  "Top-Right",     6,  "throat"),
    ("throat_bl",  "Bottom-Left",   7,  "throat"),
    ("throat_br",  "Bottom-Right",  15, "throat"),
    ("mouth_cap",  "Cap (entry)",   17, "mouth"),
    ("mouth_tl",   "Top-Left",      1,  "mouth"),
    ("mouth_tr",   "Top-Right",     2,  "mouth"),
    ("mouth_bl",   "Bottom-Left",   18, "mouth"),
    ("mouth_br",   "Bottom-Right",  8,  "mouth"),
    ("pressure_a", "Pressure A",    3,  "pressure"),
    ("pressure_b", "Pressure B",    9,  "pressure"),
]

# Order the current firmware sends values in when it does NOT prefix with pinN:
_FIRMWARE_PIN_ORDER = [4, 5, 6, 7, 15, 17, 1, 2, 18, 8, 3, 9]


def use_sim() -> bool:
    if os.environ.get("SUCTION_SIM") == "1":
        return True
    try:
        import serial  # noqa: F401
    except ImportError:
        return True
    return False


def find_esp() -> Optional[str]:
    """Return any USB serial device, or None. Works on any USB port."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return None
    for port in list_ports.comports():
        desc = port.description or ""
        if ("USB" in desc or "CP210" in desc or "CH340" in desc or "ACM" in port.device):
            return port.device
    return None


def _is_int(tok: str) -> bool:
    tok = tok.strip()
    if not tok:
        return False
    if tok[0] in "+-":
        return tok[1:].isdigit()
    return tok.isdigit()


class SensorNode:
    def __init__(self, sim: Optional[bool] = None) -> None:
        self.sim = use_sim() if sim is None else sim
        self._pin_value: dict[int, int] = {}
        self._pin_history: dict[int, list[int]] = {}  # for stability / floating detection
        self._last_rx: float = 0.0
        self._connected: bool = False
        self._lock = threading.Lock()
        self._events: "queue.Queue[tuple]" = queue.Queue()
        self._serial = None
        self._stop = threading.Event()
        self._sim_run_active = False

    # ── lifecycle ─────────────────────────────────────────
    def start(self) -> None:
        target = self._sim_loop if self.sim else self._serial_loop
        threading.Thread(target=target, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    # ── connection / freshness ────────────────────────────
    def is_connected(self) -> bool:
        with self._lock:
            return self._fresh_locked()

    def _fresh_locked(self) -> bool:
        if not self._connected:
            return False
        if self.sim:
            return True
        return (time.monotonic() - self._last_rx) < _STALE_SEC

    def _mark_disconnected(self) -> None:
        with self._lock:
            self._connected = False
            self._pin_value = {}
            self._pin_history = {}

    def _set_pin_values(self, values: dict[int, int]) -> None:
        with self._lock:
            self._pin_value = values
            for pin, v in values.items():
                h = self._pin_history.setdefault(pin, [])
                h.append(v)
                if len(h) > _HISTORY_LEN:
                    del h[0]
            self._last_rx = time.monotonic()
            self._connected = True

    # ── state the UI reads ────────────────────────────────
    def get_raw(self) -> list[int]:
        """Raw ADC values in SENSOR_LAYOUT order (-1 if sensor not reported)."""
        with self._lock:
            if not self._fresh_locked():
                return []
            return [self._pin_value.get(pin, -1) for (_, _, pin, _) in SENSOR_LAYOUT]

    def get_pin_values(self) -> dict[int, int]:
        """Raw ADC values keyed by GPIO pin. Empty if port is stale."""
        with self._lock:
            if not self._fresh_locked():
                return {}
            return dict(self._pin_value)

    def get_flags(self) -> list[str]:
        with self._lock:
            if not self._fresh_locked():
                return []
            flags = []
            for (_, _, pin, _) in SENSOR_LAYOUT:
                v = self._pin_value.get(pin, -1)
                if v < 0:
                    flags.append("0")
                else:
                    flags.append("1" if _ADC_FAULT_LOW < v < _ADC_FAULT_HIGH else "0")
            return flags

    def self_check(self) -> list[SensorStatus]:
        enabled = load_enabled_pins()
        with self._lock:
            fresh = self._fresh_locked()
            pv = dict(self._pin_value) if fresh else {}
            hist = {p: list(h) for p, h in self._pin_history.items()} if fresh else {}

        out: list[SensorStatus] = []
        for sid, label, pin, side in SENSOR_LAYOUT:
            pin_label = f"GPIO {pin}"

            # Disabled pins — show as red, don't block Ready
            if pin not in enabled:
                adc_info = f"ADC {pv[pin]}" if pin in pv else "no data"
                out.append(SensorStatus(
                    id=sid, ok=False, label=label,
                    detail=f"{pin_label} · disabled ({adc_info})",
                    present=True, side=side, disabled=True,
                ))
                continue

            if pin not in pv:
                out.append(SensorStatus(
                    id=sid, ok=False, label=label,
                    detail=f"{pin_label} · no data from ESP",
                    present=False, side=side,
                ))
                continue

            adc = pv[pin]
            h = hist.get(pin, [])

            if len(h) >= _HISTORY_LEN:
                rng = max(h) - min(h)
                avg = sum(h) // len(h)
                if rng >= _FLOAT_RANGE_MIN:
                    out.append(SensorStatus(
                        id=sid, ok=False, label=label,
                        detail=f"{pin_label} · floating (ADC {adc}, range ±{rng//2})",
                        present=False, side=side,
                    ))
                    continue
                if avg <= _ADC_FAULT_LOW or avg >= _ADC_FAULT_HIGH:
                    out.append(SensorStatus(
                        id=sid, ok=False, label=label,
                        detail=f"{pin_label} · stuck at rail (ADC {adc})",
                        present=False, side=side,
                    ))
                    continue
                out.append(SensorStatus(
                    id=sid, ok=True, label=label,
                    detail=f"{pin_label} · ADC {adc}",
                    present=True, side=side,
                ))
            else:
                out.append(SensorStatus(
                    id=sid, ok=True, label=label,
                    detail=f"{pin_label} · ADC {adc} (sampling…)",
                    present=True, side=side,
                ))
        return out

    def drain_events(self) -> list:
        out = []
        while True:
            try:
                out.append(self._events.get_nowait())
            except queue.Empty:
                break
        return out

    def start_session(self) -> None:
        if self.sim:
            if not self._sim_run_active:
                threading.Thread(target=self._sim_run, daemon=True).start()
        elif self._serial is not None:
            try:
                self._serial.write(b"START\n")
            except Exception:
                pass

    def abort(self) -> None:
        if not self.sim and self._serial is not None:
            try:
                self._serial.write(b"ABORT\n")
            except Exception:
                pass

    # ── line parsing ──────────────────────────────────────
    def _handle_line(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        parts = line.split(",")
        tag = parts[0]

        # L / E run-event frames
        if tag == "L" and len(parts) >= 5:
            self._events.put(("live", LiveSample(
                depth_cm=int(float(parts[1])),
                pressure_mmhg=float(parts[2]) if parts[2] not in ("", "-") else None,
                elapsed_ms=int(float(parts[3])),
                contact_events=int(float(parts[4])),
                phase="suction" if int(float(parts[1])) >= 8 else "insert",
            )))
            return
        if tag == "E" and len(parts) >= 6:
            self._events.put(("end", SessionMetrics(
                max_depth_cm=int(float(parts[1])),
                total_time_ms=int(float(parts[2])),
                pressure_mmhg=float(parts[3]) if parts[3] not in ("", "-") else None,
                pressure_available=(parts[4] == "1"),
                contact_events=int(float(parts[5])),
                contact_band_count=int(float(parts[6])) if len(parts) > 6 else 0,
            )))
            return

        # Current firmware: pin4:val,pin5:val,...
        if tag.startswith("pin") and ":" in tag:
            values: dict[int, int] = {}
            for part in parts:
                if ":" not in part:
                    continue
                key, val_str = part.split(":", 1)
                key = key.strip()
                if not key.startswith("pin"):
                    continue
                try:
                    pin = int(key[3:])
                    val = int(val_str)
                except ValueError:
                    continue
                values[pin] = val
            if values:
                self._set_pin_values(values)
            return

        # Earlier format: S1:val,...,P:raw
        if tag[0] == "S" and ":" in tag and tag[1:tag.index(":")].isdigit():
            values: dict[int, int] = {}
            idx = 0
            for part in parts:
                if ":" not in part:
                    continue
                key, val_str = part.split(":", 1)
                try:
                    val = int(val_str)
                except ValueError:
                    continue
                if key == "P":
                    values[3] = val   # map P → pressure A (GPIO 3)
                elif key.startswith("S") and key[1:].isdigit():
                    i = int(key[1:]) - 1
                    if 0 <= i < len(_FIRMWARE_PIN_ORDER):
                        values[_FIRMWARE_PIN_ORDER[i]] = val
                idx += 1
            if values:
                self._set_pin_values(values)
            return

        # Legacy: comma-separated raw ADC in firmware pin order
        if len(parts) >= 5 and all(_is_int(p) for p in parts):
            vals = [int(p) for p in parts]
            values = {}
            for i, v in enumerate(vals):
                if i < len(_FIRMWARE_PIN_ORDER):
                    values[_FIRMWARE_PIN_ORDER[i]] = v
            self._set_pin_values(values)
            return

    # ── real serial ───────────────────────────────────────
    def _serial_loop(self) -> None:
        import serial
        while not self._stop.is_set():
            port = find_esp()
            if port is None:
                self._mark_disconnected()
                time.sleep(1)
                continue
            try:
                self._serial = serial.Serial(port, BAUD_RATE, timeout=1)
                while not self._stop.is_set():
                    line = self._serial.readline().decode(errors="ignore")
                    if line:
                        self._handle_line(line)
                    elif (time.monotonic() - self._last_rx) > _STALE_SEC:
                        self._mark_disconnected()
            except Exception:
                self._serial = None
                self._mark_disconnected()
                time.sleep(1)

    # ── simulation ────────────────────────────────────────
    def _sim_loop(self) -> None:
        fault = os.environ.get("SUCTION_SIM_FAULT")
        base = {4: 2000, 5: 1800, 6: 2200, 7: 1900, 15: 2100,
                17: 2050, 1: 1950, 2: 2150, 18: 1850, 8: 2000,
                3: 1500, 9: 1500}
        if fault and fault.isdigit() and 0 <= int(fault) < len(SENSOR_LAYOUT):
            _, _, pin, _ = SENSOR_LAYOUT[int(fault)]
            base[pin] = 0
        while not self._stop.is_set():
            self._set_pin_values(dict(base))
            time.sleep(0.5)

    def _sim_run(self) -> None:
        self._sim_run_active = True
        try:
            elapsed = 0
            for depth, phase in [(0, "insert"), (6, "insert"), (8, "suction"), (8, "suction")]:
                elapsed += 1800
                self._events.put(("live", LiveSample(
                    depth_cm=depth,
                    pressure_mmhg=round(random.uniform(85, 115), 1),
                    elapsed_ms=elapsed,
                    contact_events=0,
                    phase=phase,
                )))
                time.sleep(0.7)
            self._events.put(("end", SessionMetrics(
                max_depth_cm=8,
                total_time_ms=elapsed,
                pressure_mmhg=round(random.uniform(85, 115), 1),
                pressure_available=True,
                contact_events=random.choice([0, 0, 1]),
                contact_band_count=3,
            )))
        finally:
            self._sim_run_active = False
