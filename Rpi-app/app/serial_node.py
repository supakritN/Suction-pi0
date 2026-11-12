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


# Factory calibration recorded on the trainer (tools/build_default_calibration.py).
_DEFAULT_CAL_PATH = Path(__file__).resolve().parent.parent / "calibration_default.json"
_DEFAULT_CAL_KEYS = ("enabled_pins", "roles", "trigger_delta_overrides", "calibrated_levels")

_cfg_cache: dict = {"mtime": None, "data": {}}


def load_default_calibration() -> dict:
    try:
        return json.loads(_DEFAULT_CAL_PATH.read_text())
    except Exception:
        return {}


def _load_config() -> dict:
    """pins_config.json, re-read only when the file changes (UI polls this often).
    Without a pins_config.json the factory calibration is used."""
    try:
        mtime = _PINS_CONFIG_PATH.stat().st_mtime_ns
    except OSError:
        d = load_default_calibration()
        return {k: d[k] for k in _DEFAULT_CAL_KEYS if k in d}
    if mtime != _cfg_cache["mtime"]:
        try:
            _cfg_cache["data"] = json.loads(_PINS_CONFIG_PATH.read_text())
        except Exception:
            _cfg_cache["data"] = {}
        _cfg_cache["mtime"] = mtime
    return dict(_cfg_cache["data"])


def _write_config(cfg: dict) -> None:
    tmp = _PINS_CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, indent=2))
    tmp.replace(_PINS_CONFIG_PATH)


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
        _write_config(cfg)
    except Exception:
        pass


def save_calibration(thresholds: dict[int, int],
                     baseline: Optional[dict[int, int]] = None,
                     triggered: Optional[dict[int, int]] = None) -> None:
    """Persist per-pin thresholds (+ the measured tube-out / tube-in levels,
    which the detector uses to recover if a session starts with the tube in)."""
    try:
        cfg = _load_config()
        cfg["trigger_delta_overrides"] = {str(pin): int(thr)
                                           for pin, thr in thresholds.items()}
        if baseline and triggered:
            cfg["calibrated_levels"] = {
                str(pin): [int(baseline[pin]), int(triggered[pin])]
                for pin in thresholds
                if baseline.get(pin, -1) >= 0 and triggered.get(pin, -1) >= 0
            }
        from datetime import datetime
        cfg["calibrated_at"] = datetime.now().isoformat(timespec="seconds")
        cfg["calibration_source"] = "auto"
        _write_config(cfg)
    except Exception:
        pass


def apply_default_calibration() -> bool:
    """Load the factory calibration into pins_config.json (Calibrate screen
    button). Auto-calibrate can overwrite it again at any time."""
    d = load_default_calibration()
    if not d:
        return False
    cfg = _load_config()
    for k in _DEFAULT_CAL_KEYS:
        if k in d:
            cfg[k] = d[k]
    cfg["calibrated_at"] = f"factory default ({d.get('recorded_at', '?')})"
    cfg["calibration_source"] = "default"
    _write_config(cfg)
    return True


def save_regression_calibration(result: dict) -> None:
    """Persist a factory + linear-regression calibration (app/regression.py)."""
    d = load_default_calibration()
    cfg = _load_config()
    for k in ("enabled_pins", "roles"):
        if k in d:
            cfg[k] = d[k]
    cfg["trigger_delta_overrides"] = result["trigger_delta_overrides"]
    cfg["calibrated_levels"] = result["calibrated_levels"]
    cfg["regression"] = {
        str(pin): {"a": round(p["a"], 4), "b": round(p["b"], 2),
                   "r2": None if p["r2"] is None else round(p["r2"], 4),
                   "mode": p["mode"], "points": p["points"]}
        for pin, p in result["pins"].items()
    }
    from datetime import datetime
    cfg["calibrated_at"] = datetime.now().isoformat(timespec="seconds")
    cfg["calibration_source"] = "regression"
    _write_config(cfg)


def load_roles():
    """Which GPIOs mean entry / 9 cm / 11 cm (pins_config "roles"); legacy
    layout (Cap = GPIO 4) when not configured."""
    from .detector import Roles
    raw = _load_config().get("roles")
    if not isinstance(raw, dict):
        return Roles()
    try:
        return Roles(entry=tuple(int(p) for p in raw.get("entry", [])),
                     d9=tuple(int(p) for p in raw.get("d9", [])),
                     d11=tuple(int(p) for p in raw.get("d11", [])))
    except Exception:
        return Roles()


def load_calibrated_levels() -> dict[int, tuple]:
    """{pin: (tube_out, tube_in[, tube-in at other depths…])} from the last
    calibration, if any."""
    out = {}
    for k, v in _load_config().get("calibrated_levels", {}).items():
        try:
            levels = tuple(int(x) for x in v)
            if len(levels) >= 2:
                out[int(k)] = levels
        except Exception:
            continue
    return out


def calibration_summary() -> str:
    """Short human label for the calibration currently in use."""
    cfg = _load_config()
    src = cfg.get("calibration_source")
    at = str(cfg.get("calibrated_at", ""))
    if src == "default":
        return "Factory defaults"
    if src == "regression":
        return f"Factory + regression ({at.replace('T', ' ')[:16]})"
    if src == "auto" or at:
        return f"Your calibration ({at.replace('T', ' ')[:16]})" if at else "Your calibration"
    return "Not calibrated"


def load_calibrated_at() -> str:
    """Return the ISO timestamp of the last calibration, or empty string."""
    return str(_load_config().get("calibrated_at", ""))

BAUD_RATE = 115200
_ADC_FAULT_LOW   = 20
_ADC_FAULT_HIGH  = 4075
_STALE_SEC       = 1.0
_EMA_ALPHA       = 0.35    # per-sample smoothing; ~50 ms time constant at 50 lines/s
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
    """Return any USB serial device, or None. Works on any USB port.

    SUCTION_PORT overrides detection: a device path (/dev/ttyACM0, COM5) or a
    pyserial URL such as socket://127.0.0.1:7777 (used by tools/fake_esp.py).
    """
    override = os.environ.get("SUCTION_PORT")
    if override:
        return override
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
        self._pin_smooth: dict[int, float] = {}
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
            self._pin_smooth = {}
            self._pin_history = {}

    def _set_pin_values(self, values: dict[int, int]) -> None:
        with self._lock:
            self._pin_value.update(values)
            sm = self._pin_smooth
            for pin, v in values.items():
                h = self._pin_history.setdefault(pin, [])
                h.append(v)
                if len(h) > _HISTORY_LEN:
                    del h[0]
                # median-of-3 kills single-sample spikes, then EMA smooths noise
                m = sorted(h[-3:])[len(h[-3:]) // 2]
                prev = sm.get(pin)
                sm[pin] = m if prev is None else prev + _EMA_ALPHA * (m - prev)
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
        """Smoothed ADC values keyed by GPIO pin. Empty if port is stale.

        Smoothing runs at the full serial rate (~100 Hz) in the reader thread,
        so the UI's slower poll sees a steady value instead of a random noisy
        sample.
        """
        with self._lock:
            if not self._fresh_locked():
                return {}
            return {p: int(round(v)) for p, v in self._pin_smooth.items()}

    def get_smoothed(self, n: int = 10) -> dict[int, int]:
        """Mean of the last n raw samples per pin (≈ n × 20 ms)."""
        with self._lock:
            if not self._fresh_locked():
                return {}
            out = {}
            for pin, h in self._pin_history.items():
                tail = h[-n:]
                if tail:
                    out[pin] = sum(tail) // len(tail)
            return out

    def get_raw_pin_values(self) -> dict[int, int]:
        """Last raw (unsmoothed) ADC values keyed by GPIO pin."""
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
            # smoothed values for display; raw history drives fault detection
            pv = {p: int(round(v)) for p, v in self._pin_smooth.items()} if fresh else {}
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
                # 20th–80th percentile spread: noise spikes can't flip a good
                # pin to "floating" (blinking dot); a floating pin spans ~2400
                srt = sorted(h)
                n = len(srt)
                rng = srt[n * 4 // 5] - srt[n // 5]
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
        try:
            self._parse_line(line)
        except (ValueError, IndexError):
            pass  # garbled / partial line — drop the line, never the connection

    def _parse_line(self, line: str) -> None:
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
            ser = None
            try:
                if "://" in port:
                    ser = serial.serial_for_url(port, BAUD_RATE, timeout=0.2)
                else:
                    # exclusive: a second app instance can't steal half the stream
                    kw = {"exclusive": True} if os.name == "posix" else {}
                    ser = serial.Serial(port, BAUD_RATE, timeout=0.2, **kw)
                ser.reset_input_buffer()   # drop stale bytes queued before we opened
                self._serial = ser
                self._read_lines(ser)
            except Exception:
                pass
            finally:
                self._serial = None
                if ser is not None:
                    try:
                        ser.close()
                    except Exception:
                        pass
            self._mark_disconnected()
            time.sleep(1)

    def _read_lines(self, ser) -> None:
        """Read in chunks and split lines ourselves. pyserial's readline() does
        one syscall per byte, which costs ~30% of a Pi 3 core at 50 lines/s
        and starves the UI thread of the GIL."""
        buf = b""
        synced = False   # the first fragment after open usually starts mid-line
        while not self._stop.is_set():
            chunk = ser.read(ser.in_waiting or 1)
            if chunk:
                buf += chunk
                *lines, buf = buf.split(b"\n")
                for raw in lines:
                    if synced:
                        self._handle_line(raw.decode(errors="ignore"))
                    synced = True
                if len(buf) > 4096:    # no newline for ages → garbage, resync
                    buf, synced = b"", False
            elif (time.monotonic() - self._last_rx) > _STALE_SEC:
                return

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
