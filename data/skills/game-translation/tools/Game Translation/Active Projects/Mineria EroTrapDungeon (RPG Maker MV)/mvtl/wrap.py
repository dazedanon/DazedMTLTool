#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
wrap.py - fit English into a fixed box.

Width and row count are SIMULTANEOUS constraints, and they fight: narrowing the
wrap to fix a horizontal overflow produces more lines and makes the vertical
overflow worse. `fit()` therefore reports both, and a caller that cannot
satisfy both gets `overflow_rows=True` rather than a silently clipped box.

This is the FREE-LINE-COUNT formulation of the balanced-line DP, and it can
orphan the tail unless the last line is charged - see LAST_LINE_WEIGHT.
`Tools\Game Translation\Text Fitting\layout.py` solves the same problem the
other way, minimising deviation from `total / n_lines` for a FIXED line count,
which charges every line inherently and cannot make that mistake. That one is
the better default. This module exists only because it has to measure through
`measure.py` - masked `⟦n⟧` sentinels, zero-width `\F[..]` portrait codes, and a
nominal budget for the digits a `\V[n]` expands to - none of which layout.py
knows about.

Either way it is a DP with width as a HARD constraint, not a greedy fill:
greedy leaves a two-word last line under a full first line, which is what makes
machine-wrapped English look machine-wrapped.

Atoms, not characters: a `⟦3⟧` sentinel, a `\F[C_Fun3]` code and a surrogate
pair are each indivisible. Breaking inside one produces a control code the
engine cannot parse.
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

# A break may not fall before these (they bind to the preceding text) or after
# these (they bind to what follows). Kinsoku, in the reduced form English needs.
NO_BREAK_BEFORE = set("、。，．,.!?:;…ー！？"
                      ")]}」』）'’♥♡❤♪")
NO_BREAK_AFTER = set("([{「『（'‘")

# How hard the final line's slack is charged, relative to every other line.
# 0.0 is Knuth-Plass (right for a page, wrong for a 4-row box - see the DP).
# 1.0 balances every line equally and starts splitting short units in two to
# even them up. 0.6 keeps a one-line unit on one line and still breaks a
# two-line unit at its sentence.
LAST_LINE_WEIGHT = 0.6

# A break that falls at a sentence or clause boundary is worth an unbalanced
# line. "Awkward line break" is on the playtest defect list for a reason: the
# reader hears the break, so putting it where the sentence already stops is
# free, and putting it between "It'll" and "cost" is not. These multiply the
# line's slack cost, so a lower number means a stronger preference.
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


def _tokens(m, segment):
    """Split one paragraph into breakable tokens with their cell widths.

    A token is a run of non-space atoms. A token wider than the box is split on
    atom boundaries by `_hard_break`, never mid-code."""
    out = []
    cur = []
    for a in _atoms(segment):
        if a.isspace() and a != " ":
            if cur:
                out.append("".join(cur))
                cur = []
        else:
            cur.append(a)
    if cur:
        out.append("".join(cur))
    return out


def _hard_break(m, word, width):
    """Split one over-long token into <= width pieces on atom boundaries."""
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
    """Balanced-line DP. Returns a list of lines, all <= width cells."""
    n = len(words)
    if n == 0:
        return [""]
    w = [m.cells(x) for x in words]
    INF = float("inf")
    # cost[i] = best cost of laying out words[i:]
    cost = [INF] * (n + 1)
    nxt = [n] * (n + 1)
    cost[n] = 0.0
    for i in range(n - 1, -1, -1):
        line = 0
        for j in range(i, n):
            line = w[j] if j == i else line + 1 + w[j]
            if line > width and j > i:
                break
            if line > width and j == i:
                # single word wider than the box; caller pre-split it
                pass
            # kinsoku: do not break BEFORE a clinging mark or AFTER an opener
            if j + 1 < n:
                nxt_first = words[j + 1][:1]
                cur_last = words[j][-1:]
                if nxt_first in NO_BREAK_BEFORE or cur_last in NO_BREAK_AFTER:
                    continue
            slack = width - line
            # The LAST line is charged too, at a reduced weight.
            #
            # Knuth-Plass leaves the final line free, which is right for a page
            # of prose and wrong for a 2-to-4 row message box: with no cost on
            # the tail, the DP fills line 1 to the brim and drops whatever is
            # left onto line 2. That shipped
            #     "Let me divine the path you should walk. It'll cost you 500G how"
            #     "about it?"
            # - a legal break, inside the box, passing every width check, and
            # obviously wrong on screen. Charging the tail makes the same text
            # split at the sentence instead.
            #
            # The weight is reduced rather than full so a short one-line unit is
            # not pushed into two lines to "balance" it; on a single line the
            # slack is constant across every breaking, so it cannot distort.
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

    Hard `\\n\\n` paragraph breaks are preserved. `<br>` is treated as a break
    and re-emitted as a newline (this game uses neither, but the injector runs
    over data a human may have hand-edited)."""
    m = measurer or measure.default()
    if not isinstance(text, str) or width <= 0:
        return Fit(text or "", 1, 0, False, False)

    paragraphs = re.split(r"\n\n", text.replace("<br>", "\n"))
    out_paras = []
    for para in paragraphs:
        # Existing single newlines are the author's soft breaks. They were
        # chosen against Japanese metrics and are now in the wrong place, so
        # they are re-flowed rather than preserved.
        flat = " ".join(l.strip() for l in para.split("\n") if l.strip() or True)
        flat = re.sub(r"[ \t]{2,}", " ", flat).strip()
        words = _tokens(m, flat)
        expanded = []
        for wd in words:
            if m.cells(wd) > width:
                expanded.extend(_hard_break(m, wd, width))
            else:
                expanded.append(wd)
        out_paras.append("\n".join(_balanced(m, expanded, width)))

    wrapped = "\n\n".join(out_paras)
    rows = wrapped.count("\n") + 1
    widest = max((m.cells(l) for l in wrapped.split("\n")), default=0)
    return Fit(
        wrapped,
        rows,
        widest,
        widest > width,
        bool(max_rows is not None and rows > max_rows),
    )


def fit_or_veto(text, width, max_rows, measurer=None, hard_width=None):
    """Wrap, and if the result overflows the box, say so instead of shipping it.

    Returns (text, problems). `problems` is a list of strings, empty on success.
    An over-tall result is NEVER silently accepted: the extra row is simply
    never drawn - no crash, no diff, invisible in review."""
    m = measurer or measure.default()
    f = fit(text, width, max_rows, m)
    problems = []
    if f.overflow_width or (hard_width and f.widest > hard_width):
        problems.append("width %d > %d cells" % (f.widest, hard_width or width))
    if f.overflow_rows:
        problems.append("rows %d > %d" % (f.rows, max_rows))
    return f.text, problems


def redistribute(text, count):
    """Split wrapped text back across `count` commands, one line each.

    Used for code 405 (absent in this game) and for any writer that must
    preserve the command count. Raises rather than changing the count, because
    a save file stores an index into the command list."""
    lines = [l for l in text.split("\n") if l.strip()] or [""]
    if len(lines) > count:
        raise ValueError("wrapped to %d lines but only %d commands available"
                         % (len(lines), count))
    return lines + [""] * (count - len(lines))
