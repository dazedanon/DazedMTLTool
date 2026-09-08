#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
The definitive CBR_EroStatus fit check, and the character budget per caption.

Three facts the naive model got wrong, each found by running it against the
JAPANESE source and watching it accuse the author:

 1. Captions sharing one (page, y, x) are mutually-exclusive VARIANTS of one
    slot, not colliding columns.
 2. A `左右-右` (right-aligned) neighbour is drawn ENDING at its x and grows
    LEFTWARD, so it occupies `x - width .. x`. The budget for the caption to
    its left therefore stops at `x - width`, not at `x`.
 3. Some slots on the same row belong to DIFFERENT pages of the same screen
    (the ero status and the mother-child handbook share y coordinates), so
    they are never on screen together.

Rule 3 cannot be derived statically, so the check is differential: a slot is
only reported when the ENGLISH is over budget AND wider than the Japanese it
replaced. `--budget` prints the character budget for every caption so a
shortened label can be chosen from a number instead of a guess.
"""
import os
import sys
import argparse
import collections

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mztl import config, measure  # noqa: E402
from cbr_layout import parse, SCREEN  # noqa: E402


# Per-slot waivers. A static model cannot know that two captions on the same y
# belong to DIFFERENT screens, so where that is proved by hand it is recorded
# here WITH ITS EVIDENCE and printed - never silently dropped. A suppression
# nobody can see is worse than the false positive it hides.
WAIVED = {
    (1, 200, 60): (
        "the x=165 neighbour on this row is drawn by CE368/370/372, the "
        "mother-child handbook - a different screen that is never on at the "
        "same time as CE1/CE18's ero status. The real neighbour is the "
        "right-aligned value at x=290, which occupies 250..290, and the "
        "caption occupies 60..250: exactly adjacent, no overlap."),
}


def slot_table(m, entries):
    """{(page,y,x): {'variants':[...], 'w':px, 'size':n, 'align':s}}"""
    out = {}
    for e in entries:
        k = (e["page"], e["y"], e["x"])
        px = m.cells(e["text"]) * (e["size"] / 2.0)
        s = out.setdefault(k, {"variants": [], "w": 0.0,
                               "size": e["size"], "align": e["align"]})
        s["variants"].append((e["text"], px))
        if px > s["w"]:
            s["w"] = px
            s["size"] = e["size"]
            s["align"] = e["align"]
    return out


def budget_for(slots, key):
    """px available to a LEFT-aligned caption before it hits its neighbour."""
    page, y, x = key
    limit = SCREEN
    for (p2, y2, x2), s2 in slots.items():
        if p2 != page or y2 != y or x2 <= x:
            continue
        start = (x2 - s2["w"]) if s2["align"] == "右" else x2
        limit = min(limit, start)
    return limit - x


def _wrap(text, width=64):
    words, line, out = text.split(), "", []
    for w in words:
        if len(line) + len(w) + 1 > width:
            out.append(line)
            line = w
        else:
            line = (line + " " + w) if line else w
    if line:
        out.append(line)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=None)
    ap.add_argument("--against", default=None)
    ap.add_argument("--budget", action="store_true")
    a = ap.parse_args()

    cfg = config.Config()
    m = measure.reset(cfg.font_path)
    cur = slot_table(m, parse(a.data or cfg.data_dir))
    base = slot_table(m, parse(a.against)) if a.against else None

    bad = 0
    waived = []
    for key in sorted(cur):
        s = cur[key]
        if s["align"] == "右":
            continue
        b = budget_for(cur, key)
        was = base.get(key, {}).get("w") if base else None
        for text, px in sorted(s["variants"], key=lambda v: -v[1]):
            over = px > b
            worse = was is None or px > was
            if a.budget:
                print("  p%s y=%-4s x=%-4s size=%-3s budget=%6.0fpx (%2d chars)"
                      "  %6.0fpx  %r"
                      % (key[0], key[1], key[2], s["size"], b,
                         int(b / (s["size"] / 2.0)), px, text[:40]))
            elif over and worse:
                if key in WAIVED:
                    waived.append((key, text, px, b))
                    break
                bad += 1
                print("  OVER  p%s y=%-4s x=%-4s size=%-3s  %6.0fpx > %6.0fpx "
                      "budget (%d chars max, was %s)  %r"
                      % (key[0], key[1], key[2], s["size"], px, b,
                         int(b / (s["size"] / 2.0)),
                         ("%.0f" % was) if was is not None else "-", text[:40]))
            break            # only the widest variant decides
    if not a.budget:
        for key, text, px, b in waived:
            print("  WAIVED  p%s y=%-4s x=%-4s  %6.0fpx > %6.0fpx  %r"
                  % (key[0], key[1], key[2], px, b, text[:40]))
            for line in _wrap(WAIVED[key]):
                print("             " + line)
        print("\ncaptions the English pushes past a neighbour: %d"
              "   (%d waived, with the evidence printed above)"
              % (bad, len(waived)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
