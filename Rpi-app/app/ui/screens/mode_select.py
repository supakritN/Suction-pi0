"""2. Mode select — create room, join room, or offline."""
import tkinter as tk

from .. import theme
from .. import widgets as w


def render(app, parent, **kw):
    frame = tk.Frame(parent, bg=theme.BG)
    frame.pack(fill="both", expand=True, padx=48, pady=36)

    w.title(frame, "Choose a mode").pack(anchor="w")
    w.subtitle(frame, "Practice on your own, or run a shared session over the local network.").pack(
        anchor="w", pady=(6, 24))

    tiles = tk.Frame(frame, bg=theme.BG)
    tiles.pack(fill="x")
    for i in range(3):
        tiles.columnconfigure(i, weight=1, uniform="tiles")

    _tile(tiles, 0, "➕", "Create room", "Host a session on this Pi",
          lambda: _create(app))
    _tile(tiles, 1, "🔗", "Join room", "Enter the host's address",
          lambda: _join(app, frame))
    _tile(tiles, 2, "📴", "Offline", "Just this device",
          lambda: _offline(app))

    foot = tk.Frame(frame, bg=theme.BG)
    foot.pack(anchor="w", pady=(26, 0))
    w.ghost_button(foot, "⚙  Scoring settings", lambda: app.show("settings")).pack(side="left")
    w.ghost_button(foot, "📋  History",         lambda: app.show("history")).pack(side="left", padx=(10, 0))


def _tile(parent, col, icon, label, hint, command):
    btn = tk.Button(parent, command=command, bg=theme.SURFACE, fg=theme.TEXT,
                    activebackground=theme.SURFACE2, activeforeground=theme.TEXT,
                    relief="flat", bd=0, cursor="hand2", highlightthickness=1,
                    highlightbackground=theme.BORDER)
    inner = tk.Frame(btn, bg=theme.SURFACE)
    tk.Label(inner, text=icon, bg=theme.SURFACE, fg=theme.ACCENT, font=theme.font(34)).pack(pady=(18, 4))
    tk.Label(inner, text=label, bg=theme.SURFACE, fg=theme.TEXT, font=theme.font(20, "bold")).pack()
    tk.Label(inner, text=hint, bg=theme.SURFACE, fg=theme.MUTED, font=theme.SMALL).pack(pady=(2, 18))
    inner.pack()
    # make the whole tile clickable, not just the button face
    for child in (inner, *inner.winfo_children()):
        child.bind("<Button-1>", lambda e, c=command: c())
    btn.grid(row=0, column=col, sticky="nsew", padx=10, pady=6, ipadx=6)


def _offline(app):
    app.mode = "offline"
    app.room = None
    app.show("preparation")


def _create(app):
    app.mode = "create"
    app.show("room", action="create")


def _join(app, frame):
    # inline host-address prompt (keeps the touch theme)
    for w_ in frame.winfo_children():
        w_.destroy()
    w.title(frame, "Join a room").pack(anchor="w")
    w.subtitle(frame, "Type the host Pi's address shown on its screen.").pack(anchor="w", pady=(6, 20))

    card = w.card(frame)
    card.pack(fill="x")
    inner = tk.Frame(card, bg=theme.SURFACE)
    inner.pack(fill="x", padx=22, pady=22)
    tk.Label(inner, text="Host address (IP)", bg=theme.SURFACE, fg=theme.MUTED, font=theme.SMALL).pack(anchor="w")
    entry = tk.Entry(inner, font=theme.font(20), bg=theme.SURFACE2, fg=theme.TEXT,
                     insertbackground=theme.TEXT, relief="flat")
    entry.pack(fill="x", ipady=12, pady=(6, 18))
    entry.focus_set()

    def go(*_):
        host = entry.get().strip()
        if not host:
            entry.focus_set()
            return
        app.mode = "join"
        app.show("room", action="join", host=host)

    row = tk.Frame(inner, bg=theme.SURFACE)
    row.pack(fill="x")
    w.primary_button(row, "Join", go).pack(side="left")
    w.ghost_button(row, "Back", lambda: app.show("mode_select")).pack(side="left", padx=(12, 0))
    entry.bind("<Return>", go)
