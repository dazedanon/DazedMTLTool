#!/usr/bin/env python3
"""Contact sheets for bulk visual classification.

3,400 images is far too many to open one at a time, so they go onto numbered
grids that can be read in one look. Every cell is composited onto a mid-grey
checker so transparent canvases and white halos are visible, and the index
printed under each cell keys back into the JSON manifest written alongside.

    python tools/scripts/imgwork/sheet.py data/image/kigaeui
    python tools/scripts/imgwork/sheet.py --all
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parents[2]
SRC = HERE / "extracted" / "images"
OUT = HERE / "extracted" / "image_sheets"

CELL_W, CELL_H = 300, 190
LABEL_H = 26
COLS = 5


def checker(size: tuple[int, int], step: int = 12) -> Image.Image:
    board = Image.new("RGBA", size, (105, 105, 105, 255))
    draw = ImageDraw.Draw(board)
    for y in range(0, size[1], step):
        for x in range(0, size[0], step):
            if (x // step + y // step) % 2:
                draw.rectangle([x, y, x + step - 1, y + step - 1], fill=(135, 135, 135, 255))
    return board


def build(folder: str, files: list[Path], start: int) -> tuple[list[Image.Image], list[dict]]:
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/consola.ttf", 13)
    except OSError:
        font = ImageFont.load_default()

    manifest: list[dict] = []
    sheets: list[Image.Image] = []
    per_sheet = COLS * 4
    for offset in range(0, len(files), per_sheet):
        batch = files[offset:offset + per_sheet]
        rows = (len(batch) + COLS - 1) // COLS
        sheet = Image.new("RGBA", (COLS * CELL_W, rows * (CELL_H + LABEL_H) + 30),
                          (24, 24, 24, 255))
        draw = ImageDraw.Draw(sheet)
        draw.text((8, 8), f"{folder}   [{start + offset} .. {start + offset + len(batch) - 1}]",
                  fill=(255, 220, 120, 255), font=font)
        for index, path in enumerate(batch):
            col, row = index % COLS, index // COLS
            x0 = col * CELL_W
            y0 = row * (CELL_H + LABEL_H) + 30
            with Image.open(path) as raw:
                img = raw.convert("RGBA")
            scale = min((CELL_W - 12) / img.width, (CELL_H - 12) / img.height, 1.0)
            view = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))),
                              Image.LANCZOS)
            tile = checker(view.size)
            tile.alpha_composite(view)
            sheet.alpha_composite(tile, dest=(x0 + (CELL_W - view.width) // 2,
                                              y0 + (CELL_H - view.height) // 2))
            draw.rectangle([x0 + 2, y0 + 2, x0 + CELL_W - 4, y0 + CELL_H - 4],
                           outline=(70, 70, 70, 255))
            number = start + offset + index
            draw.text((x0 + 6, y0 + CELL_H - 2), f"{number:>4} {path.name[:30]}",
                      fill=(210, 210, 210, 255), font=font)
            draw.text((x0 + 6, y0 + CELL_H + 11), f"     {img.width}x{img.height} {img.mode}",
                      fill=(140, 160, 190, 255), font=font)
            manifest.append({"n": number, "rel": path.relative_to(SRC).as_posix(),
                             "w": img.width, "h": img.height, "mode": img.mode})
        sheets.append(sheet)
    return sheets, manifest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folders", nargs="*")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    if args.all:
        folders = sorted({p.parent.relative_to(SRC).as_posix()
                          for p in SRC.rglob("*")
                          if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".gif")})
    else:
        folders = args.folders
    if not folders:
        raise SystemExit("name at least one folder, or pass --all")

    manifest: list[dict] = []
    counter = 0
    for folder in folders:
        directory = SRC / folder
        if not directory.exists():
            print(f"  skip (missing) {folder}")
            continue
        files = sorted(p for p in directory.iterdir()
                       if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif"))
        if not files:
            continue
        sheets, rows = build(folder, files, counter)
        counter += len(files)
        manifest.extend(rows)
        slug = folder.replace("/", "_")
        for index, sheet in enumerate(sheets):
            name = f"{slug}_{index:02d}.png" if len(sheets) > 1 else f"{slug}.png"
            sheet.convert("RGB").save(OUT / name)
            print(f"  {OUT / name}")
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"  {len(manifest)} cells -> {OUT / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
