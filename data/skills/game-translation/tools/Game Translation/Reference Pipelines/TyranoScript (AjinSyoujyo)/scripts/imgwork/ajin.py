"""Game-specific image helpers for 亜人少女, layered over the shared imgtl toolkit.

Two things this game needs that the generic toolkit does not have:

``hfill``     the UI banners are flat inside the text area but fade in alpha at
              their edges, so an erase is a per-row interpolation between the
              clean columns either side of the text - not a flat rectangle.

``bilingual`` the game already ships a house style for bilingual labels: the
              Japanese stays, and a small English word in a Roman serif sits
              under it, right-aligned (see kigaeui/fukusoukuro.png -> "clothes",
              fukusyokukuro.png -> "accessory", hairk.png -> "hair"). Where the
              art behind a label is too busy to erase cleanly, matching that
              existing convention is better than inventing a new one.
"""
from __future__ import annotations

import os
import sys
from statistics import median

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import imgtl                                      # noqa: E402
from imgtl import (font, jp_font, text, text_width, fit_size,   # noqa: F401,E402
                   ybands, xclusters, ink_bbox, alpha_range, zoom,
                   clear_rect, fill_rect, patch_rect, rowfill,
                   snap_pixels, restore_pixels, shadow_text, glow_text, logo_text)

F = imgtl.F
#: the game sets its message font to a mincho-ish serif and draws every UI label
#: in it, so English goes to a Roman serif rather than a gothic sans.
imgtl.FONTS.update({
    "times": f"{F}/times.ttf",
    "timesi": f"{F}/timesi.ttf",
    "georgia": f"{F}/georgia.ttf",
    "georgiai": f"{F}/georgiai.ttf",
    "constan": f"{F}/constan.ttf",
    "constanb": f"{F}/constanb.ttf",
    "cambria": f"{F}/cambria.ttf",
    "cambriab": f"{F}/cambriab.ttf",
    "segoeui": f"{F}/segoeui.ttf",
    "segoeuib": f"{F}/segoeuib.ttf",
    "seguisb": f"{F}/seguisb.ttf",
})


def available(name: str) -> bool:
    return os.path.exists(imgtl.FONTS.get(name, ""))


# ---------------------------------------------------------------- probing


def opaque_box(img, thr: int = 20):
    """Bounding box of pixels above an alpha threshold."""
    return ink_bbox(img, thr=thr)


def glyph_box(img, box, pred, pad: int = 0):
    """Tight bbox of pixels matching ``pred`` inside ``box``.

    Japanese glyphs have detached strokes and deep descenders; measuring is the
    only way to size an erase rect that does not leave a stray dot behind.
    """
    x0, y0, x1, y1 = box
    px = img.load()
    xs, ys = [], []
    for y in range(y0, y1):
        for x in range(x0, x1):
            if pred(px[x, y]):
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return (max(x0, min(xs) - pad), max(y0, min(ys) - pad),
            min(x1, max(xs) + 1 + pad), min(y1, max(ys) + 1 + pad))


def sample_row(img, y, xs):
    px = img.load()
    cols = [px[x, y] for x in xs]
    return tuple(int(median(c[i] for c in cols)) for i in range(4))


# ---------------------------------------------------------------- erasing


def hfill(img, box, left_w: int = 14, right_w: int = 14):
    """Erase ``box`` by interpolating each row between the clean columns on
    either side of it.

    Reproduces a horizontal alpha ramp and a vertical gradient at once, which a
    flat ``fill_rect`` cannot, and leaves the banner edges untouched.
    """
    x0, y0, x1, y1 = box
    px = img.load()
    lx = range(max(0, x0 - left_w), max(1, x0))
    rx = range(min(img.width - 1, x1), min(img.width, x1 + right_w))
    if not len(lx) or not len(rx):
        raise ValueError("hfill needs clean columns on both sides of the box")
    for y in range(y0, y1):
        left = sample_row(img, y, lx)
        right = sample_row(img, y, rx)
        span = max(1, x1 - x0 - 1)
        for i, x in enumerate(range(x0, x1)):
            t = i / span
            px[x, y] = tuple(int(left[k] + (right[k] - left[k]) * t) for k in range(4))


def flatfill(img, box, sample_box):
    """Erase with the median colour of a verified-clean rectangle."""
    px = img.load()
    sx0, sy0, sx1, sy1 = sample_box
    cols = [px[x, y] for y in range(sy0, sy1) for x in range(sx0, sx1)]
    colour = tuple(int(median(c[i] for c in cols)) for i in range(4))
    fill_rect(img, (box[0], box[1], box[2] - 1, box[3] - 1), colour)
    return colour


# ---------------------------------------------------------------- rendering


def centered(img, box, s, fname, size, fill, stroke=0, stroke_fill=None):
    """Draw ``s`` centred in ``box``."""
    cx = (box[0] + box[2]) // 2
    cy = (box[1] + box[3]) // 2
    text(img, (cx, cy), s, fname, size, fill, stroke=stroke,
         stroke_fill=stroke_fill, anchor="mm")


def fit_centered(img, box, s, fname, fill, max_size, min_size=8,
                 pad=8, stroke=0, stroke_fill=None):
    """Largest size that fits the box width, then centred. Returns the size used."""
    limit = (box[2] - box[0]) - pad * 2
    size = max_size
    while size > min_size and text_width(s, fname, size) > limit:
        size -= 1
    centered(img, box, s, fname, size, fill, stroke=stroke, stroke_fill=stroke_fill)
    return size


def bilingual(img, anchor_xy, s, fname, size, fill, anchor="rm"):
    """The game's own house style: small English under the kept Japanese.

    Matches kigaeui/fukusoukuro.png - a Roman serif, right-aligned under the
    Japanese, in the same ink colour at roughly a third of its size.
    """
    text(img, anchor_xy, s, fname, size, fill, anchor=anchor)
