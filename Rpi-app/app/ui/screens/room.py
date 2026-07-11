"""3.2 / 3.3 Room — create or join a LAN room, then show the live attendee
list (Name | Time | Score). Each participant starts their own run.
"""
import tkinter as tk

from ...net.rooms import ROOM_PORT, RoomClient, RoomServer
from .. import theme
from .. import widgets as w


def render(app, parent, action=None, host=None, **kw):
    frame = tk.Frame(parent, bg=theme.BG)
    frame.pack(fill="both", expand=True, padx=48, pady=24)

    try:
        if action == "create":
            server = RoomServer(app.username)
            server.start()
            app.room = {"role": "host", "server": server, "host": server.ip}
        elif action == "join":
            client = RoomClient(host)
            client.join(app.username)
            app.room = {"role": "client", "client": client, "host": host}
        # action == "rejoin" reuses the existing app.room
    except OSError:
        return _error(app, frame, "Could not start/connect the room. Check the network.")
    except Exception:
        return _error(app, frame, "Host not found on this network.")

    if not app.room:
        return _error(app, frame, "No room.")

    is_host = app.room.get("role") == "host"
    addr = app.room.get("host")

    w.title(frame, "Room hosted" if is_host else "Room").pack(anchor="w")
    if is_host:
        w.subtitle(frame, "Others join by typing this address on their device:").pack(anchor="w", pady=(6, 8))
        addr_card = w.card(frame)
        addr_card.pack(fill="x")
        tk.Label(addr_card, text=f"{addr}", bg=theme.SURFACE, fg=theme.ACCENT,
                 font=theme.font(30, "bold")).pack(pady=14)
        tk.Label(addr_card, text=f"port {ROOM_PORT}", bg=theme.SURFACE, fg=theme.MUTED,
                 font=theme.SMALL).pack(pady=(0, 12))

    table_card = w.card(frame)
    table_card.pack(fill="both", expand=True, pady=(14, 0))
    tk.Label(table_card, text="Attendees", bg=theme.SURFACE, fg=theme.TEXT,
             font=theme.font(18, "bold")).pack(anchor="w", padx=18, pady=(14, 4))
    table = tk.Frame(table_card, bg=theme.SURFACE)
    table.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    def refresh():
        try:
            snap = (app.room["server"].snapshot() if is_host
                    else app.room["client"].get_attendees())
        except Exception:
            return
        _render_table(table, snap.get("attendees", []), app.username)

    app.set_poll(1500, refresh)
    refresh()

    btns = tk.Frame(frame, bg=theme.BG)
    btns.pack(anchor="w", pady=(16, 0))
    w.primary_button(btns, "Start my run", lambda: app.show("preparation")).pack(side="left")
    w.ghost_button(btns, "Leave", lambda: _leave(app)).pack(side="left", padx=(12, 0))


def _render_table(table, attendees, me):
    for child in table.winfo_children():
        child.destroy()
    header = tk.Frame(table, bg=theme.SURFACE)
    header.pack(fill="x")
    _cell(header, "Name", theme.MUTED, "w", weight="bold")
    _cell(header, "Time", theme.MUTED, "e", weight="bold")
    _cell(header, "Score", theme.MUTED, "e", weight="bold")
    for a in attendees:
        row = tk.Frame(table, bg=theme.SURFACE)
        row.pack(fill="x", pady=1)
        mine = a.get("username") == me
        fg = theme.ACCENT if mine else theme.TEXT
        time_s = "—" if a.get("time_sec") is None else f"{a['time_sec']:.2f} s"
        score_s = "—" if a.get("score") is None else f"{a['score']} ({a.get('level') or ''})"
        _cell(row, a.get("username", ""), fg, "w")
        _cell(row, time_s, fg, "e")
        _cell(row, score_s, fg, "e")


def _cell(parent, text, fg, anchor, weight="normal"):
    tk.Label(parent, text=text, bg=theme.SURFACE, fg=fg, font=theme.font(14, weight),
             anchor=anchor).pack(side="left", fill="x", expand=True, padx=8, pady=6)


def _leave(app):
    room = app.room or {}
    if room.get("role") == "host" and room.get("server"):
        try:
            room["server"].shutdown()
        except Exception:
            pass
    app.room = None
    app.mode = None
    app.show("mode_select")


def _error(app, frame, message):
    for child in frame.winfo_children():
        child.destroy()
    w.title(frame, "Connection problem").pack(anchor="w")
    tk.Label(frame, text=message, bg=theme.BG, fg=theme.BAD, font=theme.BODY,
             wraplength=820, justify="left").pack(anchor="w", pady=16)
    w.primary_button(frame, "Back", lambda: app.show("mode_select")).pack(anchor="w")
