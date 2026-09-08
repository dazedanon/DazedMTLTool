#!/usr/bin/env python3
"""Convert images/out/*.png into the plugin's .tex payload.

The plugin cannot decode a PNG at runtime. Every `ImageConversion.LoadImage`
overload in this game's interop funnels into the ReadOnlySpan one:

    public static bool LoadImage(Texture2D tex, Il2CppStructArray<byte> data)
        => LoadImage(tex, new Il2CppSystem.ReadOnlySpan<byte>(...), false);

and the span path needs `Il2CppSystem.ReadOnlySpan<byte>.GetPinnableReference`,
which this build's corlib has stripped - so it throws `Method not found`
whatever argument type you hand it. `Texture2D.LoadRawTextureData` has no such
dependency, so the decoding moves here and the runtime only uploads pixels.

Format (little-endian):
    magic  "HTEX"      4 bytes
    width  int32
    height int32
    pixels width*height*4 bytes, RGBA32, rows BOTTOM-UP

Bottom-up because Unity's texture origin is the lower-left corner, and
LoadRawTextureData writes the buffer verbatim with no flip.
"""
from __future__ import annotations

import argparse
import os
import struct
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hitonatsu import common as C  # noqa: E402

SRC = os.path.join(C.PROJECT, "images", "out")
DST = os.path.join(C.PROJECT, "plugin", "HitonatsuTL", "images")

MAGIC = b"HTEX"


def pack(png_path: str, tex_path: str) -> tuple[int, int, int]:
    im = Image.open(png_path).convert("RGBA")
    w, h = im.size
    # transpose, not a reversed row loop: PIL does it in C and it is exact.
    flipped = im.transpose(Image.FLIP_TOP_BOTTOM)
    data = flipped.tobytes()
    assert len(data) == w * h * 4, f"{png_path}: unexpected buffer size"
    with open(tex_path, "wb") as f:
        f.write(MAGIC)
        f.write(struct.pack("<ii", w, h))
        f.write(data)
    return w, h, len(data) + 12


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", default=SRC)
    ap.add_argument("--dst", default=DST)
    args = ap.parse_args()

    if not os.path.isdir(args.src):
        raise SystemExit(f"no source folder {args.src}")
    os.makedirs(args.dst, exist_ok=True)

    # Mirror: a PNG removed from the source must not leave a stale .tex behind
    # for the plugin to keep loading.
    wanted = {os.path.splitext(f)[0] for f in os.listdir(args.src)
              if f.lower().endswith(".png")}
    for f in os.listdir(args.dst):
        stem, ext = os.path.splitext(f)
        if ext.lower() in (".tex", ".png") and stem not in wanted:
            os.remove(os.path.join(args.dst, f))
            print(f"  removed stale {f}")

    n = 0
    for f in sorted(os.listdir(args.src)):
        if not f.lower().endswith(".png"):
            continue
        stem = os.path.splitext(f)[0]
        w, h, size = pack(os.path.join(args.src, f),
                          os.path.join(args.dst, stem + ".tex"))
        print(f"  {stem}.tex  {w}x{h}  {size / 1024:.0f} KB")
        n += 1

    if not n:
        raise SystemExit(f"no PNGs in {args.src}")
    print(f"\n{n} image(s) -> {args.dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
