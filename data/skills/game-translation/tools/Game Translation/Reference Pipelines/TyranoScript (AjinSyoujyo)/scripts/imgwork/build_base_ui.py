#!/usr/bin/env python3
"""Home-screen menu tiles: data/image/base_ui/*.png

Every tile is a photo with a torn-edged label strip laid over it - black strip
with white text, or the ``_siro`` hover variant, white strip with black text.
The strip interior is uniform, so the glyphs are measured, erased by
interpolating across the strip row by row, and English is drawn back on the same
centre. The torn edges and the photo behind are never touched.

``_r`` files are the locked state: a padlock, no text, nothing to do.

    python tools/scripts/imgwork/build_base_ui.py [--only NAME]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent))

import ajin                                       # noqa: E402
import relabel                                    # noqa: E402
import imgtl                                      # noqa: E402

ROOT = HERE.parents[2]
imgtl.SRC = str(ROOT / "extracted" / "images" / "data" / "image" / "base_ui")
imgtl.OUT = str(ROOT / "translated_images" / "data" / "image" / "base_ui")

from imgtl import load, save                      # noqa: E402

WHITE = (255, 255, 255, 255)
BLACK = (20, 20, 20, 255)

#: stem -> (Japanese, preferred English, fallback if the preferred will not fit)
LABELS = {
    "burakkuma_ketto": ("闇市（買い物）", "Black Market", "Market"),
    "ecchi_suru":      ("エッチする",     "Have Sex",     "Sex"),
    "furo":            ("風呂",           "Bath",         "Bath"),
    "futou":           ("埠頭",           "Docks",        "Docks"),
    "kaiwa":           ("会話",           "Talk",         "Talk"),
    "kakure_ie":       ("部屋拡張",       "Expand Room",  "Expand"),
    "kigae":           ("着替え",         "Wardrobe",     "Clothes"),
    "kougai":          ("郊外",           "Outskirts",    "Outskirts"),
    "lab":             ("研究所",         "Research Lab", "Lab"),
    "shokuji":         ("食事",           "Meal",         "Meal"),
    "sigaiti":         ("市街地",         "City",         "City"),
    "souko":           ("倉庫",           "Storage",      "Storage"),
    "sukinshippu":     ("スキンシップ",   "Touch",        "Touch"),
    "sute_tasu":       ("ステータス",     "Status",       "Status"),
    "tansaku":         ("探索",           "Scavenge",     "Explore"),
    "woods":           ("森林地",         "Forest",       "Forest"),
    "youbou":          ("要望",           "Requests",     "Wants"),
}

#: file -> (label key, light text?)
#:
#: Two different naming conventions are at work. On the photo tiles, ``_siro``
#: is only the hover state - the strip lightens to grey but the type stays
#: white. On the small location plates, ``kuro``/``siro`` really are inverses:
#: black plate with white type, white plate with black type.
FILES: list[tuple[str, str, bool]] = [
    ("burakkuma_ketto.png",      "burakkuma_ketto", True),
    ("burakkuma_ketto_siro.png", "burakkuma_ketto", True),
    ("ecchi_suru.png",           "ecchi_suru",      True),
    ("ecchi_suru_siro.png",      "ecchi_suru",      True),
    ("furo.png",                 "furo",            True),
    ("furo_siro.png",            "furo",            True),
    ("futoukuro.png",            "futou",           True),
    ("futousiro.png",            "futou",           False),
    ("kaiwa.png",                "kaiwa",           True),
    ("kaiwa_siro.png",           "kaiwa",           True),
    ("kakure_ie.png",            "kakure_ie",       True),
    ("kakure_ie_siro.png",       "kakure_ie",       True),
    ("kigae.png",                "kigae",           True),
    ("kigae_siro.png",           "kigae",           True),
    ("kougaikuro.png",           "kougai",          True),
    ("kougaisiro.png",           "kougai",          False),
    ("labkuro.png",              "lab",             True),
    ("labsiro.png",              "lab",             False),
    ("shokuji.png",              "shokuji",         True),
    ("shokuji_siro.png",         "shokuji",         True),
    ("shokuji_u.png",            "shokuji",         True),
    ("sigaitikuro.png",          "sigaiti",         True),
    ("sigaitisiro.png",          "sigaiti",         False),
    ("souko.png",                "souko",           True),
    ("souko_siro.png",           "souko",           True),
    ("sukinshippu.png",          "sukinshippu",     True),
    ("sukinshippu_siro.png",     "sukinshippu",     True),
    ("sute_tasu.png",            "sute_tasu",       True),
    ("sute_tasu_siro.png",       "sute_tasu",       True),
    ("tansaku.png",              "tansaku",         True),
    ("tansaku_siro.png",         "tansaku",         True),
    ("woodskuro.png",            "woods",           True),
    ("woodssiro.png",            "woods",           False),
    ("youbou.png",               "youbou",          True),
    ("youbou_siro.png",          "youbou",          True),
    ("youbou_notice.png",        "youbou",          True),
    ("youbou_notice_siro.png",   "youbou",          True),
]

FONT = "times"

#: the Japanese fills about this fraction of its plate's height
TYPE_RATIO = 0.62

#: Seeds, not extents. These tiles have a grey plate lying on a grey photo, or a
#: dimmed state whose type is grey rather than white, so the blob search needs
#: telling *which* blob. The plate's real size is still measured from the blob -
#: an early version pinned the extent instead and the fill came out larger than
#: the plate, squaring off its rounded corners and eating the torn edge.
SEEDS: dict[str, tuple[int, int, int, int]] = {
    # A seed must land on bare plate, clear of the type - it supplies the plate's
    # tone, and a seed sitting on a glyph reads white and finds nothing.
    "burakkuma_ketto_siro.png": (60, 128, 440, 134),
    "shokuji.png":              (102, 46, 214, 50),
    "shokuji_u.png":            (104, 106, 214, 111),
    "souko.png":                (122, 90, 226, 94),
    "souko_siro.png":           (122, 90, 226, 94),
    "tansaku_siro.png":         (146, 186, 240, 190),
    "youbou_notice_siro.png":   (56, 176, 172, 180),
}

#: Erase boxes measured off a coordinate grid, for the two plates whose extent
#: cannot be found automatically: a dimmed plate whose tone matches the photo
#: behind it, and a translucent plate on a near-white photo. Pinning a box is
#: safe now that the paint is clipped per row to the plate's own tone - it was
#: not before, which is how the oversized slabs got out.
BOXES: dict[str, tuple[int, int, int, int]] = {
    "shokuji_u.png":    (100, 44, 214, 113),
    "tansaku_siro.png": (142, 182, 250, 230),
}

#: how far from the plate tone a pixel has to be to count as type. The default
#: suits white-on-black; the dimmed "unavailable" state is grey on black and
#: needs a smaller delta or its faintest strokes survive as a ghost.
GLYPH_DELTA: dict[str, int] = {
    "shokuji_u.png": 14,
}


def build(name: str, key: str, light_text: bool, verbose: bool = True) -> None:
    img = load(name)
    ink = WHITE if light_text else BLACK
    seed = SEEDS.get(name)
    if name in BOXES:
        box, tone = BOXES[name], relabel.seed_tone(img, seed)
    else:
        box, tone = relabel.plate_box(img, light_text, seed)
    fill = relabel.seed_colour(img, seed) if seed else relabel.fill_tone(img, box)
    painted, skipped = relabel.erase(img, box, tone, fill)

    jp, english, short = LABELS[key]
    height = box[3] - box[1]
    size = ajin.fit_centered(img, box, english, FONT, ink,
                             max_size=int(height * TYPE_RATIO), min_size=9, pad=4)
    # only swap in the short wording when the long one has shrunk to the
    # point of being hard to read, not merely because it had to shrink
    if size < int(height * TYPE_RATIO * 0.55) and short != english:
        img = load(name)                       # re-edit from source, never stack
        if name in BOXES:
            box, tone = BOXES[name], relabel.seed_tone(img, seed)
        else:
            box, tone = relabel.plate_box(img, light_text, seed)
        fill = relabel.seed_colour(img, seed) if seed else relabel.fill_tone(img, box)
        painted, skipped = relabel.erase(img, box, tone, fill)
        size = ajin.fit_centered(img, box, short, FONT, ink,
                                 max_size=int(height * TYPE_RATIO), min_size=9, pad=4)
        english = short
    save(img, name)
    if verbose:
        area = (box[2] - box[0]) * (box[3] - box[1])
        seeded = " (seeded)" if name in SEEDS else ""
        print(f"    {name:26s} box={box} painted={painted}/{area} "
              f"rows_kept={skipped} fill={fill[:3]} -> {english!r} @ {size}px{seeded}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    args = ap.parse_args()
    Path(imgtl.OUT).mkdir(parents=True, exist_ok=True)
    for name, key, light in FILES:
        if args.only and args.only not in name:
            continue
        build(name, key, light)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
