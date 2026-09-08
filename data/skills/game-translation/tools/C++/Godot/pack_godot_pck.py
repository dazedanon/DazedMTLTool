#!/usr/bin/env python3
"""Rebuild a Godot 4 GDPC/PCK archive from extracted files.

This repacker uses the manifest created by unpack_godot_pck.py so the archive
keeps the original path list and engine/header metadata. Files found in the
overlay directory replace the extracted originals; everything else is copied
from the base directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO


PCK_MAGIC = b"GDPC"
HEADER_SIZE = 0x70
DATA_ALIGNMENT = 16
PATH_ALIGNMENT = 4
COPY_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class PackedEntry:
    path: str
    source: Path
    offset: int
    size: int
    md5: bytes
    flags: int


def align(value: int, boundary: int) -> int:
    return (value + boundary - 1) // boundary * boundary


def load_manifest(manifest_path: Path) -> dict:
    with manifest_path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    if "header" not in manifest or "entries" not in manifest:
        raise ValueError(f"{manifest_path} does not look like an unpack manifest")
    return manifest


def safe_source_path(root: Path, packed_path: str) -> Path:
    normalized = packed_path.replace("\\", "/")
    if normalized.startswith("res://"):
        normalized = normalized[len("res://") :]
    normalized = normalized.lstrip("/")

    parts = PurePosixPath(normalized).parts
    if not parts or any(part in ("", ".", "..") for part in parts) or any(":" in part for part in parts):
        raise ValueError(f"unsafe packed path: {packed_path!r}")

    root_resolved = root.resolve()
    candidate = root.joinpath(*parts).resolve()
    if os.path.commonpath([str(root_resolved), str(candidate)]) != str(root_resolved):
        raise ValueError(f"packed path escapes source directory: {packed_path!r}")
    return candidate


def find_overlay_source(overlay_root: Path, packed_path: str) -> Path | None:
    direct = safe_source_path(overlay_root, packed_path)
    if direct.is_file():
        return direct

    normalized = packed_path.replace("\\", "/").lstrip("/")
    if normalized.startswith("assets/"):
        assets_relative = normalized[len("assets/") :]
        assets_root_source = safe_source_path(overlay_root, assets_relative)
        if assets_root_source.is_file():
            return assets_root_source

    return None


def write_header(handle: BinaryIO, header: dict, directory_offset: int) -> None:
    data = bytearray(HEADER_SIZE)
    data[:4] = PCK_MAGIC
    struct.pack_into("<I", data, 0x04, int(header["format_version"]))
    struct.pack_into("<I", data, 0x08, int(header["engine_major"]))
    struct.pack_into("<I", data, 0x0C, int(header["engine_minor"]))
    struct.pack_into("<I", data, 0x10, int(header["engine_patch"]))
    struct.pack_into("<I", data, 0x14, int(header["flags"]))
    struct.pack_into("<Q", data, 0x18, HEADER_SIZE)
    struct.pack_into("<Q", data, 0x20, directory_offset)
    handle.seek(0)
    handle.write(data)


def copy_file_with_hash(source: Path, out: BinaryIO) -> tuple[int, bytes]:
    size = 0
    hasher = hashlib.md5()
    with source.open("rb") as handle:
        while True:
            chunk = handle.read(COPY_CHUNK_SIZE)
            if not chunk:
                break
            out.write(chunk)
            hasher.update(chunk)
            size += len(chunk)
    return size, hasher.digest()


def pad_to(handle: BinaryIO, target_position: int) -> None:
    current = handle.tell()
    if target_position < current:
        raise ValueError("cannot pad backwards")
    if target_position > current:
        handle.write(b"\x00" * (target_position - current))


def write_directory(handle: BinaryIO, entries: list[PackedEntry]) -> None:
    handle.write(struct.pack("<I", len(entries)))
    for entry in entries:
        path_bytes = entry.path.encode("utf-8")
        padded_len = align(len(path_bytes), PATH_ALIGNMENT)
        handle.write(struct.pack("<I", padded_len))
        handle.write(path_bytes)
        handle.write(b"\x00" * (padded_len - len(path_bytes)))
        handle.write(struct.pack("<Q", entry.offset))
        handle.write(struct.pack("<Q", entry.size))
        handle.write(entry.md5)
        handle.write(struct.pack("<I", entry.flags))


def build_archive(manifest_path: Path, base_root: Path, overlay_root: Path | None, output_path: Path) -> int:
    manifest = load_manifest(manifest_path)
    header = manifest["header"]
    entries: list[PackedEntry] = []
    replaced = 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as out:
        out.write(b"\x00" * HEADER_SIZE)

        for manifest_entry in manifest["entries"]:
            packed_path = manifest_entry["path"]
            base_source = safe_source_path(base_root, packed_path)
            source = base_source
            if overlay_root is not None:
                overlay_source = find_overlay_source(overlay_root, packed_path)
                if overlay_source is not None:
                    source = overlay_source
                    replaced += 1

            if not source.is_file():
                raise FileNotFoundError(f"missing source for {packed_path!r}: {source}")

            pad_to(out, align(out.tell(), DATA_ALIGNMENT))
            offset = out.tell() - HEADER_SIZE
            size, md5 = copy_file_with_hash(source, out)
            entries.append(
                PackedEntry(
                    path=packed_path,
                    source=source,
                    offset=offset,
                    size=size,
                    md5=md5,
                    flags=int(manifest_entry["flags"]),
                )
            )

        pad_to(out, align(out.tell(), DATA_ALIGNMENT))
        directory_offset = out.tell()
        write_directory(out, entries)
        write_header(out, header, directory_offset)

    print(f"packed: {output_path}")
    print(f"files: {len(entries)}")
    if overlay_root is not None:
        print(f"overlay replacements: {replaced}")
    print(f"directory offset: 0x{directory_offset:x}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rebuild a Godot 4 GDPC/PCK archive from extracted files.")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("unpacked_pck") / "_pck_manifest.json",
        help="Manifest written by unpack_godot_pck.py.",
    )
    parser.add_argument(
        "--base",
        type=Path,
        default=Path("unpacked_pck"),
        help="Base extracted PCK folder.",
    )
    parser.add_argument(
        "--overlay",
        type=Path,
        default=Path("translated_assets"),
        help="Folder whose files replace matching base files. Use an empty/missing folder for no replacements.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("usa01_translated.pck"),
        help="Output PCK path.",
    )
    args = parser.parse_args(argv)

    overlay = args.overlay if args.overlay.exists() else None
    return build_archive(args.manifest, args.base, overlay, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
