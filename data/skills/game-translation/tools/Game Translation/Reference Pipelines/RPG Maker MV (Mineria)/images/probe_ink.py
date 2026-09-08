# -*- coding: utf-8 -*-
"""Measure the FULL ink footprint of each logo line (fill + white ring + black
outer ring), the plate rows, and the ring thicknesses. The first render erased
fill-core boxes +16px and the black ring runs ~20px past that, which is where
every ghost came from."""
import os
import numpy as np
from PIL import Image
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
im = Image.open(os.path.join(HERE, "src", "_Title.png")).convert("RGB")
A = np.asarray(im).astype(np.int16)

PURPLE = (114, 1, 146)
BLUE = (0, 96, 223)
PINK = (235, 0, 114)


def hue_mask(a, h, tol=78):
    return np.abs(a - np.array(h, dtype=np.int16)).max(axis=2) <= tol


def logo_ink(box, hues):
    """Ink bbox via connectivity: white/black kept only when connected to the
    fill hues, so collage hair and highlights are not counted as ink."""
    x0, y0, x1, y1 = box
    a = A[y0:y1, x0:x1]
    lum = a.mean(axis=2)
    sat = a.max(axis=2) - a.min(axis=2)
    fill = np.zeros(a.shape[:2], dtype=bool)
    for h in hues:
        fill |= hue_mask(a, h)
    white = (lum > 238) & (sat < 26)
    black = (lum < 75) & (sat < 65)
    cat = ndimage.binary_dilation(fill | white | black, iterations=3)
    lab, n = ndimage.label(cat)
    keep_ids = set(np.unique(lab[fill])) - {0}
    keep = np.isin(lab, list(keep_ids))
    ys, xs = np.nonzero(keep)
    print("  ink bbox  x %4d..%4d   y %4d..%4d   (%d px)"
          % (x0 + xs.min(), x0 + xs.max(), y0 + ys.min(), y0 + ys.max(),
             keep.sum()))
    return keep


print("line 1 (purple+blue):")
logo_ink((0, 225, 1020, 378), [PURPLE, BLUE])
print("line 2 (pink):")
logo_ink((150, 340, 1020, 505), [PINK])

# Plate rows: scan glyph-free columns for the brightness step at the plate
# boundary. Plate ~= source dimmed toward white, so it is markedly lighter
# than the same collage above/below.
print("\nplate rows (per column, first/last row where lum steps up):")
for label, cols, y0, y1 in (("plate1", (940, 960, 980, 1000), 210, 372),
                            ("plate2", (184, 190, 196, 1014), 350, 495)):
    tops, bots = [], []
    for x in cols:
        col = A[y0:y1, x].mean(axis=1)
        # the plate is a long run of high luminance; find the widest bright run
        bright = col > 150
        lab, n = ndimage.label(bright)
        if not n:
            continue
        sizes = ndimage.sum(bright, lab, range(1, n + 1))
        big = int(np.argmax(sizes)) + 1
        ys = np.nonzero(lab == big)[0]
        tops.append(y0 + ys.min())
        bots.append(y0 + ys.max())
    print("  %-7s cols %s  top %s  bottom %s"
          % (label, cols, sorted(tops), sorted(bots)))

# Ring thicknesses: walk scanlines outward from a fill pixel and measure the
# white run then the black run.
print("\nring thickness (fill->white->black runs on scanlines):")


def rings(y, x_from, x_to, hue):
    a = A[y]
    lum = a.mean(axis=1)
    sat = a.max(axis=1) - a.min(axis=1)
    isf = np.abs(a - np.array(hue, dtype=np.int16)).max(axis=1) <= 60
    isw = (lum > 238) & (sat < 26)
    isb = (lum < 75) & (sat < 65)
    runs = []
    x = x_from
    while x < x_to:
        if isf[x] and not isf[x + 1]:
            w = b = 0
            j = x + 1
            while j < x_to and not isw[j] and not isb[j]:
                j += 1
            while j < x_to and isw[j]:
                w += 1
                j += 1
            while j < x_to and not isb[j] and w and (j - x) < 60:
                j += 1
            while j < x_to and isb[j]:
                b += 1
                j += 1
            if w >= 3 and b >= 3:
                runs.append((w, b))
            x = j
        else:
            x += 1
    return runs


for y in (300, 305, 310):
    print("  y=%d line1: %s" % (y, rings(y, 23, 900, PURPLE) + rings(y, 23, 900, BLUE)))
for y in (410, 416, 422):
    print("  y=%d line2: %s" % (y, rings(y, 214, 1015, PINK)))
