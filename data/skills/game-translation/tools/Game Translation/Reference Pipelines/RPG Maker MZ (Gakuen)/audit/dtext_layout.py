#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Map every DTextPicture caption to the Show Picture that renders it.

`DTextPicture` works in two commands: a `357 dText` prepares a string, and the
next `231 Show Picture` with an EMPTY picture name draws it at that command's
x/y. So the caption's budget is not any attribute of the caption - it is the
distance to whatever is drawn to its right, which lives in a different command
entirely and which no per-unit width check can see.

On the character-creation screen the author budgeted it to the pixel:

    label `性感帯：`  4 full-width glyphs at fontSize 32 = 128 px, drawn at x=172
    value            drawn at x=300
    172 + 128 = 300  -- exactly touching, zero slack

which is why "Erogenous Zone:" (15 half-width = 240 px) lands on top of the
value. This script prints every (caption, x, y, fontSize) so the real budgets
can be computed instead of guessed.
"""
import os, sys, json, glob, collections

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from mztl import config, measure, store, codes  # noqa: E402

cfg = config.Config()
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(cfg.game_root), os.path.basename(cfg.game_root),
    "data_backup_20260824_160344")


def lists(d):
    if isinstance(d, list):
        for e in d:
            if not isinstance(e, dict):
                continue
            if isinstance(e.get("list"), list):
                yield ("ce%s" % e.get("id"), e["list"])
            for pi, p in enumerate(e.get("pages") or []):
                if isinstance(p, dict) and isinstance(p.get("list"), list):
                    yield ("t%s p%s" % (e.get("id"), pi), p["list"])
    elif isinstance(d, dict):
        for e in (d.get("events") or []):
            if not isinstance(e, dict):
                continue
            for pi, p in enumerate(e.get("pages") or []):
                if isinstance(p, dict) and isinstance(p.get("list"), list):
                    yield ("ev%s p%s" % (e.get("id"), pi), p["list"])


rows = []
for fn in sorted(glob.glob(os.path.join(SRC, "*.json"))):
    base = os.path.basename(fn)
    with open(fn, encoding="utf-8-sig") as f:
        d = json.load(f)
    for tag, L in lists(d):
        pending = None
        for i, c in enumerate(L):
            if not isinstance(c, dict):
                continue
            p = c.get("parameters") or []
            if c.get("code") == 357 and len(p) > 3 and p[0] == "DTextPicture":
                a = p[3] if isinstance(p[3], dict) else {}
                pending = (i, a.get("text", ""), a.get("fontSize", "32"))
            elif c.get("code") == 231 and pending is not None:
                # picId, name, origin, ?, x, y, ...
                if len(p) > 5 and not p[1]:
                    rows.append((base, tag, pending[0], i, int(p[0]),
                                 int(p[4]), int(p[5]), pending[1], pending[2]))
                pending = None

print("DTextPicture captions rendered by an empty-name Show Picture: %d" % len(rows))
print()
# group by (file, event, y) - a label and its value share a row
by_row = collections.defaultdict(list)
for r in rows:
    by_row[(r[0], r[1], r[6])].append(r)

m = measure.reset(cfg.font_path)
print("%-14s %-10s %4s %5s %5s %4s  %-22s %s"
      % ("file", "event", "picId", "x", "y", "size", "caption", "px wide"))
for key in sorted(by_row):
    grp = sorted(by_row[key], key=lambda r: r[5])
    if len(grp) < 2:
        continue
    for j, r in enumerate(grp):
        base, tag, ci, pi, pic, x, y, text, size = r
        size = int(size or 32)
        cells = m.cells(text.replace("\n", ""))
        px = cells * (size / 2.0)
        nxt = grp[j + 1][5] if j + 1 < len(grp) else None
        budget = (nxt - x) if nxt is not None else None
        flag = ""
        if budget is not None and px > budget:
            flag = "  <-- OVERLAPS by %dpx" % (px - budget)
        print("%-14s %-10s %5d %5d %5d %4d  %-22r %6.0f px  budget=%s%s"
              % (base, tag, pic, x, y, size, text.replace("\n", "")[:20],
                 px, budget, flag))
    print()
