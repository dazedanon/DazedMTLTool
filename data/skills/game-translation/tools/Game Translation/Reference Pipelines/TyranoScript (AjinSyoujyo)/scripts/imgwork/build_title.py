#!/usr/bin/env python3
"""Title-menu banners: data/image/title/*.png

Six labels x two states (dark idle / white hover). The banner is flat inside the
text area - the diagonal metal streak lives past x~335 and the soft smudge below
x~95 - so the glyphs are measured, erased with a per-row interpolation from the
clean columns beside them, and English is drawn on the same centre in a Roman
serif to match the mincho original.

``button_config.png`` and its hover twin are left alone: they are a pink pill
from the save/load plugin reading コンフィグ, and their only reference in the
whole app is a commented-out `[button]` in home/hnomal.ks. The title menu's own
設定 banner is the one the player sees.

    python tools/scripts/imgwork/build_title.py
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent))

import ajin                                       # noqa: E402
import imgtl                                      # noqa: E402

ROOT = HERE.parents[2]
imgtl.SRC = str(ROOT / "extracted" / "images" / "data" / "image" / "title")
imgtl.OUT = str(ROOT / "translated_images" / "data" / "image" / "title")

from imgtl import load, save                      # noqa: E402

WHITE = (255, 255, 255, 255)
BLACK = (30, 30, 30, 255)

#: file stem -> (Japanese, English). ``_s`` is the hover state of each.
LABELS = {
    "start":    ("最初から",   "New Game"),
    "continue": ("続きから",   "Continue"),
    "autosave": ("オートセーブ", "Auto Save"),
    "kaisou":   ("回想",       "Replay"),
    "settei":   ("設定",       "Config"),
    "end":      ("終了",       "Exit"),
}

FONT = "times"
MAX_SIZE = 38
BAND = (4, 4, 396, 52)      # search window for glyphs, inside the banner edges



def build(stem: str, hover: bool) -> None:
    name = f"{stem}_s.png" if hover else f"{stem}.png"
    img = load(name)
    ink = BLACK if hover else WHITE

    if hover:
        pred = (lambda p: p[3] > 120 and (p[0] + p[1] + p[2]) / 3 < 120)
    else:
        pred = (lambda p: p[3] > 120 and (p[0] + p[1] + p[2]) / 3 > 190)

    box = ajin.glyph_box(img, BAND, pred, pad=4)
    if box is None:
        raise SystemExit(f"{name}: no glyphs found")

    ajin.hfill(img, box, left_w=12, right_w=12)
    size = ajin.fit_centered(img, box, LABELS[stem][1], FONT, ink,
                             max_size=MAX_SIZE, pad=2)
    save(img, name)
    print(f"    {name:16s} glyphs={box} -> {LABELS[stem][1]!r} @ {size}px")



def main() -> int:
    Path(imgtl.OUT).mkdir(parents=True, exist_ok=True)
    for stem in LABELS:
        for hover in (False, True):
            build(stem, hover)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
