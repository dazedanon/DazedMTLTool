#!/usr/bin/env python3
"""Full-screen UI frames: data/fgimage

The 1920x1080 backdrops the status, storage and scavenge-result screens are
drawn on,
with every heading baked in. They were missed by the first image sweep because
`image_review.py` scores `data/fgimage/` as artwork - true for the 2,200
character sprites in there, wrong for these frames.

Each heading sits on its own plate: a black tab with white type, or the light
grey panel with dark type. The plates all touch the frame's dark border, so a
connected-blob search floods the whole frame; these get explicit search windows
instead and the type is measured inside each one.

Erasing has two modes.

``flat``    ``relabel.erase`` - modal colour, painted through a per-row clip.
            Right for a plate that really is one colour.

``patch``   reconstruct each covered pixel from a *clean row* of the same plate
            and replace only the pixels that differ from it. Needed wherever the
            plate is not one colour:

            * the black tabs carry a lighter (52,52,52) border strip down their
              left edge. A flat erase tuned to the (24,24,24) field skips it, so
              the first sliver of 開 survived on 開発度-陰部.
            * the header's light plate is cut off by a diagonal edge with the
              background photo showing through beyond it, and 体重 straddles it.

            Replacing only the differing pixels also leaves the plate's shipped
            grain alone, which a flat fill destroys.

    python tools/scripts/imgwork/build_screens.py [--probe]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent))

import ajin                                       # noqa: E402
import imgtl                                      # noqa: E402
import relabel                                    # noqa: E402

ROOT = HERE.parents[2]
imgtl.SRC = str(ROOT / "extracted" / "images" / "data" / "fgimage")
imgtl.OUT = str(ROOT / "translated_images" / "data" / "fgimage")

from imgtl import load, save                      # noqa: E402

WHITE = (255, 255, 255, 255)
DARK = (40, 40, 40, 255)

#: The header's diagonal edge, as ``(clean row, edge x, at row y, px per row)``.
#: Measured between y=82 and y=126, which is clear of the type. The clean row has
#: to be *above* the type (44..79 here): the edge leans right going down, so a
#: row below hands back opaque plate for exactly the columns that need photo.
EDGE = (41, 845, 82, 1.25)

#: (search window, Japanese, English, light type?, options)
#: options: ``patch`` = ``(clean row,)`` or ``EDGE``; ``size`` = forced max px.
#: The ステータス tab is left alone - it already reads "status" underneath, which
#: is the game's own bilingual convention.
STATUS = [
    ((296, 12, 405, 88),       "名前",         "Name",     False, {}),
    ((408, 8, 528, 92),        "ココ",         "Koko",     False, {}),
    ((558, 12, 675, 88),       "身長",         "Height",   False, {}),
    ((776, 29, 905, 93),       "体重",         "Weight",   False, {"patch": EDGE}),
    ((4, 142, 215, 198),       "各パラメーター", "Stats",    True,  {}),
    ((4, 642, 215, 698),       "貴方への想い",  "Feelings", True,  {}),
    ((4, 818, 215, 878),       "各種感度",      "Senses",   True,  {}),
    ((1015, 238, 1295, 298),   "開発度-口",     "Mouth",    True,  {}),
    ((1015, 512, 1295, 572),   "開発度-胸",     "Breasts",  True,  {}),
    ((1015, 784, 1290, 830),   "開発度-陰部",   "Genitals", True,  {"patch": (830,), "size": 41}),
    # the frame ends at y=1080 mid-tab, so this box is far shorter than its
    # siblings' and the height heuristic would draw it a third smaller
    ((1015, 1042, 1290, 1080), "開発度-尻穴",   "Anus",     True,  {"patch": (1079,), "size": 41}),
]

#: The storage frame's two plates are parallelograms far wider than the two- and
#: three-glyph headings on them, so the erase box is a poor guide for where the
#: English can go - both get an explicit ``draw`` box spanning the plate's
#: straight-sided interior, and a shared size, since a per-plate fit would set
#: "Items" half again bigger than "Materials" right beside it.
SOUKO = [
    ((50, 18, 268, 92),  "所持品", "Items",     False,
     {"size": 54, "draw": (44, 23, 276, 87)}),
    ((700, 18, 850, 92), "素材",   "Materials", False,
     {"size": 54, "draw": (668, 23, 886, 87)}),
]

#: the scavenge-result frame. 戦利品 appears nowhere in the scripts, so this
#: image is the only place the player is told what the panel holds.
HOUP = [
    ((1315, 534, 1601, 609), "戦利品", "Loot", True, {}),
]

FONT = "times"


def edit(img, window, english, light, patch=None, size=None, draw=None,
         font=FONT, ratio=0.72):
    """Erase the type inside ``window`` and draw ``english`` on the same centre."""
    px = img.load()
    tone = tone_rgba = None

    if patch is None:
        tone_rgba = relabel.fill_tone(img, window)
        tone = sum(tone_rgba[:3]) // 3

        def is_type(x, y):
            p = px[x, y]
            return p[3] > 140 and abs(sum(p[:3]) // 3 - tone) > 55
    else:
        if len(patch) == 1:
            source_row, = patch

            def plate(x, y):
                return px[x, source_row]
        else:
            source_row, edge_x, edge_y, slope = patch
            opaque = px[window[0] - 6, source_row]

            def plate(x, y):
                return opaque if x < edge_x + slope * (y - edge_y) else px[x, source_row]

        def is_type(x, y):
            p, q = px[x, y], plate(x, y)
            return p[3] > 140 and abs(sum(p[:3]) // 3 - sum(q[:3]) // 3) > 50

    xs = [x for x in range(window[0], window[2])
          for y in range(window[1], window[3]) if is_type(x, y)]
    ys = [y for y in range(window[1], window[3])
          for x in range(window[0], window[2]) if is_type(x, y)]
    if not xs:
        raise SystemExit(f"no type found in {window}")
    box = (max(window[0], min(xs) - 4), max(window[1], min(ys) - 4),
           min(window[2], max(xs) + 5), min(window[3], max(ys) + 5))

    if patch is None:
        relabel.erase(img, box, tone, tone_rgba)
    else:
        # dilated by 2 so the type's antialiased fringe goes with it
        def near(x, y):
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    if (0 <= x + dx < img.width and 0 <= y + dy < img.height
                            and is_type(x + dx, y + dy)):
                        return True
            return False

        doomed = [(x, y) for y in range(box[1], box[3]) for x in range(box[0], box[2])
                  if near(x, y)]
        for x, y in doomed:
            px[x, y] = plate(x, y)
        tone_rgba = plate((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)

    ink = WHITE if light else DARK
    height = box[3] - box[1]
    drawn = ajin.fit_centered(img, draw or box, english, font, ink,
                              max_size=size or max(10, int(height * ratio)),
                              min_size=10, pad=3)
    return box, tone_rgba, drawn


def probe(name, spec):
    from PIL import ImageDraw
    img = load(name)
    draw = ImageDraw.Draw(img)
    for window, jp, en, light, opts in spec:
        draw.rectangle([window[0], window[1], window[2] - 1, window[3] - 1],
                       outline=(255, 40, 40, 255), width=3)
    out = Path(imgtl.OUT) / f"_probe_{Path(name).stem}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out)
    print("  probe ->", out)


def build(name, spec):
    img = load(name)
    for window, jp, en, light, opts in spec:
        box, fill, size = edit(img, window, en, light, **opts)
        print(f"    {jp:12s} -> {en:12s} box={box} fill={fill[:3]} @{size}px")
    (Path(imgtl.OUT) / name).parent.mkdir(parents=True, exist_ok=True)
    save(img, name)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    args = ap.parse_args()
    Path(imgtl.OUT).mkdir(parents=True, exist_ok=True)
    jobs = [("status/status.png", STATUS), ("souko.png", SOUKO),
            ("houp2.png", HOUP)]
    for name, spec in jobs:
        print(f"-- {name}")
        (probe if args.probe else build)(name, spec)
    if not args.probe:
        # data/bgimage/souko.png is byte-identical to the fgimage copy; the
        # storage screen loads the fgimage one, but keep the pair in step
        twin = ROOT / "translated_images" / "data" / "bgimage" / "souko.png"
        twin.parent.mkdir(parents=True, exist_ok=True)
        twin.write_bytes((Path(imgtl.OUT) / "souko.png").read_bytes())
        print("  mirrored ->", twin)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
