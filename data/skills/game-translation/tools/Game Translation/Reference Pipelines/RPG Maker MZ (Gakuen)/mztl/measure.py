#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
measure.py - width measurement against the game's ACTUAL font.

RPG Maker MZ draws message text with `fonts/x12y12pxMaruMinyaM.ttf` at
`$gameSystem.mainFontSize()`, which returns `$dataSystem.advanced.fontSize` =
**20**. That font has exactly two advance widths (1200 and 600 over an
unitsPerEm of 1200), so it is genuinely monospace and a cell count is exact --
but only if the cell width of each character comes from the font's own cmap
rather than from `unicodedata.east_asian_width`.

The two disagree in ways that matter here:

  U+2026 …  east_asian_width 'A' (ambiguous), font advance 1200 -> 2 cells
  U+00A0    east_asian_width 'N',             font advance  600 -> 1 cell
  U+2764 ❤  east_asian_width 'A',             font advance 1200 -> 2 cells,
            and it IS in this font, unlike M+ 1m where it is missing entirely

`missing_glyphs` lists what the shipped font cannot draw, so nothing is
measured on a guess in silence. Falls back to an east-asian-width table when
fontTools is unavailable and says which mode it is in via `Measurer.exact`.

Geometry, all read out of the game rather than assumed:

  System.json advanced.screenWidth  = 816  -> Graphics.boxWidth
  System.json advanced.fontSize     = 20
  Scene_Message.messageWindowRect     ww = boxWidth, wh = calcWindowHeight(4)
  LL_MessageWindowAdjust (enabled)    this.width = boxWidth - adjustValue*2,
                                      adjustNoFace = 40   -> 736 px
  Game_System.windowPadding()       = 12   -> innerWidth 712
  Window_Message.newLineX             4 with no face, faceWidth+20 = 164 with
  half-width cell                   = 600/1200 * 20 = 10.00 px
  -> 708 / 10 = 70.8 cells unfaced, 628 / 10 = 62.8 faced, FOUR rows.
"""

import os
import re
import unicodedata

from . import codes

FONT_SIZE = 20          # $dataSystem.advanced.fontSize
BOX_WIDTH = 816         # advanced.screenWidth -> Graphics.boxWidth
MSG_ADJUST = 40         # LL_MessageWindowAdjust adjustNoFace
PADDING = 12            # Game_System.prototype.windowPadding()
NEW_LINE_X = 4          # Window_Message.newLineX, no face
FACE_WIDTH = 144        # ImageManager.faceWidth
FACE_SPACING = 20

MESSAGE_WIDTH_PX = BOX_WIDTH - MSG_ADJUST * 2 - PADDING * 2 - NEW_LINE_X   # 708
FACE_MESSAGE_WIDTH_PX = BOX_WIDTH - PADDING * 2 - (FACE_WIDTH + FACE_SPACING)  # 628
HELP_WIDTH_PX = BOX_WIDTH - PADDING * 2                                    # 792
MESSAGE_ROWS = 4        # Scene_Message.calcWindowHeight(4, false)
LINE_HEIGHT = 36        # Window_Base.itemHeight() -> lineHeight()

# What the mock renderer draws. The message WINDOW is not the screen: it is
# 736 px wide (LL_MessageWindowAdjust) and centred, so it starts 40 px in, and
# the text starts a further padding + newLineX inside that. Drawing the box at
# full screen width would show every line comfortably clearing an edge that is
# 108 px further out than the real one.
MSG_WINDOW_WIDTH = BOX_WIDTH - MSG_ADJUST * 2          # 736
MSG_WINDOW_X = (BOX_WIDTH - MSG_WINDOW_WIDTH) // 2     # 40
MSG_TEXT_X = MSG_WINDOW_X + PADDING + NEW_LINE_X       # 56
CONTENTS_WIDTH = MESSAGE_WIDTH_PX                      # 708, the drawable run
HELP_ROWS = 2           # Scene_MenuBase.helpWindowRect

# Anything matching this renders to nothing and costs no width.
ZERO_WIDTH_RE = re.compile(
    codes.BRACKET_CODE_PATTERN +
    r"|\\+(?:name|count|gold)\b"  # notify-message inserts (below)
    r"|\\+[A-Za-z]"               # \G (below)
    r"|\\+[.|!^<>{}$]"            # pause / instant / font-size / gold sign
    r"|\u27e6\d+\u27e7"           # our own placeholders
)

# \V[n], \G and the notify inserts are the exception: they render a VALUE, not
# nothing. Budget a nominal width so a line built around a variable is not
# measured as if the number were free.
VALUE_CODE_RE = re.compile(r"\\+[VvGg](?:\[\d+\])?|\\+(?:name|count|gold)\b")
VALUE_CODE_CELLS = 4            # up to 4 digits / "9999G"

# LL_StandingPicture consumes these before the base window parser. Other
# bracket codes retain their existing value-width handling.
PORTRAIT_PREFIX_RE = re.compile(r"\\+(?:[Ff]{1,4}|[FfMm][1-8])\[")


class Measurer(object):
    """Cell widths for one font. One cell = one half-width glyph = 10 px."""

    def __init__(self, font_path=None, font_size=FONT_SIZE):
        self.font_size = font_size
        self.exact = False
        self._adv = {}
        self._upem = 1000
        self.half_px = font_size / 2.0
        self.font_path = font_path
        if font_path and os.path.exists(font_path):
            self._load(font_path)

    def _load(self, path):
        try:
            from fontTools.ttLib import TTFont
        except ImportError:
            return
        try:
            f = TTFont(path, lazy=True)
            self._upem = f["head"].unitsPerEm
            cmap = f.getBestCmap()
            hmtx = f["hmtx"].metrics
            for cp, glyph in cmap.items():
                m = hmtx.get(glyph)
                if m:
                    self._adv[cp] = m[0]
            f.close()
        except Exception:
            self._adv = {}
            return
        # Half-width cell = the advance of an ASCII digit.
        half = self._adv.get(ord("0"))
        if half:
            self.half_px = half / float(self._upem) * self.font_size
        self.exact = bool(self._adv)

    # -------------------------------------------------------------- per char
    def cell_width(self, ch):
        """Width of one character in half-width cells (0, 1 or 2)."""
        adv = self._adv.get(ord(ch))
        if adv is not None:
            return 2 if adv > self._upem * 0.75 else (1 if adv else 0)
        if unicodedata.combining(ch):
            return 0
        # Not in the shipped font: the browser falls back to
        # advanced.fallbackFonts ("Verdana, sans-serif"), whose metrics we do
        # not control. Assume wide, which is the conservative reading and what
        # a CJK-range symbol actually renders as.
        return 2 if unicodedata.east_asian_width(ch) in ("W", "F", "A") else 1

    def missing_glyphs(self, text):
        """Characters in `text` the shipped font cannot draw."""
        if not self.exact:
            return set()
        return {c for c in text
                if ord(c) not in self._adv and not c.isspace()}

    # -------------------------------------------------------------- per line
    def visible(self, text):
        """Strip everything that renders to nothing, keep value codes as a
        nominal run of digits so their width is budgeted."""
        # Remove whole portrait selectors first. In \F3[\V[1]], the
        # variable selects a portrait and contributes no visible digits.
        t = re.sub(codes.BRACKET_CODE_PATTERN,
                   lambda m: "" if PORTRAIT_PREFIX_RE.match(m.group(0)) else m.group(0),
                   text)
        t = VALUE_CODE_RE.sub("\u0000" * VALUE_CODE_CELLS, t)
        t = ZERO_WIDTH_RE.sub("", t)
        return t

    def cells(self, text):
        """Rendered width of one line in half-width cells."""
        t = self.visible(text)
        return sum(1 if c == "\u0000" else self.cell_width(c) for c in t)

    def px(self, text):
        return self.cells(text) * self.half_px

    def rows(self, text):
        r"""Rendered row count. `\n[` is an actor-name code, not a break -
        this game has no \N codes at all, but the guard is free."""
        t = re.sub(r"\\+[nN]\[", "\u0001", text)
        t = t.replace("<br>", "\n")
        return t.count("\n") + 1

    def fits(self, text, width, max_rows=None):
        lines = text.split("\n")
        if max_rows is not None and len(lines) > max_rows:
            return False
        return all(self.cells(l) <= width for l in lines)

    def worst_line(self, text):
        """(cells, line) of the widest rendered line."""
        best = (0, "")
        for l in text.split("\n"):
            c = self.cells(l)
            if c >= best[0]:
                best = (c, l)
        return best


_DEFAULT = None


def default(font_path=None):
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = Measurer(font_path)
    return _DEFAULT


def reset(font_path=None):
    global _DEFAULT
    _DEFAULT = Measurer(font_path)
    return _DEFAULT
