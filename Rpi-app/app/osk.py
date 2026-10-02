"""
osk.py -- Touch on-screen keyboard for fullscreen Tkinter kiosks.

Why this exists
---------------
A Tkinter app running fullscreen on a Raspberry Pi has no keyboard: the desktop
OSK (squeekboard / matchbox-keyboard / onboard) is not told that an X11 Entry
wants text, and even when it is launched by hand the fullscreen window sits on
top of it. This module draws the keyboard *inside* the app window instead, so it
behaves identically on Wayland, on X11 and over VNC.

Usage -- two lines
------------------
    from app.ui import osk          # or: import osk

    root = tk.Tk()
    ...build your UI...
    osk.install(root)               # <- that's it
    root.mainloop()

Every tk/ttk Entry, Spinbox and Text in the app now raises the keyboard on
focus. Nothing else in your code has to change.

Options
-------
    osk.install(root, thai=False)          # English only, drops the ก/EN key
    osk.install(root, height_ratio=0.38)   # keyboard height as a share of window
    osk.install(root, theme=osk.LIGHT)     # LIGHT or DARK (default)

    osk.numeric(weight_entry)              # this field gets a number pad
    osk.ignore(readonly_entry)             # never raise the keyboard here

    kb = osk.install(root)
    kb.hide()                              # hide programmatically

Design notes
------------
* The keyboard is a Frame `place()`d over the window, not a Toplevel, so there
  is no window-manager z-order or focus-stealing to fight with.
* Keys never take focus; characters are inserted straight into the remembered
  target widget, so the caret stays where the user put it.
* If the focused field would sit under the keyboard, the keyboard moves to the
  top of the window instead of the bottom.
* Dialogs work too: the keyboard rebuilds itself inside whichever Toplevel owns
  the focused widget.

Python 3.7+, stdlib only.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

__all__ = ["install", "numeric", "ignore", "OnScreenKeyboard", "DARK", "LIGHT"]


# --------------------------------------------------------------------------
# themes
# --------------------------------------------------------------------------

DARK = {
    "bar": "#12161c",
    "key": "#262d38",
    "key_active": "#3a4557",
    "key_fg": "#f2f5f9",
    "mod": "#1b222c",
    "accent": "#2f81f7",
    "accent_fg": "#ffffff",
    "border": "#000000",
    "hint": "#8b95a5",
}

LIGHT = {
    "bar": "#e9edf2",
    "key": "#ffffff",
    "key_active": "#d3dae4",
    "key_fg": "#16202b",
    "mod": "#cdd5e0",
    "accent": "#2f81f7",
    "accent_fg": "#ffffff",
    "border": "#b8c2d0",
    "hint": "#5d6a7a",
}


# --------------------------------------------------------------------------
# layouts.  "<name>" entries are special keys; everything else is literal text.
# Each row item is either "char" or ("lower", "upper") or "<special>".
# The trailing float is an optional width weight (default 1.0).
# --------------------------------------------------------------------------

EN_ROWS = [
    ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"],
    ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p"],
    ["a", "s", "d", "f", "g", "h", "j", "k", "l", "<bs>"],
    ["<shift>", "z", "x", "c", "v", "b", "n", "m", "-", "<enter>"],
    ["<sym>", "<lang>", "<space>", "@", ".", "<tab>"],
]

EN_SHIFT_MAP = {
    "1": "!", "2": "@", "3": "#", "4": "$", "5": "%",
    "6": "^", "7": "&", "8": "*", "9": "(", "0": ")",
    "-": "_", ".": ",", "@": "'",
}

SYM_ROWS = [
    ["!", "@", "#", "$", "%", "^", "&", "*", "(", ")"],
    ["-", "_", "=", "+", "[", "]", "{", "}", "\\", "|"],
    [";", ":", "'", '"', ",", ".", "/", "?", "<", "<bs>"],
    ["`", "~", "<", ">", "°", "µ", "±", "€", "฿", "<enter>"],
    ["<abc>", "<lang>", "<space>", "-", ".", "<tab>"],
]

# Thai Kedmanee, trimmed to what fits a 10-key row.
TH_ROWS = [
    ["ๆ", "ไ", "ํ", "พ", "ะ", "ั", "ี", "ร", "น", "ย"],
    ["ฟ", "ห", "ก", "ด", "เ", "้", "่", "า", "ส", "ว"],
    ["ผ", "ป", "แ", "อ", "ิ", "ื", "ท", "ม", "ใ", "<bs>"],
    ["<shift>", "บ", "ล", "ง", "ข", "ช", "ค", "ต", "จ", "<enter>"],
    ["<sym>", "<lang>", "<space>", "ฯ", ".", "<tab>"],
]

TH_SHIFT_ROWS = [
    ["๑", "๒", "๓", "๔", "๕", "ู", "฿", "๖", "๗", "๘"],
    ["ฤ", "ฏ", "ฎ", "โ", "ฌ", "็", "๋", "ษ", "ศ", "ซ"],
    ["ณ", "ฯ", "ญ", "ฐ", "ึ", "์", "ธ", "ั", "ฏ", "<bs>"],
    ["<shift>", "ฺ", "ฒ", "ฬ", "ถ", "ฑ", "ฅ", "ฉ", "ฮ", "<enter>"],
    ["<sym>", "<lang>", "<space>", "ฯ", ".", "<tab>"],
]

NUM_ROWS = [
    ["7", "8", "9"],
    ["4", "5", "6"],
    ["1", "2", "3"],
    ["0", ".", "<bs>"],
    ["<clear>", "<enter>"],
]

SPECIAL_LABEL = {
    "<bs>": "⌫",
    "<shift>": "⇧",
    "<space>": "Space",
    "<enter>": "⏎",
    "<tab>": "⇥",
    "<sym>": "?!#",
    "<abc>": "ABC",
    "<lang>": "TH/EN",
    "<clear>": "C",
}

SPECIAL_WIDTH = {
    "<bs>": 1.0,
    "<shift>": 1.4,
    "<space>": 4.0,
    "<enter>": 1.6,
    "<tab>": 1.4,
    "<sym>": 1.4,
    "<abc>": 1.4,
    "<lang>": 1.4,
    "<clear>": 1.6,
}

MOD_KEYS = {"<shift>", "<sym>", "<abc>", "<lang>", "<tab>", "<bs>", "<clear>"}

_TEXT_WIDGET_CLASSES = {
    "Entry", "TEntry", "Spinbox", "TSpinbox", "Text", "TCombobox",
}
_NUMERIC_CLASSES = {"Spinbox", "TSpinbox"}

_MODE_ATTR = "_osk_mode"

# Families tried in order.  The first one actually installed wins.
# UI_FONTS must carry the ⌫ ⇧ ⏎ ⇥ glyphs; THAI_FONTS must carry Thai.
UI_FONTS = ["DejaVu Sans", "Noto Sans", "FreeSans", "Liberation Sans", "Helvetica"]
THAI_FONTS = ["Noto Sans Thai", "Noto Sans Thai UI", "Sarabun", "TH Sarabun New",
              "Loma", "Garuda", "Waree", "Noto Sans", "DejaVu Sans"]


def _is_combining_thai(ch):
    """Thai vowels/tone marks that have no standalone shape (แสดงด้วย ◌)."""
    o = ord(ch)
    return o == 0x0E31 or 0x0E34 <= o <= 0x0E3A or 0x0E47 <= o <= 0x0E4E


def _pick_font(candidates, fallback="Helvetica"):
    """Return the first installed family from `candidates`."""
    try:
        import tkinter.font as tkfont
        have = {f.lower() for f in tkfont.families()}
    except Exception:
        return fallback
    for name in candidates:
        if name.lower() in have:
            return name
    return fallback


# --------------------------------------------------------------------------
# public helpers
# --------------------------------------------------------------------------

def numeric(widget):
    """Mark a field so it gets the number pad instead of the full keyboard."""
    setattr(widget, _MODE_ATTR, "numeric")
    return widget


def ignore(widget):
    """Mark a field so the keyboard never appears for it."""
    setattr(widget, _MODE_ATTR, "off")
    return widget


def install(root, **kwargs):
    """Attach a keyboard to `root` and return it. See module docstring."""
    return OnScreenKeyboard(root, **kwargs)


# --------------------------------------------------------------------------
# the keyboard
# --------------------------------------------------------------------------

class OnScreenKeyboard:

    def __init__(self, root, *, thai=True, height_ratio=0.42, theme=None,
                 min_key_font=11, max_key_font=30, auto_install=True,
                 font=None, thai_font=None, numpad_width=0.40):
        self.root = root
        self.thai = thai
        self.height_ratio = height_ratio
        self.numpad_width = numpad_width
        self.theme = dict(theme or DARK)

        self._min_font = min_key_font
        self._max_font = max_key_font
        self.ui_font = font or _pick_font(UI_FONTS)
        self.thai_font = thai_font or _pick_font(THAI_FONTS, self.ui_font)

        self._host = None          # Toplevel the frame currently lives in
        self._frame = None         # the keyboard Frame
        self._keys_area = None
        self._target = None        # widget receiving characters
        self._visible = False
        self._mode = "text"        # "text" | "numeric"
        self._layer = "en"         # "en" | "sym" | "th"
        self._shift = 0            # 0 off, 1 one-shot, 2 locked
        self._buttons = []
        self._repeat_job = None
        self._suspend_hide = False

        if auto_install:
            self._bind_global()

    # ---------------------------------------------------------------- events

    def _bind_global(self):
        self.root.bind_all("<FocusIn>", self._on_focus_in, add="+")
        self.root.bind_all("<Button-1>", self._on_click, add="+")
        self.root.bind_all("<Configure>", self._on_configure, add="+")
        self.root.bind_all("<Escape>", lambda e: self.hide(), add="+")

    def _on_focus_in(self, event):
        w = event.widget
        if self._is_ours(w):
            return
        if self._is_text_widget(w):
            self.show_for(w)
        else:
            self.hide()

    def _on_click(self, event):
        w = event.widget
        if self._is_ours(w):
            return
        if self._is_text_widget(w):
            # re-show after the user dismissed it while the field kept focus
            self.show_for(w)

    def _on_configure(self, event):
        if self._visible and event.widget is self._host:
            self._place_frame()

    # ------------------------------------------------------------ predicates

    def _is_ours(self, widget):
        f = self._frame
        if f is None:
            return False
        try:
            return widget is f or str(widget).startswith(str(f) + ".")
        except Exception:
            return False

    @staticmethod
    def _mode_of(widget):
        return getattr(widget, _MODE_ATTR, None)

    def _is_text_widget(self, widget):
        if widget is None:
            return False
        if self._mode_of(widget) == "off":
            return False
        try:
            cls = widget.winfo_class()
        except Exception:
            return False
        if cls not in _TEXT_WIDGET_CLASSES:
            return False
        # skip disabled / readonly fields
        try:
            state = str(widget.cget("state"))
            if state in ("disabled", "readonly"):
                return False
        except Exception:
            pass
        return True

    def _resolve_mode(self, widget):
        explicit = self._mode_of(widget)
        if explicit in ("numeric", "text"):
            return explicit
        try:
            if widget.winfo_class() in _NUMERIC_CLASSES:
                return "numeric"
        except Exception:
            pass
        return "text"

    # -------------------------------------------------------------- lifecycle

    def show_for(self, widget):
        self._target = widget
        mode = self._resolve_mode(widget)
        top = widget.winfo_toplevel()

        rebuild = (self._frame is None or self._host is not top
                   or mode != self._mode)
        self._mode = mode
        if rebuild:
            self._build(top)
        self._place_frame()
        self._visible = True

    def hide(self, _event=None):
        if self._frame is not None:
            self._frame.place_forget()
        self._visible = False
        self._cancel_repeat()

    def toggle(self):
        if self._visible:
            self.hide()
        elif self._target is not None:
            self.show_for(self._target)

    @property
    def visible(self):
        return self._visible

    # ------------------------------------------------------------ construction

    def _build(self, top):
        if self._frame is not None:
            self._frame.destroy()
        self._host = top
        t = self.theme
        self._frame = tk.Frame(top, bg=t["bar"], bd=0,
                               highlightthickness=1,
                               highlightbackground=t["border"])
        self._render()

    def _render(self):
        for child in self._frame.winfo_children():
            child.destroy()
        self._buttons = []
        t = self.theme

        header = tk.Frame(self._frame, bg=t["bar"])
        header.pack(fill="x", padx=6, pady=(4, 0))
        tk.Label(header, text=self._title(), bg=t["bar"], fg=t["hint"],
                 font=(self.thai_font, 10)).pack(side="left")
        close = tk.Button(header, text="✕", bd=0, takefocus=0,
                          bg=t["bar"], fg=t["hint"],
                          activebackground=t["bar"],
                          activeforeground=t["key_fg"],
                          font=(self.ui_font, 13), padx=10, pady=0,
                          command=self.hide)
        close.pack(side="right")

        body = tk.Frame(self._frame, bg=t["bar"])
        body.pack(fill="both", expand=True, padx=4, pady=4)
        self._keys_area = body

        rows = self._rows()
        if self._mode == "numeric":
            # centre a narrow pad rather than stretching digits across the bar
            pad = tk.Frame(body, bg=t["bar"])
            pad.place(relx=0.5, rely=0.5, anchor="center",
                      relwidth=self.numpad_width, relheight=1.0)
            container = pad
        else:
            container = body

        for r, row in enumerate(rows):
            container.grid_rowconfigure(r, weight=1, uniform="kbrow")

        for r, row in enumerate(rows):
            col = 0
            for item in row:
                span = max(1, int(round(SPECIAL_WIDTH.get(item, 1.0) * 2)))
                btn = self._make_key(container, item)
                btn.grid(row=r, column=col, columnspan=span,
                         sticky="nsew", padx=2, pady=2)
                for c in range(col, col + span):
                    container.grid_columnconfigure(c, weight=1, uniform="kbcol")
                col += span

    def _title(self):
        if self._mode == "numeric":
            return "Number pad"
        return {"en": "English", "sym": "Symbols", "th": "ไทย"}[self._layer]

    def _rows(self):
        if self._mode == "numeric":
            return NUM_ROWS
        if self._layer == "sym":
            return SYM_ROWS
        if self._layer == "th":
            return TH_SHIFT_ROWS if self._shift else TH_ROWS
        return EN_ROWS

    def _label_for(self, item):
        if item.startswith("<"):
            if item == "<shift>":
                return {0: "⇧", 1: "⇧", 2: "⇪"}[self._shift]
            return SPECIAL_LABEL.get(item, item)
        ch = self._char_for(item)
        if len(ch) == 1 and _is_combining_thai(ch):
            return "◌" + ch      # show ◌ั rather than a floating mark
        return ch

    def _char_for(self, item):
        if self._layer == "th":
            return item
        if self._shift:
            return EN_SHIFT_MAP.get(item, item.upper())
        return item

    def _family_for(self, item):
        """Special keys keep the UI font (for ⌫ ⇧ ⏎); Thai chars get a Thai font."""
        if self._layer == "th" and not item.startswith("<"):
            return self.thai_font
        return self.ui_font

    def _make_key(self, parent, item):
        t = self.theme
        is_mod = item in MOD_KEYS
        is_go = item == "<enter>"
        bg = t["accent"] if is_go else (t["mod"] if is_mod else t["key"])
        fg = t["accent_fg"] if is_go else t["key_fg"]
        if item == "<shift>" and self._shift:
            bg = t["accent"]
            fg = t["accent_fg"]

        btn = tk.Button(parent, text=self._label_for(item), bd=0, takefocus=0,
                        bg=bg, fg=fg,
                        activebackground=t["key_active"],
                        activeforeground=t["key_fg"],
                        highlightthickness=0,
                        font=(self._family_for(item), 14),
                        command=lambda i=item: self._press(i))
        if item == "<bs>":
            btn.bind("<ButtonPress-1>", lambda e: self._start_repeat("<bs>"))
            btn.bind("<ButtonRelease-1>", lambda e: self._cancel_repeat())
        self._buttons.append((btn, item))
        return btn

    # ---------------------------------------------------------------- geometry

    def _place_frame(self):
        top = self._host
        top.update_idletasks()
        H = top.winfo_height()
        W = top.winfo_width()
        if H <= 1 or W <= 1:
            top.after(50, self._place_frame)
            return

        kb_h = max(180, int(H * self.height_ratio))
        kb_h = min(kb_h, int(H * 0.6))

        y = H - kb_h
        tgt = self._target
        if tgt is not None:
            try:
                ty = tgt.winfo_rooty() - top.winfo_rooty()
                th = tgt.winfo_height()
                if ty + th + 10 > y and ty > kb_h + 10:
                    y = 0            # field is low on screen -> keyboard on top
            except Exception:
                pass

        self._frame.place(in_=top, x=0, y=y, width=W, height=kb_h)
        self._frame.lift()
        self._scale_fonts(kb_h, W)

    def _scale_fonts(self, kb_h, kb_w):
        rows = max(1, len(self._rows()))
        key_h = kb_h / (rows + 1)
        size = int(key_h * 0.42)
        size = max(self._min_font, min(self._max_font, size))
        for btn, item in self._buttons:
            weight = "bold" if item in ("<enter>", "<shift>") else "normal"
            btn.configure(font=(self._family_for(item), size, weight))

    # ------------------------------------------------------------- key presses

    def _press(self, item):
        w = self._target
        if w is None:
            return

        if item == "<shift>":
            self._shift = {0: 1, 1: 2, 2: 0}[self._shift]
            self._refresh_labels()
            return
        if item == "<sym>":
            self._layer, self._prev_layer = "sym", self._layer
            self._render(); self._place_frame(); return
        if item == "<abc>":
            self._layer = getattr(self, "_prev_layer", "en")
            self._render(); self._place_frame(); return
        if item == "<lang>":
            if not self.thai:
                return
            self._layer = "th" if self._layer != "th" else "en"
            self._shift = 0
            self._render(); self._place_frame(); return

        if item == "<bs>":
            self._backspace(w)
        elif item == "<clear>":
            self._clear(w)
        elif item == "<space>":
            self._insert(w, " ")
        elif item == "<tab>":
            nxt = w.tk_focusNext()
            if nxt is not None:
                nxt.focus_set()
            return
        elif item == "<enter>":
            self.hide()
            try:
                w.event_generate("<Return>")
            except Exception:
                pass
            return
        else:
            self._insert(w, self._char_for(item))

        if self._shift == 1:          # one-shot shift
            self._shift = 0
            self._refresh_labels()
        self._refocus()

    def _refresh_labels(self):
        if self._layer == "th":
            self._render()
            self._place_frame()
            return
        t = self.theme
        for btn, item in self._buttons:
            btn.configure(text=self._label_for(item))
            if item == "<shift>":
                on = bool(self._shift)
                btn.configure(bg=t["accent"] if on else t["mod"],
                              fg=t["accent_fg"] if on else t["key_fg"])
        self._refocus()

    def _refocus(self):
        try:
            self._target.focus_set()
        except Exception:
            pass

    # ------------------------------------------------------- text manipulation

    @staticmethod
    def _is_text_box(w):
        return w.winfo_class() == "Text"

    def _insert(self, w, ch):
        try:
            if self._is_text_box(w):
                if w.tag_ranges("sel"):
                    w.delete("sel.first", "sel.last")
                w.insert("insert", ch)
            else:
                if w.selection_present():
                    w.delete("sel.first", "sel.last")
                w.insert(w.index("insert"), ch)
        except Exception:
            pass

    def _backspace(self, w):
        try:
            if self._is_text_box(w):
                if w.tag_ranges("sel"):
                    w.delete("sel.first", "sel.last")
                else:
                    w.delete("insert-1c", "insert")
            else:
                if w.selection_present():
                    w.delete("sel.first", "sel.last")
                else:
                    i = w.index("insert")
                    if i > 0:
                        w.delete(i - 1, i)
        except Exception:
            pass

    def _clear(self, w):
        try:
            if self._is_text_box(w):
                w.delete("1.0", "end")
            else:
                w.delete(0, "end")
        except Exception:
            pass
        self._refocus()

    # ------------------------------------------------------------- key repeat

    def _start_repeat(self, item, delay=450):
        self._cancel_repeat()

        def step(d):
            self._press(item)
            self._repeat_job = self._frame.after(d, step, max(60, int(d * 0.7)))

        self._repeat_job = self._frame.after(delay, step, 140)

    def _cancel_repeat(self):
        if self._repeat_job is not None and self._frame is not None:
            try:
                self._frame.after_cancel(self._repeat_job)
            except Exception:
                pass
        self._repeat_job = None


# --------------------------------------------------------------------------
# self-test: `python3 osk.py`
# --------------------------------------------------------------------------

if __name__ == "__main__":
    root = tk.Tk()
    root.title("osk demo")
    root.geometry("800x480")
    root.configure(bg="#0d1117")

    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass

    box = tk.Frame(root, bg="#0d1117")
    box.pack(fill="both", expand=True, padx=40, pady=30)

    tk.Label(box, text="Trainee name", bg="#0d1117", fg="#c9d1d9",
             font=("DejaVu Sans", 13)).pack(anchor="w")
    name = ttk.Entry(box, font=("DejaVu Sans", 18))
    name.pack(fill="x", pady=(4, 18), ipady=8)

    tk.Label(box, text="Room / host IP", bg="#0d1117", fg="#c9d1d9",
             font=("DejaVu Sans", 13)).pack(anchor="w")
    host = ttk.Entry(box, font=("DejaVu Sans", 18))
    host.pack(fill="x", pady=(4, 18), ipady=8)

    tk.Label(box, text="Depth weight", bg="#0d1117", fg="#c9d1d9",
             font=("DejaVu Sans", 13)).pack(anchor="w")
    depth = ttk.Entry(box, font=("DejaVu Sans", 18))
    depth.pack(fill="x", pady=(4, 18), ipady=8)
    numeric(depth)

    install(root)
    root.mainloop()
