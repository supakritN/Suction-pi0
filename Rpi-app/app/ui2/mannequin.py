"""Supine mannequin (tracheostomy route), side view, on a Tk canvas.

The patient lies on a bed, head on a pillow (left), face up; the catheter comes
down from above into the trach tube and runs along the trachea toward the chest,
past the Entry / 9 cm / 11 cm sensors. The oral route is sketched faintly
(not installed yet).

Pi 3 performance — measured on the device: on its X server *filled shapes are
fast, lines are very slow* (~1.4 ms per line segment; the smoothed body outline
alone cost 377–737 ms per full redraw, a filled body 14 ms). So everything here
is a filled polygon: outlines are an offset copy behind the fill, thick lines
are polygon strips, grid / ticks are 1-px rectangles. Curves are smoothed once
in Python, animations step at 10 Hz, and only the catheter, the guide and the
sensor dots change per frame.
"""
from __future__ import annotations

import math
import tkinter as tk

from . import style as S

VIEW = (28, 50, 500, 416)          # design-space crop shown on the canvas (zoomed on the airway)


def _chaikin(pts, closed=False, rounds=3):
    """Pre-smooth a polyline once. Doubled points stay (almost) sharp corners."""
    for _ in range(rounds):
        out = [] if closed else [pts[0]]
        n = len(pts)
        for i in (range(n) if closed else range(n - 1)):
            (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
            out.append((0.75 * x0 + 0.25 * x1, 0.75 * y0 + 0.25 * y1))
            out.append((0.25 * x0 + 0.75 * x1, 0.25 * y0 + 0.75 * y1))
        if not closed:
            out.append(pts[-1])
        pts = out
    return pts


def _rot(pts):
    """Upright profile (facing right) → lying on the back, face up."""
    return [(y + 6, 500 - x) for x, y in pts]


_HEAD_UP = [(150, 330), (138, 262), (118, 214), (104, 160), (112, 108), (146, 64), (196, 40),
            (252, 36), (302, 52), (332, 86), (338, 114), (334, 128), (362, 156), (340, 166),
            (344, 180), (337, 188), (343, 196), (335, 220), (306, 233), (284, 244), (286, 300),
            (300, 326)]
# half-body mannequin, flat cut at the chest (doubled points = sharp corners)
BODY = _rot(_HEAD_UP) + [(368, 150), (410, 126), (460, 118), (504, 116), (504, 116),
                         (504, 404), (504, 404), (350, 404), (350, 404)]
BODY_S = _chaikin(BODY, closed=True)
TRACHEA_S = _chaikin(_rot([(268, 236), (264, 270), (262, 320), (262, 382), (262, 470)]))
ORAL_S = _chaikin(_rot([(337, 188), (300, 190), (272, 204), (268, 236)]))
TRACH_TUBE_S = _chaikin(_rot([(320, 257), (296, 264), (276, 273), (266, 287), (263, 302)]))
FLANGE = _rot([(318, 244), (322, 272)])
# catheter path: (cm from the trach-tube opening, x, y) — comes down from above
PATH = [(c, *_rot([(x, y)])[0]) for c, x, y in
        [(-9, 486, 250), (-5, 404, 254), (0, 320, 257), (2, 296, 264), (4, 276, 273),
         (5.5, 266, 287), (7, 263, 303), (9, 262, 322), (11, 262, 346), (12.5, 262, 362)]]
SENSORS = {"entry": 0.0, "9cm": 9.0, "11cm": 11.0}
TIP_CM = {0: -3.0, 1: 2.0, 2: 9.0, 3: 11.0}       # detector level → catheter tip
GUIDE_FROM, GUIDE_TO, GUIDE_STEP = -8.0, 4.0, 0.7   # guide loop (cm per 10 Hz step)


def _point_at(cm: float) -> tuple[float, float]:
    if cm <= PATH[0][0]:
        return PATH[0][1:]
    for (c0, x0, y0), (c1, x1, y1) in zip(PATH, PATH[1:]):
        if cm <= c1:
            t = (cm - c0) / (c1 - c0)
            return x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
    return PATH[-1][1:]


def _path_between(a: float, b: float) -> list[tuple[float, float]]:
    return [_point_at(a)] + [(x, y) for c, x, y in PATH if a < c < b] + [_point_at(b)]


def _strip(pts, width):
    """Polyline → filled polygon of the given width (canvas coords, flat list)."""
    if len(pts) < 2:
        return []
    h = width / 2.0
    left, right = [], []
    n = len(pts)
    for i, (x, y) in enumerate(pts):
        x0, y0 = pts[max(i - 1, 0)]
        x1, y1 = pts[min(i + 1, n - 1)]
        dx, dy = x1 - x0, y1 - y0
        d = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / d * h, dx / d * h
        left.append((x + nx, y + ny))
        right.append((x - nx, y - ny))
    out = []
    for x, y in left + right[::-1]:
        out.extend((x, y))
    return out


class Mannequin:
    def __init__(self, parent, bg=S.BG):
        self.canvas = tk.Canvas(parent, bg=bg, highlightthickness=0, bd=0)
        self._size = (0, 0)
        self._s, self._ox, self._oy = 1.0, 0.0, 0.0
        self.cm = TIP_CM[0]
        self.target = TIP_CM[0]
        self.level = 0
        self.guide_cm = GUIDE_FROM
        self._guide_on = None
        self._blink = 0
        self._frame = 0         # animations step every other tick (10 Hz)
        self._warn = False      # 11 cm reached → blinking "too deep" banner
        self.states = {"entry": False, "9cm": False, "11cm": False}
        self._items = {}
        self.canvas.bind("<Configure>", self._on_resize)

    # ── geometry ──
    def _xy(self, x, y):
        return self._ox + x * self._s, self._oy + y * self._s

    def _pts(self, pts):
        return [self._xy(x, y) for x, y in pts]

    def _flat(self, pts):
        return [v for p in self._pts(pts) for v in p]

    def _on_resize(self, e):
        if (e.width, e.height) == self._size or e.width < 50:
            return
        self._size = (e.width, e.height)
        x0, y0, x1, y1 = VIEW
        vw, vh = x1 - x0, y1 - y0
        self._s = min(e.width / vw, e.height / vh)
        self._ox = (e.width - vw * self._s) / 2 - x0 * self._s
        self._oy = (e.height - vh * self._s) / 2 - y0 * self._s
        self._draw()

    def _rect(self, x0, y0, x1, y1, fill):
        return self.canvas.create_rectangle(x0, y0, x1, y1, fill=fill, outline="")

    def _ring(self, x, y, r, ring, inner):
        return (self.canvas.create_oval(x - r, y - r, x + r, y + r, fill=ring, outline=""),
                self.canvas.create_oval(x - r + 2, y - r + 2, x + r - 2, y + r - 2,
                                        fill=inner, outline=""))

    # ── static drawing ──
    def _draw(self):
        c = self.canvas
        c.delete("all")
        self._items = {}
        w, h = self._size
        s = self._s
        # sparse 1-px grid as rectangles (lines are slow on the Pi)
        for x in range(0, w, 40):
            self._rect(x, 0, x + 1, h, S.GRID)
        for y in range(0, h, 40):
            self._rect(0, y, w, y + 1, S.GRID)
        # HUD corner brackets
        L, t, i = 18, 2, 6
        for (x, y, dx, dy) in ((i, i, 1, 1), (w - i, i, -1, 1), (i, h - i, 1, -1), (w - i, h - i, -1, -1)):
            self._rect(min(x, x + dx * L), min(y, y + dy * t), max(x, x + dx * L), max(y, y + dy * t), S.ACCENT)
            self._rect(min(x, x + dx * t), min(y, y + dy * L), max(x, x + dx * t), max(y, y + dy * L), S.ACCENT)
        # bed + pillow
        bx0, by0 = self._xy(VIEW[0] - 40, 404)
        bx1, by1 = self._xy(VIEW[2] + 40, 410)
        self._rect(bx0, by0, bx1, by1, S.LINE)
        c.create_oval(*self._xy(30, 382), *self._xy(230, 410), fill=S.PILLOW, outline="")
        # body: edge colour = offset copies behind the fill (no outline strokes)
        body = self._flat(BODY_S)
        e = max(1.5, 1.6 * s)
        for dx, dy in ((-e, 0), (e, 0), (0, -e), (0, e)):
            c.create_polygon([v + (dx if k % 2 == 0 else dy) for k, v in enumerate(body)],
                             fill=S.BODY_LINE, outline="")
        c.create_polygon(body, fill=S.SKIN, outline="")
        # airways
        c.create_polygon(_strip(self._pts(TRACHEA_S), 16 * s), fill=S.AIRWAY, outline="")
        c.create_polygon(_strip(self._pts(TRACHEA_S), max(1.2, 1.2 * s)), fill=S.AIRWAY_LINE, outline="")
        c.create_polygon(_strip(self._pts(ORAL_S), max(1.2, 1.2 * s)), fill=S.FAINT, outline="")
        x, y = self._xy(150, 126)
        c.create_text(x, y, text="ORAL · NOT INSTALLED", fill=S.FAINT, font=S.f(8, mono=True), anchor="s")
        # cm ruler along the trachea
        for cm in range(6, 13):
            px, py = self._xy(*_point_at(cm))
            big = cm in (9, 11)
            col = S.BAD if cm == 11 else S.ACCENT if big else S.FAINT     # 11 cm = danger depth
            self._rect(px, py + 12 * s, px + (2 if cm == 11 else 1), py + (21 if big else 16) * s, col)
        # trach tube + flange
        c.create_polygon(_strip(self._pts(TRACH_TUBE_S), 11 * s), fill=S.TRACH_OUT, outline="")
        c.create_polygon(_strip(self._pts(TRACH_TUBE_S), 6 * s), fill=S.TRACH_IN, outline="")
        c.create_polygon(_strip(self._pts(FLANGE), 4 * s), fill=S.TRACH_OUT, outline="")
        # guide (ghost catheter) + cue
        self._items["guide"] = c.create_polygon(0, 0, 0, 0, 0, 0, fill=S.GUIDE, outline="")
        gx, gy = self._xy(*_point_at(-6.2))
        self._items["cue"] = c.create_text(gx + 14 * s, gy, text="INSERT HERE ↓", fill=S.ACCENT,
                                           font=S.f(11, "bold", True), anchor="w")
        # sensors + labels
        r = max(6, 8 * s)
        lab = {"entry": ((298, 158), "w", "ENTRY"),
               "9cm": ((314, 296), "ne", "9 CM"),
               "11cm": ((356, 296), "nw", "11 CM")}
        for key, cm in SENSORS.items():
            px, py = self._xy(*_point_at(cm))
            (lx, ly), anchor, text = lab[key]
            lx, ly = self._xy(lx, ly)
            danger = key == "11cm"
            c.create_polygon(_strip([(px, py), (lx, ly)], 1.2), fill=S.BAD if danger else S.FAINT,
                             outline="")
            c.create_text(lx, ly, text=text, fill=S.BAD if danger else S.MUTED,
                          font=S.f(10, "bold", True), anchor=anchor)
            self._items[key] = self._ring(px, py, r, S.MUTED, S.BG)
        x, y = self._xy(VIEW[0], VIEW[1])
        c.create_text(x + 16, y + 10, text="ROUTE · TRACHEOSTOMY · SUPINE", fill=S.ACCENT,
                      font=S.f(9, mono=True), anchor="nw")
        # "too deep" banner (hidden unless the tube reaches 11 cm)
        bx, by = self._xy(400, 84)
        self._items["warn_bg"] = c.create_rectangle(bx - 120 * s, by - 18 * s, bx + 120 * s,
                                                    by + 18 * s, fill=S.BAD, outline="", state="hidden")
        self._items["warn_txt"] = c.create_text(bx, by, text="⚠  TOO DEEP · 11 CM", fill=S.BG,
                                                font=S.f(14, "bold"), state="hidden")
        # real catheter (on top)
        self._items["tube"] = c.create_polygon(0, 0, 0, 0, 0, 0, fill=S.TUBE, outline="")
        self._items["tip"] = c.create_oval(0, 0, 0, 0, fill=S.TUBE, outline="")
        self._guide_on = None
        self._redraw_tube()
        self._show_guide(self.level == 0)
        self._paint_warn(self._warn)
        for key, on in self.states.items():
            self._paint_sensor(key, on)

    def _redraw_tube(self):
        if "tube" not in self._items:
            return
        s = self._s
        self.canvas.coords(self._items["tube"],
                           *_strip(self._pts(_path_between(PATH[0][0], self.cm)), max(3, 4.5 * s)))
        tx, ty = self._xy(*_point_at(self.cm))
        r = max(3, 5 * s)
        self.canvas.coords(self._items["tip"], tx - r, ty - r, tx + r, ty + r)

    def _paint_sensor(self, key, on, color=None):
        items = self._items.get(key)
        if items:
            ring, inner = items
            col = color or (S.ACCENT if on else None)
            self.canvas.itemconfig(ring, fill=col or S.MUTED)
            self.canvas.itemconfig(inner, fill=col or S.BG)

    def _show_guide(self, on):
        if on == self._guide_on or "guide" not in self._items:
            return
        self._guide_on = on
        st = "normal" if on else "hidden"
        self.canvas.itemconfig(self._items["guide"], state=st)
        self.canvas.itemconfig(self._items["cue"], state=st)

    def _paint_warn(self, visible):
        st = "normal" if visible else "hidden"
        for k in ("warn_bg", "warn_txt"):
            if k in self._items:
                self.canvas.itemconfig(self._items[k], state=st)

    # ── live updates ──
    def set_state(self, level: int, entry: bool, d9: bool, d11: bool) -> None:
        self.level = level
        self.target = TIP_CM.get(level, TIP_CM[0])
        self._show_guide(level == 0)
        warn = level >= 3
        if warn != self._warn:
            self._warn = warn
            self._paint_warn(warn)
            if not warn:
                self._paint_sensor("11cm", self.states["11cm"])
        for key, on in (("entry", entry), ("9cm", d9), ("11cm", d11)):
            if self.states[key] != on:
                self.states[key] = on
                self._paint_sensor(key, on)

    def tick(self) -> None:
        """Advance animations; call from the screen's poll (~20 Hz)."""
        self._frame ^= 1
        if self._frame and self._guide_on and "guide" in self._items:
            self.guide_cm += GUIDE_STEP
            if self.guide_cm > GUIDE_TO:
                self.guide_cm = GUIDE_FROM
            tail = max(GUIDE_FROM, self.guide_cm - 5)
            self.canvas.coords(self._items["guide"],
                               *_strip(self._pts(_path_between(tail, self.guide_cm)), max(3, 4 * self._s)))
            self._blink = (self._blink + 1) % 10
            if self._blink in (0, 5):
                self.canvas.itemconfig(self._items["cue"],
                                       fill=S.ACCENT if self._blink == 0 else S.FAINT)
        if self._frame and self._warn and "warn_bg" in self._items:
            self._blink = (self._blink + 1) % 6           # ~0.3 s on / 0.3 s off
            if self._blink in (0, 3):
                on = self._blink == 0
                self._paint_warn(on)
                self._paint_sensor("11cm", True, S.BAD if on else S.MUTED)
        d = self.target - self.cm
        if abs(d) < 0.05:
            if d:
                self.cm = self.target
                self._redraw_tube()
            return
        self.cm += d * 0.35
        self._redraw_tube()
