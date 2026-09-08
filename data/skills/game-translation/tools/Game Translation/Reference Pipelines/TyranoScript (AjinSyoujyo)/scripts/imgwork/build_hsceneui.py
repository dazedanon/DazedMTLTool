#!/usr/bin/env python3
"""H-scene command buttons: data/image/hsceneui/*.png

Forty-two small plates - black rounded rectangle, white type, a wispy grey
grunge streak across the bottom, and on some a pink corner flash for the
selected state.

The grunge is what makes these awkward. `relabel.erase` paints the plate flat,
which wipes it; a brightness threshold cannot separate the glyphs' dark halo
from the grunge, because the two overlap completely in tone (the plate sits at
15, the grunge runs 20..200 and so does the halo).

What does separate them is that **every tile of a given size is the same plate
art with the type in a different place**, so a per-pixel estimate across a size
group recovers the bare plate and the erase then needs no threshold at all -
repaint whatever differs from the donor.

Which estimate matters. Across the 23 samples at one pixel most are bare plate,
some are glyph core (bright) and some are the glyph's drop shadow (darker than
the plate). So:

* the minimum tracks the shadow, not the plate - every erase came out as a dark
  ghost of the Japanese;
* the median is right almost everywhere but fails on the pixels where more than
  half the tiles happen to be inked, leaving white specks.

``plate_stack`` takes the mode instead: the densest cluster of samples, which is
bare plate as long as no single glyph position is the majority. A despeckle pass
then catches whatever the cluster still got wrong on the small groups.

Pink corner flashes are excluded from the mask by saturation, not position, since
the donor is bare plate wherever a tile has a flash.

Three tiles are a pixel taller or shorter than their group and so miss it by
size alone, but the art is the same: ``ALIGN`` gives each the offset that lines
it up with a donor, found by scoring every offset in +/-2 and keeping the one
whose non-glyph pixels agree to within 3/255. Every tile the game actually loads
is covered that way; the local median inpaint is kept as the fallback for a tile
with no group at all.

    python tools/scripts/imgwork/build_hsceneui.py [--only NAME] [--sheet]
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from statistics import median

from PIL import Image

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent))

import ajin                                       # noqa: E402
import imgtl                                      # noqa: E402
import relabel                                    # noqa: E402

ROOT = HERE.parents[2]
imgtl.SRC = str(ROOT / "extracted" / "images" / "data" / "image" / "hsceneui")
imgtl.OUT = str(ROOT / "translated_images" / "data" / "image" / "hsceneui")

from imgtl import load, save                      # noqa: E402

WHITE = (255, 255, 255, 255)
FONT = "times"

#: the Japanese fills about this fraction of its plate's height
TYPE_RATIO = 0.62

#: file -> (Japanese, preferred English, fallback when the preferred shrinks
#: below legibility). Wordings follow the ones the script already uses:
#: フェラ -> Blowjob, 正常位 -> Missionary, 前戯 -> Foreplay, 道具 -> Tools,
#: 髪コキ -> hair-job, and 服飾 -> accessory from the game's own bilingual
#: wardrobe labels.
LABELS: dict[str, tuple[str, str, str]] = {
    "anal.png":         ("アナル",       "Anal",         "Anal"),
    "anal_ball.png":    ("アナルボール", "Anal Beads",   "Beads"),
    "anal_plug.png":    ("アナルプラグ", "Anal Plug",    "Plug"),
    "anal_sippo.png":   ("アナル尻尾",   "Tail Plug",    "Tail"),
    "anal_t.png":       ("アナル",       "Anal",         "Anal"),
    "auto.png":         ("オート",       "Auto",         "Auto"),
    "back.png":         ("戻る",         "Back",         "Back"),
    "bakku.png":        ("バック",       "Doggy",        "Doggy"),
    "danmen.png":       ("断面図表示",   "Cutaway On",   "Cutaway"),
    "danmen_h.png":     ("断面図非表示", "Cutaway Off",  "No Cutaway"),
    "deirudo.png":      ("ディルド",     "Dildo",        "Dildo"),
    "dougu.png":        ("道具",         "Tools",        "Tools"),
    "fera.png":         ("フェラ",       "Blowjob",      "Blowjob"),
    "fukuhoka.png":     ("服（他）",     "Other",        "Other"),
    "fukusita.png":     ("服（下）",     "Bottoms",      "Bottoms"),
    "fukusyoku.png":    ("服飾",         "Accessory",    "Accessory"),
    "fukuue.png":       ("服（上）",     "Tops",         "Tops"),
    "fukuzen.png":      ("服（全）",     "All",          "All"),
    "gomu.png":         ("ゴム",         "Condom",       "Condom"),
    "hagesiku.png":     ("激しく",       "Faster",       "Faster"),
    "haimenbakku.png":  ("背面バック",   "Rear Entry",   "Rear"),
    "hoka.png":         ("他",           "Other",        "Other"),
    "hoka2.png":        ("他2",          "Other 2",      "Other 2"),
    "ingo_settei.png":  ("淫語設定",     "Lewd Words",   "Lewd"),
    "kamikoki.png":     ("髪コキ",       "Hair Job",     "Hair"),
    "ketuana.png":      ("尻穴",         "Anus",         "Anus"),
    "kuri.png":         ("クリ",         "Clit",         "Clit"),
    "modoru.png":       ("戻る",         "Back",         "Back"),
    "mune.png":         ("胸",           "Breasts",      "Breasts"),
    "nuku.png":         ("抜く",         "Pull Out",     "Pull Out"),
    "seijyoui.png":     ("正常位",       "Missionary",   "Missionary"),
    "setei.png":        ("設定",         "Settings",     "Settings"),
    "sitagihoka.png":   ("下着（他）",   "Lingerie",     "Lingerie"),
    "sitagisita.png":   ("下着（下）",   "Panties",      "Panties"),
    "sitagiue.png":     ("下着（上）",   "Bra",          "Bra"),
    "sode.png":         ("袖",           "Sleeves",      "Sleeves"),
    "sounyuu.png":      ("挿入",         "Insert",       "Insert"),
    "titu.png":         ("膣",           "Vagina",       "Vagina"),
    "titunai.png":      ("膣内",         "Inside",       "Inside"),
    "yukkuri.png":      ("ゆっくり",     "Slower",       "Slower"),
}

#: no type on these - a padlock, a hit-test rectangle and an effect strip.
#: 前戯.png is a dead asset: nothing under resources/app references it, it is the
#: only tile drawn inverted (dark type on a white plate), and it is alone at its
#: size, so there is no donor for it either.
SKIP = {"click_range.png", "ef.png", "lock.png", "locks.png", "前戯.png"}

#: tile -> (donor size, dx, dy) for the tiles whose canvas is off by a pixel
ALIGN: dict[str, tuple[tuple[int, int], int, int]] = {
    "titu.png":     ((120, 62), 0, -1),
    "ketuana.png":  ((119, 62), 0, 0),
    "seijyoui.png": ((235, 43), 0, 1),
}

#: tiles drawn the other way up: black type on a white plate
DARK_TYPE: set[str] = set()

BLACK = (25, 25, 25, 255)


def groups() -> dict[tuple[int, int], list[str]]:
    """Tile names by exact canvas size; only sizes with a stackable group."""
    out: dict[tuple[int, int], list[str]] = defaultdict(list)
    for path in sorted(Path(imgtl.SRC).glob("*.png")):
        out[Image.open(path).size].append(path.name)
    return out


def mode_pixel(samples, spread: int = 60):
    """The sample at the centre of the densest run within ``spread`` tone units."""
    ordered = sorted(samples, key=lambda p: sum(p[:3]))
    best_i, best_n = 0, 0
    lo = 0
    for hi in range(len(ordered)):
        while sum(ordered[hi][:3]) - sum(ordered[lo][:3]) > spread * 3:
            lo += 1
        if hi - lo + 1 > best_n:
            best_n, best_i = hi - lo + 1, (lo + hi) // 2
    return ordered[best_i]


def plate_stack(names: list[str]) -> Image.Image:
    """Per-pixel mode across the group - the plate with every glyph removed."""
    images = [load(n) for n in names]
    width, height = images[0].size
    reads = [im.load() for im in images]
    plate = Image.new("RGBA", (width, height))
    write = plate.load()
    for y in range(height):
        for x in range(width):
            write[x, y] = mode_pixel([r[x, y] for r in reads])
    return despeckle(plate)


def despeckle(plate, radius: int = 2, delta: int = 30) -> Image.Image:
    """Pull isolated bright pixels back to their neighbourhood.

    Cleans the specks a small group's mode cannot resolve. The grunge wisps are
    several pixels wide and survive a radius-2 median; a stray glyph pixel does
    not.
    """
    source = plate.copy()
    read, write = source.load(), plate.load()
    for y in range(plate.height):
        for x in range(plate.width):
            near = [read[u, v]
                    for v in range(max(0, y - radius), min(plate.height, y + radius + 1))
                    for u in range(max(0, x - radius), min(plate.width, x + radius + 1))]
            mid = tuple(int(median(c[i] for c in near)) for i in range(4))
            if sum(read[x, y][:3]) // 3 - sum(mid[:3]) // 3 > delta:
                write[x, y] = mid
    return plate


def neutral(pixel, limit: int = 30) -> bool:
    """True for greys. The pink selected-state corner is not one."""
    return max(pixel[:3]) - min(pixel[:3]) <= limit


def erase_against(img, plate, offset=(0, 0), delta: int = 12, grow: int = 1) -> int:
    """Repaint every grey pixel that differs from the bare plate."""
    px, pp = img.load(), plate.load()
    ox, oy = offset

    def donor(x, y):
        return pp[min(plate.width - 1, max(0, x + ox)),
                  min(plate.height - 1, max(0, y + oy))]

    hot = {(x, y) for y in range(img.height) for x in range(img.width)
           if neutral(px[x, y])
           and abs(sum(px[x, y][:3]) - sum(donor(x, y)[:3])) // 3 > delta}
    mask = {(x + dx, y + dy) for x, y in hot
            for dy in range(-grow, grow + 1) for dx in range(-grow, grow + 1)
            if 0 <= x + dx < img.width and 0 <= y + dy < img.height}
    for x, y in mask:
        if neutral(px[x, y]):
            px[x, y] = donor(x, y)
    return len(mask)


def inpaint(img, box, light_type: bool = True, threshold: int = 150,
            inset: int = 5, grow: int = 2, radius: int = 6) -> int:
    """Fallback for a tile with no group: local median over the glyph strokes.

    Keeps the grunge, which a flat fill would not, at the cost of a faint halo
    where the glyph's dark outline reaches past the mask.
    """
    x0, y0 = box[0] + inset, box[1] + inset
    x1, y1 = box[2] - inset, box[3] - inset
    source = img.copy()
    read, write = source.load(), img.load()
    def inked(x, y):
        if read[x, y][3] <= 100:
            return False
        level = sum(read[x, y][:3]) // 3
        return level > threshold if light_type else level < 255 - threshold

    hot = {(x, y) for y in range(y0, y1) for x in range(x0, x1) if inked(x, y)}
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


def text_box(img):
    """Where the type may go: the plate blob, or the opaque canvas if the blob
    search cannot separate plate from border (the small odd-sized tiles)."""
    try:
        return relabel.plate_box(img, True, None)[0]
    except ValueError:
        x0, y0, x1, y1 = ajin.opaque_box(img)
        return (x0 + 3, y0 + 3, x1 - 3, y1 - 3)


def build(name: str, plate, offset=(0, 0), verbose: bool = True) -> None:
    jp, english, short = LABELS[name]
    light_type = name not in DARK_TYPE
    ink = WHITE if light_type else BLACK
    img = load(name)
    box = text_box(img)

    def clean(target):
        if plate is not None:
            return erase_against(target, plate, offset), "stack"
        return inpaint(target, box, light_type), "inpaint"

    touched, how = clean(img)
    height = box[3] - box[1]
    cap = int(height * TYPE_RATIO)
    size = ajin.fit_centered(img, box, english, FONT, ink,
                             max_size=cap, min_size=9, pad=5)
    if size < int(cap * 0.55) and short != english:
        img = load(name)
        touched, how = clean(img)
        english = short
        size = ajin.fit_centered(img, box, english, FONT, ink,
                                 max_size=cap, min_size=9, pad=5)
    save(img, name)
    if verbose:
        print(f"    {name:18s} {jp:8s} box={box} {how} touched={touched:5d} "
              f"-> {english!r} @ {size}px")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    args = ap.parse_args()
    Path(imgtl.OUT).mkdir(parents=True, exist_ok=True)

    by_size = groups()
    plates: dict[tuple[int, int], Image.Image] = {}
    for size, names in by_size.items():
        usable = [n for n in names if n not in SKIP]
        if len(usable) >= 3:
            plates[size] = plate_stack(usable)
            print(f"  plate {size} from {len(usable)} tiles")

    for size, names in sorted(by_size.items()):
        for name in names:
            if name in SKIP or name not in LABELS:
                continue
            if args.only and args.only not in name:
                continue
            donor_size, ox, oy = ALIGN.get(name, (size, 0, 0))
            build(name, plates.get(donor_size), (ox, oy))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
