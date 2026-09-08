#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
wrap.py - fit English into a fixed box.

Width and row count are SIMULTANEOUS constraints and they fight: narrowing the
wrap to cure a horizontal overflow produces more lines and makes the vertical
one worse. `fit()` reports both, so a caller that cannot satisfy both gets
`overflow_rows=True` rather than a silently clipped box - and on VX Ace the
clipping really is silent, because `Window_Message` draws a fifth row into a
four-row bitmap and simply loses it.

The layout is a balanced-line DP with width as a HARD constraint, not a greedy
fill: greedy leaves a two-word last line under a full first line, which is what
makes machine-wrapped English look machine-wrapped. Three corrections on top of
Knuth-Plass:

* the LAST line is charged, at `LAST_LINE_WEIGHT`. A free tail fills line 1 to
  the brim and drops the remainder onto line 2, which passes every width check
  and reads wrong.
* a break at a sentence or clause boundary is discounted, because the reader
  hears the break.
* atoms, not characters: a `⟦3⟧` sentinel, a `\NAME[エリス]` tag and a surrogate
  pair are each indivisible, and breaking inside one produces a control code
  the engine cannot parse.
"""

import re

from . import measure

ATOM_RE = re.compile(
    r"⟦\d+⟧"
    r"|\\+[A-Za-z]+\[[^\]]*\]"
    r"|\\+[A-Za-z.|!^<>{}$]"
    r"|.",
    re.S,
)

# A break may not fall before these (they cling to the text before them) or
# after these (they bind to what follows). Kinsoku, in the reduced form English
# needs, plus the marks this game's prose actually uses.
NO_BREAK_BEFORE = set("、。，．,.!?:;…ー！？"
                      ")]}」』）'’♥♡❤♪～")
NO_BREAK_AFTER = set("([{「『（'‘")

LAST_LINE_WEIGHT = 0.6

BREAK_BONUS = [
    (re.compile(r"(?:[.!?…]|\.\.\.)[\"'”’】）)\]]?$"), 0.45),
    (re.compile(r"[,;:—–-]$"), 0.75),
]


def _break_weight(line):
    for rx, w in BREAK_BONUS:
        if rx.search(line):
            return w
    return 1.0


class Fit(object):
    __slots__ = ("text", "rows", "widest", "overflow_width", "overflow_rows")

    def __init__(self, text, rows, widest, overflow_width, overflow_rows):
        self.text = text
        self.rows = rows
        self.widest = widest
        self.overflow_width = overflow_width
        self.overflow_rows = overflow_rows

    @property
    def ok(self):
        return not (self.overflow_width or self.overflow_rows)

    def __repr__(self):
        return "Fit(rows=%d widest=%d ow=%s or_=%s)" % (
            self.rows, self.widest, self.overflow_width, self.overflow_rows)


def _atoms(s):
    return ATOM_RE.findall(s)


def _tokens(segment):
    out, cur = [], []
    for a in _atoms(segment):
        if a.isspace():
            if cur:
                out.append("".join(cur))
                cur = []
        else:
            cur.append(a)
    if cur:
        out.append("".join(cur))
    return out


def _hard_break(m, word, width):
    """Split one over-long token into <= width pieces, on atom boundaries."""
    pieces, cur, cw = [], [], 0
    for a in _atoms(word):
        w = m.cells(a)
        if cur and cw + w > width:
            pieces.append("".join(cur))
            cur, cw = [a], w
        else:
            cur.append(a)
            cw += w
    if cur:
        pieces.append("".join(cur))
    return pieces or [word]


def _balanced(m, words, width):
    n = len(words)
    if n == 0:
        return [""]
    w = [m.cells(x) for x in words]
    INF = float("inf")
    cost = [INF] * (n + 1)
    nxt = [n] * (n + 1)
    cost[n] = 0.0
    for i in range(n - 1, -1, -1):
        line = 0
        for j in range(i, n):
            line = w[j] if j == i else line + 1 + w[j]
            if line > width and j > i:
                break
            if j + 1 < n:
                nxt_first = words[j + 1][:1]
                cur_last = words[j][-1:]
                if nxt_first in NO_BREAK_BEFORE or cur_last in NO_BREAK_AFTER:
                    continue
            slack = width - line
            c = float(slack) * slack * (LAST_LINE_WEIGHT if j + 1 == n else 1.0)
            if j + 1 != n:
                c *= _break_weight(words[j])
            if cost[j + 1] + c < cost[i]:
                cost[i] = cost[j + 1] + c
                nxt[i] = j + 1
        if cost[i] == INF:
            # Every candidate break was vetoed by kinsoku; fall back to greedy
            # so a pathological line still produces output.
            line = 0
            j = i
            while j < n:
                add = w[j] if j == i else 1 + w[j]
                if line + add > width and j > i:
                    break
                line += add
                j += 1
            nxt[i] = max(j, i + 1)
            cost[i] = cost[nxt[i]]
    lines = []
    i = 0
    while i < n:
        j = nxt[i]
        lines.append(" ".join(words[i:j]))
        i = j
    return lines


def fit(text, width, max_rows=None, measurer=None):
    """Wrap `text` to `width` cells, reporting both overflow kinds.

    The author's own single newlines are RE-FLOWED, not preserved: they were
    chosen against Japanese metrics at a different line length and are now in
    the wrong place. A blank line (`\\n\\n`) is a deliberate paragraph break and
    survives."""
    m = measurer or measure.default()
    if not isinstance(text, str) or width <= 0:
        return Fit(text or "", 1, 0, False, False)

    out_paras = []
    for para in re.split(r"\n\s*\n", text):
        flat = re.sub(r"[ \t]{2,}", " ",
                      " ".join(l.strip() for l in para.split("\n"))).strip()
        words = []
        for wd in _tokens(flat):
            if m.cells(wd) > width:
                words.extend(_hard_break(m, wd, width))
            else:
                words.append(wd)
        out_paras.append("\n".join(_balanced(m, words, width)))

    wrapped = "\n\n".join(out_paras)
    rows = wrapped.count("\n") + 1
    widest = max((m.cells(l) for l in wrapped.split("\n")), default=0)
    return Fit(wrapped, rows, widest, widest > width,
               bool(max_rows is not None and rows > max_rows))


def fit_or_veto(text, width, max_rows, measurer=None, hard_width=None):
    """Wrap, and if the result overflows the box, SAY SO instead of shipping it.

    Returns (text, problems). An over-tall result is never silently accepted:
    the extra row is simply never drawn - no crash, no diff, invisible in
    review."""
    m = measurer or measure.default()
    f = fit(text, width, max_rows, m)
    problems = []
    if f.widest > (hard_width or width):
        problems.append("width %d > %d cells" % (f.widest, hard_width or width))
    if f.overflow_rows:
        problems.append("rows %d > %d" % (f.rows, max_rows))
    return f.text, problems


def redistribute(lines, count):
    """Spread `lines` across exactly `count` commands, one or more each.

    The command count is what a save file indexes into, so this raises rather
    than returning a different number of commands."""
    if len(lines) > count:
        per = [1] * count
        for i in range(len(lines) - count):
            per[i % count] += 1
        groups, k = [], 0
        for p in per:
            groups.append(lines[k:k + p])
            k += p
        return groups
    return [[l] for l in lines] + [[] for _ in range(count - len(lines))]
