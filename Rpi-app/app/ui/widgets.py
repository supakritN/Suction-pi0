"""Reusable styled Tk widgets (flat, large, touch-friendly)."""
from __future__ import annotations

import tkinter as tk

from . import theme


def title(parent, text):
    return tk.Label(parent, text=text, bg=theme.BG, fg=theme.TEXT, font=theme.H1)


def heading(parent, text):
    return tk.Label(parent, text=text, bg=theme.SURFACE, fg=theme.TEXT, font=theme.H2)


def subtitle(parent, text):
    return tk.Label(parent, text=text, bg=theme.BG, fg=theme.MUTED, font=theme.BODY,
                    wraplength=820, justify="left")


def card(parent):
    return tk.Frame(parent, bg=theme.SURFACE, highlightbackground=theme.BORDER,
                    highlightthickness=1, bd=0)


def _btn(parent, text, command, bg, fg, font=theme.BTN, pady=16):
    return tk.Button(parent, text=text, command=command, bg=bg, fg=fg,
                     activebackground=bg, activeforeground=fg, font=font,
                     relief="flat", bd=0, padx=26, pady=pady, cursor="hand2",
                     highlightthickness=0)


def primary_button(parent, text, command):
    return _btn(parent, text, command, theme.ACCENT, theme.ACCENT_INK)


def button(parent, text, command):
    return _btn(parent, text, command, theme.SURFACE2, theme.TEXT)


def ghost_button(parent, text, command):
    return _btn(parent, text, command, theme.BG, theme.MUTED, font=theme.BODY, pady=12)
