"""5 / 4.2 Process — the live run. Starts the session on the node, shows
depth / pressure / time / contact, and advances to Results when the node
reports session end (or the user presses Done).
"""
import tkinter as tk

from ... import config as cfg_store
from ... import results_log
from ... import scoring
from .. import theme
from .. import widgets as w

_state = {}


def render(app, parent, **kw):
    frame = tk.Frame(parent, bg=theme.BG)
    frame.pack(fill="both", expand=True, padx=48, pady=30)

    w.title(frame, "Practice in progress").pack(anchor="w")
    phase = tk.Label(frame, text="starting…", bg=theme.SURFACE2, fg=theme.ACCENT,
                     font=theme.font(14, "bold"), padx=14, pady=6)
    phase.pack(anchor="w", pady=(10, 20))

    grid = tk.Frame(frame, bg=theme.BG)
    grid.pack(fill="x")
    for i in range(4):
        grid.columnconfigure(i, weight=1, uniform="m")
    depth = _metric(grid, 0, "Depth (cm)", "0")
    pressure = _metric(grid, 1, "Pressure (mmHg)", "—")
    elapsed = _metric(grid, 2, "Time (s)", "0.0")
    contact = _metric(grid, 3, "Contact events", "0")

    done = w.primary_button(frame, "Done", lambda: _finish(app))
    done.pack(anchor="w", pady=(26, 0))
    done.configure(state="disabled")

    _state[id(app)] = {"metrics": None}
    app.node.start_session()

    def poll():
        for kind, obj in app.node.drain_events():
            if kind == "live":
                phase.config(text=obj.phase)
                depth.config(text=str(obj.depth_cm))
                pressure.config(text="—" if obj.pressure_mmhg is None else str(obj.pressure_mmhg))
                elapsed.config(text=f"{obj.elapsed_ms / 1000:.1f}")
                contact.config(text=str(obj.contact_events))
                done.configure(state="normal")
            elif kind == "end":
                _state[id(app)]["metrics"] = obj
                _finish(app)
                return

    app.set_poll(150, poll)


def _metric(parent, col, label, value):
    cell = tk.Frame(parent, bg=theme.SURFACE, highlightbackground=theme.BORDER, highlightthickness=1)
    cell.grid(row=0, column=col, sticky="nsew", padx=8, pady=6, ipady=10)
    val = tk.Label(cell, text=value, bg=theme.SURFACE, fg=theme.TEXT, font=theme.font(30, "bold"))
    val.pack(pady=(10, 2))
    tk.Label(cell, text=label, bg=theme.SURFACE, fg=theme.MUTED, font=theme.SMALL).pack(pady=(0, 8))
    return val


def _finish(app):
    st = _state.get(id(app), {})
    metrics = st.get("metrics")
    if metrics is None:
        # user pressed Done before the node reported end
        app.node.abort()
        return
    app.clear_poll()
    result = scoring.score_session(metrics, cfg_store.load_config())
    app.last_metrics = metrics
    app.last_score = result

    # log this run to a CSV the instructor can open in Excel
    try:
        room_addr = app.room.get("host") if app.room else None
        app.last_csv = results_log.log_result(app.username, app.mode, room_addr, metrics, result)
    except Exception:
        app.last_csv = None

    if app.room:
        try:
            if app.room.get("role") == "host":
                app.room["server"].record(app.username, metrics.to_dict())
            else:
                app.room["client"].send_result(app.username, metrics.to_dict())
        except Exception:
            pass

    app.show("results")
