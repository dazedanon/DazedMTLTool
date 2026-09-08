"""Create loose overrides that hide the config-screen font selector.

Do not patch yst00109 for this. No-oping the selector bytecode made the game
close at startup in testing. YU-RIS will load loose files from the game root
before falling back to Graphics.ypf, so hiding the baked row and selector parts
as loose PNGs is safer and reversible.
"""
import os
import sys
from pathlib import Path

from PIL import Image


FONT_ASSET_PATTERNS = ("btn_font_*.png", "tip_font*.png")


def patch_back_system(src_path, dst_path):
    im = Image.open(src_path).convert("RGBA")

    # Cover the right-side "フォント選択" label + underline by cloning a blank
    # strip from just below it, preserving the background texture.
    x0, y0, x1, y1 = 670, 418, 1078, 456
    src_y0 = 462
    patch = im.crop((x0, src_y0, x1, src_y0 + (y1 - y0)))
    im.paste(patch, (x0, y0))

    dst_path.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst_path)
    print(f"wrote {dst_path}")


def write_transparent_font_assets(src_dir, dst_dir):
    dst_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for pattern in FONT_ASSET_PATTERNS:
        for src in sorted(src_dir.glob(pattern)):
            im = Image.open(src).convert("RGBA")
            transparent = Image.new("RGBA", im.size, (0, 0, 0, 0))
            dst = dst_dir / src.name
            transparent.save(dst)
            written.append(dst)
    print(f"wrote {len(written)} transparent font-selector overrides")
    for path in written:
        print(f"  {path}")


def main(argv):
    if len(argv) != 3:
        print("usage: patch_config_font_selector.py <extracted cgsys/config dir> <game root>")
        return 1

    src_dir = Path(argv[1])
    game_root = Path(argv[2])
    dst_dir = game_root / "cgsys" / "config"

    patch_back_system(src_dir / "back_system.png", dst_dir / "back_system.png")
    write_transparent_font_assets(src_dir, dst_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
