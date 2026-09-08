#!/usr/bin/env python3
"""Appearance selection cards: data/image/blui, data/image/kigaeui

The hair, makeup, accessory and body cards on the wardrobe and black-market
screens. Each is a 136x284 thumbnail with the item art on top and a caption
strip across the bottom - white type on a near-black plate, or its inverse on
the ``s`` hover twin.

Unlike the buttons there is no room for a second line here, so the caption is
replaced rather than annotated. The strip's interior is genuinely flat, which
makes this the one case in the image work where a plain fill is correct: the
white rule above the caption, the small centre mark below it and the corner
decoration all sit outside the box, and ``relabel.erase``'s per-row clip keeps
the paint inside the plate's own tone run.

The same twenty items appear three times over - numbered in blui, named in
kigaeui, and named again under kigaeui/hair_g for the greyed-out state - so the
table is keyed by caption and each entry lists every file that carries it.

Only the cards the scripts actually load are listed. blui also ships a full set
of underwear and clothing cards (2-*.png, boro, forma, katadasi, ...) that
``f.blbUI`` resolves to kigaeui instead, so those are dead copies.

    python tools/scripts/imgwork/build_cards.py [--only NAME]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent))

import ajin                                       # noqa: E402
import imgtl                                      # noqa: E402
import relabel                                    # noqa: E402

ROOT = HERE.parents[2]
SRC = ROOT / "extracted" / "images" / "data" / "image"
OUT = ROOT / "translated_images" / "data" / "image"

FONT = "times"
WHITE = (240, 240, 240, 255)
BLACK = (28, 28, 28, 255)

#: the caption's own ink band, measured from the card's bottom edge: the type
#: runs H-34..H-17 on every card, with flat plate above it to H-43 and below it
#: to H-4. Given as (left, top, right, bottom) with top and bottom counted back
#: from the canvas, so the 283- and 284-tall cards share one box.
BOX = (6, 36, 129, 15)

#: (Japanese, English) -> the stems that carry it. Each stem is expanded to
#: itself and its ``s`` hover twin.
CARDS: list[tuple[str, str, tuple[str, ...]]] = [
    ("ツーサイドアップ",  "Two Side Up",    ("blui/0-0", "kigaeui/tsu", "kigaeui/hair_g/tsu")),
    ("ツインテール",      "Twin Tails",     ("blui/0-1", "kigaeui/tt", "kigaeui/hair_g/tt")),
    ("ロングヘア",        "Long Hair",      ("blui/0-2", "kigaeui/lg", "kigaeui/hair_g/lg")),
    ("ショート(跳)",      "Short (Flip)",   ("blui/0-3", "kigaeui/sth", "kigaeui/hair_g/sth")),
    ("ショート",          "Short",          ("blui/0-4", "kigaeui/st", "kigaeui/hair_g/st")),
    ("ベリーショート",    "Very Short",     ("blui/0-5", "kigaeui/bst", "kigaeui/hair_g/bst")),
    ("ツーサイドアップ2", "Two Side Up 2",  ("blui/0-6", "kigaeui/tsu2", "kigaeui/hair_g/tsu2")),
    ("ツインテール2",     "Twin Tails 2",   ("blui/0-7", "kigaeui/tt2", "kigaeui/hair_g/tt2")),
    ("ロングヘア2",       "Long Hair 2",    ("blui/0-8", "kigaeui/lg2", "kigaeui/hair_g/lg2")),
    ("ショート2(跳)",     "Short 2 (Flip)", ("blui/0-9", "kigaeui/st2h", "kigaeui/hair_g/st2h")),
    ("ショート2",         "Short 2",        ("blui/0-10", "kigaeui/st2", "kigaeui/hair_g/st2")),
    ("ベリーショート2",   "Very Short 2",   ("blui/0-11", "kigaeui/bst2", "kigaeui/hair_g/bst2")),
    ("マスク",            "Mask",           ("blui/3-0", "kigaeui/mask")),
    ("チョーカー",        "Choker",         ("blui/3-1", "kigaeui/tyoka")),
    ("猫耳",              "Cat Ears",       ("blui/3-2", "kigaeui/nekomimi")),
    ("ヘアピン",          "Hairpin",        ("blui/3-3", "kigaeui/heapin")),
    ("眼鏡",              "Glasses",        ("blui/3-4", "kigaeui/megane")),
    ("ピアス(耳)",        "Ear Piercing",   ("blui/3-5", "kigaeui/piasumimi")),
    ("ピアス(臍)",        "Navel Piercing", ("blui/3-6", "kigaeui/piasuheso")),
    ("ピアス(顔)",        "Face Piercing",  ("blui/3-7", "kigaeui/piasukao")),
    ("手袋(長)",          "Long Gloves",    ("blui/4-1",)),
    ("目シャドー(黒)",    "Eyeshadow (Black)", ("blui/4-2",)),
    ("目シャドー(赤)",    "Eyeshadow (Red)",   ("blui/4-3",)),
    ("陰毛Lv1",           "Pubic Hair Lv1", ("blui/4-5",)),
    ("陰毛Lv2",           "Pubic Hair Lv2", ("blui/4-6",)),
    ("陰毛Lv3",           "Pubic Hair Lv3", ("blui/4-7",)),
    ("陰毛Lv4",           "Pubic Hair Lv4", ("blui/4-8",)),
    ("陰毛Lv5",           "Pubic Hair Lv5", ("blui/4-9",)),
    ("陰毛Lv0",           "Pubic Hair Lv0", ("blui/4-10",)),
]


def build(name: str, english: str) -> None:
    img = Image.open(SRC / name).convert("RGBA")
    width, height = img.size
    box = (BOX[0], height - BOX[1], BOX[2], height - BOX[3])
    tone_rgba = relabel.fill_tone(img, box)
    tone = sum(tone_rgba[:3]) // 3
    painted, kept = relabel.erase(img, box, tone, tone_rgba)

    ink = BLACK if tone > 128 else WHITE
    size = ajin.fit_centered(img, box, english, FONT, ink,
                             max_size=box[3] - box[1], min_size=8, pad=4)
    out = OUT / name
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    print(f"    {name:26s} {img.size} box={box} plate={tone:3d} "
          f"painted={painted:4d} rows_kept={kept} -> {english!r} @ {size}px")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    args = ap.parse_args()
    seen = 0
    for jp, english, stems in CARDS:
        for stem in stems:
            for name in (f"{stem}.png", f"{stem}s.png"):
                if args.only and args.only not in name:
                    continue
                if not (SRC / name).exists():
                    continue
                build(name, english)
                seen += 1
    print(f"  {seen} cards")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
