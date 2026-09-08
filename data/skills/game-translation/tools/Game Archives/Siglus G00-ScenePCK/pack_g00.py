"""Pack edited PNGs back into RealLive/Siglus G00 files.

This writer uses each original .g00 as a template, then replaces only pixel
payloads with the edited PNG pixels. That preserves the original G00 format,
region table, part table, and unknown metadata bytes.

Supported for this game:
  0: 24-bit RGB
  2: RGBA with region/block metadata

Format 1 is intentionally rejected for now because this game inventory did not
contain any format-1 G00 files.
"""

from __future__ import annotations

import argparse
import csv
import json
import struct
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from unpack_g00 import G00Error, decode_format0, decode_format1, decode_format2, decompress_type1, s32, u16, u32


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ORIGINAL = ROOT / "g00"
DEFAULT_PNG = ROOT / "_workspace" / "out" / "images" / "g00_png"
DEFAULT_OUTPUT = ROOT / "_workspace" / "out" / "images" / "g00_repacked"
DEFAULT_MANIFEST = ROOT / "_workspace" / "out" / "images" / "g00_repack_manifest.csv"


@dataclass(frozen=True)
class Region:
    x1: int
    y1: int
    x2: int
    y2: int
    origin_x: int
    origin_y: int


def p16(value: int) -> bytes:
    return struct.pack("<H", value)


def p32(value: int) -> bytes:
    return struct.pack("<I", value)


def encode_literals_type0(raw_rgb: bytes) -> bytes:
    """Type-0 G00 stream with only literal 3-byte RGB pixels."""
    if len(raw_rgb) % 3:
        raise G00Error("format0 RGB payload is not pixel-aligned")
    out = bytearray()
    for pos in range(0, len(raw_rgb), 8 * 3):
        chunk = raw_rgb[pos : pos + 8 * 3]
        pixel_count = len(chunk) // 3
        out.append((1 << pixel_count) - 1)
        out.extend(chunk)
    return bytes(out)


def encode_literals_type1(raw: bytes) -> bytes:
    """Type-1/2 G00 stream with only byte literals."""
    out = bytearray()
    for pos in range(0, len(raw), 8):
        chunk = raw[pos : pos + 8]
        out.append((1 << len(chunk)) - 1)
        out.extend(chunk)
    return bytes(out)


def has_partial_or_full_transparency(img: Image.Image) -> bool:
    if img.mode in {"RGBA", "LA"}:
        return img.getchannel("A").getextrema()[0] < 255
    if img.mode == "P" and "transparency" in img.info:
        return True
    return False


def resolve_relative_file(value: str) -> Path:
    rel = Path(value)
    if rel.is_absolute():
        raise G00Error("--file values must be relative to the G00/PNG roots")
    if rel.suffix.lower() == ".png":
        rel = rel.with_suffix(".g00")
    elif rel.suffix.lower() != ".g00":
        rel = rel.with_suffix(".g00")
    return rel


def parse_format2_regions(data: bytes) -> list[Region]:
    region_count = u32(data, 0x05)
    regions: list[Region] = []
    for i in range(region_count):
        off = 0x09 + i * 24
        regions.append(
            Region(
                x1=s32(data, off),
                y1=s32(data, off + 4),
                x2=s32(data, off + 8),
                y2=s32(data, off + 12),
                origin_x=s32(data, off + 16),
                origin_y=s32(data, off + 20),
            )
        )
    return regions


def rgba_with_alpha_mode(
    edited: Image.Image,
    original_rgba: Image.Image,
    alpha_mode: str,
) -> tuple[Image.Image, str, str]:
    edited_rgba = edited.convert("RGBA")
    original_rgba = original_rgba.convert("RGBA")
    original_has_alpha = has_partial_or_full_transparency(original_rgba)
    edited_has_alpha = has_partial_or_full_transparency(edited_rgba)
    warning = ""
    used = alpha_mode

    if alpha_mode == "auto":
        if original_has_alpha and not edited_has_alpha:
            used = "original"
            warning = "edited PNG had no transparent pixels; reused original alpha"
        else:
            used = "edited"

    if used == "edited":
        return edited_rgba, used, warning

    red, green, blue, _ = edited_rgba.split()
    if used == "original":
        return Image.merge("RGBA", (red, green, blue, original_rgba.getchannel("A"))), used, warning
    if used == "opaque":
        opaque = Image.new("L", edited_rgba.size, 255)
        return Image.merge("RGBA", (red, green, blue, opaque)), used, warning
    raise G00Error(f"unknown alpha mode: {alpha_mode}")


def pack_format0(data: bytes, edited: Image.Image, width: int, height: int) -> tuple[bytes, str, str]:
    warning = ""
    if has_partial_or_full_transparency(edited):
        original_img, _ = decode_g00_from_bytes(data)
        base = original_img.convert("RGBA")
        base.alpha_composite(edited.convert("RGBA"))
        rgb_img = base.convert("RGB")
        warning = "edited PNG had alpha; composited it over the original RGB image"
    else:
        rgb_img = edited.convert("RGB")

    stream = encode_literals_type0(rgb_img.tobytes())
    compressed_size = len(stream) + 8
    uncompressed_size = u32(data, 0x09)
    out = bytearray()
    out.append(0)
    out.extend(p16(width))
    out.extend(p16(height))
    out.extend(p32(compressed_size))
    out.extend(p32(uncompressed_size))
    out.extend(stream)
    return bytes(out), "n/a", warning


def pack_format2(
    data: bytes,
    edited: Image.Image,
    width: int,
    height: int,
    alpha_mode: str,
) -> tuple[bytes, str, str]:
    regions = parse_format2_regions(data)
    region_count = len(regions)
    h_off = 0x09 + region_count * 24
    compressed_size = u32(data, h_off)
    uncompressed_size = u32(data, h_off + 4)
    raw = decompress_type1(data[h_off + 8 : h_off + compressed_size], uncompressed_size)
    if u32(raw, 0) != region_count:
        raise G00Error("format2 raw block count differs from region count")

    original_img, _ = decode_g00_from_bytes(data)
    rgba_img, used_alpha_mode, warning = rgba_with_alpha_mode(edited, original_img, alpha_mode)
    rgba = rgba_img.tobytes()
    new_raw = bytearray(raw)

    for region_index, region in enumerate(regions):
        index_off = 4 + region_index * 8
        block_off = u32(raw, index_off)
        block_len = s32(raw, index_off + 4)
        if block_len <= 0:
            continue
        block_end = block_off + block_len
        if block_off < 0 or block_end > len(raw):
            raise G00Error("format2 block points outside decompressed data")
        if u16(raw, block_off) != 1:
            raise G00Error("unsupported format2 block type")
        part_count = u16(raw, block_off + 2)
        pos = block_off + 0x74
        for _ in range(part_count):
            if pos + 0x5C > block_end:
                raise G00Error("format2 part header exceeds block")
            px = u16(raw, pos) + region.x1
            py = u16(raw, pos + 2) + region.y1
            pw = u16(raw, pos + 6)
            ph = u16(raw, pos + 8)
            pos += 0x5C
            row_size = pw * 4
            if px < 0 or py < 0 or px + pw > width or py + ph > height:
                raise G00Error("format2 part rectangle exceeds image bounds")
            if pos + row_size * ph > block_end:
                raise G00Error("format2 part pixels exceed block")
            for y in range(ph):
                src = ((py + y) * width + px) * 4
                dst = pos + y * row_size
                new_raw[dst : dst + row_size] = rgba[src : src + row_size]
            pos += row_size * ph

    stream = encode_literals_type1(bytes(new_raw))
    out = bytearray(data[:h_off])
    out.extend(p32(len(stream) + 8))
    out.extend(p32(len(new_raw)))
    out.extend(stream)
    return bytes(out), used_alpha_mode, warning


def decode_g00_from_bytes(data: bytes) -> tuple[Image.Image, dict]:
    if len(data) < 13:
        raise G00Error("G00 file is too small")
    fmt = data[0]
    width = u16(data, 1)
    height = u16(data, 3)
    if fmt == 0:
        return decode_format0(data, width, height)
    if fmt == 1:
        return decode_format1(data, width, height)
    if fmt == 2:
        return decode_format2(data, width, height)
    raise G00Error(f"unsupported G00 format {fmt}")


def pack_one(
    rel: Path,
    original_root: Path,
    png_root: Path,
    output_root: Path,
    alpha_mode: str,
) -> dict:
    original_path = original_root / rel
    png_path = png_root / rel.with_suffix(".png")
    output_path = output_root / rel
    if not original_path.exists():
        raise G00Error(f"missing original G00: {original_path}")
    if not png_path.exists():
        raise G00Error(f"missing edited PNG: {png_path}")

    data = original_path.read_bytes()
    if len(data) < 13:
        raise G00Error("G00 file is too small")
    fmt = data[0]
    width = u16(data, 1)
    height = u16(data, 3)
    edited = Image.open(png_path)
    if edited.size != (width, height):
        raise G00Error(
            f"edited PNG dimensions {edited.size[0]}x{edited.size[1]} do not match original {width}x{height}"
        )

    if fmt == 0:
        packed, used_alpha, warning = pack_format0(data, edited, width, height)
    elif fmt == 2:
        packed, used_alpha, warning = pack_format2(data, edited, width, height, alpha_mode)
    elif fmt == 1:
        raise G00Error("format 1 packing is not implemented; this game has no format-1 G00 files")
    else:
        raise G00Error(f"unsupported G00 format {fmt}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(packed)
    return {
        "source_png": str(png_path.relative_to(ROOT)),
        "original_g00": str(original_path.relative_to(ROOT)),
        "output_g00": str(output_path.relative_to(ROOT)),
        "format": fmt,
        "width": width,
        "height": height,
        "alpha_mode": used_alpha,
        "warning": warning,
    }


def write_manifest(rows: list[dict], manifest: Path) -> None:
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with manifest.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "source_png",
                "original_g00",
                "output_g00",
                "format",
                "width",
                "height",
                "alpha_mode",
                "warning",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--original", type=Path, default=DEFAULT_ORIGINAL, help="original G00 root")
    ap.add_argument("--png", type=Path, default=DEFAULT_PNG, help="edited PNG root")
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="repacked G00 output root")
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0, help="pack only the first N files")
    ap.add_argument("--file", action="append", default=[], help="relative .g00/.png path to pack; can repeat")
    ap.add_argument(
        "--alpha-mode",
        choices=["auto", "edited", "original", "opaque"],
        default="auto",
        help="format-2 alpha handling; auto reuses original alpha if an editor flattened it",
    )
    ap.add_argument(
        "--allow-in-place",
        action="store_true",
        help="allow --output to be the original G00 root; use with your own backups",
    )
    args = ap.parse_args(argv)

    original_root = args.original.resolve()
    png_root = args.png.resolve()
    output_root = args.output.resolve()
    if output_root == original_root and not args.allow_in_place:
        print("Refusing to overwrite the original G00 root without --allow-in-place", file=sys.stderr)
        return 1

    if args.file:
        files = [resolve_relative_file(item) for item in args.file]
    else:
        files = [p.relative_to(original_root) for p in sorted(original_root.rglob("*.g00"))]
    if args.limit:
        files = files[: args.limit]
    if not files:
        print(f"No G00 files found under {original_root}", file=sys.stderr)
        return 1

    rows: list[dict] = []
    errors: list[tuple[str, str]] = []
    total = len(files)
    print(f"Packing {total} PNG files from {png_root}")
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = {
            pool.submit(pack_one, rel, original_root, png_root, output_root, args.alpha_mode): rel
            for rel in files
        }
        for done, fut in enumerate(as_completed(futures), 1):
            rel = futures[fut]
            try:
                row = fut.result()
                rows.append(row)
                if done == 1 or done % 50 == 0 or done == total:
                    msg = f"[{done:4}/{total}] ok {rel} -> {row['output_g00']}"
                    if row.get("warning"):
                        msg += f" ({row['warning']})"
                    print(msg)
            except Exception as exc:
                errors.append((str(rel), str(exc)))
                print(f"[{done:4}/{total}] FAIL {rel}: {exc}", file=sys.stderr)

    rows.sort(key=lambda r: r["original_g00"])
    write_manifest(rows, args.manifest.resolve())
    print(f"Wrote {len(rows)} G00 files under {output_root}")
    print(f"Wrote manifest: {args.manifest.resolve()}")
    if errors:
        err_path = args.manifest.resolve().with_suffix(".errors.json")
        err_path.write_text(json.dumps(errors, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{len(errors)} files failed; details: {err_path}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

