#!/usr/bin/env python3
"""Render the English title logo.

TitleLogo.png is the only player-facing image with Japanese baked into it
(1400x300, ひと夏の思い出). Its background is fully transparent and the ink is
near-white anti-aliased hairline mincho, so there is nothing to reconstruct -
the whole canvas is redrawn rather than edited in place.

Measured from the shipped PNG:
    canvas   1400 x 300
    ink bbox x 90..1323, y 56..251  (1234 x 196)
    ink RGB  mean (251, 251, 251), effectively pure white
    alpha    45.9% non-zero

Matching the FEEL matters more than matching the metrics: the Japanese is a
high-contrast hairline face, so the English wants a light, high-contrast serif
at a generous tracking, not a default UI serif at default spacing.
"""
from __future__ import annotations

import argparse
import os
import sys

from PIL import Image, ImageDraw, ImageFont

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(PROJECT, "images", "src", "TitleLogo.png")
OUT = os.path.join(PROJECT, "images", "out", "TitleLogo.png")

CANVAS = (1400, 300)
INK = (252, 252, 252, 255)
# The shipped ink spans x 90..1323 of 1400 - the author leaves ~6% margin each
# side rather than bleeding to the edge.
TARGET_W = 1234
CENTER_Y = (56 + 251) // 2


def fit_font(text: str, path: str, target_w: int, tracking: int,
             lo: int = 20, hi: int = 220) -> tuple[ImageFont.FreeTypeFont, int]:
    """Largest size whose tracked width still fits target_w."""
    best = None
    while lo <= hi:
        mid = (lo + hi) // 2
        f = ImageFont.truetype(path, mid)
        w = sum(f.getlength(c) for c in text) + tracking * (len(text) - 1)
        if w <= target_w:
            best = (f, mid)
            lo = mid + 1
        else:
            hi = mid - 1
    if best is None:
        raise SystemExit(f"{text!r} will not fit {target_w}px in {path}")
    return best


def draw_tracked(img: Image.Image, text: str, font: ImageFont.FreeTypeFont,
                 tracking: int, center_y: int) -> None:
    """Draw with manual letter spacing; PIL has no tracking of its own."""
    d = ImageDraw.Draw(img)
    total = sum(font.getlength(c) for c in text) + tracking * (len(text) - 1)
    x = (CANVAS[0] - total) / 2
    for c in text:
        d.text((x, center_y), c, font=font, fill=INK, anchor="lm")
        x += font.getlength(c) + tracking


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--text", default="A Summer to Remember")
    ap.add_argument("--font", default=r"C:\Windows\Fonts\constani.ttf",
                    help="Constantia Italic: light, high-contrast, humanist - the "
                         "closest match on this machine to the shipped hairline "
                         "mincho. georgiai.ttf is the heavier fallback.")
    ap.add_argument("--tracking", type=int, default=6)
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()

    if not os.path.exists(SRC):
        raise SystemExit(f"missing source {SRC}")
    src = Image.open(SRC)
    if src.size != CANVAS:
        raise SystemExit(f"source is {src.size}, expected {CANVAS} - the game build "
                         f"changed, re-measure before rendering")

    img = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    font, size = fit_font(args.text, args.font, TARGET_W, args.tracking)
    draw_tracked(img, args.text, font, args.tracking, CENTER_Y)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    img.save(args.out)
    print(f"{args.text!r} at {size}px, tracking {args.tracking} -> {args.out}")
    print("now run tools/pack_images.py - the plugin loads .tex, not .png "
          "(ImageConversion.LoadImage is unusable on this build)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
