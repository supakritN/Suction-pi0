"""Name entry — the only step before practice (offline, factory calibration)."""
import tkinter as tk

from .. import style as S
from ...serial_node import calibration_summary

_ROWS = ["QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"]
_NUMS = "1234567890"


def render(app, parent, **kw):
    frame = tk.Frame(parent, bg=S.BG)
    frame.pack(fill="both", expand=True, padx=26, pady=(10, 8))

    top = tk.Frame(frame, bg=S.BG)
    top.pack(fill="x")
    S.label(top, "SUCTION TRAINING", 22, "bold", fg=S.ACCENT, mono=True).pack(side="left")
    S.tag(top, f"Offline · {calibration_summary()}").pack(side="right", anchor="s", pady=(0, 6))

    entry_row = tk.Frame(frame, bg=S.BG)
    entry_row.pack(fill="x", pady=(8, 8))
    entry = tk.Entry(entry_row, font=S.f(20), bg=S.PANEL, fg=S.INK, relief="flat",
                     insertbackground=S.INK, highlightthickness=1,
                     highlightbackground=S.LINE, highlightcolor=S.ACCENT)
    entry.pack(side="left", fill="x", expand=True, ipady=8)
    if app.username:
        entry.insert(0, app.username)
    entry.focus_set()

    def start(*_):
        value = entry.get().strip()
        if not value:
            entry.focus_set()
            entry.config(highlightbackground=S.BAD)
            return
        app.username = value
        app.show("practice")

    S.button(entry_row, "Start  →", start).pack(side="left", padx=(10, 0), ipady=2)
    entry.bind("<Return>", start)

    kb = tk.Frame(frame, bg=S.BG)
    kb.pack(fill="both", expand=True)
    nums = [False]

    def press(ch):
        if ch == "⌫":
            entry.delete(max(0, len(entry.get()) - 1), tk.END)
        else:
            entry.insert(tk.END, ch)

    def key(parent, text, cmd, width=1, accent=False):
        b = tk.Button(parent, text=text, command=cmd, font=S.f(14, "bold", True),
                      bg=S.ACCENT if accent else S.PANEL, fg=S.ON_ACCENT if accent else S.INK,
                      activebackground=S.PANEL_HI, activeforeground=S.ACCENT, relief="flat", bd=0,
                      highlightthickness=1, highlightbackground=S.LINE, cursor="hand2")
        return b

    def build():
        for w in kb.winfo_children():
            w.destroy()
        rows = [_NUMS] if nums[0] else _ROWS
        for r, chars in enumerate(rows):
            row = tk.Frame(kb, bg=S.BG)
            row.pack(fill="both", expand=True, pady=2)
            pad = (10 - len(chars)) * 0.5
            if pad:
                tk.Frame(row, bg=S.BG).pack(side="left", fill="x", expand=True, ipadx=pad * 26)
            for ch in chars:
                key(row, ch, lambda c=ch: press(c)).pack(side="left", fill="both",
                                                         expand=True, padx=2)
            if pad:
                tk.Frame(row, bg=S.BG).pack(side="left", fill="x", expand=True, ipadx=pad * 26)
        row = tk.Frame(kb, bg=S.BG)
        row.pack(fill="both", expand=True, pady=2)
        key(row, "ABC" if nums[0] else "123",
            lambda: (nums.__setitem__(0, not nums[0]), build())).pack(
            side="left", fill="both", expand=True, padx=2)
        key(row, "space", lambda: press(" ")).pack(side="left", fill="both", expand=True,
                                                    padx=2, ipadx=120)
        key(row, "⌫", lambda: press("⌫")).pack(side="left", fill="both", expand=True, padx=2)

    build()
