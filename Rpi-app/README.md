# Suction Trainer — Raspberry Pi App

Touchscreen training app for the suction rig. Grew out of the original ESP
sensor-monitor into the full accepted flow: **name → mode → preparation →
tutorial → process → results**, with UI-editable scoring weights and LAN
rooms. Pure Python + Tkinter (only `pyserial` is an external dependency).

## Run

On the Pi with the ESP connected:
```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

No hardware? Use the built-in simulator (drives sensors + a full run):
```bash
SUCTION_SIM=1 python3 main.py
# force a faulted sensor on the Preparation screen:
SUCTION_SIM=1 SUCTION_SIM_FAULT=2 python3 main.py
```

`ESC` or the **✕ Exit** button quits. On macOS/Windows the app runs in a
window; on the Pi it goes fullscreen on the local display.

## Screen flow

1. **Name** — type a name, press OK (no login/password).
2. **Mode** — Create room · Join room · Offline.
3. **Preparation** — sensor self-check; the **Ready** button appears only
   when every sensor passes, and names any faulted sensor.
4. **Tutorial** — quick popup of the steps, then the run starts.
5. **Process** — live depth / pressure / time / contact; ends automatically
   on the node's session-end (or press **Done**).
6. **Results** — total score, level, and per-category breakdown.
   In a room the result is also sent to the host.

## Structure

```
pi0-Rpi-app/
  main.py                 # entry point (display guard + launch)
  scoring_config.json     # UI-editable weights, thresholds, levels, PIN
  requirements.txt
  app/
    models.py             # SensorStatus, SessionMetrics, ScoreResult, Attendee
    config.py             # load/save scoring_config.json, PIN check
    scoring.py            # data-driven scoring engine
    serial_node.py        # ESP serial: self-check + run frames + SUCTION_SIM
    net/rooms.py          # LAN room host/client (stdlib HTTP)
    ui/
      app.py              # Tk root + screen manager + shared state
      theme.py            # colors + fonts (touch-friendly)
      widgets.py          # styled buttons, cards
      screens/            # name, mode_select, preparation, process, results, room, settings
```

## Scoring weights (editable in the UI)

`scoring_config.json` holds the accepted defaults (Depth 30 / Duration 20 /
Pressure 20 / Contact 30, same band cut-points as the firmware). The
**⚙ Scoring settings** screen (PIN-gated, default `0000`) edits the weights
live; each category scores `weight × fraction`, the total normalizes to 100,
and pressure drops out of the denominator when it can't be mapped to mmHg.

## Records (CSV)

Every finished run is appended to a CSV next to `main.py`, so results open
straight in Excel/Sheets:

- `results.csv` — every run on this device (offline or in a room)
- `room_results.csv` — on a host, every attendee result received over the network

Columns: `timestamp, name, mode, room, total, level, depth_pts, duration_pts,
pressure_pts, contact_pts, max_depth_cm, total_time_s, pressure_mmhg,
contact_events`. The Results screen shows which file it was saved to.

## Rooms (LAN)

Create room → this Pi hosts and shows its **address (IP)**; others pick
*Join room* and type that address. Everyone runs their own session; each
result is scored with the **host's** rubric and appears in the shared
attendee list (Name · Time · Score). No internet or accounts — same
network only. (mDNS auto-discovery and short room codes are a later add.)

## Serial protocol (ESP → app)

Newline-terminated lines:

| Line | Meaning |
| --- | --- |
| `1,0,1,1` | sensor connected flags (self-check / idle) — the legacy format |
| `L,<depthCm>,<mmHg>,<elapsedMs>,<contactEvents>` | live run sample |
| `E,<maxDepth>,<totalMs>,<mmHg>,<pAvail 0\|1>,<contact>` | session end |

App → ESP: `START` / `ABORT`. The current firmware emits only the first
form (used by Preparation); scoring consumes `L`/`E` once the firmware is
extended. Until then, `SUCTION_SIM=1` exercises the whole flow.

## Autostart on the Pi

Edit `Suction.desktop` paths to match your install, then:
```bash
mkdir -p ~/.config/autostart && cp Suction.desktop ~/.config/autostart/
```
