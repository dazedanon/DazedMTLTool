#!/usr/bin/env python3
"""Splice translated tutorial PNGs into the cooked UE5.6 texture uexp files.

All 15 TutorialPagePics textures are single-mip, inline (mip data is the last
block before the 4-byte 0x9E2A83C1 package footer). 14 are PF_B8G8R8A8
(uncompressed BGRA) and tutorial_09_symbol_pattern is PF_DXT1 (BC1). Because the
replacement keeps identical dimensions/format, the mip byte count is unchanged,
so we overwrite the pixel bytes in place — no header/offset edits, .uasset
untouched. Output goes to work/image_patch/ mirroring the content path.
"""
import math
import os
import re
import struct
from pathlib import Path

import numpy as np
from PIL import Image

TOOLING = Path(__file__).resolve().parent.parent
SRC = TOOLING / "work/legacy_unpacked/NoEcstasyNoLife/Content/_IkaseruGame/UI/Tutorial/TutorialPagePics"
PNGS = TOOLING / "images_translated"
REL = "NoEcstasyNoLife/Content/_IkaseruGame/UI/Tutorial/TutorialPagePics"
OUT = TOOLING / "work/image_patch"

FOOTER = bytes.fromhex("c1832a9e")


def parse_texture(uexp: bytes):
    m = re.search(rb"PF_([A-Z0-9_]+)\x00", uexp)
    if not m:
        raise ValueError("no pixel format")
    fmt = m.group(1).decode()
    sx, sy, _ns = struct.unpack_from("<iii", uexp, m.start() - 16)
    first, nmips = struct.unpack_from("<ii", uexp, m.end())
    if nmips != 1:
        raise ValueError(f"unexpected mip count {nmips}")
    return fmt, sx, sy


def find_mip_offset(uexp: bytes, sx: int, sy: int, mip: int) -> int:
    """The single inline mip payload is followed by a trailer that begins with
    the FTexture2DMipMap dims (SizeX, SizeY as int32), then the 4-byte package
    footer. Locate that SizeX/SizeY pair near EOF to get the payload end, so the
    payload offset is found WITHOUT clobbering the trailer."""
    want = struct.pack("<ii", sx, sy)
    # the trailer sits in the last ~64 bytes; search backward from EOF
    search_start = max(0, len(uexp) - 80)
    idx = uexp.rfind(want, search_start)
    if idx < 0:
        raise ValueError("could not locate SizeX/SizeY trailer")
    payload_end = idx
    mip_off = payload_end - mip
    if mip_off <= 0:
        raise ValueError(f"bad mip offset {mip_off}")
    return mip_off


def encode_bc1(rgb: np.ndarray) -> bytes:
    """rgb: (H, W, 3) uint8 -> BC1/DXT1 opaque (4-colour) blocks, row-major."""
    h, w, _ = rgb.shape
    bw, bh = w // 4, h // 4
    # reshape into (bh, bw, 4, 4, 3) blocks
    blocks = rgb[: bh * 4, : bw * 4].reshape(bh, 4, bw, 4, 3).transpose(0, 2, 1, 3, 4)
    blocks = blocks.reshape(bh * bw, 16, 3).astype(np.int32)

    cmin = blocks.min(axis=1)  # (N,3)
    cmax = blocks.max(axis=1)

    def to565(c):
        r = (c[:, 0] >> 3) & 0x1F
        g = (c[:, 1] >> 2) & 0x3F
        b = (c[:, 2] >> 3) & 0x1F
        return (r << 11) | (g << 5) | b

    def from565(v):
        r = ((v >> 11) & 0x1F) << 3
        g = ((v >> 5) & 0x3F) << 2
        b = (v & 0x1F) << 3
        r |= r >> 5
        g |= g >> 6
        b |= b >> 5
        return np.stack([r, g, b], axis=-1).astype(np.int32)

    c0 = to565(cmax)
    c1 = to565(cmin)
    # opaque 4-colour mode needs c0 > c1; if equal, nudge so palette is valid
    swap = c0 < c1
    c0, c1 = np.where(swap, c1, c0), np.where(swap, c0, c1)
    equal = c0 == c1
    # decode endpoints back to 8-bit and build the 4-colour palette
    e0 = from565(c0)
    e1 = from565(c1)
    p0 = e0
    p1 = e1
    p2 = (2 * e0 + e1) // 3
    p3 = (e0 + 2 * e1) // 3
    palette = np.stack([p0, p1, p2, p3], axis=1)  # (N,4,3)

    # nearest palette index per pixel
    diff = blocks[:, :, None, :] - palette[:, None, :, :]  # (N,16,4,3)
    dist = (diff * diff).sum(axis=3)  # (N,16,4)
    idx = dist.argmin(axis=2).astype(np.uint32)  # (N,16)
    # when both endpoints identical, all indices 0 (flat colour)
    idx[equal] = 0

    indices = np.zeros(blocks.shape[0], dtype=np.uint32)
    for i in range(16):
        indices |= (idx[:, i] & 0x3) << (2 * i)

    out = np.empty((blocks.shape[0], 8), dtype=np.uint8)
    out[:, 0] = c0 & 0xFF
    out[:, 1] = (c0 >> 8) & 0xFF
    out[:, 2] = c1 & 0xFF
    out[:, 3] = (c1 >> 8) & 0xFF
    out[:, 4] = indices & 0xFF
    out[:, 5] = (indices >> 8) & 0xFF
    out[:, 6] = (indices >> 16) & 0xFF
    out[:, 7] = (indices >> 24) & 0xFF
    return out.tobytes()


def main():
    out_dir = OUT / REL
    out_dir.mkdir(parents=True, exist_ok=True)
    done = 0
    for uexp_path in sorted(SRC.glob("*.uexp")):
        name = uexp_path.stem
        png = PNGS / f"{name}.png"
        if not png.exists():
            print(f"skip {name}: no translated PNG")
            continue
        uexp = bytearray(uexp_path.read_bytes())
        fmt, sx, sy = parse_texture(uexp)
        img = Image.open(png).convert("RGBA")
        if img.size != (sx, sy):
            img = img.resize((sx, sy), Image.LANCZOS)
        arr = np.asarray(img)  # (H,W,4) RGBA

        if fmt == "B8G8R8A8":
            bgra = arr[:, :, [2, 1, 0, 3]].tobytes()
            mip = len(bgra)
        elif fmt == "DXT1":
            bgra = encode_bc1(arr[:, :, :3])
            mip = len(bgra)
        else:
            print(f"skip {name}: unsupported format {fmt}")
            continue

        assert bytes(uexp[-4:]) == FOOTER, f"{name}: footer mismatch"
        mip_off = find_mip_offset(bytes(uexp), sx, sy, mip)
        uexp[mip_off : mip_off + mip] = bgra

        (out_dir / f"{name}.uexp").write_bytes(bytes(uexp))
        uasset = uexp_path.with_suffix(".uasset")
        (out_dir / f"{name}.uasset").write_bytes(uasset.read_bytes())
        print(f"baked {name}: {fmt} {sx}x{sy} mip={mip}B @ {mip_off}")
        done += 1
    print(f"\n{done} textures baked -> {out_dir}")


if __name__ == "__main__":
    main()
