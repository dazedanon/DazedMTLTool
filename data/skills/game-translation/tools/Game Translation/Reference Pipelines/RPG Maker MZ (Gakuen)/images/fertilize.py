#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
fertilize.py - redraw the three `受精` overlay captions in English.

These are the only images in the game with baked player-facing text (confirmed
by the user against the full `img.zip`; the neighbouring `受精なるか……？！`,
`受精成功` and `受精演出途中` are framed anatomy art with no lettering, and the
title screen is deliberately left in Japanese).

Each one is a fully transparent 816x624 overlay with a single line of
handwritten kana in the top-left, so there is nothing to ERASE: the English is
drawn onto a fresh transparent canvas at the same anchor. That is the cleanest
case in `image-translation.md` - no background to reconstruct, no decoration to
preserve.

Measured from the originals (`audit/img_survey.py` + a per-pixel scan):

    受精…….png          text box x 170..477, y  90..163   soft pink  + white
    受精……sippai.png    text box x 170..785, y  90..163   dull grey  + white
    受精……成功！.png       text box x 170..729, y  88..163   magenta    + white

so all three share a left anchor of x=170 and a vertical band centred on y=126.
Keeping that anchor matters because the three are shown in sequence at the same
screen position - re-centring one of them would make the caption jump.

The typeface is the game's OWN `fonts/f910-shin-comic-2.04.otf`, which carries
both the handwritten look and a full Latin set, so the English reads as part of
the game rather than pasted on. It also has U+2665 HEART, which U+2764 - the
character the dialogue uses - is missing from.
"""

import os
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(HERE, "src")
OUT = os.path.join(HERE, "out")
FONT = os.path.join(ROOT, "fonts", "f910-shin-comic-2.04.otf")

W, H = 816, 624
LEFT = 170            # the shared left anchor of all three originals
BAND_MID = 126        # vertical centre of the original lettering band
RIGHT_MARGIN = 24
STROKE = 7            # the white halo, measured at 6-8 px on the originals

# fill colour sampled from each original's densest non-white, non-outline run
JOBS = [
    # (source filename, english, fill)
    ("受精…….png", "Fertilization...", (248, 132, 143, 255)),
    ("受精……sippai.png", "Fertilization... Failed...", (155, 155, 150, 255)),
    ("受精……成功！.png", "Fertilization... Success♥", (240, 0, 240, 255)),
]


def fit_font(text, max_w, max_h, start=88):
    """Largest size whose rendered box fits the original's band."""
    size = start
    while size > 12:
        f = ImageFont.truetype(FONT, size)
        box = f.getbbox(text, stroke_width=STROKE)
        if (box[2] - box[0]) <= max_w and (box[3] - box[1]) <= max_h:
            return f, box
        size -= 2
    return ImageFont.truetype(FONT, 12), ImageFont.truetype(
        FONT, 12).getbbox(text, stroke_width=STROKE)


def main():
    os.makedirs(OUT, exist_ok=True)
    if not os.path.exists(FONT):
        sys.exit("missing font: %s" % FONT)

    # ONE size for all three. They are shown in sequence at the same screen
    # position, so sizing each to its own width would make the caption jump
    # from 88 px to 50 px between frames - the original art keeps a single
    # handwriting size and lets the longer lines run wider.
    max_w = W - LEFT - RIGHT_MARGIN
    shared = min(fit_font(t, max_w, 96)[0].size for _n, t, _f in JOBS)
    print("shared font size: %d px" % shared)

    for name, text, fill in JOBS:
        src = os.path.join(SRC, name)
        if not os.path.exists(src):
            sys.exit("missing source: %s" % src)
        base = Image.open(src).convert("RGBA")
        if base.size != (W, H):
            sys.exit("%s is %s, expected %dx%d" % (name, base.size, W, H))

        # Nothing to erase - the caption is the only opaque thing on the
        # canvas, so a fresh transparent layer IS the erase.
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)

        font = ImageFont.truetype(FONT, shared)
        box = font.getbbox(text, stroke_width=STROKE)
        x = LEFT - box[0]
        y = BAND_MID - (box[1] + box[3]) // 2
        d.text((x, y), text, font=font, fill=fill,
               stroke_width=STROKE, stroke_fill=(255, 255, 255, 255))

        dst = os.path.join(OUT, name)
        img.save(dst)
        bb = img.getbbox()
        print("  %-24s %-30r size=%d  drawn bbox=%s"
              % (name, text, font.size, bb))
    print("\nwrote %d image(s) -> %s" % (len(JOBS), OUT))


if __name__ == "__main__":
    main()
