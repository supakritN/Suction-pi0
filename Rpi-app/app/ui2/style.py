"""v2 look: clean medical white with a futuristic HUD touch — white panels,
navy ink, medical teal/cyan accents, outline mannequin, monospace readouts.

Flat colours and static lines only (no alpha / glow effects): Tk on a
Raspberry Pi 3 has neither, and redraws must stay cheap. Sized for the Pi's
HDMI at 2.25× scale (≈ 853×480 usable). DejaVu fonts only.

Other screens: app.py calls set_scale() from the detected display profile
(app/display.py); f() and px() then scale fonts and fixed pixel sizes.
"""
import tkinter as tk

BG      = "#f7fafc"   # clinical white
GRID    = "#e8eff5"
PANEL   = "#ffffff"
PANEL_HI = "#e6f6fa"  # pressed / hover
LINE    = "#d5e0ea"
INK     = "#0f1f33"   # navy text
MUTED   = "#5d7189"
FAINT   = "#a9b8c8"
ACCENT  = "#0891b2"   # medical teal-cyan
ACCENT2 = "#d97706"   # amber
OK      = "#059669"   # green
BAD     = "#e11d48"   # warning red
ON_ACCENT = "#ffffff" # text on teal buttons

# mannequin
SKIN      = "#eef6fa"  # body fill
BODY_LINE = "#0ea5e9"
AIRWAY    = "#cdeef3"
AIRWAY_LINE = "#14b8a6"
TUBE      = "#f59e0b"  # catheter
GUIDE     = "#9fdcea"
PILLOW    = "#e3ebf2"
TRACH_OUT = "#5d7189"
TRACH_IN  = "#ffffff"

SANS = "DejaVu Sans"
MONO = "DejaVu Sans Mono"

SCALE = 1.0   # set once at start-up from the display profile


def set_scale(scale):
    global SCALE
    SCALE = float(scale)


def px(n):
    """Scale a fixed pixel size (widths, wrap lengths, paddings)."""
    return max(1, int(round(n * SCALE))) if n else 0


def f(size, weight="normal", mono=False):
    return (MONO if mono else SANS, max(6, int(round(size * SCALE))), weight)


def label(parent, text="", size=12, weight="normal", fg=INK, bg=BG, mono=False, **kw):
    return tk.Label(parent, text=text, bg=bg, fg=fg, font=f(size, weight, mono), **kw)


def tag(parent, text, bg=BG, fg=MUTED):
    """Small monospace caps label, e.g. 'LARICE / PRESS-04'."""
    return tk.Label(parent, text=text.upper(), bg=bg, fg=fg, font=f(9, "normal", True))


def button(parent, text, command, kind="primary", size=15, padx=22, pady=10):
    colors = {
        "primary":   (ACCENT, ON_ACCENT, "#0e7490"),
        "secondary": (PANEL, INK, PANEL_HI),
        "ghost":     (BG, MUTED, BG),
        "danger":    (BAD, "#ffffff", "#be123c"),
    }[kind]
    bg, fg, active = colors
    return tk.Button(parent, text=text, command=command, bg=bg, fg=fg,
                     activebackground=active, activeforeground=fg, font=f(size, "bold"),
                     relief="flat", bd=0, padx=px(padx), pady=px(pady), cursor="hand2",
                     highlightthickness=1 if kind == "secondary" else 0,
                     highlightbackground=LINE)


def draw_grid(canvas, w, h, step=40, tag_="grid"):
    canvas.delete(tag_)
    step = px(step)
    for x in range(0, w, step):
        canvas.create_line(x, 0, x, h, fill=GRID, tags=tag_)
    for y in range(0, h, step):
        canvas.create_line(0, y, w, y, fill=GRID, tags=tag_)
    canvas.tag_lower(tag_)


def draw_brackets(canvas, w, h, inset=6, length=18, color=ACCENT, tag_="hud"):
    """HUD corner brackets around a canvas."""
    canvas.delete(tag_)
    i, L = px(inset), px(length)
    for (x, y, dx, dy) in ((i, i, 1, 1), (w - i, i, -1, 1), (i, h - i, 1, -1), (w - i, h - i, -1, -1)):
        canvas.create_line(x, y, x + dx * L, y, fill=color, width=2, tags=tag_)
        canvas.create_line(x, y, x, y + dy * L, fill=color, width=2, tags=tag_)
