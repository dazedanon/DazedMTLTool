#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
key_logo.py — turn a logo that was exported flattened onto the editor's
transparency CHECKERBOARD (RGB, no alpha) back into a transparent PNG.

The checkerboard is two near-white/grey colours in a regular grid, connected to
the image border. We mark low-saturation bright pixels as candidate background,
then flood-fill from the border through them, so the logo (coloured + its
ENCLOSED white parts / letter counters) stays opaque while the surrounding
checkerboard becomes transparent. Output is trimmed to the logo's bbox.

  python key_logo.py logo.png -o logo_keyed.png [--sat 14 --bright 218]
"""
import argparse, sys
import numpy as np
from PIL import Image
from scipy.ndimage import label


def key(path, sat=14, bright=218, trim=True):
    im = np.array(Image.open(path).convert("RGB")).astype(int)
    mx, mn = im.max(2), im.min(2)
    is_bg = ((mx - mn) < sat) & (mn > bright)          # low-saturation + bright = checker
    lbl, _ = label(is_bg)
    border = set(lbl[0]).union(lbl[-1], lbl[:, 0], lbl[:, -1])
    border.discard(0)
    alpha = np.where(np.isin(lbl, list(border)), 0, 255).astype(np.uint8)
    rgba = np.dstack([im.astype(np.uint8), alpha])
    if trim:
        ys, xs = np.where(alpha > 0)
        rgba = rgba[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    return Image.fromarray(rgba)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--sat", type=int, default=14)
    ap.add_argument("--bright", type=int, default=218)
    ap.add_argument("--no-trim", action="store_true")
    args = ap.parse_args()
    out = key(args.image, args.sat, args.bright, trim=not args.no_trim)
    out.save(args.out)
    print("wrote %s  size=%s" % (args.out, out.size))


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        try: s.reconfigure(encoding="utf-8", errors="replace")
        except Exception: pass
    main()
