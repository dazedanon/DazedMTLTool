#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Forum Post Generator — a dark, F95-styled GUI that builds an F95-style BBCode game
thread from simple fields.

Features:
  * Live, interactive preview (clickable/collapsible spoilers, clickable links,
    REAL image thumbnails for URLs and local files).
  * Full F95 field set: Original Title, Aliases, Developer/Publisher/Translator with
    link rows, Voice, Length, multiple Store links, VNDB, Other Games, Developer Notes,
    Required note, Genre tags, Installation, Downloads, Extras, Screenshots.
  * Release Date / Thread Updated default to TODAY (YYYY-MM-DD) — one-click "Today".
  * Image insertion: pick from your PC (📁) or paste an image URL — it auto-previews.
  * F95-accurate formatting toolbar with hover tooltips.
  * Forum-style TAG picker (genre) — toggle chips, filter, add / rename / delete.
  * Crash-safe AUTOSAVE: written on every change, restored on launch.
  * Per-game save/load profiles, "Copy BBCode", "Copy thread title".

Run:  python forum_post_generator.py   (or double-click Run.bat)
Deps: customtkinter, pillow  (pip install customtkinter pillow) + tkinter (bundled)
"""

import datetime
import io
import json
import os
import re
import sys
import threading
import urllib.request
import webbrowser
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog

import customtkinter as ctk

try:
    from PIL import Image, ImageTk, ImageGrab
    HAS_PIL = True
except Exception:
    HAS_PIL = False

# --------------------------------------------------------------------------
# F95-like theme
# --------------------------------------------------------------------------
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

BG = "#1a1b1e"
PANEL = "#212226"
CARD = "#2a2b30"
ENTRY_BG = "#303137"
ACCENT = "#e2444f"
ACCENT_HOVER = "#c8323d"
LOGO_RED = "#ec2b39"
TXT = "#e3e5e9"
MUTED = "#a6abb3"
LINK = "#69b1ff"
PREVIEW_BG = "#17181b"
SPOIL_BAR = "#3a3c42"
SPOIL_BG = "#202126"
CHIP_BG = "#2f3036"
TIP_BG = "#0c0c0e"

# --------------------------------------------------------------------------
# Win32 borderless-window plumbing (custom title bar)
# --------------------------------------------------------------------------
_WIN = sys.platform == "win32"
if _WIN:
    try:
        import ctypes
        from ctypes import wintypes

        _u32 = ctypes.windll.user32

        GWL_STYLE      = -16
        WS_CAPTION     = 0x00C00000      # = WS_BORDER | WS_DLGFRAME (the bit we remove)
        WS_THICKFRAME  = 0x00040000      # sizing border  -> KEEP (native resize)
        WS_MINIMIZEBOX = 0x00020000      # KEEP
        WS_MAXIMIZEBOX = 0x00010000      # KEEP
        WS_SYSMENU     = 0x00080000      # KEEP (Alt+Space, some snap/restore paths)

        SWP_NOSIZE     = 0x0001
        SWP_NOMOVE     = 0x0002
        SWP_NOZORDER   = 0x0004
        SWP_NOACTIVATE = 0x0010
        SWP_FRAMECHANGED = 0x0020

        SW_MINIMIZE = 6
        SW_MAXIMIZE = 3
        SW_RESTORE  = 9

        GA_ROOT          = 2
        HTCAPTION        = 2
        WM_NCLBUTTONDOWN = 0x00A1

        # 64-bit-safe pointer variants (truncation-safe; verified on this machine)
        _u32.GetWindowLongPtrW.restype  = ctypes.c_longlong
        _u32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        _u32.SetWindowLongPtrW.restype  = ctypes.c_longlong
        _u32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_longlong]
        _u32.GetParent.restype   = wintypes.HWND
        _u32.GetParent.argtypes  = [wintypes.HWND]
        _u32.GetAncestor.restype = wintypes.HWND
        _u32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        _u32.IsZoomed.restype    = wintypes.BOOL
        _u32.IsZoomed.argtypes   = [wintypes.HWND]
        _u32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        _u32.SendMessageW.restype = ctypes.c_longlong
        _u32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                      wintypes.WPARAM, wintypes.LPARAM]
        _u32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND,
                                      ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                      wintypes.UINT]
        # PostMessageW is NON-blocking (unlike SendMessageW): used to start the
        # native window-move loop without re-entering Tcl from inside a callback.
        _u32.PostMessageW.restype  = wintypes.BOOL
        _u32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                      wintypes.WPARAM, wintypes.LPARAM]
        _u32.ReleaseCapture.restype  = wintypes.BOOL
        _u32.ReleaseCapture.argtypes = []

        # RedrawWindow: force the scrolled child widgets to repaint NOW so fast
        # scrolling doesn't leave smear/artifacts (Tk widgets are child HWNDs).
        RDW_INVALIDATE  = 0x0001
        RDW_UPDATENOW   = 0x0100
        RDW_ALLCHILDREN = 0x0080
        _u32.RedrawWindow.argtypes = [wintypes.HWND, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
        _u32.RedrawWindow.restype  = wintypes.BOOL

        # --- native custom frame (WM_NCCALCSIZE): keep the OS window normal so it
        #     plays native min/max/restore animations, but don't draw the caption ---
        GWL_WNDPROC   = -4
        WM_NCCALCSIZE = 0x0083
        WM_NCHITTEST  = 0x0084
        HTLEFT, HTRIGHT, HTTOP = 10, 11, 12
        HTTOPLEFT, HTTOPRIGHT = 13, 14
        HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT = 15, 16, 17
        MONITOR_DEFAULTTONEAREST = 2

        WNDPROCTYPE = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND,
                                         wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

        class _NCCALCSIZE_PARAMS(ctypes.Structure):
            _fields_ = [("rgrc", wintypes.RECT * 3), ("lppos", ctypes.c_void_p)]

        class _MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                        ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

        _u32.CallWindowProcW.restype  = ctypes.c_longlong
        _u32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT,
                                         wintypes.WPARAM, wintypes.LPARAM]
        _u32.GetWindowRect.argtypes   = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        _u32.GetWindowRect.restype    = wintypes.BOOL
        _u32.MonitorFromWindow.restype  = ctypes.c_void_p
        _u32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        _u32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MONITORINFO)]
        _u32.GetMonitorInfoW.restype  = wintypes.BOOL
    except Exception:
        # If ctypes plumbing fails to load, fall back to the native title bar.
        _WIN = False

HERE = os.path.dirname(os.path.abspath(__file__))
PROFILES_DIR = os.path.join(HERE, "profiles")
os.makedirs(PROFILES_DIR, exist_ok=True)
AUTOSAVE_PATH = os.path.join(PROFILES_DIR, "_autosave_session.json")
TAGS_PATH = os.path.join(HERE, "tags.json")
PASTED_DIR = os.path.join(HERE, "pasted_images")

SIZE_MAP = {"1": 11, "2": 12, "3": 13, "4": 15, "5": 18, "6": 24, "7": 30}
COLOR_NAMES = {"red": "#e2444f", "green": "#7bd88f", "blue": LINK, "yellow": "#ffd866",
               "orange": "#ffa657", "purple": "#b89bff", "white": "#ffffff", "gray": MUTED}
COLOR_CHOICES = [("Red", "red"), ("Orange", "orange"), ("Yellow", "yellow"), ("Green", "green"),
                 ("Blue", "blue"), ("Purple", "purple"), ("White", "white")]
FONT_CHOICES = ["Arial", "Tahoma", "Verdana", "Georgia", "Times New Roman", "Courier New", "Comic Sans MS"]
SMILIES = [(":)", "Smile"), (";)", "Wink"), (":D", "Big grin"), (":p", "Stick out tongue"),
           (":(", "Frown"), (":mad:", "Mad"), (":cry:", "Crying"), (":love:", "Love"),
           (":cool:", "Cool"), (":oops:", "Embarrassed"), (":eek:", "EEK!"), (":giggle:", "Giggle")]
IMG_TYPES = [("Images", "*.png *.jpg *.jpeg *.gif *.webp *.bmp *.avif"), ("All files", "*.*")]

# F95 thread prefixes (engine + status), for the title-line helper.
PREFIXES = ["VN", "RPGM", "Unity", "Ren'Py", "HTML", "RAGS", "QSP", "Flash", "Others",
            "Completed", "Abandoned", "Onhold", "Mod"]

# Common F95 game tags. Editable at runtime; persisted to tags.json.
DEFAULT_TAGS = [
    "2D Game", "2DCG", "3D Game", "3DCG", "Adventure", "Ahegao", "AI CG", "Anal Sex",
    "Animated", "BDSM", "Bestiality", "Big Ass", "Big Tits", "Blackmail", "Bukkake", "Censored",
    "Character Creation", "Cheating", "Combat", "Corruption", "Cosplay", "Creampie", "Dating Sim",
    "Dilf", "Drugs", "Dystopian setting", "Exhibitionism", "Fantasy", "Female Domination",
    "Female Protagonist", "Footjob", "Furry", "Futa/Trans", "Futa/Trans Protagonist", "Gay",
    "Graphic Violence", "Groping", "Group Sex", "Handjob", "Harem", "Horror", "Humiliation",
    "Humor", "Incest", "Internal View", "Interracial", "Japanese Game", "Kinetic Novel",
    "Lactation", "Lesbian", "Loli", "Male Domination", "Male Protagonist", "Management",
    "Masturbation", "Milf", "Mind Control", "Mobile Game", "Monster", "Monster Girl",
    "Multiple Endings", "Multiple Penetration", "Multiple Protagonist", "Necrophilia", "Netorare",
    "No Sexual Content", "NTR", "Oral Sex", "Paranormal", "Parody", "Platformer", "Point & Click",
    "Possession", "PoV", "Pregnancy", "Prostitution", "Puzzle", "Rape", "Real Porn", "Religion",
    "Romance", "RPG", "Sandbox", "Scat", "School Setting", "Sci-Fi", "Sex Toys", "Sexual Harassment",
    "Shooter", "Shota", "Side-scroller", "Simulator", "Sissification", "Slave", "Sleep Sex",
    "Spanking", "Strategy", "Stripping", "Superpowers", "Swinging", "Teasing", "Tentacles",
    "Text Based", "Titfuck", "Trainer", "Transformation", "Trap", "Turn Based Combat", "Twins",
    "Urination", "Vaginal Sex", "Virgin", "Virtual Reality", "Voiced", "Vore", "Voyeurism",
]


def _today():
    return datetime.date.today().isoformat()


def _open_src(src):
    try:
        if src.startswith(("http://", "https://")):
            webbrowser.open(src)
        elif os.path.isfile(src):
            os.startfile(src)  # noqa: P204 (Windows)
    except Exception:
        pass


# --------------------------------------------------------------------------
# tooltip
# --------------------------------------------------------------------------
class Tooltip:
    def __init__(self, widget, text, delay=400):
        self.widget, self.text, self.delay = widget, text, delay
        self.tip = None
        self.after_id = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _e=None):
        self._cancel()
        self.after_id = self.widget.after(self.delay, self._show)

    def _show(self):
        if self.tip or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2 - 30
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        except tk.TclError:
            return
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self.tip, text=self.text, bg=TIP_BG, fg="#eef0f3", font=("Segoe UI", 10),
                 padx=8, pady=4, bd=1, relief="solid").pack()

    def _hide(self, _e=None):
        self._cancel()
        if self.tip:
            self.tip.destroy()
            self.tip = None

    def _cancel(self):
        if self.after_id:
            try:
                self.widget.after_cancel(self.after_id)
            except tk.TclError:
                pass
            self.after_id = None


# --------------------------------------------------------------------------
# BBCode generation
# --------------------------------------------------------------------------
def _is_url(s):
    return s.startswith("http://") or s.startswith("https://")


def image_bb(src, alt="", full=False):
    """src may be an attachment ID (digits), an http(s) URL, or a local file path."""
    src = (src or "").strip()
    if not src:
        return ""
    if src.isdigit():
        t = ' type="full"' if full else ""
        a = f' alt="{alt}"' if alt else ""
        return f"[ATTACH{t}{a}]{src}[/ATTACH]"
    if _is_url(src):
        return f"[IMG]{src}[/IMG]"
    # Local file: keep the full path so the live preview can render it. On the forum
    # itself a local path won't load — upload the image and replace it with the URL/ID.
    return f"[IMG]{src}[/IMG]"


def _links_str(rows, default_label="Link"):
    parts = []
    for r in (rows or []):
        url = (r.get("url") or "").strip()
        if not url:
            continue
        label = (r.get("label") or default_label).strip() or default_label
        parts.append(f"[URL='{url}']{label}[/URL]")
    return " - ".join(parts)


def build_bbcode(d):
    out = []

    # ---- header / cover + overview --------------------------------------
    top_head = image_bb(d.get("banner_src"), d.get("banner_alt"), full=True)
    block = []
    ov = (d.get("overview_short") or "").strip()
    if ov:
        block.append("[B]Overview[/B]:\n" + ov)
    ovs = (d.get("overview_spoiler") or "").strip()
    if ovs:
        block.append("[SPOILER]\n" + ovs + "\n[/SPOILER]")
    inner = "\n".join(block).strip()
    if top_head or inner:
        out.append("[CENTER]" + top_head + ("\n\n" if top_head and inner else "") + inner + "[/CENTER]")

    # ---- details --------------------------------------------------------
    det = []

    def line(label, value):
        if value and str(value).strip():
            det.append(f"[B]{label}[/B]: {str(value).strip()}")

    def named(label, name, links_rows, extra_links=None):
        name = (name or "").strip()
        rows = list(links_rows or [])
        if extra_links:
            rows = rows + extra_links
        links = _links_str(rows)
        if not name and not links:
            return
        s = f"[B]{label}[/B]: " + name
        if links:
            s += (" " if name else "") + links
        det.append(s)

    line("Thread Updated", d.get("thread_updated"))
    line("Release Date", d.get("release_date"))
    line("Original Title", d.get("original_title"))
    line("Aliases", d.get("aliases"))

    cien = (d.get("cien_url") or "").strip()
    named("Developer", d.get("developer"), d.get("developer_links"),
          extra_links=[{"label": "ci-en", "url": cien}] if cien else None)
    named("Publisher", d.get("publisher"), d.get("publisher_links"))
    named("Translator", d.get("translator"), d.get("translator_links"))

    line("Censored", d.get("censored"))
    line("Version", d.get("version"))
    line("OS", d.get("os"))
    lang = (d.get("language") or "").strip()
    note = (d.get("language_note") or "").strip()
    if lang:
        det.append(f"[B]Language[/B]: {lang}" + (f" ({note})" if note else ""))
    line("Voice", d.get("voice"))
    line("Length", d.get("length"))

    vndb = (d.get("vndb_url") or "").strip()
    if vndb:
        det.append(f"[B]VNDB[/B]: [URL='{vndb}']Link[/URL]")

    # Store: new multi-link rows, plus legacy single store_url for old profiles.
    store_rows = list(d.get("store_links") or [])
    if (d.get("store_url") or "").strip():
        store_rows = [{"label": d.get("store_label") or "Store", "url": d.get("store_url")}] + store_rows
    store_links = _links_str(store_rows, default_label="Store")
    if store_links:
        det.append(f"[B]Store[/B]: {store_links}")

    other = (d.get("other_games_url") or "").strip()
    if other:
        det.append(f"[B]Other Games[/B]: [URL='{other}']Link[/URL]")

    if det:
        out.append("\n".join(det))

    # ---- spoiler sections ----------------------------------------------
    def spoiler_section(label, body):
        body = (body or "").strip()
        if body:
            out.append(f"[B]{label}[/B]:\n[SPOILER]\n{body}\n[/SPOILER]")

    spoiler_section("Genre", d.get("genre"))
    spoiler_section("Installation", d.get("installation"))
    spoiler_section("Developer Notes", d.get("developer_notes"))
    spoiler_section("Translator Notes", d.get("translator_notes"))

    req = (d.get("required_note") or "").strip()
    if req:
        out.append("[CENTER]" + req + "[/CENTER]")

    # ---- downloads ------------------------------------------------------
    dls = [r for r in d.get("downloads", []) if (r.get("url") or "").strip()]
    extras = [r for r in d.get("extras", []) if (r.get("url") or "").strip()]
    shots = [r for r in d.get("screenshots", []) if (r.get("src") or r.get("id") or "").strip()]
    if dls or extras or shots:
        dl = ["[CENTER][B][SIZE=6]DOWNLOAD[/SIZE][/B]"]
        win = (d.get("download_os_label") or "Win").strip() or "Win"
        size_line = ""
        if dls:
            links = " - ".join(f"[URL='{r['url'].strip()}']{(r.get('host') or 'LINK').strip()}[/URL]" for r in dls)
            size_line = f"[SIZE=5][B]{win}[/B]: {links} "
        if extras:
            ex = " - ".join(f"[URL='{r['url'].strip()}']{(r.get('label') or 'Link').strip()}[/URL]" for r in extras)
            size_line = (size_line + f"\n\n[B]Extras[/B]: {ex}[/SIZE]") if size_line else f"[SIZE=5][B]Extras[/B]: {ex}[/SIZE]"
        elif size_line:
            size_line += "[/SIZE]"
        if size_line:
            dl.append(size_line)
        if shots:
            ss_full = (d.get("ss_size") == "Full image")
            dl.append("\n" + " ".join(
                image_bb(r.get("src") or r.get("id"), r.get("alt", ""), full=ss_full) for r in shots))
        dl.append("[/CENTER]")
        out.append("\n".join(dl))

    return "\n\n".join(p for p in out if p.strip()).strip() + "\n"


# --------------------------------------------------------------------------
# BBCode -> interactive rendered preview
# --------------------------------------------------------------------------
TOKEN_RE = re.compile(r"(\[/?[a-zA-Z][^\]]*\])")
TAG_RE = re.compile(r"\[(/?)([a-zA-Z]+)(?:[=\s]([^\]]*))?\]")
BBCODE_STRIP_RE = re.compile(r"\[/?[a-zA-Z][^\]]*\]")


def _attr(argstr, key):
    m = re.search(rf'{key}\s*=\s*"?([^"\]]+)"?', argstr or "", re.I)
    return m.group(1).strip() if m else ""


class Style:
    __slots__ = ("bold", "italic", "underline", "strike", "size", "color", "just", "depth", "link", "mono")

    def __init__(self):
        self.bold = self.italic = self.underline = self.strike = self.mono = False
        self.size = 13
        self.color = TXT
        self.just = None
        self.depth = 0
        self.link = None

    def copy(self):
        s = Style()
        for k in self.__slots__:
            setattr(s, k, getattr(self, k))
        return s


class PreviewRenderer:
    def __init__(self, text_widget, image_loader=None):
        self.t = text_widget
        self.image_loader = image_loader
        self._font_cache = {}
        self._seq = 0
        self.open_state = {}

    def _font(self, size, bold, italic, underline, strike, mono=False):
        key = (size, bold, italic, underline, strike, mono)
        f = self._font_cache.get(key)
        if f is None:
            f = tkfont.Font(family="Consolas" if mono else "Segoe UI", size=size,
                            weight="bold" if bold else "normal", slant="italic" if italic else "roman",
                            underline=underline, overstrike=strike)
            self._font_cache[key] = f
        return f

    def render(self, bbcode):
        t = self.t
        t.configure(state="normal")
        t.delete("1.0", "end")
        st = Style()
        stack = []
        in_attach = None
        self.body_stack = []
        self.ordinal = 0
        for part in TOKEN_RE.split(bbcode):
            if not part:
                continue
            m = TAG_RE.fullmatch(part)
            if m:
                closing, name, arg = m.group(1), m.group(2).lower(), (m.group(3) or "").strip().strip('"\'')
                if not closing:
                    if name in ("attach", "img", "media"):
                        in_attach = {"alt": _attr(arg, "alt") or "", "tag": name}
                        continue
                    stack.append(st.copy())
                    if name == "b": st.bold = True
                    elif name == "i": st.italic = True
                    elif name == "u": st.underline = True
                    elif name in ("s", "strike"): st.strike = True
                    elif name in ("code", "icode"): st.mono = True
                    elif name == "center": st.just = "center"
                    elif name == "left": st.just = "left"
                    elif name == "right": st.just = "right"
                    elif name == "size": st.size = SIZE_MAP.get(arg, st.size)
                    elif name == "color": st.color = COLOR_NAMES.get(arg.lower(), arg if arg.startswith("#") else st.color)
                    elif name == "url": st.color = LINK; st.underline = True; st.link = arg or None
                    elif name in ("spoiler", "quote"):
                        st.depth += 1
                        self.ordinal += 1
                        body = f"body{self.ordinal}"
                        self._spoiler_header(st, body, self.ordinal, "Quote" if name == "quote" else "Spoiler")
                        self.body_stack.append(body)
                else:
                    if name in ("attach", "img", "media"):
                        in_attach = None
                        continue
                    if name in ("spoiler", "quote") and self.body_stack:
                        self.body_stack.pop()
                    if stack:
                        st = stack.pop()
                continue
            if in_attach is not None:
                self._image(in_attach.get("tag"), part.strip(), in_attach.get("alt"), st)
                continue
            self._emit(part, st)
        for ordn, is_open in list(self.open_state.items()):
            try:
                self.t.tag_configure(f"body{ordn}", elide=not is_open)
            except tk.TclError:
                pass
        t.insert("end", "\n")
        t.configure(state="disabled")

    def _emit(self, text, st):
        tag = f"r{self._seq}"; self._seq += 1
        cfg = dict(font=self._font(st.size, st.bold, st.italic, st.underline, st.strike, st.mono), foreground=st.color)
        if st.just:
            cfg["justify"] = st.just
        if st.mono:
            cfg["background"] = "#101216"
        if st.depth:
            cfg["lmargin1"] = cfg["lmargin2"] = 14 * st.depth
            cfg["background"] = SPOIL_BG
        self.t.tag_configure(tag, **cfg)
        start = self.t.index("end-1c")
        self.t.insert("end", text)
        self.t.tag_add(tag, start, "end-1c")
        for b in self.body_stack:
            self.t.tag_add(b, start, "end-1c")
        if st.link:
            url = st.link
            self.t.tag_bind(tag, "<Button-1>", lambda e, u=url: webbrowser.open(u))
            self.t.tag_bind(tag, "<Enter>", lambda e: self.t.configure(cursor="hand2"))
            self.t.tag_bind(tag, "<Leave>", lambda e: self.t.configure(cursor=""))

    def _spoiler_header(self, st, body, ordn, label):
        is_open = self.open_state.setdefault(ordn, True)
        htag = f"h{self._seq}"; self._seq += 1
        self.t.tag_configure(htag, font=self._font(12, True, False, False, False), foreground=TXT,
                             background=SPOIL_BAR, justify=st.just or "left",
                             lmargin1=14 * (st.depth - 1), spacing1=5, spacing3=3)
        start = self.t.index("end-1c")
        self.t.insert("end", f" {'▼' if is_open else '▶'} {label} \n")
        self.t.tag_add(htag, start, "end-1c")
        for b in self.body_stack:
            self.t.tag_add(b, start, "end-1c")

        def toggle(_e=None, b=body, h=htag, o=ordn):
            now = not self.open_state.get(o, True)
            self.open_state[o] = now
            try:
                self.t.tag_configure(b, elide=not now)
            except tk.TclError:
                return
            rng = self.t.tag_ranges(h)
            if rng:
                pos = f"{rng[0]}+1c"
                self.t.configure(state="normal")
                self.t.delete(pos, f"{rng[0]}+2c")
                self.t.insert(pos, "▼" if now else "▶", h)
                self.t.configure(state="disabled")

        self.t.tag_bind(htag, "<Button-1>", toggle)
        self.t.tag_bind(htag, "<Enter>", lambda e: self.t.configure(cursor="hand2"))
        self.t.tag_bind(htag, "<Leave>", lambda e: self.t.configure(cursor=""))

    def _image(self, tag, inner, alt, st):
        photo = None
        if tag in ("img", "media") and self.image_loader:
            photo = self.image_loader(inner)
        if photo is not None:
            itag = f"img{self._seq}"; self._seq += 1
            cfg = {"justify": st.just or "left"}
            if st.depth:
                cfg["lmargin1"] = cfg["lmargin2"] = 14 * st.depth
            self.t.tag_configure(itag, **cfg)
            start = self.t.index("end-1c")
            self.t.image_create("end", image=photo, padx=4, pady=4)
            self.t.insert("end", "\n")
            end = self.t.index("end-1c")
            self.t.tag_add(itag, start, end)
            for b in self.body_stack:
                self.t.tag_add(b, start, end)
            self.t.tag_bind(itag, "<Button-1>", lambda e, s=inner: _open_src(s))
            self.t.tag_bind(itag, "<Enter>", lambda e: self.t.configure(cursor="hand2"))
            self.t.tag_bind(itag, "<Leave>", lambda e: self.t.configure(cursor=""))
            return
        # fallback chip (attachment IDs, or images that can't be previewed)
        label = (alt or "").strip()
        warn = False
        if not label:
            if inner and inner.isdigit():
                label = f"attachment {inner}"
            elif inner.startswith(("http://", "https://")):
                label = inner
            elif inner:
                base = os.path.basename(inner)
                if not os.path.isfile(inner):
                    label, warn = f"not found: {base}", True
                else:
                    label = base
            else:
                label = "image"
        ctag = f"c{self._seq}"; self._seq += 1
        self.t.tag_configure(ctag, font=self._font(11, False, True, False, False),
                             foreground="#ffb454" if warn else MUTED,
                             background=CHIP_BG, justify=st.just or "left", lmargin1=14 * st.depth)
        start = self.t.index("end-1c")
        self.t.insert("end", f"  {'⚠' if warn else '🖼'} {label}  ")
        self.t.tag_add(ctag, start, "end-1c")
        for b in self.body_stack:
            self.t.tag_add(b, start, "end-1c")


# --------------------------------------------------------------------------
# repeating rows
# --------------------------------------------------------------------------
class Repeater(ctk.CTkFrame):
    """columns: list of (key, placeholder, weight) or (key, placeholder, weight, kind).
    kind=="file" adds a 📁 picker button that fills that field with a local path."""

    def __init__(self, master, columns, on_change, add_text="+ Add", paste_image=None):
        super().__init__(master, fg_color="transparent")
        self.columns = columns
        self.on_change = on_change
        self.paste_image = paste_image   # callable -> local image path, or None
        self.rows = []
        # No empty container frame: rows pack directly above the Add button. (An
        # empty CTkFrame defaults to ~200px, which made the section reserve a big
        # blank block until the first add/remove.)
        self._add_btn = ctk.CTkButton(self, text=add_text, height=26, width=90, fg_color=CARD,
                                      hover_color=SPOIL_BAR, text_color=TXT,
                                      command=lambda: (self.add_row(), self.on_change()))
        self._add_btn.pack(anchor="w", pady=(4, 0))

    def _browse(self, entry):
        path = filedialog.askopenfilename(title="Select image", filetypes=IMG_TYPES)
        if path:
            entry.delete(0, "end")
            entry.insert(0, path)
            self.on_change()

    def _paste_image_to(self, entry):
        path = self.paste_image() if self.paste_image else None
        if not path:
            return  # no image -> normal text paste
        entry.delete(0, "end")
        entry.insert(0, path)
        self.on_change()
        return "break"

    def add_row(self, data=None):
        data = data or {}
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", pady=2, before=self._add_btn)
        entries = {}
        for col in self.columns:
            key, ph, weight = col[0], col[1], col[2]
            kind = col[3] if len(col) > 3 else "text"
            # No textvariable: customtkinter disables placeholder_text whenever a
            # textvariable is bound, so the "name vs URL" hints would never show.
            e = ctk.CTkEntry(row, placeholder_text=ph, height=28, fg_color=ENTRY_BG, border_width=0)
            val = data.get(key, "")
            if val:
                e.insert(0, val)
            for ev in ("<KeyRelease>", "<FocusOut>", "<<Paste>>"):
                e.bind(ev, lambda _e: self.on_change())
            e.pack(side="left", fill="x", expand=True, padx=(0, 4))
            if kind == "file":
                ctk.CTkButton(row, text="📁", width=30, height=28, fg_color=CARD, hover_color=SPOIL_BAR,
                              text_color=TXT, command=lambda ent=e: self._browse(ent)).pack(side="left", padx=(0, 4))
                if self.paste_image:
                    e.bind("<<Paste>>", lambda ev, ent=e: self._paste_image_to(ent))
            entries[key] = e
        ctk.CTkButton(row, text="✕", width=28, height=28, fg_color="#3a2b2b", hover_color="#5a2b2b",
                      text_color="#ff9b9b", command=lambda r=row: self._remove(r)).pack(side="left")
        self.rows.append((row, entries))

    def _remove(self, row):
        self.rows = [(r, e) for (r, e) in self.rows if r is not row]
        row.destroy()
        self.on_change()

    def get(self):
        return [{k: v.get() for k, v in e.items()} for _, e in self.rows]

    def set(self, items):
        for r, _ in self.rows:
            r.destroy()
        self.rows = []
        for it in (items or []):
            self.add_row(it)


# --------------------------------------------------------------------------
# borderless, F95-themed modal prompt (replaces CTkInputDialog)
# --------------------------------------------------------------------------
class PromptDialog(ctk.CTkToplevel):
    """A small borderless dialog themed like the app (no native title bar, F95 red
    accent). Supports one or more labelled text fields. Use PromptDialog.ask(...)."""

    def __init__(self, parent, title, fields, ok_text="Ok"):
        super().__init__(parent)
        self.result = None
        self.configure(fg_color=PANEL)
        try:
            self.overrideredirect(True)
        except Exception:
            pass
        try:
            self.attributes("-topmost", True)
        except Exception:
            pass

        outer = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=0, border_width=1, border_color=ACCENT)
        outer.pack(fill="both", expand=True)

        bar = ctk.CTkFrame(outer, fg_color=CARD, corner_radius=0, height=34)
        bar.pack(fill="x")
        lf = ctk.CTkLabel(bar, text="F95", font=("Segoe UI Black", 13), text_color=LOGO_RED)
        lf.pack(side="left", padx=(12, 2), pady=6)
        lt = ctk.CTkLabel(bar, text=title, font=("Segoe UI Semibold", 12), text_color=TXT)
        lt.pack(side="left", pady=6)
        ctk.CTkButton(bar, text="✕", width=40, height=34, corner_radius=0, fg_color=CARD,
                      hover_color=ACCENT, text_color=TXT, command=self._cancel).pack(side="right")
        for w in (bar, lf, lt):
            w.bind("<ButtonPress-1>", self._drag_start, add="+")
            w.bind("<B1-Motion>", self._drag_move, add="+")

        body = ctk.CTkFrame(outer, fg_color=PANEL)
        body.pack(fill="both", expand=True, padx=18, pady=(8, 14))
        self.entries = []
        for (label, ph, default) in fields:
            ctk.CTkLabel(body, text=label, text_color=MUTED, font=("Segoe UI", 12),
                         anchor="w").pack(fill="x", pady=(8, 0))
            e = ctk.CTkEntry(body, placeholder_text=ph, width=340, height=32,
                             fg_color=ENTRY_BG, border_width=0)
            if default:
                e.insert(0, default)
            e.pack(fill="x", pady=(2, 0))
            self.entries.append(e)

        btns = ctk.CTkFrame(body, fg_color="transparent")
        btns.pack(fill="x", pady=(18, 0))
        ctk.CTkButton(btns, text=ok_text, height=34, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      text_color="#ffffff", command=self._ok).pack(side="left", expand=True, fill="x", padx=(0, 5))
        ctk.CTkButton(btns, text="Cancel", height=34, fg_color=CARD, hover_color=SPOIL_BAR,
                      text_color=TXT, command=self._cancel).pack(side="left", expand=True, fill="x", padx=(5, 0))

        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self._cancel())
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.update_idletasks()
        self._center(parent)
        if self.entries:
            self.entries[0].focus_set()
        try:
            self.transient(parent)
            self.grab_set()
        except Exception:
            pass

    def _center(self, parent):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        try:
            x = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
            y = parent.winfo_rooty() + (parent.winfo_height() - h) // 3
        except Exception:
            x = (self.winfo_screenwidth() - w) // 2
            y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"+{max(0, x)}+{max(0, y)}")

    def _drag_start(self, e):
        self._dx, self._dy = e.x, e.y

    def _drag_move(self, _e=None):
        try:
            self.geometry(f"+{self.winfo_pointerx() - getattr(self, '_dx', 0)}"
                          f"+{self.winfo_pointery() - getattr(self, '_dy', 0)}")
        except Exception:
            pass

    def _ok(self):
        self.result = [e.get() for e in self.entries]
        self._close()

    def _cancel(self):
        self.result = None
        self._close()

    def _close(self):
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()

    @staticmethod
    def ask(parent, title, fields, ok_text="Ok"):
        d = PromptDialog(parent, title, fields, ok_text)
        parent.wait_window(d)
        return d.result


# --------------------------------------------------------------------------
# main app
# --------------------------------------------------------------------------
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Forum Post Generator")
        self.geometry("1360x920")
        self.minsize(1100, 720)
        self.configure(fg_color=BG)
        try:
            _ico = os.path.join(HERE, "app.ico")
            if os.path.isfile(_ico):
                self.iconbitmap(_ico)
        except Exception:
            pass

        self._debounce = None
        self.current_profile = None
        self.vars = {}
        self.texts = {}
        self.active_text = None
        self.all_tags = self._load_tags()
        self.selected_tags = []
        self.chip_btns = {}
        self._img_cache = {}  # src -> PhotoImage | "loading" | "error"
        self._win_hwnd = None
        self._caption_stripped = False
        self._old_wndproc = None
        self._new_wndproc = None    # keep a ref so the ctypes callback isn't GC'd
        self._grips = []            # edge/corner resize handles
        self._rs_ghost = None       # translucent preview shown during a grip-resize

        self._build_toolbar()
        self._build_formatbar()
        self._build_body()
        self._refresh_profile_list()
        self._setup_shortcuts()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._restore_session()
        self.after(150, self.update_output)
        # Borderless custom title bar (Windows only). Deferred so the native
        # HWND exists & is mapped before we touch its window styles.
        if _WIN:
            self.update_idletasks()
            self._win_hwnd = self._get_hwnd()
            self.bind("<Configure>", self._sync_max_icon, add="+")
            self.after(10, self._install_native_frame)
            self.after(60, self._add_resize_grips)

    # ---- borderless window management (Windows) -------------------------
    def _get_hwnd(self):
        """The caption-owning top-level HWND. winfo_id() returns Tk's inner
        client window (no caption); its parent is the real top-level. Verified
        on this machine: GetParent(winfo_id()) carries WS_CAPTION."""
        try:
            cid = self.winfo_id()
            parent = _u32.GetParent(cid)
            if not parent:
                parent = _u32.GetAncestor(cid, GA_ROOT)
            return parent or cid
        except Exception:
            return None

    def _strip_caption(self):
        """Remove WS_CAPTION while keeping resize/min/max/sysmenu so the OS
        still does taskbar button, minimize/restore, maximize-to-workarea and
        Aero Snap. Falls back silently to the native title bar on any error."""
        if not _WIN:
            return
        try:
            hwnd = self._win_hwnd or self._get_hwnd()
            self._win_hwnd = hwnd
            if not hwnd:
                return
            style = _u32.GetWindowLongPtrW(hwnd, GWL_STYLE)
            style = ((style & ~WS_CAPTION)
                     | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU)
            _u32.SetWindowLongPtrW(hwnd, GWL_STYLE, style)
            # SWP_FRAMECHANGED forces WM_NCCALCSIZE so the (now-gone) caption
            # strip is recomputed away — without it a white sliver lingers.
            _u32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                              SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER
                              | SWP_NOACTIVATE | SWP_FRAMECHANGED)
            self._caption_stripped = True
            self._sync_max_icon()
        except Exception:
            self._caption_stripped = False  # native title bar stays; app still works

    def _install_native_frame(self):
        """Keep the window a NORMAL OS window (so Windows plays its native
        minimize-to-taskbar / maximize / restore animations + Aero Snap), but
        hide the title bar by subclassing the WndProc and removing the caption
        in WM_NCCALCSIZE. Resize on every edge comes from WM_NCHITTEST. Falls
        back to the plain borderless style (no animation) if anything fails."""
        if not _WIN:
            return
        hwnd = self._win_hwnd or self._get_hwnd()
        self._win_hwnd = hwnd
        if not hwnd:
            return
        try:
            style = _u32.GetWindowLongPtrW(hwnd, GWL_STYLE)
            style |= (WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU)
            _u32.SetWindowLongPtrW(hwnd, GWL_STYLE, style)

            def _py_wndproc(h, msg, wp, lp):
                try:
                    if msg == WM_NCCALCSIZE and wp:
                        if _u32.IsZoomed(h):
                            # maximized: clamp the client to the monitor work area
                            # so it doesn't cover the taskbar
                            mon = _u32.MonitorFromWindow(h, MONITOR_DEFAULTTONEAREST)
                            mi = _MONITORINFO()
                            mi.cbSize = ctypes.sizeof(_MONITORINFO)
                            if mon and _u32.GetMonitorInfoW(mon, ctypes.byref(mi)):
                                p = ctypes.cast(ctypes.c_void_p(lp),
                                                ctypes.POINTER(_NCCALCSIZE_PARAMS))
                                p.contents.rgrc[0] = mi.rcWork
                        return 0  # remove the caption: client covers the whole frame
                    if msg == WM_NCHITTEST and not _u32.IsZoomed(h):
                        x = lp & 0xFFFF
                        x -= 0x10000 if x >= 0x8000 else 0
                        y = (lp >> 16) & 0xFFFF
                        y -= 0x10000 if y >= 0x8000 else 0
                        r = wintypes.RECT()
                        _u32.GetWindowRect(h, ctypes.byref(r))
                        b = 8  # resize-grip thickness
                        left, right = x < r.left + b, x >= r.right - b
                        top, bot = y < r.top + b, y >= r.bottom - b
                        if top and left: return HTTOPLEFT
                        if top and right: return HTTOPRIGHT
                        if bot and left: return HTBOTTOMLEFT
                        if bot and right: return HTBOTTOMRIGHT
                        if left: return HTLEFT
                        if right: return HTRIGHT
                        if top: return HTTOP
                        if bot: return HTBOTTOM
                except Exception:
                    pass
                return _u32.CallWindowProcW(self._old_wndproc, h, msg, wp, lp)

            self._new_wndproc = WNDPROCTYPE(_py_wndproc)   # MUST keep a ref (no GC)
            self._old_wndproc = ctypes.c_void_p(_u32.GetWindowLongPtrW(hwnd, GWL_WNDPROC))
            newptr = ctypes.cast(self._new_wndproc, ctypes.c_void_p).value
            _u32.SetWindowLongPtrW(hwnd, GWL_WNDPROC, ctypes.c_longlong(newptr))
            _u32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                              SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER
                              | SWP_NOACTIVATE | SWP_FRAMECHANGED)
            self._caption_stripped = True
            self._sync_max_icon()
        except Exception:
            try:
                self._strip_caption()  # fallback: borderless, no native animation
            except Exception:
                pass

    def _add_resize_grips(self):
        """Thin invisible frames at the edges/corners that show the resize cursor.
        Dragging one shows a translucent 'ghost' of the target size and applies
        the real resize ONCE on release -> smooth (the heavy window isn't resized
        live every frame, which customtkinter can't keep up with). Grips exist
        because every Tk widget is a real child HWND covering the window edges."""
        if not _WIN:
            return
        # The top bar + format bar reach the window edges with their own colors, so
        # grips placed over them show dark notches ("cuts"). The body has a 10px BG
        # margin all around, so we keep grips ONLY over that margin: left/right below
        # the bars, plus the bottom edge and bottom corners -> fully invisible.
        try:
            off = self.titlebar.winfo_height() + self.formatbar.winfo_height()
        except Exception:
            off = 92
        if off < 40:
            off = 92
        T, C = 6, 10  # edge thickness / corner size (fits inside the 10px BG margin)
        # (place kwargs, cursor, (move_left, move_right, move_top, move_bottom))
        specs = [
            (dict(relx=0, y=off, relheight=1.0, height=-off, width=T, anchor="nw"), "sb_h_double_arrow", (1, 0, 0, 0)),
            (dict(relx=1.0, y=off, relheight=1.0, height=-off, width=T, anchor="ne"), "sb_h_double_arrow", (0, 1, 0, 0)),
            (dict(relx=0, rely=1.0, relwidth=1, height=T, anchor="sw"), "sb_v_double_arrow", (0, 0, 0, 1)),
            (dict(relx=0, rely=1.0, width=C, height=C, anchor="sw"), "bottom_left_corner", (1, 0, 0, 1)),
            (dict(relx=1.0, rely=1.0, width=C, height=C, anchor="se"), "bottom_right_corner", (0, 1, 0, 1)),
        ]
        for place_kw, cursor, dirs in specs:
            try:
                g = tk.Frame(self, bg=BG, cursor=cursor, highlightthickness=0, bd=0)
                g.place(**place_kw)
                g.bind("<ButtonPress-1>", lambda _e, d=dirs: self._resize_press(d))
                g.bind("<B1-Motion>", self._resize_drag)
                g.bind("<ButtonRelease-1>", self._resize_release)
                g.lift()
                self._grips.append(g)
            except Exception:
                pass

    def _resize_press(self, dirs):
        self._rs_dirs = dirs
        self._rs_px, self._rs_py = self.winfo_pointerx(), self.winfo_pointery()
        # use the real OS window rect (screen px); Tk's winfo/geometry disagree with
        # it by the thick-frame border under our custom frame, which caused drift.
        r = None
        if _WIN and self._win_hwnd:
            r = wintypes.RECT()
            if not _u32.GetWindowRect(self._win_hwnd, ctypes.byref(r)):
                r = None
        if r is not None:
            self._rs_x, self._rs_y = r.left, r.top
            self._rs_w, self._rs_h = r.right - r.left, r.bottom - r.top
        else:
            self._rs_x, self._rs_y = self.winfo_rootx(), self.winfo_rooty()
            self._rs_w, self._rs_h = self.winfo_width(), self.winfo_height()
        try:
            g = tk.Toplevel(self)
            g.overrideredirect(True)
            g.configure(bg=ACCENT)
            try:
                g.attributes("-alpha", 0.28)
                g.attributes("-topmost", True)
            except Exception:
                pass
            g.geometry(f"{self._rs_w}x{self._rs_h}+{self._rs_x}+{self._rs_y}")
            self._rs_ghost = g
        except Exception:
            self._rs_ghost = None

    def _resize_rect(self):
        ml, mr, mt, mb = self._rs_dirs
        dx = self.winfo_pointerx() - self._rs_px
        dy = self.winfo_pointery() - self._rs_py
        x, y, w, h = self._rs_x, self._rs_y, self._rs_w, self._rs_h
        if ml:
            x, w = self._rs_x + dx, self._rs_w - dx
        if mr:
            w = self._rs_w + dx
        if mt:
            y, h = self._rs_y + dy, self._rs_h - dy
        if mb:
            h = self._rs_h + dy
        minw, minh = 1100, 720
        if w < minw:
            if ml:
                x -= (minw - w)
            w = minw
        if h < minh:
            if mt:
                y -= (minh - h)
            h = minh
        return x, y, w, h

    def _resize_drag(self, _e=None):
        if not self._rs_ghost:
            return
        x, y, w, h = self._resize_rect()
        try:
            self._rs_ghost.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            pass

    def _resize_release(self, _e=None):
        if not self._rs_ghost:
            return
        x, y, w, h = self._resize_rect()
        try:
            self._rs_ghost.destroy()
        except Exception:
            pass
        self._rs_ghost = None
        if _WIN and self._win_hwnd:
            try:
                # set the real OS window rect directly (screen px) -> no Tk frame/
                # scaling mismatch, applied once -> smooth
                _u32.SetWindowPos(self._win_hwnd, 0, x, y, w, h, SWP_NOZORDER | SWP_NOACTIVATE)
                return
            except Exception:
                pass
        try:
            self.wm_geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            pass

    def _is_max(self):
        if _WIN and self._win_hwnd:
            try:
                return bool(_u32.IsZoomed(self._win_hwnd))
            except Exception:
                pass
        try:
            return self.state() == "zoomed"
        except Exception:
            return False

    def _win_min(self):
        # native minimize -> the OS plays its minimize-to-taskbar animation
        try:
            if _WIN and self._win_hwnd:
                _u32.ShowWindow(self._win_hwnd, SW_MINIMIZE)
            else:
                self.iconify()
        except Exception:
            try:
                self.iconify()
            except Exception:
                pass

    def _toggle_max(self, _e=None):
        # native maximize/restore -> the OS plays its zoom animation
        try:
            if _WIN and self._win_hwnd:
                _u32.ShowWindow(self._win_hwnd, SW_RESTORE if self._is_max() else SW_MAXIMIZE)
            else:
                self.state("normal" if self.state() == "zoomed" else "zoomed")
        except Exception:
            pass
        self.after(40, self._sync_max_icon)

    def _sync_max_icon(self, _e=None):
        # "❐" = ❐ restore glyph (shown when maximized);
        # "☐" = ☐ maximize glyph (shown when normal).
        btn = getattr(self, "_btn_max", None)
        if btn is not None:
            try:
                btn.configure(text=("❐" if self._is_max() else "☐"))
            except Exception:
                pass

    def _win_close(self):
        self._on_close()  # reuse existing autosave-then-destroy

    # ---- drag the window by the toolbar empty area ----------------------
    # Native move via PostMessage. PostMessageW is non-blocking, so this Tk
    # callback RETURNS before Windows starts its move-loop -> no Tcl re-entrancy
    # crash (the bug SendMessageW caused), and the OS does a smooth, flicker-free
    # native move (no smearing) WITH drag-to-edge Aero Snap. Dragging a maximized
    # window auto-restores it. Manual geometry move is the non-Windows fallback.
    def _drag_start(self, _e=None):
        self._drag_off = None
        if _WIN and self._win_hwnd:
            try:
                _u32.ReleaseCapture()
                _u32.PostMessageW(self._win_hwnd, WM_NCLBUTTONDOWN, HTCAPTION, 0)
                self.after(20, self._sync_max_icon)
                return
            except Exception:
                pass
        try:  # fallback (non-Windows): manual geometry move
            self._drag_off = (self.winfo_pointerx() - self.winfo_x(),
                              self.winfo_pointery() - self.winfo_y())
        except Exception:
            self._drag_off = None

    def _drag_move(self, _e=None):
        off = getattr(self, "_drag_off", None)
        if not off:
            return
        try:
            self.geometry(f"+{self.winfo_pointerx() - off[0]}+{self.winfo_pointery() - off[1]}")
        except Exception:
            pass

    # ---- add the min / max / close buttons + drag to the toolbar -------
    def _build_window_buttons(self, bar):
        """Three flat themed window buttons at the FAR right of `bar`, in
        visual Windows order (min, max/restore, close). They are packed
        side='right' so they sit RIGHT of the existing action buttons; the
        pack order below makes the visual left->right order min, max, close."""
        def wbtn(txt, cmd, hover, font=("Segoe UI", 13)):
            return ctk.CTkButton(bar, text=txt, width=46, height=32, command=cmd,
                                 fg_color=PANEL, hover_color=hover, text_color=TXT,
                                 corner_radius=0, font=font)
        # close packed FIRST => ends up at the extreme right edge. fill="y" makes
        # them full-height so they sit flush in the corner like real OS controls.
        self._btn_close = wbtn("✕", self._win_close, ACCENT)   # ✕ reddens on hover
        self._btn_close.pack(side="right", padx=0, pady=0, fill="y")
        self._btn_max = wbtn("☐", self._toggle_max, SPOIL_BAR)  # ☐ maximize
        self._btn_max.pack(side="right", padx=0, pady=0, fill="y")
        self._btn_min = wbtn("—", self._win_min, SPOIL_BAR)     # — minimize
        self._btn_min.pack(side="right", padx=0, pady=0, fill="y")
        Tooltip(self._btn_min, "Minimize")
        Tooltip(self._btn_max, "Maximize / Restore")
        Tooltip(self._btn_close, "Close")

    def _bind_titlebar_drag(self, *widgets):
        for w in widgets:
            w.bind("<ButtonPress-1>", self._drag_start, add="+")
            w.bind("<B1-Motion>", self._drag_move, add="+")
            w.bind("<Double-Button-1>", self._toggle_max, add="+")

    # ---- top toolbar ----------------------------------------------------
    def _build_toolbar(self):
        bar = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=0)
        bar.pack(fill="x", side="top")
        self.titlebar = bar
        lbl_f95 = ctk.CTkLabel(bar, text="F95", font=("Segoe UI Black", 18), text_color=LOGO_RED)
        lbl_f95.pack(side="left", padx=(16, 2), pady=8)
        lbl_name = ctk.CTkLabel(bar, text="Post Generator", font=("Segoe UI Semibold", 15), text_color=TXT)
        lbl_name.pack(side="left", pady=8)
        self.autosave_lbl = ctk.CTkLabel(bar, text="", font=("Segoe UI", 11), text_color=MUTED)
        self.autosave_lbl.pack(side="left", padx=12)

        def tb(txt, cmd, accent=False, width=92, tip=""):
            b = ctk.CTkButton(bar, text=txt, width=width, height=32, command=cmd,
                              fg_color=ACCENT if accent else CARD, hover_color=ACCENT_HOVER if accent else SPOIL_BAR,
                              text_color="#ffffff" if accent else TXT, font=("Segoe UI", 13))
            if tip:
                Tooltip(b, tip)
            return b

        # Window controls FIRST so they claim the far-right corner; the action
        # buttons then stack to their left.
        if _WIN:
            self._build_window_buttons(bar)

        tb("⧉ Copy BBCode", self.copy_bbcode, accent=True, width=130, tip="Copy the generated BBCode to clipboard").pack(side="right", padx=(4, 16), pady=10)
        tb("⧉ Title", self.copy_title, width=72, tip="Copy the thread title line for F95's title box").pack(side="right", padx=4, pady=10)
        tb("Save As", self.save_as, tip="Save as a new named profile").pack(side="right", padx=4, pady=10)
        tb("Save", self.save, tip="Save the current profile").pack(side="right", padx=4, pady=10)
        tb("Load", self.load_selected, tip="Load the selected profile").pack(side="right", padx=4, pady=10)
        self.profile_menu = ctk.CTkOptionMenu(bar, values=["(no profiles)"], width=180, fg_color=CARD,
                                              button_color=SPOIL_BAR, button_hover_color=ACCENT, text_color=TXT)
        self.profile_menu.pack(side="right", padx=4, pady=10)
        tb("New", self.new_post, tip="Start a blank post (dates default to today)").pack(side="right", padx=4, pady=10)
        tb("Clear", self.clear_all, tip="Clear every field and start fresh").pack(side="right", padx=4, pady=10)

        # Make the empty toolbar area + passive labels drag the window (Windows
        # only; the buttons themselves fall back gracefully if win32 fails).
        if _WIN:
            self._bind_titlebar_drag(bar, lbl_f95, lbl_name, self.autosave_lbl)

    # ---- formatting toolbar (F95 button set) ---------------------------
    def _build_formatbar(self):
        fb = ctk.CTkFrame(self, fg_color="#1d1e22", corner_radius=0)
        fb.pack(fill="x", side="top")
        self.formatbar = fb
        ctk.CTkLabel(fb, text="Format:", text_color=MUTED, font=("Segoe UI", 12)).pack(side="left", padx=(16, 4), pady=6)

        spec = [
            ("⌫", "Remove formatting", self._clear_format, None, 30),
            "sep",
            ("B", "Bold", lambda: self._wrap("[B]", "[/B]"), ("Segoe UI", 13, "bold"), 30),
            ("I", "Italic", lambda: self._wrap("[I]", "[/I]"), ("Segoe UI", 13, "italic"), 30),
            ("U", "Underline", lambda: self._wrap("[U]", "[/U]"), ("Segoe UI", 13, "underline"), 30),
            ("S", "Strike-through", lambda: self._wrap("[S]", "[/S]"), ("Segoe UI", 13, "overstrike"), 30),
            "sep",
            ("🎨", "Text color", self._color_menu, None, 34),
            ("Aa", "Font family", self._font_menu, None, 38),
            ("A↕", "Font size", self._size_menu, None, 38),
            "sep",
            ("🔗", "Insert link", self._link, None, 34),
            ("🖼", "Insert image (URL or file)", self._insert_image, None, 34),
            ("🙂", "Smilies", self._smilie_menu, None, 34),
            ("▤", "Spoiler", lambda: self._wrap("[SPOILER]\n", "\n[/SPOILER]"), None, 34),
            ("⊕", "Insert (media / quote / code …)", self._insert_menu, None, 34),
            "sep",
            ("≡", "Alignment", self._align_menu, None, 34),
            ("☰", "List", self._list_menu, None, 34),
            ("▦", "Insert table", self._table, None, 34),
            "sep",
            ("↶", "Undo", self._undo, None, 30),
            ("↷", "Redo", self._redo, None, 30),
            "sep",
            ("</>", "Toggle BB code (show raw)", self._show_bbcode, None, 38),
        ]
        for item in spec:
            if item == "sep":
                tk.Frame(fb, width=1, bg=SPOIL_BAR).pack(side="left", fill="y", padx=4, pady=8)
                continue
            icon, tip, cmd, font, w = item
            b = ctk.CTkButton(fb, text=icon, width=w, height=28, command=cmd, fg_color=CARD,
                              hover_color=SPOIL_BAR, text_color=TXT, font=font or ("Segoe UI", 13))
            b.pack(side="left", padx=2, pady=6)
            Tooltip(b, tip)
        ctk.CTkLabel(fb, text="select text in a field, then click", text_color=MUTED,
                     font=("Segoe UI", 11)).pack(side="left", padx=10)

    # ---- body -----------------------------------------------------------
    def _build_body(self):
        body = ctk.CTkFrame(self, fg_color=BG)
        body.pack(fill="both", expand=True, padx=10, pady=10)
        body.grid_columnconfigure(0, weight=0, minsize=580)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        form = ctk.CTkScrollableFrame(body, fg_color=PANEL, label_text="")
        form.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.form_frame = form
        self._build_form(form)
        self._smooth_scrollable(form)

        right = ctk.CTkTabview(body, fg_color=PANEL, segmented_button_selected_color=ACCENT,
                               segmented_button_selected_hover_color=ACCENT_HOVER)
        right.grid(row=0, column=1, sticky="nsew")
        right.add("Preview")
        right.add("BBCode")
        self.tabview = right

        pv = right.tab("Preview")
        pv.grid_rowconfigure(1, weight=1)
        pv.grid_columnconfigure(0, weight=1)
        ctrl = ctk.CTkFrame(pv, fg_color="transparent")
        ctrl.grid(row=0, column=0, columnspan=2, sticky="w")
        ctk.CTkButton(ctrl, text="Expand all", width=80, height=24, fg_color=CARD, hover_color=SPOIL_BAR,
                      text_color=TXT, command=lambda: self._spoilers(True)).pack(side="left", padx=2, pady=4)
        ctk.CTkButton(ctrl, text="Collapse all", width=84, height=24, fg_color=CARD, hover_color=SPOIL_BAR,
                      text_color=TXT, command=lambda: self._spoilers(False)).pack(side="left", padx=2, pady=4)
        if not HAS_PIL:
            ctk.CTkLabel(ctrl, text="install Pillow for image previews:  pip install pillow",
                         text_color="#ffb454", font=("Segoe UI", 11)).pack(side="left", padx=10)
        self.preview = tk.Text(pv, wrap="word", bg=PREVIEW_BG, fg=TXT, bd=0, padx=18, pady=14,
                               insertbackground=TXT, selectbackground=ACCENT, spacing2=2, cursor="")
        self.preview.grid(row=1, column=0, sticky="nsew")
        sb = ctk.CTkScrollbar(pv, command=self._preview_scroll)
        sb.grid(row=1, column=1, sticky="ns")
        self.preview.configure(yscrollcommand=sb.set, state="disabled")
        self.renderer = PreviewRenderer(self.preview, image_loader=self._preview_image)

        bb = right.tab("BBCode")
        bb.grid_rowconfigure(0, weight=1)
        bb.grid_columnconfigure(0, weight=1)
        self.bbcode_box = ctk.CTkTextbox(bb, fg_color=PREVIEW_BG, text_color=TXT, font=("Consolas", 12), wrap="word")
        self.bbcode_box.grid(row=0, column=0, sticky="nsew")
        ctk.CTkLabel(bb, text="✎ Editable — the Format buttons above work here too. Editing this updates the "
                             "preview live; changing a form field regenerates it, so tweak BBCode last.",
                     text_color=MUTED, font=("Segoe UI", 11), anchor="w", wraplength=620, justify="left"
                     ).grid(row=1, column=0, sticky="w", padx=4, pady=(2, 0))
        self._bb_inner = getattr(self.bbcode_box, "_textbox", self.bbcode_box)
        try:
            self._bb_inner.configure(undo=True, autoseparators=True, maxundo=-1)
        except tk.TclError:
            pass
        self._bb_inner.bind("<FocusIn>", lambda e: setattr(self, "active_text", self._bb_inner))
        self._bb_inner.bind("<KeyRelease>", self._on_bbcode_edit)
        self._bb_inner.bind("<<Paste>>", self._on_paste)
        self._bb_inner.bind("<Left>", self._sel_left)
        self._bb_inner.bind("<Right>", self._sel_right)

    # ---- smooth scrolling (reduce CTk fast-scroll artifacts) -----------
    def _preview_scroll(self, *args):
        self.preview.yview(*args)
        try:
            self.preview.update_idletasks()
        except Exception:
            pass

    def _force_repaint(self, widget=None):
        """Repaint scrolled child widgets immediately so fast scrolling can't
        leave smear/artifacts. Tk widgets are real child HWNDs, so we ask Windows
        to redraw them (RDW_ALLCHILDREN) rather than relying on lazy repaint."""
        try:
            self.update_idletasks()
        except Exception:
            pass
        if not _WIN:
            return
        try:
            hwnd = widget.winfo_id() if widget is not None else self._win_hwnd
            if hwnd:
                _u32.RedrawWindow(hwnd, None, None,
                                  RDW_INVALIDATE | RDW_UPDATENOW | RDW_ALLCHILDREN)
        except Exception:
            pass

    def _smooth_scrollable(self, sf):
        """Force a clean repaint after each scroll step (scrollbar drag AND mouse
        wheel) so customtkinter's CTkScrollableFrame doesn't smear on fast scroll."""
        try:
            cv = sf._parent_canvas
            sb = sf._scrollbar

            def _cmd(*args):
                cv.yview(*args)
                self._force_repaint(cv)

            sb.configure(command=_cmd)
        except Exception:
            pass
        # mouse wheel scrolls via _mouse_wheel_all, bypassing the scrollbar command
        try:
            _orig = sf._mouse_wheel_all
            _cv = sf._parent_canvas

            def _wheel(event, _o=_orig, _c=_cv):
                r = _o(event)
                self._force_repaint(_c)
                return r

            sf._mouse_wheel_all = _wheel
        except Exception:
            pass

    def _chip_wheel(self, event):
        # scroll ONLY the tag list when the pointer is over it; "break" stops the
        # event from also scrolling the outer form
        try:
            cv = self.chip_wrap._parent_canvas
            cv.yview_scroll(int(-event.delta / 120), "units")
            self._force_repaint(cv)
        except Exception:
            pass
        return "break"

    # ---- Notepad-style shortcuts ---------------------------------------
    def _setup_shortcuts(self):
        # Ctrl+A = select all (Tk's default is "move to start of line")
        for seq in ("<Control-a>", "<Control-A>"):
            try:
                self.bind_class("Text", seq, self._text_select_all)
                self.bind_class("Entry", seq, self._entry_select_all)
            except Exception:
                pass

    def _text_select_all(self, event):
        w = event.widget
        try:
            w.tag_remove("sel", "1.0", "end")
            w.tag_add("sel", "1.0", "end-1c")
            w.mark_set("insert", "1.0")   # so a Left press lands at the top-left
            w.see("1.0")
        except Exception:
            pass
        return "break"

    def _entry_select_all(self, event):
        w = event.widget
        try:
            w.select_range(0, "end")
            w.icursor("end")
        except Exception:
            pass
        return "break"

    def _sel_left(self, event):
        # Notepad behaviour: Left collapses a selection to its START (top-left)
        w = event.widget
        if w.tag_ranges("sel"):
            try:
                w.mark_set("insert", "sel.first")
                w.tag_remove("sel", "1.0", "end")
                w.see("insert")
            except Exception:
                pass
            return "break"
        return None

    def _sel_right(self, event):
        # Notepad behaviour: Right collapses a selection to its END (bottom-right)
        w = event.widget
        if w.tag_ranges("sel"):
            try:
                w.mark_set("insert", "sel.last")
                w.tag_remove("sel", "1.0", "end")
                w.see("insert")
            except Exception:
                pass
            return "break"
        return None

    # ---- form helpers ---------------------------------------------------
    def _section(self, parent, title):
        ctk.CTkLabel(parent, text=title.upper(), font=("Segoe UI Semibold", 12), text_color=ACCENT,
                     anchor="w").pack(fill="x", padx=4, pady=(14, 2))
        ctk.CTkFrame(parent, height=2, fg_color=CARD).pack(fill="x", padx=4, pady=(0, 6))

    def _entry(self, parent, name, label, default="", placeholder=""):
        ctk.CTkLabel(parent, text=label, font=("Segoe UI", 12), text_color=MUTED, anchor="w").pack(fill="x", padx=4)
        var = tk.StringVar(value=default)
        var.trace_add("write", lambda *_: self.schedule())
        self.vars[name] = var
        ctk.CTkEntry(parent, textvariable=var, placeholder_text=placeholder, height=30,
                     fg_color=ENTRY_BG, border_width=0).pack(fill="x", padx=4, pady=(0, 6))

    def _row2(self, parent, specs):
        wrap = ctk.CTkFrame(parent, fg_color="transparent")
        wrap.pack(fill="x")
        for i, (name, label, default, ph) in enumerate(specs):
            col = ctk.CTkFrame(wrap, fg_color="transparent")
            col.pack(side="left", fill="x", expand=True, padx=(0 if i == 0 else 6, 0))
            self._entry(col, name, label, default, ph)

    def _image_field(self, parent, name, label, placeholder=""):
        ctk.CTkLabel(parent, text=label, font=("Segoe UI", 12), text_color=MUTED, anchor="w").pack(fill="x", padx=4)
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=4, pady=(0, 6))
        var = tk.StringVar()
        var.trace_add("write", lambda *_: self.schedule())
        self.vars[name] = var
        e = ctk.CTkEntry(row, textvariable=var, placeholder_text=placeholder, height=30,
                         fg_color=ENTRY_BG, border_width=0)
        e.pack(side="left", fill="x", expand=True, padx=(0, 4))
        e.bind("<<Paste>>", lambda ev, v=var: self._on_paste_to_var(v))  # Ctrl+V an image
        b = ctk.CTkButton(row, text="📁", width=34, height=30, fg_color=CARD, hover_color=SPOIL_BAR,
                          text_color=TXT, command=lambda v=var: self._browse_image(v))
        b.pack(side="left")
        Tooltip(b, "Pick an image from your PC")

    def _browse_image(self, var):
        path = filedialog.askopenfilename(title="Select image", filetypes=IMG_TYPES)
        if path:
            var.set(path)
            self.schedule()

    def _textarea(self, parent, name, label, height=90, default=""):
        if label:
            ctk.CTkLabel(parent, text=label, font=("Segoe UI", 12), text_color=MUTED, anchor="w").pack(fill="x", padx=4)
        box = ctk.CTkTextbox(parent, height=height, fg_color=ENTRY_BG, text_color=TXT, border_width=0, wrap="word")
        box.pack(fill="x", padx=4, pady=(0, 6))
        if default:
            box.insert("1.0", default)
        box.bind("<KeyRelease>", lambda e: self.schedule())
        inner = getattr(box, "_textbox", box)
        try:
            inner.configure(undo=True, autoseparators=True, maxundo=-1)
        except tk.TclError:
            pass
        inner.bind("<FocusIn>", lambda e, t=inner: setattr(self, "active_text", t))
        inner.bind("<<Paste>>", self._on_paste)
        inner.bind("<Left>", self._sel_left)
        inner.bind("<Right>", self._sel_right)
        self.texts[name] = box

    def _option(self, parent, name, label, values, default):
        ctk.CTkLabel(parent, text=label, font=("Segoe UI", 12), text_color=MUTED, anchor="w").pack(fill="x", padx=4)
        var = tk.StringVar(value=default)
        var.trace_add("write", lambda *_: self.schedule())
        self.vars[name] = var
        ctk.CTkOptionMenu(parent, variable=var, values=values, fg_color=ENTRY_BG, button_color=SPOIL_BAR,
                          button_hover_color=ACCENT, text_color=TXT).pack(fill="x", padx=4, pady=(0, 6))

    def _links_rep(self, parent, attr, label, label_ph="Label (e.g. Website)"):
        ctk.CTkLabel(parent, text=label, font=("Segoe UI", 11), text_color=MUTED, anchor="w").pack(fill="x", padx=4)
        rep = Repeater(parent, [("label", label_ph, 1), ("url", "URL (https://...)", 2)], self.schedule, add_text="+ link")
        rep.pack(fill="x", padx=4, pady=(0, 4))
        setattr(self, attr, rep)

    # ---- form -----------------------------------------------------------
    def _build_form(self, f):
        today = _today()

        self._section(f, "Header")
        self._entry(f, "title", "Game name", "", "Sumire's Secret")
        self._image_field(f, "banner_src", "Cover / banner — attachment ID, URL, or 📁 file", "6109121  •  https://…/cover.jpg")
        self._entry(f, "banner_alt", "Cover alt (optional)", "", "Cover.jpg")

        self._section(f, "Overview")
        self._textarea(f, "overview_short", "Overview (shown)", 80)
        self._textarea(f, "overview_spoiler", "Overview details / story (in spoiler, optional)", 110)

        self._section(f, "Details")
        self._row2(f, [("thread_updated", "Thread Updated", today, today),
                       ("release_date", "Release Date", today, today)])
        ctk.CTkButton(f, text="Set both dates to today", height=24, width=170, fg_color=CARD,
                      hover_color=SPOIL_BAR, text_color=TXT, command=self._dates_today).pack(anchor="w", padx=4, pady=(0, 4))
        self._entry(f, "original_title", "Original Title (JP, optional)", "", "彼には言えない…")
        self._entry(f, "aliases", "Aliases (optional)", "", "Romaji / English alias")

        self._entry(f, "developer", "Developer", "", "Studio name")
        self._links_rep(f, "dev_links", "Developer links (DLSite, Website, ci-en…)")
        self._entry(f, "publisher", "Publisher (optional)", "", "Kagura Games")
        self._links_rep(f, "pub_links", "Publisher links (Website, Twitter, Discord…)")
        self._entry(f, "translator", "Translator (optional)", "", "DazedAnon / Sinflower")
        self._links_rep(f, "tl_links", "Translator links (Discord, Gumroad…)")

        self._row2(f, [("version", "Version", "", "1.0"), ("os", "OS", "Windows", "Windows")])
        self._option(f, "censored", "Censored", ["Yes", "No", "Yes (Mosaics)", "Partial"], "No")
        self._entry(f, "language", "Language", "English", "English, Japanese, Chinese")
        self._entry(f, "language_note", "Language note (optional, BBCode ok)", "", "[URL='...']Sonnet 4.6[/URL]")
        self._row2(f, [("voice", "Voice (optional)", "", "Japanese"),
                       ("length", "Length (optional)", "", "~2h")])
        self._entry(f, "vndb_url", "VNDB URL (optional)", "", "https://vndb.org/v19652")
        ctk.CTkLabel(f, text="Store links (Steam, DLsite, DMM…)", font=("Segoe UI", 11),
                     text_color=MUTED, anchor="w").pack(fill="x", padx=4)
        self.store_links_rep = Repeater(f, [("label", "Name (e.g. Steam)", 1), ("url", "URL (https://...)", 2)],
                                        self.schedule, add_text="+ store")
        self.store_links_rep.pack(fill="x", padx=4, pady=(0, 4))
        self._entry(f, "other_games_url", "Other Games URL (optional)", "", "https://f95zone.to/sam/...")

        self._section(f, "Genre / Tags")
        self._build_tags(f)

        self._section(f, "Installation  (one step per line)")
        self._textarea(f, "installation", "", 70, default="1. Extract and run.")
        self._section(f, "Developer Notes  (optional, BBCode ok)")
        self._textarea(f, "developer_notes", "", 80)
        self._section(f, "Translator Notes  (optional)")
        self._textarea(f, "translator_notes", "", 70)
        self._section(f, "Required / Patch note  (optional, centered, BBCode ok)")
        self._textarea(f, "required_note", "", 60)

        self._section(f, "Downloads")
        self._entry(f, "download_os_label", "Download label", "Win", "Win (v1.0)")
        self.dl_rep = Repeater(f, [("host", "HOST (e.g. PIXELDRAIN)", 1), ("url", "URL (https://...)", 2)], self.schedule)
        self.dl_rep.pack(fill="x", padx=4, pady=(0, 4))
        self._section(f, "Extras  (optional)")
        self.ex_rep = Repeater(f, [("label", "Label (e.g. Patch only)", 1), ("url", "URL (https://...)", 2)], self.schedule)
        self.ex_rep.pack(fill="x", padx=4, pady=(0, 4))
        self._section(f, "Screenshots  (attachment ID, URL, or 📁 file)")
        self._option(f, "ss_size", "Show as  (F95 attachments only)", ["Thumbnail", "Full image"], "Thumbnail")
        self.ss_rep = Repeater(f, [("src", "ID / URL / file path", 2, "file"), ("alt", "Alt (optional)", 1)],
                               self.schedule, paste_image=self._clipboard_image_path)
        self.ss_rep.pack(fill="x", padx=4, pady=(0, 10))

    def _dates_today(self):
        today = _today()
        self.vars["thread_updated"].set(today)
        self.vars["release_date"].set(today)

    # ---- tags -----------------------------------------------------------
    def _build_tags(self, parent):
        bar = ctk.CTkFrame(parent, fg_color="transparent")
        bar.pack(fill="x", padx=4)
        self.tag_filter = tk.StringVar()
        self.tag_filter.trace_add("write", lambda *_: self._render_chips())
        ctk.CTkEntry(bar, textvariable=self.tag_filter, placeholder_text="filter / new tag…", height=28,
                     fg_color=ENTRY_BG, border_width=0).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ctk.CTkButton(bar, text="+ Add", width=64, height=28, fg_color=CARD, hover_color=SPOIL_BAR,
                      text_color=TXT, command=self._add_tag).pack(side="left", padx=2)
        ctk.CTkButton(bar, text="Clear", width=56, height=28, fg_color=CARD, hover_color=SPOIL_BAR,
                      text_color=TXT, command=self._clear_tags).pack(side="left", padx=2)
        self.tag_count = ctk.CTkLabel(parent, text="", font=("Segoe UI", 11), text_color=MUTED, anchor="w")
        self.tag_count.pack(fill="x", padx=4)
        self.chip_wrap = ctk.CTkScrollableFrame(parent, fg_color=ENTRY_BG, height=190)
        self.chip_wrap.pack(fill="x", padx=4, pady=(2, 6))
        self._smooth_scrollable(self.chip_wrap)
        self.chip_wrap.bind("<MouseWheel>", self._chip_wheel, add="+")
        try:
            self.chip_wrap._parent_canvas.bind("<MouseWheel>", self._chip_wheel, add="+")
        except Exception:
            pass
        for c in range(3):
            self.chip_wrap.grid_columnconfigure(c, weight=1, uniform="tag")
        self._render_chips()

    def _render_chips(self):
        for w in self.chip_wrap.winfo_children():
            w.destroy()
        self.chip_btns = {}
        flt = (self.tag_filter.get() if hasattr(self, "tag_filter") else "").strip().lower()
        shown = [t for t in self.all_tags if flt in t.lower()] if flt else list(self.all_tags)
        for i, tag in enumerate(shown):
            sel = tag in self.selected_tags
            b = ctk.CTkButton(self.chip_wrap, text=tag, height=26,
                              fg_color=ACCENT if sel else CARD, hover_color=ACCENT_HOVER if sel else SPOIL_BAR,
                              text_color="#ffffff" if sel else TXT, font=("Segoe UI", 11),
                              command=lambda t=tag: self._toggle_tag(t))
            b.grid(row=i // 3, column=i % 3, sticky="ew", padx=3, pady=3)
            b.bind("<Button-3>", lambda e, t=tag: self._chip_menu(t))
            b.bind("<MouseWheel>", self._chip_wheel, add="+")  # wheel scrolls tags only
            self.chip_btns[tag] = b
        self._update_tag_count()

    def _update_tag_count(self):
        if hasattr(self, "tag_count"):
            self.tag_count.configure(text=f"{len(self.selected_tags)} selected  ·  right-click a tag to rename / delete")

    def _toggle_tag(self, tag):
        if tag in self.selected_tags:
            self.selected_tags.remove(tag)
        else:
            self.selected_tags.append(tag)
        b = self.chip_btns.get(tag)
        if b:
            sel = tag in self.selected_tags
            b.configure(fg_color=ACCENT if sel else CARD, hover_color=ACCENT_HOVER if sel else SPOIL_BAR,
                        text_color="#ffffff" if sel else TXT)
        self._update_tag_count()
        self.schedule()

    def _add_tag(self):
        name = (self.tag_filter.get() or "").strip()
        if not name:
            return
        if name not in self.all_tags:
            self.all_tags.append(name)
            self._save_tags()
        if name not in self.selected_tags:
            self.selected_tags.append(name)
        self.tag_filter.set("")
        self._render_chips()
        self.schedule()

    def _clear_tags(self):
        self.selected_tags = []
        self._render_chips()
        self.schedule()

    def _chip_menu(self, tag):
        menu = tk.Menu(self, tearoff=0, bg=CARD, fg=TXT, activebackground=ACCENT, activeforeground="#fff", bd=0)
        menu.add_command(label=f"Rename “{tag}”…", command=lambda: self._rename_tag(tag))
        menu.add_command(label=f"Delete “{tag}” from list", command=lambda: self._delete_tag(tag))
        try:
            menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())
        finally:
            menu.grab_release()

    def _rename_tag(self, tag):
        res = PromptDialog.ask(self, "Rename tag", [("New name", "", tag)])
        new = (res[0].strip() if res else "")
        if not new or new == tag:
            return
        self.all_tags = [new if t == tag else t for t in self.all_tags]
        self.selected_tags = [new if t == tag else t for t in self.selected_tags]
        self._save_tags()
        self._render_chips()
        self.schedule()

    def _delete_tag(self, tag):
        self.all_tags = [t for t in self.all_tags if t != tag]
        self.selected_tags = [t for t in self.selected_tags if t != tag]
        self._save_tags()
        self._render_chips()
        self.schedule()

    def _load_tags(self):
        try:
            if os.path.exists(TAGS_PATH):
                data = json.load(open(TAGS_PATH, encoding="utf-8"))
                if isinstance(data, list) and data:
                    return [str(t) for t in data]
        except Exception:
            pass
        return list(DEFAULT_TAGS)

    def _save_tags(self):
        try:
            json.dump(self.all_tags, open(TAGS_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _genre_text(self):
        # alphabetical (case-insensitive), matching F95 genre-line convention
        return ", ".join(sorted(self.selected_tags, key=str.lower))

    # ---- image preview loader ------------------------------------------
    def _preview_image(self, src):
        if not HAS_PIL:
            return None
        src = (src or "").strip()
        if not src:
            return None
        is_url = src.startswith(("http://", "https://"))
        is_file = (not is_url) and os.path.isfile(src)
        if not (is_url or is_file):
            return None
        cached = self._img_cache.get(src)
        if isinstance(cached, str):  # "loading" / "error"
            return None
        if cached is not None:
            return cached
        if is_file:
            try:
                im = self._thumb(Image.open(src))
                photo = ImageTk.PhotoImage(im)
                self._img_cache[src] = photo
                return photo
            except Exception:
                self._img_cache[src] = "error"
                return None
        self._img_cache[src] = "loading"
        threading.Thread(target=self._fetch_image, args=(src,), daemon=True).start()
        return None

    def _fetch_image(self, url):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            data = urllib.request.urlopen(req, timeout=12).read()
            im = self._thumb(Image.open(io.BytesIO(data)))
            im.load()
            self.after(0, lambda: self._finalize_image(url, im))
        except Exception:
            self.after(0, lambda: self._img_cache.__setitem__(url, "error"))

    def _finalize_image(self, url, im):
        try:
            self._img_cache[url] = ImageTk.PhotoImage(im)
            self.update_output()
        except Exception:
            self._img_cache[url] = "error"

    def _thumb(self, im):
        im = im.convert("RGBA")
        im.thumbnail((380, 300))
        return im

    # ---- formatting toolbar actions ------------------------------------
    def _wrap(self, open_t, close_t, inner_default=""):
        t = self.active_text
        if t is None:
            return self._toast("Click inside a text box first")
        try:
            if t.tag_ranges("sel"):
                sel = t.get("sel.first", "sel.last")
                t.delete("sel.first", "sel.last")
                t.insert("insert", open_t + sel + close_t)
            else:
                t.insert("insert", open_t + inner_default + close_t)
        except tk.TclError:
            t.insert("insert", open_t + inner_default + close_t)
        t.focus_set()
        self._after_edit(t)

    def _clear_format(self):
        t = self.active_text
        if t is None:
            return self._toast("Click inside a text box first")
        try:
            if t.tag_ranges("sel"):
                sel = t.get("sel.first", "sel.last")
                t.delete("sel.first", "sel.last")
                t.insert("insert", BBCODE_STRIP_RE.sub("", sel))
                t.focus_set()
                self._after_edit(t)
        except tk.TclError:
            pass

    def _popup(self, items):
        menu = tk.Menu(self, tearoff=0, bg=CARD, fg=TXT, activebackground=ACCENT, activeforeground="#fff", bd=0)
        for label, cmd in items:
            if label == "-":
                menu.add_separator()
            else:
                menu.add_command(label=label, command=cmd)
        try:
            menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())
        finally:
            menu.grab_release()

    def _color_menu(self):
        self._popup([(n, (lambda c=code: self._wrap(f"[COLOR={c}]", "[/COLOR]"))) for n, code in COLOR_CHOICES])

    def _font_menu(self):
        self._popup([(fn, (lambda x=fn: self._wrap(f"[FONT={x}]", "[/FONT]"))) for fn in FONT_CHOICES])

    def _size_menu(self):
        self._popup([(f"Size {n}", (lambda s=n: self._wrap(f"[SIZE={s}]", "[/SIZE]"))) for n in range(1, 8)])

    def _smilie_menu(self):
        self._popup([(f"{code}   {name}", (lambda c=code: self._wrap(c + " ", ""))) for code, name in SMILIES])

    def _insert_image(self):
        self._popup([
            ("Paste from clipboard (Ctrl+V)", self._image_from_clipboard),
            ("From URL…", self._image_from_url),
            ("From file… (📁)", self._image_from_file),
        ])

    def _image_from_url(self):
        res = PromptDialog.ask(self, "Insert image", [("Image URL", "https://.../image.png", "")])
        url = (res[0].strip() if res else "")
        if url:
            self._wrap(f"[IMG]{url}", "[/IMG]")

    def _clipboard_image_path(self):
        """Return a local path for an image on the clipboard (saving a pasted
        bitmap into pasted_images/), or None if the clipboard holds no image."""
        if not HAS_PIL:
            return None
        try:
            data = ImageGrab.grabclipboard()
        except Exception:
            return None
        if data is None:
            return None
        if isinstance(data, list):  # files copied in Explorer
            for p in data:
                if isinstance(p, str) and os.path.isfile(p) and p.lower().endswith(
                        (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".avif")):
                    return p
            return None
        try:  # a raw bitmap (screenshot / "copy image")
            if isinstance(data, Image.Image):
                os.makedirs(PASTED_DIR, exist_ok=True)
                fn = "paste_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".png"
                path = os.path.join(PASTED_DIR, fn)
                data.convert("RGBA").save(path)
                return path
        except Exception:
            pass
        return None

    def _image_from_clipboard(self):
        path = self._clipboard_image_path()
        if not path:
            return self._toast("No image on the clipboard")
        if self.active_text is not None:
            self._wrap(f"[IMG]{path}", "[/IMG]")
        else:
            self.ss_rep.add_row({"src": path, "alt": os.path.basename(path)})
            self.schedule()
            self._toast("Pasted image added to Screenshots")

    def _on_paste(self, event):
        # if the clipboard holds an image, insert it as [IMG]; otherwise let the
        # normal text paste proceed (return None)
        path = self._clipboard_image_path()
        if not path:
            return
        w = event.widget
        try:
            w.insert("insert", f"[IMG]{path}[/IMG]")
        except Exception:
            return
        if w is getattr(self, "_bb_inner", None):
            self._render_from_box()
        else:
            self.schedule()
        return "break"

    def _on_paste_to_var(self, var):
        # paste a clipboard image into a single-value image field (cover / src);
        # if there's no image, fall through to the normal text paste
        path = self._clipboard_image_path()
        if not path:
            return
        var.set(path)
        self.schedule()
        return "break"

    def _image_from_file(self):
        path = filedialog.askopenfilename(title="Select image", filetypes=IMG_TYPES)
        if path:
            self._wrap(f"[IMG]{path}", "[/IMG]")

    def _insert_menu(self):
        self._popup([
            ("Media (embed)", lambda: self._wrap("[MEDIA=youtube]", "[/MEDIA]")),
            ("Quote", lambda: self._wrap("[QUOTE]\n", "\n[/QUOTE]")),
            ("Spoiler (titled)", lambda: self._wrap("[SPOILER=Title]\n", "\n[/SPOILER]")),
            ("Inline spoiler", lambda: self._wrap("[ISPOILER]", "[/ISPOILER]")),
            ("-", None),
            ("Code", lambda: self._wrap("[CODE]\n", "\n[/CODE]")),
            ("Inline code", lambda: self._wrap("[ICODE]", "[/ICODE]")),
        ])

    def _align_menu(self):
        self._popup([
            ("Align left", lambda: self._wrap("[LEFT]\n", "\n[/LEFT]")),
            ("Align center", lambda: self._wrap("[CENTER]\n", "\n[/CENTER]")),
            ("Align right", lambda: self._wrap("[RIGHT]\n", "\n[/RIGHT]")),
        ])

    def _list_menu(self):
        self._popup([
            ("Bulleted list", lambda: self._wrap("[LIST]\n[*]", "\n[/LIST]")),
            ("Numbered list", lambda: self._wrap("[LIST=1]\n[*]", "\n[/LIST]")),
        ])

    def _table(self):
        self._wrap("[TABLE]\n[TR]\n[TD]", "[/TD]\n[TD][/TD]\n[/TR]\n[/TABLE]")

    def _link(self):
        res = PromptDialog.ask(self, "Insert link",
                               [("Display name", "e.g. PIXELDRAIN  (or leave blank)", ""),
                                ("Link URL", "https://...", "")])
        if not res:
            return
        name, url = res[0].strip(), res[1].strip()
        if not url:
            return self._toast("A URL is required for a link")
        self._wrap(f"[URL='{url}']", "[/URL]", inner_default=name or "link")

    def _undo(self):
        if self.active_text:
            try:
                self.active_text.edit_undo()
                self._after_edit(self.active_text)
            except tk.TclError:
                pass

    def _redo(self):
        if self.active_text:
            try:
                self.active_text.edit_redo()
                self._after_edit(self.active_text)
            except tk.TclError:
                pass

    def _show_bbcode(self):
        try:
            self.tabview.set("BBCode")
        except Exception:
            pass

    def _spoilers(self, expand):
        for k in list(self.renderer.open_state.keys()):
            self.renderer.open_state[k] = expand
        if self.active_text is getattr(self, "_bb_inner", None):
            self._render_from_box()
        else:
            self.update_output()

    # ---- BBCode editor (live, toolbar-aware) ---------------------------
    def _after_edit(self, t):
        """Route a toolbar edit: form fields regenerate from the form; the
        BBCode box re-renders the preview directly (so manual edits survive)."""
        if t is getattr(self, "_bb_inner", None):
            self._render_from_box()
        else:
            self.schedule()

    def _on_bbcode_edit(self, _e=None):
        self._render_from_box()

    def _render_from_box(self):
        try:
            self.renderer.render(self.bbcode_box.get("1.0", "end-1c"))
        except Exception:
            pass

    # ---- data <-> widgets ----------------------------------------------
    def collect(self):
        d = {k: v.get() for k, v in self.vars.items()}
        for k, box in self.texts.items():
            d[k] = box.get("1.0", "end-1c")
        d["genre"] = self._genre_text()
        d["tags_selected"] = list(self.selected_tags)
        d["developer_links"] = self.dev_links.get()
        d["publisher_links"] = self.pub_links.get()
        d["translator_links"] = self.tl_links.get()
        d["store_links"] = self.store_links_rep.get()
        d["downloads"] = self.dl_rep.get()
        d["extras"] = self.ex_rep.get()
        d["screenshots"] = self.ss_rep.get()
        return d

    def apply(self, d):
        today = _today()
        defaults = {"os": "Windows", "language": "English", "censored": "No",
                    "download_os_label": "Win", "thread_updated": today, "release_date": today,
                    "ss_size": "Thumbnail"}
        for k, var in self.vars.items():
            var.set(d.get(k, defaults.get(k, "")))
        for k, box in self.texts.items():
            box.delete("1.0", "end")
            box.insert("1.0", d.get(k, ""))
        # tags: explicit list, else parse a legacy genre string
        tags = d.get("tags_selected")
        if tags is None and (d.get("genre") or "").strip():
            tags = [t.strip() for t in re.split(r"[,\n]", d["genre"]) if t.strip()]
        tags = tags or []
        for t in tags:
            if t not in self.all_tags:
                self.all_tags.append(t)
        self.selected_tags = list(tags)
        self._render_chips()
        self.dev_links.set(d.get("developer_links", []))
        self.pub_links.set(d.get("publisher_links", []))
        self.tl_links.set(d.get("translator_links", []))
        self.store_links_rep.set(d.get("store_links", []))
        self.dl_rep.set(d.get("downloads", []))
        self.ex_rep.set(d.get("extras", []))
        # screenshots: migrate legacy "id" key to "src"
        shots = []
        for r in d.get("screenshots", []):
            shots.append({"src": r.get("src") or r.get("id", ""), "alt": r.get("alt", "")})
        self.ss_rep.set(shots)
        self.update_output()

    # ---- live update + autosave ----------------------------------------
    def schedule(self):
        if self._debounce:
            self.after_cancel(self._debounce)
        self._debounce = self.after(250, self._tick)

    def _tick(self):
        self._debounce = None
        self.update_output()
        self._autosave()

    def update_output(self):
        try:
            bb = build_bbcode(self.collect())
        except Exception as e:
            bb = f"[error building post: {e}]"
        self.bbcode_box.delete("1.0", "end")
        self.bbcode_box.insert("1.0", bb)
        try:
            self.renderer.render(bb)
        except Exception as e:
            self.preview.configure(state="normal")
            self.preview.delete("1.0", "end")
            self.preview.insert("1.0", f"(preview error: {e})")
            self.preview.configure(state="disabled")

    def _autosave(self):
        try:
            data = self.collect()
            data["_profile"] = self.current_profile
            json.dump(data, open(AUTOSAVE_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            self.autosave_lbl.configure(text="✓ autosaved")
            self.after(1400, lambda: self.autosave_lbl.configure(text=""))
        except Exception:
            pass

    def _restore_session(self):
        try:
            if os.path.exists(AUTOSAVE_PATH):
                d = json.load(open(AUTOSAVE_PATH, encoding="utf-8"))
                self.current_profile = d.get("_profile")
                self.apply(d)
                self.title("Forum Post Generator — recovered session"
                           f"{' (' + self.current_profile + ')' if self.current_profile else ''}")
                return
        except Exception:
            pass
        self.apply({"installation": "1. Extract and run."})

    def _on_close(self):
        self._autosave()
        self.destroy()

    # ---- actions --------------------------------------------------------
    def copy_bbcode(self):
        # copy exactly what's shown in the BBCode box (includes any manual tweaks)
        self.clipboard_clear()
        self.clipboard_append(self.bbcode_box.get("1.0", "end-1c"))
        self._toast("Copied BBCode to clipboard")

    def copy_title(self):
        title = (self.vars["title"].get() or "").strip()
        ver = (self.vars["version"].get() or "").strip()
        dev = (self.vars["developer"].get() or "").strip()
        parts = [title] if title else []
        if ver:
            parts.append(f"[{ver}]")
        if dev:
            parts.append(f"[{dev}]")
        line = " ".join(parts).strip()
        if not line:
            return self._toast("Fill game name / version / developer first")
        self.clipboard_clear()
        self.clipboard_append(line)
        self._toast(f"Copied title:  {line}")

    def new_post(self):
        self.current_profile = None
        self.renderer.open_state.clear()
        self.selected_tags = []
        self.title("Forum Post Generator")
        self.apply({"installation": "1. Extract and run."})

    def clear_all(self):
        # wipe every field to empty (dates still default to today)
        self.current_profile = None
        self.renderer.open_state.clear()
        self.selected_tags = []
        self.title("Forum Post Generator")
        self.apply({})
        self._toast("Cleared")

    def _profile_path(self, name):
        safe = re.sub(r"[^A-Za-z0-9 _.\-]+", "_", name).strip() or "post"
        return os.path.join(PROFILES_DIR, safe + ".json")

    def save(self):
        name = (self.vars["title"].get() or self.current_profile or "").strip()
        if not name:
            return self.save_as()
        path = self._profile_path(name)
        json.dump(self.collect(), open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        self.current_profile = os.path.splitext(os.path.basename(path))[0]
        self.title(f"Forum Post Generator — {self.current_profile}")
        self._refresh_profile_list()
        self._toast(f"Saved: {os.path.basename(path)}")

    def save_as(self):
        res = PromptDialog.ask(self, "Save As", [("Profile name", "My Game v1.0", "")])
        name = (res[0].strip() if res else "")
        if name:
            self.vars["title"].set(name)
            self.save()

    def load_selected(self):
        name = self.profile_menu.get()
        path = os.path.join(PROFILES_DIR, name + ".json")
        if not os.path.exists(path):
            return self._toast("No profile selected")
        self.apply(json.load(open(path, encoding="utf-8")))
        self.current_profile = name
        self.title(f"Forum Post Generator — {name}")
        self._toast(f"Loaded: {name}")

    def _refresh_profile_list(self):
        names = sorted(os.path.splitext(f)[0] for f in os.listdir(PROFILES_DIR)
                       if f.endswith(".json") and not f.startswith("_"))
        self.profile_menu.configure(values=names or ["(no profiles)"])
        self.profile_menu.set(self.current_profile if self.current_profile in names else (names[0] if names else "(no profiles)"))

    def _toast(self, msg):
        # Keep the taskbar text current, and show the message on-screen since
        # the native caption is hidden by the custom title bar.
        base = f"Forum Post Generator{' — ' + self.current_profile if self.current_profile else ''}"
        self.title(f"Forum Post Generator — {msg}")
        try:
            self.autosave_lbl.configure(text=msg)
            self._toast_seq = getattr(self, "_toast_seq", 0) + 1
            seq = self._toast_seq
            def _clear():
                if getattr(self, "_toast_seq", None) == seq:
                    try:
                        self.autosave_lbl.configure(text="")
                    except Exception:
                        pass
            self.after(1800, _clear)
        except Exception:
            pass
        self.after(1800, lambda: self.title(base))


if __name__ == "__main__":
    App().mainloop()
