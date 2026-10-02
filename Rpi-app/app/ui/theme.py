"""Colors and fonts — clean clinical / medical palette.

Light background, teal medical accent, deep-green OK, clinical red for fault.
Designed to feel like a hospital-grade device UI, not a dark gaming app.
"""

# Backgrounds
BG       = "#f4f6f8"   # page background — cool clinical off-white
SURFACE  = "#ffffff"   # cards
SURFACE2 = "#eef3f6"   # input fields, subdued panels
BORDER   = "#d9e0e6"   # 1px dividers

# Text
TEXT     = "#172026"   # near-black for body text
MUTED    = "#64717d"   # secondary labels

# Brand accent — medical teal
ACCENT     = "#0d9488"   # buttons, highlights, active lines
ACCENT_INK = "#ffffff"   # text on accent

# Semantic status
OK   = "#15803d"   # medical green (ready / passed)
BAD  = "#b91c1c"   # medical red (fault / critical)
WARN = "#b45309"   # amber (caution)


FAMILY = "DejaVu Sans"       # present on Raspberry Pi OS


def font(size, weight="normal"):
    return (FAMILY, size, weight)


H1    = font(30, "bold")
H2    = font(22, "bold")
BODY  = font(16)
SMALL = font(13)
BTN   = font(18, "bold")
BIG   = font(52, "bold")
