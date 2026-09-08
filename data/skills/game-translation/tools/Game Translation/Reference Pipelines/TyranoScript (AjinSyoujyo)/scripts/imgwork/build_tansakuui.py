#!/usr/bin/env python3
"""Scavenging-screen action plates: data/image/tansakuui/

Only seven of the 120 files in this folder carry text - the rest are item icons,
crates and arrow glyphs. Each plate is a light frame with a magnifier tail, and
**the inside of the frame is transparent, not dark**: what looks like a black
panel is the game's background showing through. So the type is erased to alpha,
never filled, and the dimmed ``s`` state keeps its faint translucent wash.

    python tools/scripts/imgwork/build_tansakuui.py
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent))

import ajin                                       # noqa: E402
import imgtl                                      # noqa: E402

ROOT = HERE.parents[2]
imgtl.SRC = str(ROOT / "extracted" / "images" / "data" / "image" / "tansakuui")
imgtl.OUT = str(ROOT / "translated_images" / "data" / "image" / "tansakuui")

from imgtl import load, save                      # noqa: E402

PLATES = {
    "脱出.png":     ("脱出",   "Escape"),
    "調べる1.png":  ("調べる", "Search"),
    "調べる1s.png": ("調べる", "Search"),
    "調べる2.png":  ("調べる", "Search"),
    "調べる2s.png": ("調べる", "Search"),
    "鍵開け.png":   ("鍵開け", "Pick Lock"),
    "鍵開けs.png":  ("鍵開け", "Pick Lock"),
}

FONT = "timesbd"
#: inside the frame, clear of the border on every side
#: the frame's horizontal bar ends at y=13; below that the plate is clear,
#: so the box may start at 14 and still catch the tips of the tall kanji.
MARGIN_X, TOP, BOTTOM = 18, 14, 83


def wash(img, box):
    """The plate's own backdrop inside the frame: transparent on the live
    plates, a faint translucent grey on the dimmed ones."""
    px = img.load()
    counts = Counter(px[x, y] for y in range(box[1], box[3])
                     for x in range(box[0], box[2]))
    return counts.most_common(1)[0][0]


def build(name: str) -> None:
    img = load(name)
    px = img.load()
    interior = (MARGIN_X, TOP, img.width - MARGIN_X, min(BOTTOM, img.height - 60))
    base = wash(img, interior)

    def is_glyph(x, y):
        return px[x, y][3] > base[3] + 40

    xs = [x for x in range(*interior[::2]) for y in range(interior[1], interior[3])
          if is_glyph(x, y)]
    ys = [y for y in range(interior[1], interior[3]) for x in range(interior[0], interior[2])
          if is_glyph(x, y)]
    if not xs:
        raise SystemExit(f"{name}: no type inside the frame")

    box = [min(xs), min(ys), max(xs) + 1, max(ys) + 1]
    limit = (box[0] - 10, box[1] - 10, box[2] + 10, box[3] + 10)
    for _ in range(12):                       # grow until the edges are clean
        grew = False
        for side, (dx, dy) in enumerate(((0, -1), (0, 1), (-1, 0), (1, 0))):
            if side < 2:
                row = box[1] - 1 if side == 0 else box[3]
                if (interior[1] <= row < interior[3] and row >= limit[1]
                        and row <= limit[3] and any(
                        px[x, row][3] > base[3] + 12 for x in range(box[0], box[2]))):
                    box[1 if side == 0 else 3] += -1 if side == 0 else 1
                    grew = True
            else:
                col = box[0] - 1 if side == 2 else box[2]
                if (interior[0] <= col < interior[2] and col >= limit[0]
                        and col <= limit[2] and any(
                        px[col, y][3] > base[3] + 12 for y in range(box[1], box[3]))):
                    box[0 if side == 2 else 2] += -1 if side == 2 else 1
                    grew = True
        if not grew:
            break
    box = (max(interior[0], box[0] - 1), max(interior[1], box[1] - 1),
           min(interior[2], box[2] + 1), min(interior[3], box[3] + 1))

    # the most opaque bright pixel, not merely the brightest - an antialiased
    # edge can be pure white at alpha 80 and would wash the English out
    ink = max((px[x, y] for y in range(box[1], box[3]) for x in range(box[0], box[2])
               if px[x, y][3] > base[3] + 40), key=lambda p: (p[3], sum(p[:3])))
    ajin.fill_rect(img, (box[0], box[1], box[2] - 1, box[3] - 1), base)

    english = PLATES[name][1]
    size = int((box[3] - box[1]) * 0.86)
    while size > 10 and ajin.text_width(english, FONT, size) > (box[2] - box[0]) - 10:
        size -= 1
    centre = ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
    shadow = (0, 0, 0, min(200, ink[3]))
    imgtl.shadow_text(img, centre, english, FONT, size, ink,
                      shadow=shadow, offset=(3, 3), blur=0.6, anchor="mm")
    save(img, name)
    print(f"    {name:16s} box={box} wash={base} ink={ink} -> {english!r} @ {size}px")


def main() -> int:
    Path(imgtl.OUT).mkdir(parents=True, exist_ok=True)
    for name in PLATES:
        build(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
