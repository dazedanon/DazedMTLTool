# -*- coding: utf-8 -*-
"""Measure the circle-name plate in the bottom-left corner."""
import os
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
im = Image.open(os.path.join(HERE, "src", "_Title.png")).convert("RGB")
a = np.asarray(im).astype(int)
H, W = a.shape[:2]

NAVY = (0, 0, 142)


def bbox(mask, label):
    ys, xs = np.nonzero(mask)
    if not len(xs):
        print("  %s: none" % label)
        return None
    b = (xs.min(), ys.min(), xs.max(), ys.max())
    print("  %-22s x %4d..%4d   y %4d..%4d   (%dx%d)"
          % (label, b[0], b[2], b[1], b[3], b[2] - b[0] + 1, b[3] - b[1] + 1))
    return b


# Search the bottom-left quadrant only.
reg = a[H - 140:H, 0:520]
d = np.abs(reg - np.array(NAVY)).max(axis=2)
navy = d <= 70
lum = reg.mean(axis=2)
sat = reg.max(axis=2) - reg.min(axis=2)
white = (lum > 225) & (sat < 30)
black = lum < 45

print("circle-name plate, offsets are absolute:")
for m, lbl in ((navy, "navy fill"), (white, "white outline"), (black, "black outer")):
    ys, xs = np.nonzero(m)
    if len(xs):
        print("  %-22s x %4d..%4d   y %4d..%4d"
              % (lbl, xs.min(), xs.max(), ys.min() + H - 140, ys.max() + H - 140))

# The whole badge = anything that is navy, white or black in that corner, as one
# connected block. Row/column profiles say where it really starts and stops.
badge = navy | white | black
rows = badge.sum(axis=1)
cols = badge.sum(axis=0)
rr = [i + H - 140 for i, v in enumerate(rows) if v > 6]
cc = [i for i, v in enumerate(cols) if v > 4]
print("\n  badge rows  %d..%d" % (rr[0], rr[-1]))
print("  badge cols  %d..%d" % (cc[0], cc[-1]))
print("\n  exact fill colour :", tuple(a[rr[0] + 25, cc[0] + 30]))
print("  background behind :", tuple(a[rr[0] - 12, cc[0] + 30]),
      tuple(a[rr[-1] + 12, cc[0] + 30]))
