#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
measure.py - width measurement against the game's ACTUAL font.

RPG Maker MV draws message text with `fonts/mplus-1m-regular.ttf` at
`Window_Base.standardFontSize()` = 28px. That font has exactly two advance
widths (500 and 1000 units per 1000 upem), so it is genuinely monospace and a
cell count is exact -- but only if the cell width of each character comes from
the font's own cmap rather than from `unicodedata.east_asian_width`.

The two disagree in ways that matter here:

  U+2026 …  east_asian_width 'A' (ambiguous), font advance 1000 -> 2 cells
  U+00A0    east_asian_width 'N',             font advance  500 -> 1 cell
  U+2764 ❤  NOT IN THE FONT AT ALL

That last case is the one a table-driven measurer gets silently wrong. The game
text is full of ❤ (U+2764) and it renders from a browser fallback font whose
metrics we do not control. `cell_width` reports it as 2 cells, which is the
conservative reading, and `missing_glyphs` lets a QA pass list every character
the shipped font cannot draw so nothing is measured on a guess without saying
so.

Falls back to an east-asian-width table when fontTools is unavailable, and says
which mode it is in via `Measurer.exact`.
"""

import os
import re
import unicodedata

FONT_SIZE = 28          # Window_Base.prototype.standardFontSize()
BOX_WIDTH = 1020        # Community_Basic screenWidth -> Graphics.boxWidth
PADDING = 18            # Window_Base.prototype.standardPadding()
CONTENTS_WIDTH = BOX_WIDTH - PADDING * 2      # 984 px
MESSAGE_ROWS = 4        # Window_Message.prototype.numVisibleRows()
HELP_ROWS = 2           # Window_Help numLines

# Anything matching this renders to nothing and costs no width.
ZERO_WIDTH_RE = re.compile(
    r"\\+[A-Za-z]+\[[^\]]*\]"      # \F[C_Fun3]  \V[66]  \AA[F]  \M[yes]
    r"|\\+[A-Za-z]"               # \G  \. is below
    r"|\\+[.|!^<>{}$]"            # pause / instant / font-size / gold
    r"|\u27e6\d+\u27e7"           # our own placeholders
)

# \V[n] and \G are the exception: they render a VALUE, not nothing. We budget a
# nominal width for them so a line built around a variable is not measured as
# if the number were free.
VALUE_CODE_RE = re.compile(r"\\+[VvGg](?:\[\d+\])?")
VALUE_CODE_CELLS = 4            # up to 4 digits / "9999G"


class Measurer(object):
    """Cell widths for one font. One cell = one half-width glyph = 14px."""

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
        """Width of one character in half-width cells (1 or 2)."""
        adv = self._adv.get(ord(ch))
        if adv is not None:
            return 2 if adv > self._upem * 0.75 else (1 if adv else 0)
        if unicodedata.combining(ch):
            return 0
        # Not in the shipped font: the browser falls back. Assume wide, which
        # is what a CJK-range symbol (❤ ♪ ♡) actually renders as.
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
        t = VALUE_CODE_RE.sub("\u0000" * VALUE_CODE_CELLS, text)
        t = ZERO_WIDTH_RE.sub("", t)
        return t

    def cells(self, text):
        """Rendered width of one line in half-width cells."""
        t = self.visible(text)
        return sum(1 if c == "\u0000" else self.cell_width(c) for c in t)

    def px(self, text):
        return self.cells(text) * self.half_px

    def rows(self, text):
        """Rendered row count. `\\n[` is an actor-name code, not a break, but
        this game has no \\N codes at all -- still handled for safety."""
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
