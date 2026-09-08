#!/usr/bin/env python3
"""Draw proposed erase boxes onto a contact sheet so they can all be checked at once.

Auto-detection on photo-backed label strips is unreliable enough that every box
gets looked at before anything is written. Boxes that are wrong get pinned in the
caller's geometry table; this script is how they are spotted.

    python tools/scripts/imgwork/probe_boxes.py base_ui
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent))

ROOT = HERE.parents[2]
SRC = ROOT / "extracted" / "images"
OUT = ROOT / "extracted" / "image_sheets"

CELL_W, CELL_H, LABEL_H, COLS = 330, 230, 26, 4


def sheet(entries, title, path):
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/consola.ttf", 13)
    except OSError:
        font = ImageFont.load_default()
    rows = (len(entries) + COLS - 1) // COLS
    canvas = Image.new("RGBA", (COLS * CELL_W, rows * (CELL_H + LABEL_H) + 30), (24, 24, 24, 255))
    draw = ImageDraw.Draw(canvas)
    draw.text((8, 8), title, fill=(255, 220, 120, 255), font=font)
    for index, (name, img, box, note) in enumerate(entries):
        col, row = index % COLS, index // COLS
        x0 = col * CELL_W
        y0 = row * (CELL_H + LABEL_H) + 30
        view = img.copy()
        if box:
            ImageDraw.Draw(view).rectangle([box[0], box[1], box[2] - 1, box[3] - 1],
                                           outline=(255, 40, 40, 255), width=2)
        scale = min((CELL_W - 12) / view.width, (CELL_H - 12) / view.height, 2.0)
        view = view.resize((max(1, int(view.width * scale)), max(1, int(view.height * scale))),
                           Image.LANCZOS)
        tile = Image.new("RGBA", view.size, (110, 110, 110, 255))
        tile.alpha_composite(view)
        canvas.alpha_composite(tile, dest=(x0 + (CELL_W - view.width) // 2,
                                           y0 + (CELL_H - view.height) // 2))
        draw.rectangle([x0 + 2, y0 + 2, x0 + CELL_W - 4, y0 + CELL_H - 4], outline=(70, 70, 70, 255))
        draw.text((x0 + 6, y0 + CELL_H - 2), f"{name[:34]}", fill=(215, 215, 215, 255), font=font)
        draw.text((x0 + 6, y0 + CELL_H + 11), f"  {note}", fill=(150, 190, 150, 255), font=font)
    canvas.convert("RGB").save(path)
    print("  ", path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("family")
    args = ap.parse_args()

    if args.family == "base_ui":
        import build_base_ui as B
        import imgtl
        imgtl.SRC = str(SRC / "data" / "image" / "base_ui")
        from imgtl import load
        entries = []
        for name, key, dark in B.FILES:
            img = load(name)
            try:
                box = B.locate(img, dark)
                note = f"{box}"
            except Exception as exc:                      # noqa: BLE001
                box, note = None, f"FAIL {exc}"
            entries.append((name, img, box, note))
        for offset in range(0, len(entries), COLS * 3):
            sheet(entries[offset:offset + COLS * 3], f"base_ui boxes [{offset}]",
                  OUT / f"probe_base_ui_{offset // (COLS * 3):02d}.png")
    else:
        raise SystemExit(f"unknown family {args.family}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
