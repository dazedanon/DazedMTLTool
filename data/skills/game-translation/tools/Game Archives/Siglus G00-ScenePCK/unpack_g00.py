"""Unpack RealLive/Siglus G00 images to PNG.

This decoder covers the three G00 variants used by RealLive/Siglus:

  0: 24-bit RGB
  1: paletted RGBA
  2: RGBA with region/block metadata

The compression streams are the two small LZSS variants used by the engine.
Outputs are written as PNG files, with optional JSON sidecars for format 2
region metadata.
"""

from __future__ import annotations

import argparse
import csv
import json
import struct
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "g00"
DEFAULT_OUTPUT = ROOT / "_workspace" / "out" / "images" / "g00_png"
DEFAULT_MANIFEST = ROOT / "_workspace" / "out" / "images" / "g00_manifest.csv"


@dataclass
class Region:
    x1: int
    y1: int
    x2: int
    y2: int
    origin_x: int
    origin_y: int


@dataclass
class Part:
    region_index: int
    x: int
    y: int
    width: int
    height: int
    trans: int


class G00Error(Exception):
    pass


def u16(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def s32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<i", data, off)[0]


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def decompress_type0(src: bytes, expected_size: int) -> bytes:
    """G00 format 0 LZSS: literals and backrefs are 3-byte RGB pixels."""
    out = bytearray()
    pos = 0
    bit = 0x100
    flag = 0
    while pos < len(src) and len(out) < expected_size:
        if bit == 0x100:
            if pos >= len(src):
                break
            flag = src[pos]
            pos += 1
            bit = 1
        if flag & bit:
            if pos + 3 > len(src):
                raise G00Error("truncated type0 literal")
            out.extend(src[pos : pos + 3])
            pos += 3
        else:
            if pos + 2 > len(src):
                raise G00Error("truncated type0 backref")
            code = src[pos] | (src[pos + 1] << 8)
            pos += 2
            distance_pixels = code >> 4
            count_bytes = ((code & 0x0F) + 1) * 3
            ref = len(out) - distance_pixels * 3
            if ref < 0 or ref >= len(out):
                raise G00Error("invalid type0 backref")
            for i in range(count_bytes):
                out.append(out[ref + i])
                if len(out) >= expected_size:
                    break
        bit <<= 1
    if len(out) != expected_size:
        raise G00Error(f"type0 decompressed {len(out)} bytes, expected {expected_size}")
    return bytes(out)


def decompress_type1(src: bytes, expected_size: int) -> bytes:
    """G00 format 1/2 LZSS: byte literals, 12-bit distance, 2..17 length."""
    out = bytearray()
    pos = 0
    bit = 0x100
    flag = 0
    while pos < len(src) and len(out) < expected_size:
        if bit == 0x100:
            if pos >= len(src):
                break
            flag = src[pos]
            pos += 1
            bit = 1
        if flag & bit:
            if pos >= len(src):
                raise G00Error("truncated literal")
            out.append(src[pos])
            pos += 1
        else:
            if pos + 2 > len(src):
                raise G00Error("truncated backref")
            code = src[pos] | (src[pos + 1] << 8)
            pos += 2
            ref = len(out) - (code >> 4)
            count = (code & 0x0F) + 2
            if ref < 0 or ref >= len(out):
                raise G00Error("invalid backref")
            for i in range(count):
                out.append(out[ref + i])
                if len(out) >= expected_size:
                    break
        bit <<= 1
    if len(out) != expected_size:
        raise G00Error(f"decompressed {len(out)} bytes, expected {expected_size}")
    return bytes(out)


def decode_format0(data: bytes, width: int, height: int) -> tuple[Image.Image, dict]:
    compressed_size = u32(data, 0x05)
    uncompressed_size = u32(data, 0x09)
    if compressed_size != len(data) - 5:
        raise G00Error("bad format0 compressed size")
    if uncompressed_size != width * height * 4:
        raise G00Error("bad format0 uncompressed size")
    rgb = decompress_type0(data[0x0D : 0x0D + compressed_size - 8], width * height * 3)
    img = Image.frombytes("RGB", (width, height), rgb)
    return img, {"format": 0, "width": width, "height": height}


def decode_format1(data: bytes, width: int, height: int) -> tuple[Image.Image, dict]:
    compressed_size = u32(data, 0x05)
    uncompressed_size = u32(data, 0x09)
    if compressed_size != len(data) - 5:
        raise G00Error("bad format1 compressed size")
    raw = decompress_type1(data[0x0D : 0x0D + compressed_size - 8], uncompressed_size)
    palette_len = u16(raw, 0)
    pal_start = 2
    pix_start = pal_start + palette_len * 4
    if pix_start + width * height > len(raw):
        raise G00Error("format1 palette/pixel table exceeds decompressed data")
    palette = [raw[pal_start + i * 4 : pal_start + i * 4 + 4] for i in range(palette_len)]
    pixels = raw[pix_start : pix_start + width * height]
    rgba = bytearray(width * height * 4)
    for i, idx in enumerate(pixels):
        if idx >= palette_len:
            raise G00Error("format1 palette index out of range")
        rgba[i * 4 : i * 4 + 4] = palette[idx]
    img = Image.frombytes("RGBA", (width, height), bytes(rgba))
    return img, {"format": 1, "width": width, "height": height, "palette_len": palette_len}


def decode_format2(data: bytes, width: int, height: int) -> tuple[Image.Image, dict]:
    region_count = u32(data, 0x05)
    regions: list[Region] = []
    for i in range(region_count):
        p = 0x09 + i * 24
        regions.append(
            Region(
                x1=s32(data, p),
                y1=s32(data, p + 4),
                x2=s32(data, p + 8),
                y2=s32(data, p + 12),
                origin_x=s32(data, p + 16),
                origin_y=s32(data, p + 20),
            )
        )

    h_off = 0x09 + region_count * 24
    compressed_size = u32(data, h_off)
    uncompressed_size = u32(data, h_off + 4)
    if compressed_size != len(data) - h_off:
        raise G00Error("bad format2 compressed size")
    raw = decompress_type1(data[h_off + 8 : h_off + compressed_size], uncompressed_size)

    block_count = u32(raw, 0)
    if block_count != region_count:
        raise G00Error("format2 block count differs from region count")
    index = []
    for i in range(block_count):
        index.append((u32(raw, 4 + i * 8), s32(raw, 8 + i * 8)))

    canvas = bytearray(width * height * 4)
    parts: list[Part] = []
    duplicates = 0
    for region_index, (region, (offset, length)) in enumerate(zip(regions, index)):
        if length <= 0:
            duplicates += 1
            continue
        block = raw[offset : offset + length]
        if len(block) != length:
            raise G00Error("format2 block exceeds decompressed data")
        if u16(block, 0) != 1:
            raise G00Error("unknown format2 block type")
        part_count = u16(block, 2)
        pos = 0x74
        for _ in range(part_count):
            px = u16(block, pos) + region.x1
            py = u16(block, pos + 2) + region.y1
            trans = u16(block, pos + 4)
            pw = u16(block, pos + 6)
            ph = u16(block, pos + 8)
            pos += 0x5C
            row_size = pw * 4
            if pos + row_size * ph > len(block):
                raise G00Error("format2 part exceeds block data")
            for y in range(ph):
                dst = ((py + y) * width + px) * 4
                src = pos + y * row_size
                canvas[dst : dst + row_size] = block[src : src + row_size]
            pos += row_size * ph
            parts.append(Part(region_index, px, py, pw, ph, trans))

    img = Image.frombytes("RGBA", (width, height), bytes(canvas))
    meta = {
        "format": 2,
        "width": width,
        "height": height,
        "region_count": region_count,
        "duplicate_region_count": duplicates,
        "regions": [asdict(r) for r in regions],
        "parts": [asdict(p) for p in parts],
    }
    return img, meta


def decode_g00(path: Path) -> tuple[Image.Image, dict]:
    data = path.read_bytes()
    if len(data) < 13:
        raise G00Error("file too small")
    fmt = data[0]
    width = u16(data, 1)
    height = u16(data, 3)
    if width <= 0 or height <= 0:
        raise G00Error("invalid image dimensions")
    if fmt == 0:
        return decode_format0(data, width, height)
    if fmt == 1:
        return decode_format1(data, width, height)
    if fmt == 2:
        return decode_format2(data, width, height)
    raise G00Error(f"unsupported G00 format {fmt}")


def out_path_for(src: Path, in_root: Path, out_root: Path) -> Path:
    rel = src.relative_to(in_root)
    return out_root / rel.with_suffix(".png")


def unpack_one(src: Path, in_root: Path, out_root: Path, write_metadata: bool) -> dict:
    img, meta = decode_g00(src)
    out_path = out_path_for(src, in_root, out_root)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    meta_path = ""
    if write_metadata and meta.get("format") == 2:
        sidecar = out_path.with_suffix(".g00.json")
        sidecar.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        meta_path = str(sidecar.relative_to(ROOT))
    return {
        "source": str(src.relative_to(ROOT)),
        "output": str(out_path.relative_to(ROOT)),
        "metadata": meta_path,
        "format": meta["format"],
        "width": meta["width"],
        "height": meta["height"],
        "regions": meta.get("region_count", 1),
    }


def write_manifest(rows: list[dict], manifest: Path) -> None:
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with manifest.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["source", "output", "metadata", "format", "width", "height", "regions"],
        )
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0, help="decode only the first N files")
    ap.add_argument("--no-metadata", action="store_true", help="skip format 2 JSON sidecars")
    args = ap.parse_args(argv)

    in_root = args.input.resolve()
    out_root = args.output.resolve()
    files = sorted(in_root.rglob("*.g00"))
    if args.limit:
        files = files[: args.limit]
    if not files:
        print(f"No .g00 files found under {in_root}", file=sys.stderr)
        return 1

    rows: list[dict] = []
    errors: list[tuple[str, str]] = []
    total = len(files)
    print(f"Decoding {total} G00 files from {in_root}")
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = {
            pool.submit(unpack_one, p, in_root, out_root, not args.no_metadata): p for p in files
        }
        for done, fut in enumerate(as_completed(futures), 1):
            src = futures[fut]
            try:
                row = fut.result()
                rows.append(row)
                if done == 1 or done % 50 == 0 or done == total:
                    print(f"[{done:4}/{total}] ok {src.name} -> {row['output']}")
            except Exception as exc:  # keep the batch moving and report at the end
                errors.append((str(src), str(exc)))
                print(f"[{done:4}/{total}] FAIL {src}: {exc}", file=sys.stderr)

    rows.sort(key=lambda r: r["source"])
    write_manifest(rows, args.manifest.resolve())
    print(f"Wrote {len(rows)} PNG files under {out_root}")
    print(f"Wrote manifest: {args.manifest.resolve()}")
    if errors:
        err_path = args.manifest.resolve().with_suffix(".errors.json")
        err_path.write_text(json.dumps(errors, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{len(errors)} files failed; details: {err_path}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
