"""ESP sensor-node interface (USB serial).

The only place the app touches hardware. A background thread reads the ESP
and keeps the latest sensor state; the UI polls it from the Tk main loop
(never blocks the UI). Set env ``SUCTION_SIM=1`` to run with a simulated
node so the whole app works without the rig.

Serial line protocol (ESP -> app), all newline-terminated:
  * ``1,0,1,1``                         legacy sensor flags (self-check / idle)
  * ``L,<depthCm>,<mmHg>,<elapsedMs>,<contactEvents>``   live run sample
  * ``E,<maxDepth>,<totalMs>,<mmHg>,<pAvail0|1>,<contact>``  session end
App -> ESP: ``START\n`` / ``ABORT\n``.
The legacy firmware only emits the first form; L/E are consumed when the
firmware is extended (see docs). SIM emits all three.
"""
from __future__ import annotations

import os
import queue
import random
import threading
import time
from typing import Optional

from .models import LiveSample, SensorStatus, SessionMetrics

BAUD_RATE = 115200

# Labels for the known 6-sensor rig; generic fallback if the count differs.
SENSOR_LAYOUT = [
    ("neck", "Neck-entry sensor (throat cap)"),
    ("depth6a", "6 cm depth sensor A (mount)"),
    ("depth6b", "6 cm depth sensor B (mount)"),
    ("depth8a", "8 cm depth sensor A (mount)"),
    ("depth8b", "8 cm depth sensor B (mount)"),
    ("pressure", "Suction pressure sensor (mount)"),
]


def use_sim() -> bool:
    if os.environ.get("SUCTION_SIM") == "1":
        return True
    try:
        import serial  # noqa: F401
    except ImportError:
        return True
    return False


def find_esp() -> Optional[str]:
    """Return the ESP's serial device path, or None. (from the original app)"""
    try:
        from serial.tools import list_ports
    except ImportError:
        return None
    for port in list_ports.comports():
        desc = port.description or ""
        if ("USB" in desc or "CP210" in desc or "CH340" in desc or "ACM" in port.device):
            return port.device
    return None


class SensorNode:
    def __init__(self, sim: Optional[bool] = None) -> None:
        self.sim = use_sim() if sim is None else sim
        self._flags: list[str] = []
        self._flags_lock = threading.Lock()
        self._events: "queue.Queue[tuple]" = queue.Queue()
        self._serial = None
        self._stop = threading.Event()
        self._sim_run_active = False

    # -- lifecycle -----------------------------------------------------
    def start(self) -> None:
        target = self._sim_loop if self.sim else self._serial_loop
        threading.Thread(target=target, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    # -- state the UI reads -------------------------------------------
    def _set_flags(self, flags: list[str]) -> None:
        with self._flags_lock:
            self._flags = flags

    def get_flags(self) -> list[str]:
        with self._flags_lock:
            return list(self._flags)

    def self_check(self) -> list[SensorStatus]:
        flags = self.get_flags()
        statuses = []
        for i, flag in enumerate(flags):
            if i < len(SENSOR_LAYOUT):
                sid, label = SENSOR_LAYOUT[i]
            else:
                sid, label = f"sensor{i+1}", f"Sensor {i + 1}"
            statuses.append(SensorStatus(id=sid, ok=(flag == "1"), label=label))
        return statuses

    def drain_events(self) -> list:
        out = []
        while True:
            try:
                out.append(self._events.get_nowait())
            except queue.Empty:
                break
        return out

    # -- commands ------------------------------------------------------
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

    # -- line parsing --------------------------------------------------
    def _handle_line(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        parts = line.split(",")
        tag = parts[0]

        if all(tok in ("0", "1") for tok in parts):
            self._set_flags(parts)
        elif tag == "L" and len(parts) >= 5:
            self._events.put(("live", LiveSample(
                depth_cm=int(float(parts[1])),
                pressure_mmhg=float(parts[2]) if parts[2] not in ("", "-") else None,
                elapsed_ms=int(float(parts[3])),
                contact_events=int(float(parts[4])),
                phase="suction" if int(float(parts[1])) >= 8 else "insert",
            )))
        elif tag == "E" and len(parts) >= 6:
            self._events.put(("end", SessionMetrics(
                max_depth_cm=int(float(parts[1])),
                total_time_ms=int(float(parts[2])),
                pressure_mmhg=float(parts[3]) if parts[3] not in ("", "-") else None,
                pressure_available=(parts[4] == "1"),
                contact_events=int(float(parts[5])),
                contact_band_count=int(float(parts[6])) if len(parts) > 6 else 0,
            )))

    # -- real serial ---------------------------------------------------
    def _serial_loop(self) -> None:  # pragma: no cover - hardware path
        import serial
        while not self._stop.is_set():
            port = find_esp()
            if port is None:
                time.sleep(2)
                continue
            try:
                self._serial = serial.Serial(port, BAUD_RATE, timeout=1)
                while not self._stop.is_set():
                    line = self._serial.readline().decode(errors="ignore")
                    if line:
                        self._handle_line(line)
            except Exception:
                self._serial = None
                time.sleep(2)

    # -- simulation ----------------------------------------------------
    def _sim_loop(self) -> None:
        # All six sensors report connected (fault one if SUCTION_SIM_FAULT set).
        fault = os.environ.get("SUCTION_SIM_FAULT")
        flags = ["1"] * len(SENSOR_LAYOUT)
        if fault and fault.isdigit() and 0 <= int(fault) < len(flags):
            flags[int(fault)] = "0"
        while not self._stop.is_set():
            self._set_flags(flags)
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
