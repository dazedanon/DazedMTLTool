# -*- coding: utf-8 -*-
"""Locate each logo line's plate band and glyph extent by INK colour.

The logo ink is two saturated hues with a white outline and a near-black
shadow. Scanning for those hues finds the glyphs regardless of what the collage
behind the plate is doing, which a luminance scan cannot.
"""
import os
import sys
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
im = Image.open(os.path.join(HERE, "src", "_Title.png")).convert("RGB")
px = im.load()
W, H = im.size

PURPLE = (114, 1, 146)          # 魔王ミネリアと, first half of line 1
BLUE = (0, 96, 223)             # 名もなき村の,   second half of line 1
PINK = (235, 0, 114)            # エロトラップダンジョン, line 2


def near(c, t, tol=55):
    return (abs(c[0] - t[0]) < tol and abs(c[1] - t[1]) < tol
            and abs(c[2] - t[2]) < tol)


for name, target in (("line1 purple", PURPLE), ("line1 blue", BLUE),
                     ("line2 pink", PINK)):
    rows = []
    for y in range(H):
        n = sum(1 for x in range(0, W, 2) if near(px[x, y], target))
        if n > 3:
            rows.append(y)
    if not rows:
        print(name, "not found")
        continue
    runs = []
    for y in rows:
        if runs and y - runs[-1][1] <= 3:
            runs[-1][1] = y
        else:
            runs.append([y, y])
    runs = [r for r in runs if r[1] - r[0] > 10]
    print("%s: bands %s" % (name, runs))
    for a, b in runs:
        xs = [x for y in range(a, b + 1) for x in range(W) if near(px[x, y], target)]
        print("     y %d..%d   x %d..%d   height %d"
              % (a, b, min(xs), max(xs), b - a + 1))

print("\nplate wash columns (sampled where no ink of either hue sits):")
for y in (236, 240, 246, 344, 350, 356, 362, 368, 470, 476, 482):
    print("   y=%3d   x=8 %-16s x=300 %-16s x=700 %-16s x=1000 %s"
          % (y, px[8, y], px[300, y], px[700, y], px[1000, y]))
