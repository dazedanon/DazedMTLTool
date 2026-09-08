"""Restore hidden RGB under transparent config PNG pixels.

Some YU-RIS config button sprites are visually transparent by alpha, but the
engine still leaks or keys off the RGB values in fully transparent pixels. Our
English-rendered replacements wrote black RGB there, which can show as a gray
rectangle behind unselected option text. This copies RGB from the extracted
original for alpha==0 pixels while preserving the translated visible pixels.
"""
from pathlib import Path
import sys

from PIL import Image


def fix_one(original_path, target_path):
    original = Image.open(original_path).convert("RGBA")
    target = Image.open(target_path).convert("RGBA")
    if original.size != target.size:
        return False, "size mismatch"

    opx = original.load()
    tpx = target.load()
    changed = 0
    width, height = target.size
    for y in range(height):
        for x in range(width):
            r, g, b, a = tpx[x, y]
            if a == 0:
                or_, og, ob, _oa = opx[x, y]
                if (r, g, b) != (or_, og, ob):
                    tpx[x, y] = (or_, og, ob, a)
                    changed += 1

    if changed:
        target.save(target_path)
    return True, str(changed)


def main():
    if len(sys.argv) < 3:
        print("usage: fix_config_transparent_rgb.py <original_config_dir> <target_config_dir> [target_config_dir...]")
        return 1

    original_dir = Path(sys.argv[1])
    target_dirs = [Path(arg) for arg in sys.argv[2:]]
    names = sorted(p.name for p in original_dir.glob("*.png"))
    for target_dir in target_dirs:
        print(f"target: {target_dir}")
        for name in names:
            original_path = original_dir / name
            target_path = target_dir / name
            if not target_path.exists():
                continue
            ok, info = fix_one(original_path, target_path)
            if ok and info != "0":
                print(f"  {name}: {info} transparent RGB pixels restored")
            elif not ok:
                print(f"  {name}: skipped ({info})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
