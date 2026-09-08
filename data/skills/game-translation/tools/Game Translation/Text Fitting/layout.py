#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
layout.py — re-wrap a translation to the line count its source had.

The subtitle and dialogue boxes in this game are fixed-size and authored around
the Japanese line breaks, so a 2-line source that comes back as one long English
line overflows or renders off-centre even when the English itself is good. The
model is asked to preserve the line count and mostly does, but ~7% of units come
back with a different one.

This is a layout problem, not a translation problem, so it is fixed deterministically
here rather than by paying for another model pass: flatten to a single line, then
split at the word boundaries that give the most balanced result, preferring breaks
that fall after sentence punctuation.
"""

import re

# Atoms are separated by ASCII space/tab or by the full-width space. The separator
# is kept alongside its atom because 　 (U+3000) is a pacing gap between gasps, not
# indentation — collapsing it to a plain space changes how a line reads aloud.
# ⟦0⟧-style masked control codes are single atoms and never split down the middle.
_SPLIT_RE = re.compile(r"([ \t]+|　+)")

# A break reads best right after one of these; a mid-clause break is a last resort.
_STRONG_END = ("...", "…", ".", "!", "?", "！", "？", "。", "♥", "★", "♪", "~", "〜")
_WEAK_END = (",", "、", "，", "-", "—", ":", ";")

_STRONG_BONUS = 0.45      # as a fraction of the ideal line length, squared-cost units
_WEAK_BONUS = 0.15


def _display_width(s):
    """Rough cell width: CJK and full-width punctuation occupy two columns."""
    w = 0
    for ch in s:
        o = ord(ch)
        if (0x1100 <= o <= 0x115F or 0x2E80 <= o <= 0xA4CF or 0xAC00 <= o <= 0xD7A3
                or 0xF900 <= o <= 0xFAFF or 0xFE30 <= o <= 0xFE4F
                or 0xFF00 <= o <= 0xFF60 or 0xFFE0 <= o <= 0xFFE6):
            w += 2
        elif o == 0x3000:
            w += 2
        else:
            w += 1
    return w


def flatten(text):
    """Collapse a translation to one line, preserving full-width pacing gaps.

    Only ASCII whitespace is trimmed: 　 is content here, not padding.
    """
    parts = [p.strip(" \t\r") for p in text.split("\n")]
    joined = " ".join(p for p in parts if p)
    return re.sub(r"[ \t]{2,}", " ", joined).strip(" \t\r")


def _atomize(flat):
    """[(atom, separator_that_follows), ...] — the last separator is ''.

    A separator before the first atom is glued onto it rather than dropped: a line
    that opens with 　 is deliberately indented (an aside, an inner thought), and
    losing it silently changes the layout the writer chose.
    """
    parts = _SPLIT_RE.split(flat)
    atoms, seps = [], []
    lead = ""
    for i, part in enumerate(parts):
        if i % 2 == 0:
            if part:
                atoms.append(lead + part)
                seps.append("")
                lead = ""
        elif atoms:
            seps[-1] = part
        else:
            lead = part
    if seps:
        seps[-1] = ""
    return atoms, seps


# A line wider than the box is clipped on screen, so exceeding the width has to
# dominate every aesthetic term. Without this the punctuation bonus can buy an
# unusable line: breaking after "...is there...?" scored so well that a leftover
# 54-cell line beat three balanced ones that all fit.
OVERFLOW_PENALTY = 1000.0


def reflow(text, n_lines, max_width=0):
    """Re-wrap `text` to exactly `n_lines`, balanced, breaking on word boundaries.

    With `max_width`, lines over that width are penalised so heavily that the
    solver only produces one when no arrangement avoids it.

    Returns the text unchanged when it already has that many lines, when n_lines
    is 1, or when there are too few word boundaries to split on.
    """
    if n_lines < 1:
        return text
    if text.count("\n") + 1 == n_lines and max_width <= 0:
        return text
    flat = flatten(text)
    if n_lines == 1:
        return flat

    atoms, seps = _atomize(flat)
    if len(atoms) < n_lines:
        return flat        # not enough words to make that many lines

    widths = [_display_width(a) for a in atoms]
    sep_w = [_display_width(s) for s in seps]
    total = sum(widths) + sum(sep_w)
    ideal = total / n_lines

    # cost[i][k] = best cost of laying out atoms[i:] in k lines
    n = len(atoms)
    INF = float("inf")
    cost = [[INF] * (n_lines + 1) for _ in range(n + 1)]
    choice = [[0] * (n_lines + 1) for _ in range(n + 1)]
    cost[n][0] = 0.0

    for i in range(n - 1, -1, -1):
        for k in range(1, n_lines + 1):
            best, best_j = INF, i + 1
            run = 0
            for j in range(i, n):
                run += widths[j] + (sep_w[j - 1] if j > i else 0)
                remaining = n - (j + 1)
                if remaining < k - 1:
                    break
                tail = cost[j + 1][k - 1]
                if tail == INF:
                    continue
                dev = (run - ideal) / ideal
                c = dev * dev + tail
                if max_width > 0 and run > max_width:
                    c += OVERFLOW_PENALTY * (run - max_width)
                if k > 1:                       # a break happens after atoms[j]
                    a = atoms[j]
                    if a.endswith(_STRONG_END):
                        c -= _STRONG_BONUS
                    elif a.endswith(_WEAK_END):
                        c -= _WEAK_BONUS
                if c < best:
                    best, best_j = c, j
            cost[i][k], choice[i][k] = best, best_j

    if cost[0][n_lines] == INF:
        return flat

    lines, i, k = [], 0, n_lines
    while k > 0:
        j = choice[i][k]
        buf = []
        for t in range(i, j + 1):
            buf.append(atoms[t])
            if t < j:
                buf.append(seps[t] or " ")   # keep 　 gaps inside the line
        lines.append("".join(buf))
        i, k = j + 1, k - 1
    return "\n".join(lines)


def line_count(s):
    """Displayed line count: CRLF normalised, one trailing terminator dropped.

    CSV cells routinely end with a stray CR that the engine drops before it is
    ever shown; counting it invents a phantom empty line.
    """
    t = (s or "").replace("\r\n", "\n").replace("\r", "\n")
    if t.endswith("\n"):
        t = t[:-1]
    return len(t.split("\n"))


def widest(text):
    """Width in cells of the longest line."""
    return max((_display_width(ln) for ln in (text or "").split("\n")), default=0)


def restore_indent(text, source):
    """Re-apply the source's leading 　 indents to the translation.

    A line opening with 　 is an indented continuation — an inner thought carried
    across two lines, a spaced-out chant. It is layout, and wrapping loses it.

    Indents are matched by position when the line counts agree. When wrapping has
    changed the count, only the FIRST indented source line is honoured, applied to
    the corresponding wrapped line, because any finer mapping would be guesswork.
    """
    if "　" not in (source or ""):
        return text
    src_lines = [ln for ln in (source or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    if src_lines and src_lines[-1] == "":
        src_lines.pop()
    tl_lines = text.split("\n")
    marks = [i for i, ln in enumerate(src_lines) if ln.startswith("　")]
    if not marks:
        return text
    if len(src_lines) == len(tl_lines):
        for i in marks:
            if not tl_lines[i].startswith("　"):
                tl_lines[i] = "　" + tl_lines[i].lstrip(" \t")
    else:
        i = marks[0]
        if i < len(tl_lines) and not tl_lines[i].startswith("　"):
            tl_lines[i] = "　" + tl_lines[i].lstrip(" \t")
    return "\n".join(tl_lines)


def fit_box(text, max_width, max_lines):
    """Fit `text` into a box `max_width` cells wide and `max_lines` tall.

    Preserving the writer's breaks is preferred, so per-line wrapping is tried
    first. But that can only ever add lines: two 56-cell lines each split in half
    give four, when re-flowing the same words freely fits three. When per-line
    wrapping busts the height, the text is re-wrapped as a whole into the fewest
    lines that satisfy the width — deliberate breaks are lost, but a line pushed
    out of the box is not shown at all, so height wins.

    Returns (text, fits). `fits` is False when the words cannot be made to fit at
    any breaking — that unit needs a shorter translation, not better wrapping.
    """
    if max_width <= 0:
        return text, True
    per_line = fit_width(text, max_width)
    if max_lines <= 0 or line_count(per_line) <= max_lines:
        return per_line, widest(per_line) <= max_width
    flat = flatten(text)
    need = max(1, -(-_display_width(flat) // max_width))
    for n in range(need, max_lines + 1):
        cand = reflow(flat, n, max_width)
        if widest(cand) <= max_width:
            return cand, True
    return reflow(flat, max_lines, max_width), False


def fit_width(text, max_width, hard_cap=4):
    """Break only the lines that overflow, leaving every other break untouched.

    These dialogue RectTransforms are 959-1025 units wide inside an 800x450
    reference canvas, so TMP's own word wrap only engages well past the right edge
    of the screen — a line that "fits the rect" is still visually cut off. The
    Japanese never hit that, because full-width glyphs forced the developer to break
    early; English has to be broken to the *visible* budget instead.

    Each line is wrapped independently rather than flattening the whole string and
    re-splitting it. Flattening merges lines the writer separated on purpose: it
    turned "Rapid Fire・Starting Coins×2 / Damage×0.5" into "Rapid Fire・Starting /
    Coins×2 Damage×0.5", which reads as one garbled stat instead of two.
    """
    if max_width <= 0 or not text:
        return text
    out = []
    for line in text.split("\n"):
        w = _display_width(line)
        if w <= max_width:
            out.append(line)
            continue
        n = min(hard_cap, max(2, -(-w // max_width)))    # ceil division
        wrapped = reflow(line, n, max_width)
        while widest(wrapped) > max_width and n < hard_cap:
            n += 1
            nxt = reflow(line, n, max_width)
            if nxt == wrapped:          # no further break point available
                break
            wrapped = nxt
        out.append(wrapped)
    return "\n".join(out)
