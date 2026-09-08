# -*- coding: utf-8 -*-
"""Build a clean plate by PIL-filling the masked text boxes from the ORIGINAL
background (no ML), for regions where Qwen's Object-Remover added haze/noise or
changed a coloured background (e.g. the 666 red banner, t13's black column).

Each box is filled with a vertical gradient sampled from a strip just above and
just below the box, so flat backgrounds fill solid and vertically-graded panels
match. Edges are feathered so the patch melts into the panel.
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

SRC = Path(r"C:/Users/sw/Desktop/Tools/C++/FModel/Output/Exports/NoEcstasyNoLife/Content/_IkaseruGame/UI/Tutorial/TutorialPagePics")
REG = Path("work/tut_regions")
OUT = Path("work/tut_plates")


def med(a):
    return tuple(int(np.median(a[..., c])) for c in range(3))


def fill_box(img, arr, box, grow=10, feather=6, strip=14):
    x0, y0, x1, y1 = box
    x0 = max(0, x0 - grow); y0 = max(0, y0 - grow)
    x1 = min(img.width, x1 + grow); y1 = min(img.height, y1 + grow)
    # sample background just above and below the box
    top = arr[max(0, y0 - strip):max(1, y0 - 2), x0:x1]
    bot = arr[min(arr.shape[0] - 1, y1 + 2):min(arr.shape[0], y1 + strip), x0:x1]
    ct = med(top) if top.size else med(arr[y0:y1, x0:x1])
    cb = med(bot) if bot.size else ct
    h, w = y1 - y0, x1 - x0
    grad = Image.new("RGB", (w, h))
    gd = ImageDraw.Draw(grad)
    for i in range(h):
        t = i / max(1, h - 1)
        gd.line([(0, i), (w, i)], fill=tuple(int(ct[c] + (cb[c] - ct[c]) * t) for c in range(3)))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rectangle([feather, feather, w - feather, h - feather], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(feather))
    img.paste(grad, (x0, y0), mask)


def build(name, grow=10, feather=6):
    img = Image.open(SRC / f"{name}.png").convert("RGB")
    arr = np.asarray(img).astype(int)
    rects = json.loads((REG / f"{name}.json").read_text())["rects"]
    for box in rects:
        fill_box(img, arr, box, grow=grow, feather=feather)
    OUT.mkdir(parents=True, exist_ok=True)
    img.convert("RGBA").save(OUT / f"{name}.png")
    print("clean plate:", name, len(rects), "boxes")


if __name__ == "__main__":
    for n in sys.argv[1:]:
        build(n)
