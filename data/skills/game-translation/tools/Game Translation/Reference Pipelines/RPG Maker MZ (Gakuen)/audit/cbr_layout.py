#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Measure every CBR_EroStatus caption against the one drawn to its right.

`CBR_EroStatus` builds its page from `355`/`655` script lines of the form
`<key>-<value>`, grouped into one entry per `テキスト-`:

    テキスト-オナニー回数：      the caption
    x-60                      absolute x
    y-200                     absolute y
    サイズ-20                  font size
    左右-右                    align (左 default / 中 / 右)

Nothing declares a width. A caption's real budget is the distance to the next
caption on the SAME y, which lives in a different entry entirely - so no
per-unit width check can see it. The author budgeted these to the pixel:

    `現在のアズサ`  6 full-width glyphs at size 35 = 210 px from x=20 -> ends 230
    `(ループ回数`   drawn at x=235

5 px of slack. "Current Azusa" is 227.5 px at the same size and lands on top of
the loop counter - the shipped screen read `Current Azus<<Loop Count 4 time(s)`.

TWO MODELLING FACTS, both learned by running this against the JAPANESE source
first and watching it accuse the author:

  * Several captions commonly share ONE (page, y, x). They are mutually
    exclusive VARIANTS of one slot, chosen at draw time by the heroine's state,
    so they are one column as wide as its widest variant - not a stack of
    columns colliding. Treating them as separate columns reported 61 overlaps
    in the source.
  * Even collapsed, the source still "overlaps" 7 times, because some variants
    are mutually exclusive across DIFFERENT x (the pregnancy row draws either
    one wide caption or a narrow one plus a value). That is a limit of any
    static model.

So the useful check is DIFFERENTIAL: run with `--against <japanese data/>` and
it reports only slots where the ENGLISH is wider than the Japanese it replaced.
The author's own layout is the ground truth, and a slot that already overlapped
in Japanese is not something this patch broke.
"""
import os
import sys
import re
import json
import argparse
import collections

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from mztl import config, measure  # noqa: E402

SCREEN = 816
KEYS = ("テキスト", "画像", "x", "y", "サイズ", "左右", "上下", "透明度",
        "ページ", "初期化")
ROW_RE = re.compile(r"^(%s)-(.*)$" % "|".join(KEYS), re.S)


def parse(data_dir):
    """[{page, y, x, size, align, text}] for every positioned caption."""
    with open(os.path.join(data_dir, "CommonEvents.json"),
              encoding="utf-8-sig") as f:
        ces = json.load(f)
    out = []
    for ce in ces:
        if not ce or not isinstance(ce, dict):
            continue
        page, cur = 1, None
        for c in ce.get("list") or []:
            if c.get("code") not in (355, 655):
                continue
            v = ((c.get("parameters") or [""]) + [""])[0]
            mm = ROW_RE.match(v)
            if not mm:
                continue
            k, val = mm.groups()
            if k == "ページ":
                if val.strip().isdigit():
                    page = int(val)
                continue
            if k == "テキスト":
                if cur:
                    out.append(cur)
                cur = {"ce": ce.get("id"), "page": page, "text": val,
                       "x": None, "y": None, "size": 28, "align": "左"}
            elif cur is not None:
                if k in ("x", "y"):
                    s = val.strip()
                    cur[k] = int(s) if s.lstrip("-").isdigit() else None
                elif k == "サイズ" and val.strip().isdigit():
                    cur["size"] = int(val)
                elif k == "左右":
                    cur["align"] = val.strip()
        if cur:
            out.append(cur)
    return [e for e in out if e["x"] is not None and e["y"] is not None]


def widths(m, entries):
    """{(page, y, x): (widest_caption, px)}"""
    out = {}
    for e in entries:
        k = (e["page"], e["y"], e["x"])
        px = m.cells(e["text"]) * (e["size"] / 2.0)
        if k not in out or px > out[k][1]:
            out[k] = (e, px)
    return out


def budgets(slots):
    """{(page, y, x): px to the next slot on this row}"""
    rows = collections.defaultdict(list)
    for (page, y, x) in slots:
        rows[(page, y)].append(x)
    out = {}
    for (page, y), xs in rows.items():
        xs = sorted(xs)
        for j, x in enumerate(xs):
            out[(page, y, x)] = (xs[j + 1] if j + 1 < len(xs) else SCREEN) - x
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=None)
    ap.add_argument("--against", default=None,
                    help="the Japanese data/ - makes the check differential")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    cfg = config.Config()
    m = measure.reset(cfg.font_path)
    cur = widths(m, parse(args.data or cfg.data_dir))
    bud = budgets(cur)
    base = widths(m, parse(args.against)) if args.against else None

    print("CBR_EroStatus: %d distinct slots" % len(cur))
    print("%-4s %-5s %-5s %-4s %-34s %7s %7s %s"
          % ("page", "y", "x", "size", "widest variant", "px", "budget", "was"))
    bad = 0
    for k in sorted(cur):
        e, px = cur[k]
        b = bud[k]
        if e["align"] == "右":
            continue                       # grows leftward, cannot collide
        was = base.get(k, (None, None))[1] if base else None
        over = px > b
        # Differential: only a slot the ENGLISH made worse.
        if base is not None and not (over and (was is None or px > was)):
            if not args.all:
                continue
        elif base is None and not over and not args.all:
            continue
        if over:
            bad += 1
        print("%-4s %-5s %-5s %-4s %-34r %7.0f %7d %s%s"
              % (e["page"], e["y"], e["x"], e["size"], e["text"][:32], px, b,
                 ("%.0f" % was) if was is not None else "-",
                 "  <-- OVERLAPS" if over else ""))
    print()
    print("slots the English pushes past its neighbour: %d" % bad)
    return 0


if __name__ == "__main__":
    sys.exit(main())
