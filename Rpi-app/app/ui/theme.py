"""Colors and fonts — a flat, touch-friendly clinical theme."""

BG = "#0f1720"
SURFACE = "#182430"
SURFACE2 = "#21313f"
BORDER = "#2c3e4f"
TEXT = "#eaf2f8"
MUTED = "#9fb3c4"
ACCENT = "#2dd4bf"
ACCENT_INK = "#052e2b"
OK = "#34d399"
BAD = "#f87171"
WARN = "#fbbf24"

FAMILY = "DejaVu Sans"       # present on Raspberry Pi OS


def font(size, weight="normal"):
    return (FAMILY, size, weight)


H1 = font(30, "bold")
H2 = font(22, "bold")
BODY = font(16)
SMALL = font(13)
BTN = font(18, "bold")
BIG = font(52, "bold")
