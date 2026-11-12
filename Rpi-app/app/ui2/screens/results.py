"""Results — big score, what was measured, practice again."""
import os
import tkinter as tk

from .. import style as S


def render(app, parent, **kw):
    score, m = app.last_score, app.last_metrics
    frame = tk.Frame(parent, bg=S.BG)
    frame.pack(fill="both", expand=True, padx=26, pady=(12, 10))
    if not score:
        S.label(frame, "No result yet.", 16).pack(anchor="w")
        S.button(frame, "Back", lambda: app.show("name")).pack(anchor="w", pady=10)
        return

    btns = tk.Frame(frame, bg=S.BG)
    btns.pack(side="bottom", fill="x", pady=(8, 0))
    S.button(btns, "Practice again", lambda: app.show("practice")).pack(side="left")
    S.button(btns, "Main menu", lambda: app.show("name"), kind="secondary").pack(
        side="left", padx=(10, 0))
    if app.last_csv:
        S.tag(btns, f"saved · {os.path.basename(str(app.last_csv))}").pack(side="right")

    S.tag(frame, f"Result · {app.username or ''}").pack(anchor="w")
    body = tk.Frame(frame, bg=S.BG)
    body.pack(fill="both", expand=True, pady=(4, 0))

    left = tk.Frame(body, bg=S.BG)
    left.pack(side="left", fill="y", padx=(0, 26))
    big = tk.Frame(left, bg=S.BG)
    big.pack(anchor="w")
    S.label(big, f"{int(round(score.raw_score))}", 72, "bold", fg=S.ACCENT, mono=True).pack(side="left")
    S.label(big, f"/{int(round(score.available_score))}", 22, "bold", fg=S.MUTED, mono=True).pack(
        side="left", anchor="s", pady=(0, 14))
    S.label(left, score.level, 18, "bold").pack(anchor="w")
    S.label(left, score.note, 11, fg=S.MUTED, wraplength=S.px(280), justify="left").pack(anchor="w")

    tk.Frame(body, bg=S.LINE, width=1).pack(side="left", fill="y", padx=(0, 22))
    right = tk.Frame(body, bg=S.BG)
    right.pack(side="left", fill="both", expand=True)

    def row(label, value, sub="", fg=S.INK):
        r = tk.Frame(right, bg=S.BG)
        r.pack(fill="x", pady=3)
        S.label(r, label, 13, fg=S.MUTED).pack(side="left")
        S.label(r, value, 14, "bold", fg=fg, mono=True).pack(side="right")
        if sub:
            S.tag(r, sub).pack(side="right", padx=8)

    row("Max depth", f"{m.max_depth_cm} cm", "too deep" if m.max_depth_cm >= 11 else "",
        fg=S.BAD if m.max_depth_cm >= 11 else S.INK)
    row("Total time", f"{m.total_time_ms / 1000:.1f} s")
    row("Passes", f"{m.contact_band_count}")
    tk.Frame(right, bg=S.LINE, height=1).pack(fill="x", pady=6)
    for c in score.categories:
        pts = f"{round(c.points)}/{round(c.max_points)}" if c.available else "—"
        row(c.key.capitalize(), pts, c.label)
