#!/usr/bin/env python3
"""Extract UE5 Texture2D assets (inline uexp pixel data) to PNG.

Targets this game's UI/tutorial art, which is uncompressed PF_B8G8R8A8 with the
top mip stored inline in the .uexp (no .ubulk). Parses the FTexturePlatformData
header (SizeX, SizeY, pixel-format FName) to locate the first mip, then writes
the BGRA pixels as PNG. Compressed formats (BC/DXT) are decoded via
texture2ddecoder when present.
"""
import struct
import sys
from pathlib import Path

from PIL import Image

try:
    import texture2ddecoder
except ImportError:
    texture2ddecoder = None

TOOLING = Path(__file__).resolve().parent.parent
LEGACY = TOOLING / "work" / "legacy_unpacked" / "NoEcstasyNoLife" / "Content"

# game-specific image folders worth extracting (UI / tutorial / charm / CG art),
# skipping environment/megascan/material-library noise
# game's own UI / tutorial / HUD art only — no 3D-prop maps or environment
# textures (those are streamed to .ubulk and are not player-facing "images")
TARGET_DIRS = [
    "_IkaseruGame/UI",
]

# pixel-format name -> (bytes/pixel for raw, texture2ddecoder decoder or None)
FORMATS = {
    "PF_B8G8R8A8": ("bgra", 4),
    "PF_R8G8B8A8": ("rgba", 4),
    "PF_G8": ("gray", 1),
    "PF_DXT1": ("bc1", 0),
    "PF_DXT5": ("bc3", 0),
    "PF_BC3": ("bc3", 0),
    "PF_BC4": ("bc4", 0),
    "PF_BC5": ("bc5", 0),
    "PF_BC7": ("bc7", 0),
    "PF_BC6H": ("bc6h", 0),
}


def find_platform_data(blob):
    """Return (sizeX, sizeY, fmt_name, pixel_offset) for the first mip, or None."""
    for fmt_name in FORMATS:
        marker = fmt_name.encode("ascii")
        # FName is stored as a length-prefixed string: <int32 len><ascii\0>
        needle = struct.pack("<i", len(fmt_name) + 1) + marker + b"\x00"
        idx = blob.find(needle)
        if idx < 0:
            continue
        # UE layout right before the PixelFormat FName:
        #   ...SizeX(int32) SizeY(int32) PackedData/NumSlices(int32) <FName>
        # so SizeX is at idx-12 and SizeY at idx-8. Validate against file size;
        # if it doesn't fit, fall back to scanning a wider window.
        candidates = []
        if idx - 12 >= 0:
            candidates.append(struct.unpack_from("<ii", blob, idx - 12))
        for back in range(8, 48, 4):
            p = idx - back
            if p >= 0:
                candidates.append(struct.unpack_from("<ii", blob, p))
        for size_x, size_y in candidates:
            if 0 < size_x <= 16384 and 0 < size_y <= 16384:
                kind, bpp = FORMATS[fmt_name]
                expected = size_x * size_y * (bpp if bpp else 0.5)
                # require the raw/compressed size to plausibly fit the file
                if bpp and expected > len(blob):
                    continue
                if not bpp and expected > len(blob):
                    continue
                # the first mip's pixel block follows the format name; the mip
                # struct has its own bulk-data header, so scan forward for the
                # offset where exactly sizeX*sizeY*bpp bytes fit to EOF-ish
                want = size_x * size_y * (bpp if bpp else 1)
                start = idx + len(needle)
                # the mip serialized size (int) appears shortly after; find the
                # largest contiguous tail matching the raw size for uncompressed
                if bpp:
                    # locate pixel block: search a small window for an int32 ==
                    # mip byte count, pixels follow right after the bulk header
                    for q in range(start, min(start + 256, len(blob) - 4)):
                        val = struct.unpack_from("<i", blob, q)[0]
                        if val == want and q + 4 + want <= len(blob) + 0:
                            return size_x, size_y, fmt_name, q + 4
                    # fallback: assume pixels are the trailing `want` bytes
                    if want <= len(blob):
                        return size_x, size_y, fmt_name, len(blob) - want
                else:
                    # compressed: return the marker; caller computes block size
                    return size_x, size_y, fmt_name, start
        # if we matched the format name but not dims, keep trying other formats
    return None


def decode_to_image(blob, size_x, size_y, fmt_name, offset):
    kind, bpp = FORMATS[fmt_name]
    if kind == "bgra":
        raw = blob[offset : offset + size_x * size_y * 4]
        if len(raw) < size_x * size_y * 4:
            return None
        return Image.frombytes("RGBA", (size_x, size_y), raw, "raw", "BGRA")
    if kind == "rgba":
        raw = blob[offset : offset + size_x * size_y * 4]
        return Image.frombytes("RGBA", (size_x, size_y), raw, "raw", "RGBA")
    if kind == "gray":
        raw = blob[offset : offset + size_x * size_y]
        return Image.frombytes("L", (size_x, size_y), raw)
    if texture2ddecoder is None:
        return None
    block = {
        "bc1": (8, texture2ddecoder.decode_bc1),
        "bc3": (16, texture2ddecoder.decode_bc3),
        "bc4": (8, texture2ddecoder.decode_bc4),
        "bc5": (16, texture2ddecoder.decode_bc5),
        "bc7": (16, texture2ddecoder.decode_bc7),
        "bc6h": (16, getattr(texture2ddecoder, "decode_bc6", None)),
    }.get(kind)
    if not block or block[1] is None:
        return None
    bytes_per_block, decoder = block
    blocks = ((size_x + 3) // 4) * ((size_y + 3) // 4)
    raw = blob[offset : offset + blocks * bytes_per_block]
    if len(raw) < blocks * bytes_per_block:
        return None
    rgba = decoder(raw, size_x, size_y)
    return Image.frombytes("RGBA", (size_x, size_y), rgba, "raw", "BGRA")


def extract_one(uexp_path, out_path):
    blob = uexp_path.read_bytes()
    info = find_platform_data(blob)
    if not info:
        return False, "no platform data / unknown format"
    size_x, size_y, fmt_name, offset = info
    try:
        img = decode_to_image(blob, size_x, size_y, fmt_name, offset)
    except Exception as exc:  # noqa: BLE001
        return False, f"decode error: {exc}"
    if img is None:
        return False, f"could not decode {fmt_name} {size_x}x{size_y}"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return True, f"{fmt_name} {size_x}x{size_y}"


def main():
    out_root = TOOLING / "extracted_images"
    targets = sys.argv[1:] or TARGET_DIRS
    total = ok = 0
    for rel_dir in targets:
        base = LEGACY / rel_dir
        if not base.exists():
            print(f"skip (missing): {rel_dir}")
            continue
        for uexp in sorted(base.rglob("*.uexp")):
            # only Texture2D assets carry a pixel-format marker; cheap pre-check
            head = uexp.read_bytes()
            if b"PF_" not in head:
                continue
            total += 1
            rel = uexp.relative_to(LEGACY).with_suffix(".png")
            out_path = out_root / rel
            success, msg = extract_one(uexp, out_path)
            if success:
                ok += 1
                print(f"OK  {rel}  [{msg}]")
            else:
                print(f"--  {rel}  [{msg}]")
    print(f"\nextracted {ok}/{total} textures to {out_root}")


if __name__ == "__main__":
    main()
