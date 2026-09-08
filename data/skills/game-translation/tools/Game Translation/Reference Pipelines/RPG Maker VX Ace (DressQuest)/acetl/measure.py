#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
measure.py - how wide a line renders, in half-width cells.

The unit is the CELL - one half-width glyph - and the cell is 10 px here,
MEASURED rather than inferred.

No script in this game assigns `Font.default_size` and no `Fonts\` folder
ships with it, so the size is the engine default and the face is whatever the
player has. The first build guessed the budget from the widest line the AUTHOR
shipped (66 cells unfaced, 56 faced) on the theory that English no wider than
the Japanese cannot clip where the Japanese did not. That theory has a
precondition, and this game fails it: the author's own longest lines DO clip.

What settled it was a screenshot. A faced line injected as 54 characters
rendered 51 before the right edge cut it off. A faced line is drawn from
`new_line_x` = 112 to the content edge at 640 - 12, so 516 px carried 51
half-width characters, and MS Gothic reproduces that clip at exactly 51 of 54
when set to 20 px. Hence `FONT_PX = 20`, a 10 px cell, and:

    unfaced  616 px -> 61 cells
    faced    504 px -> 50 cells

Height is NOT the same kind of limit. `Window_Message#process_new_line` calls
`input_pause` and `new_page` when the text outgrows the box, so a tall message
costs a click and loses nothing; only width is destructive, because
`process_normal_character` advances x and draws without ever testing the right
edge.

Where a real TTF can be found, its cmap is used to decide per character (and
`missing_glyphs` lists what it cannot draw) instead of trusting
`unicodedata.east_asian_width`, which gets three things wrong that matter:

    U+2026 …   'A' ambiguous in the table, full width in the font
    U+00A0     'N' narrow in the table, present at half width
    U+2764 ❤   often not in the font at all - the engine draws nothing

`exact` says which mode is in force, so nothing is measured on a guess in
silence.
"""

import os
import re
import unicodedata

SCREEN_WIDTH = 640          # Graphics.resize_screen(640, 480)
FONT_PX = 20                # Font.default_size, MEASURED in game: a
                            # 54-character faced line clipped after 51,
                            # which MS Gothic reproduces exactly at 20
CELL_PX = FONT_PX / 2.0     # a half-width glyph = 10 px
PADDING = 12                # Window_Base#standard_padding
CONTENTS_WIDTH = SCREEN_WIDTH - PADDING * 2       # 616 px
LINE_HEIGHT = 24            # Window_Base#line_height
MESSAGE_ROWS = 4            # Window_Message#visible_line_number
FACE_INDENT = 112           # Window_Message#new_line_x when a face is set

# Everything matching this renders nothing and costs no width. `\NAME[..]` is
# in the first alternative: the game's own script consumes it in
# `convert_escape_characters`, before a single glyph is drawn.
ZERO_WIDTH_RE = re.compile(
    r"\\+[A-Za-z]+\[[^\]]*\]"      # \NAME[エリス]  \C[2]  \I[64]  \V[1]
    r"|\\+[A-Za-z]"                # \G is handled below, \\ etc.
    r"|\\+[.|!^<>{}$]"             # waits, instant, font size, gold window
    r"|\u27e6\d+\u27e7"            # our own sentinels
)

# The exception: these render a VALUE, so a line built around one is not free.
# `\G` draws the currency unit, which is the fullwidth `Ｇ` in this game.
#
# The `(?![A-Za-z])` is load-bearing: without it `\N` matches the front of
# `\NAME[エリス]`, the rest of the tag is then measured as visible text, and
# every name-tagged line reads ~10 cells too wide. That silently inflated the
# whole width census before it was caught.
VALUE_CODE_RE = re.compile(r"\\+[VvNnPp](?![A-Za-z])(?:\[\d+\])?")
VALUE_CODE_CELLS = 4            # up to four digits
GOLD_CODE_RE = re.compile(r"\\+[Gg](?![A-Za-z])")
GOLD_CELLS = 2


class Measurer(object):
    def __init__(self, font_path=None):
        self.exact = False
        self._adv = {}
        self._upem = 1000
        self.font_path = font_path
        if font_path and os.path.exists(font_path):
            self._load(font_path)

    def _load(self, path):
        try:
            from fontTools.ttLib import TTFont, TTCollection
        except ImportError:
            return
        try:
            if path.lower().endswith(".ttc"):
                f = TTCollection(path, lazy=True).fonts[0]
            else:
                f = TTFont(path, lazy=True)
            self._upem = f["head"].unitsPerEm
            cmap = f.getBestCmap()
            hmtx = f["hmtx"].metrics
            for cp, glyph in cmap.items():
                m = hmtx.get(glyph)
                if m:
                    self._adv[cp] = m[0]
        except Exception:
            self._adv = {}
            return
        self.exact = bool(self._adv)

    # -------------------------------------------------------------- per char
    def cell_width(self, ch):
        """Width of one character in half-width cells (0, 1 or 2)."""
        adv = self._adv.get(ord(ch))
        if adv is not None:
            return 2 if adv > self._upem * 0.75 else (1 if adv else 0)
        if unicodedata.combining(ch):
            return 0
        # Not in the font, or no font: assume wide for anything the table calls
        # wide, full or ambiguous, which is what ❤ ♪ ♡ actually render as.
        return 2 if unicodedata.east_asian_width(ch) in ("W", "F", "A") else 1

    def missing_glyphs(self, text):
        if not self.exact:
            return set()
        return {c for c in self.visible(text)
                if c != "\u0000" and not c.isspace() and ord(c) not in self._adv}

    # -------------------------------------------------------------- per line
    def visible(self, text):
        t = VALUE_CODE_RE.sub("\u0000" * VALUE_CODE_CELLS, text)
        t = GOLD_CODE_RE.sub("\u0000" * GOLD_CELLS, t)
        return ZERO_WIDTH_RE.sub("", t)

    def cells(self, text):
        return sum(1 if c == "\u0000" else self.cell_width(c)
                   for c in self.visible(text))

    def rows(self, text):
        return text.count("\n") + 1

    def fits(self, text, width, max_rows=None):
        lines = text.split("\n")
        if max_rows is not None and len(lines) > max_rows:
            return False
        return all(self.cells(l) <= width for l in lines)

    def worst_line(self, text):
        best = (0, "")
        for l in text.split("\n"):
            c = self.cells(l)
            if c >= best[0]:
                best = (c, l)
        return best

    # ------------------------------------------------------------ diagnostics
    def px_per_em(self, cells_that_fit, px=CONTENTS_WIDTH):
        """What the corpus implies the font size is, for the record."""
        return px / (cells_that_fit / 2.0) if cells_that_fit else 0.0


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
