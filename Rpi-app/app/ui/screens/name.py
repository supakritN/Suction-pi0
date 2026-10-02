"""1. Name entry — built-in touchscreen keyboard."""
import tkinter as tk

from .. import theme
from .. import widgets as w

_ROWS = ["QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"]
_NUM_ROW = "1234567890"


def render(app, parent, **kw):
    frame = tk.Frame(parent, bg=theme.BG)
    frame.pack(fill="both", expand=True, padx=32, pady=12)

    w.title(frame, "Enter your name").pack(anchor="w")

    card = w.card(frame)
    card.pack(fill="x")
    inner = tk.Frame(card, bg=theme.SURFACE)
    inner.pack(fill="x", padx=22, pady=(12, 10))

    tk.Label(inner, text="Name", bg=theme.SURFACE, fg=theme.MUTED,
             font=theme.SMALL).pack(anchor="w")
    entry = tk.Entry(inner, font=theme.font(22), bg=theme.SURFACE2, fg=theme.TEXT,
                     insertbackground=theme.TEXT, relief="flat")
    entry.pack(fill="x", ipady=10, pady=(4, 0))
    entry.focus_set()

    def submit(*_):
        value = entry.get().strip()
        if not value:
            return
        app.username = value
        app.show("mode_select")

    # ── keyboard state ──────────────────────────────────────
    _num_mode = [False]

    kb = tk.Frame(frame, bg=theme.BG)
    kb.pack(fill="x", pady=(8, 0))

    def _make_key(parent, text, w_=3, accent=False):
        bg  = theme.ACCENT   if accent else theme.SURFACE
        fg  = theme.ACCENT_INK if accent else theme.TEXT
        abg = theme.ACCENT   if accent else theme.SURFACE2
        return tk.Button(
            parent, text=text, width=w_,
            font=theme.font(14, "bold"),
            bg=bg, fg=fg,
            activebackground=abg, activeforeground=fg,
            relief="flat", bd=0, cursor="hand2",
        )

    def _press(ch):
        if ch == "⌫":
            cur = entry.get()
            if cur:
                entry.delete(len(cur) - 1, tk.END)
        elif ch == "OK":
            submit()
        else:
            entry.insert(tk.END, ch)

    def _rebuild():
        for child in kb.winfo_children():
            child.destroy()

        rows = [_NUM_ROW] if _num_mode[0] else _ROWS
        for row_str in rows:
            row = tk.Frame(kb, bg=theme.BG)
            row.pack(pady=2)
            for ch in row_str:
                btn = _make_key(row, ch)
                btn.config(command=lambda c=ch: _press(c))
                btn.pack(side="left", padx=2, ipady=6)

        bot = tk.Frame(kb, bg=theme.BG)
        bot.pack(pady=2)

        toggle_lbl = "ABC" if _num_mode[0] else "123"
        tog = _make_key(bot, toggle_lbl, w_=4)
        tog.config(command=lambda: (_num_mode.__setitem__(0, not _num_mode[0]), _rebuild()))
        tog.pack(side="left", padx=2, ipady=6)

        sp = _make_key(bot, "Space", w_=14)
        sp.config(command=lambda: _press(" "))
        sp.pack(side="left", padx=2, ipady=6)

        bs = _make_key(bot, "⌫", w_=4)
        bs.config(command=lambda: _press("⌫"))
        bs.pack(side="left", padx=2, ipady=6)

        ok = _make_key(bot, "OK", w_=6, accent=True)
        ok.config(command=submit)
        ok.pack(side="left", padx=2, ipady=6)

    _rebuild()
    entry.bind("<Return>", submit)
