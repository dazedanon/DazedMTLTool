#!/usr/bin/env python3
"""Wardrobe and black-market buttons: data/image/kigaeui, data/image/blui

These are the one place the game already ships a bilingual house style - the
Japanese stays and a small Roman serif sits under it, right-aligned against the
plate's bottom-right corner (服装 / clothes, 髪型 / hair, 購入 / buy). Half the
buttons have it, half do not, and several that do are wrong: every 服装 variant
reads just "clothes" whatever is in the brackets, both 下着（他）and 下着（上）
read "underclothes_top", and all three undress buttons - 全て外す, 1つ外す and
外す - read a bare "Remove".

Two treatments, picked by whether the plate has room for a second line:

``subline``  the category buttons, where the Japanese sits in the upper two
             thirds. Keep the Japanese, erase whatever is in the sub-line band
             and set it correctly, in the shipped position and style.

``swap``     the market and wardrobe tabs, where the Japanese fills the whole
             plate and a sub-line would have to be drawn over it. These are
             relabelled like the rest of the UI, through ``relabel.erase``.

The sub-line band is erased with a local median inpaint rather than a flat fill
or a group stack: the band is a few pixels tall, the plates carry grunge that
differs slightly from button to button, and the type is thin enough that the
median of its own surroundings reconstructs the plate under it.

    python tools/scripts/imgwork/build_wardrobe.py [--only NAME]
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from statistics import median

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
WHITE = (235, 235, 235, 255)
BLACK = (34, 34, 34, 255)

#: canvas size -> the band the sub-line occupies, measured off the shipped
#: buttons that have one. The undress buttons' band starts far enough right to
#: clear 外す, at the cost of the last two rows of its tail.
BANDS: dict[tuple[int, int], tuple[int, int, int, int]] = {
    (155, 46): (25, 33, 153, 46),
    (155, 47): (25, 33, 153, 47),
    (154, 46): (25, 33, 152, 46),
    (147, 52): (84, 31, 145, 51),
    (146, 52): (84, 31, 144, 51),
}

#: file -> English sub-line. The Japanese is kept; only this line is set.
SUBLINE: dict[str, str] = {
    "kigaeui/hukusou_bzenkuro.png":       "clothes (all)",
    "kigaeui/hukusou_bzensiro.png":       "clothes (all)",
    "kigaeui/hukusou_ue_kuro.png":        "clothes (top)",
    "kigaeui/hukusou_ue_siro.png":        "clothes (top)",
    "kigaeui/hukusou_sita_kuro.png":      "clothes (btm)",
    "kigaeui/hukusou_sita_siro.png":      "clothes (btm)",
    "kigaeui/hukusou_hoka_kuro.png":      "clothes (etc.)",
    "kigaeui/hukusou_hoka_siro.png":      "clothes (etc.)",
    "kigaeui/sitagi_botan_ue_kuro.png":   "underwear (top)",
    "kigaeui/sitagi_botan_ue_siro.png":   "underwear (top)",
    "kigaeui/sitagi_botan_sita_kuro.png": "underwear (btm)",
    "kigaeui/sitagi_botan_sita_siro.png": "underwear (btm)",
    "kigaeui/sitagi_botan_hoka_kuro.png": "underwear (etc.)",
    "kigaeui/sitagi_botan_hoka_siro.png": "underwear (etc.)",
    "kigaeui/hoka_meiku_kuro.png":        "makeup",
    "kigaeui/hoka_meiku_siro.png":        "makeup",
    "kigaeui/sodekei_kuro.png":           "sleeves",
    "kigaeui/sodekei_siro.png":           "sleeves",
    "kigaeui/inmou_kuro.png":             "pubic hair",
    "kigaeui/inmou_siro.png":             "pubic hair",
    "kigaeui/mizugi_kuro.png":            "swimsuit",
    "kigaeui/mizugi_siro.png":            "swimsuit",
    "kigaeui/髪型(後)kuro.png":            "hair (back)",
    "kigaeui/髪型(後)siro.png":            "hair (back)",
    "blui/hukusou_bzenkuro.png":          "clothes (all)",
    "blui/hukusou_bzensiro.png":          "clothes (all)",
    "blui/hukusou_ue_kuro.png":           "clothes (top)",
    "blui/hukusou_ue_siro.png":           "clothes (top)",
    "blui/hukusou_sita_kuro.png":         "clothes (btm)",
    "blui/hukusou_sita_siro.png":         "clothes (btm)",
    "blui/hukusou_hoka_kuro.png":         "clothes (etc.)",
    "blui/hukusou_hoka_siro.png":         "clothes (etc.)",
    "blui/sitagi_botan_ue_kuro.png":      "underwear (top)",
    "blui/sitagi_botan_ue_siro.png":      "underwear (top)",
    "blui/sitagi_botan_sita_kuro.png":    "underwear (btm)",
    "blui/sitagi_botan_sita_siro.png":    "underwear (btm)",
    "blui/sitagi_botan_hoka_kuro.png":    "underwear (etc.)",
    "blui/sitagi_botan_hoka_siro.png":    "underwear (etc.)",
    "blui/sodekei_kuro.png":              "sleeves",
    "blui/sodekei_siro.png":              "sleeves",
    "blui/mizugi_kuro.png":               "swimsuit",
    "blui/mizugi_siro.png":               "swimsuit",
}

#: file -> (Japanese, English, light type?). The Japanese is erased and replaced.
#: The bare name is white type on a black plate; the ``s`` twin is its inverse.
SWAP: dict[str, tuple[str, str, bool]] = {
    "blui/kamigata.png":     ("髪型", "Hair", True),
    "blui/kamigatas.png":    ("髪型", "Hair", False),
    "blui/hukusou.png":      ("服装", "Clothes", True),
    "blui/hukusous.png":     ("服装", "Clothes", False),
    "blui/sitagi.png":       ("下着", "Underwear", True),
    "blui/sitagis.png":      ("下着", "Underwear", False),
    "blui/hukusyoku.png":    ("服飾", "Accessory", True),
    "blui/hukusyokus.png":   ("服飾", "Accessory", False),
    "blui/hoka.png":         ("他", "Etc.", True),
    "blui/hokas.png":        ("他", "Etc.", False),
    "blui/irib.png":         ("衣類系", "Clothing", True),
    "blui/iribs.png":        ("衣類系", "Clothing", False),
    "blui/sozaib_k.png":     ("素材系", "Materials", True),
    "blui/sozaib_s.png":     ("素材系", "Materials", False),
    "blui/wired_item.png":   ("怪しいアイテム", "Odd Items", True),
    "blui/wired_items.png":  ("怪しいアイテム", "Odd Items", False),
    "blui/keyk.png":         ("鍵類", "Keys", True),
    "blui/keys.png":         ("鍵類", "Keys", False),
    "blui/work_notice.png":  ("仕事依頼", "Work Request", False),
    "blui/work_notices.png": ("仕事依頼", "Work Request", False),
    "blui/sozaik.png":       ("素材", "Materials", True),
    "blui/sozais.png":       ("素材", "Materials", False),
    "blui/back.png":         ("戻る", "Back", True),
    "blui/backs.png":        ("戻る", "Back", False),
    "blui/work.png":         ("仕事依頼", "Work Request", True),
    # the undress trio ships all three as a bare "Remove"; there is no room for
    # a corrected sub-line beside 外す, so these are replaced outright
    "kigaeui/aout.png":      ("全て外す", "Remove All", True),
    "kigaeui/aouts.png":     ("全て外す", "Remove All", False),
    "kigaeui/oout.png":      ("1つ外す", "Remove One", True),
    "kigaeui/oouts.png":     ("1つ外す", "Remove One", False),
    "kigaeui/remove.png":    ("外す", "Remove", True),
    "kigaeui/remove_s.png":  ("外す", "Remove", False),
    "blui/works.png":        ("仕事依頼", "Work Request", False),
}

#: boxes the blob search gets wrong: the notice pair carries a red badge in the
#: top-right that the plate blob runs into
PINNED: dict[str, tuple[int, int, int, int]] = {
    "blui/work_notice.png":  (6, 46, 150, 104),
    "blui/work_notices.png": (6, 46, 150, 104),
    # the blob search stops two columns short of the canvas and strands the
    # tail of ム
    "blui/wired_item.png":   (0, 0, 119, 35),
    "blui/wired_items.png":  (0, 0, 119, 35),
}


def plate_tone(px, band) -> int:
    x0, y0, x1, y1 = band
    return Counter(sum(px[x, y][:3]) // 3
                   for y in range(y0, y1) for x in range(x0, x1)).most_common(1)[0][0]


def clear_band(img, band, tone, delta: int = 55, grow: int = 2, radius: int = 5) -> int:
    """Erase whatever type is in the band, keeping the plate's grunge."""
    x0, y0, x1, y1 = band
    source = img.copy()
    read, write = source.load(), img.load()
    hot = {(x, y) for y in range(y0, y1) for x in range(x0, x1)
           if read[x, y][3] > 100 and abs(sum(read[x, y][:3]) // 3 - tone) > delta}
    mask = {(x + dx, y + dy) for x, y in hot
            for dy in range(-grow, grow + 1) for dx in range(-grow, grow + 1)
            if x0 <= x + dx < x1 and y0 <= y + dy < y1}
    for x, y in sorted(mask):
        near = [read[u, v]
                for v in range(max(0, y - radius), min(img.height, y + radius + 1))
                for u in range(max(0, x - radius), min(img.width, x + radius + 1))
                if (u, v) not in mask]
        if near:
            write[x, y] = tuple(int(median(c[i] for c in near)) for i in range(4))
    return len(mask)


def build_subline(rel: str, english: str) -> None:
    img = Image.open(SRC / rel).convert("RGBA")
    band = BANDS.get(img.size)
    if band is None:
        print(f"    SKIP {rel}: no band measured for {img.size}")
        return
    tone = plate_tone(img.load(), band)
    touched = clear_band(img, band, tone)

    ink = BLACK if tone > 128 else WHITE
    limit = band[2] - band[0] - 2
    size = max(8, int(img.height * 0.26))
    while size > 8 and imgtl.text_width(english, FONT, size) > limit:
        size -= 1
    ajin.bilingual(img, (band[2] - 1, band[3] - 2), english, FONT, size, ink, anchor="rs")
    save(img, rel)
    print(f"    {rel:38s} {img.size} sub band={band} plate={tone:3d} "
          f"cleared={touched:4d} -> {english!r} @ {size}px")


def build_swap(rel: str, jp: str, english: str, light_type: bool) -> None:
    img = Image.open(SRC / rel).convert("RGBA")
    pinned = PINNED.get(rel)
    if pinned is not None:
        box, tone = pinned, plate_tone(img.load(), pinned)
    else:
        box, tone = relabel.plate_box(img, light_type, None)
    fill = relabel.fill_tone(img, box)
    light_plate = sum(fill[:3]) // 3 > 128
    painted, kept = relabel.erase(img, box, tone, fill)
    ink = BLACK if light_plate else WHITE
    height = box[3] - box[1]
    size = ajin.fit_centered(img, box, english, FONT, ink,
                             max_size=int(height * 0.62), min_size=9, pad=5)
    save(img, rel)
    print(f"    {rel:38s} {img.size} swap box={box} fill={fill[:3]} "
          f"painted={painted:5d} -> {english!r} @ {size}px")


def save(img, rel: str) -> None:
    out = OUT / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    args = ap.parse_args()
    for rel, english in SUBLINE.items():
        if args.only and args.only not in rel:
            continue
        if not (SRC / rel).exists():
            print(f"    MISSING {rel}")
            continue
        build_subline(rel, english)
    for rel, (jp, english, light_type) in SWAP.items():
        if args.only and args.only not in rel:
            continue
        if not (SRC / rel).exists():
            print(f"    MISSING {rel}")
            continue
        build_swap(rel, jp, english, light_type)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
