#!/usr/bin/env python3
"""Extract files from a Godot 4 GDPC/PCK archive.

This is intentionally small and dependency-free. It copies the raw packed
files to disk and writes a manifest with offsets, sizes, flags, and hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO


PCK_MAGIC = b"GDPC"
HEADER_SIZE = 0x70
ENTRY_OVERHEAD = 4 + 8 + 8 + 16 + 4
COPY_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class PckHeader:
    format_version: int
    engine_major: int
    engine_minor: int
    engine_patch: int
    flags: int
    file_base: int
    directory_offset: int


@dataclass(frozen=True)
class PckEntry:
    path: str
    offset: int
    data_offset: int
    size: int
    md5: str
    flags: int
    extractable: bool


def read_exact(handle: BinaryIO, size: int) -> bytes:
    data = handle.read(size)
    if len(data) != size:
        raise EOFError(f"wanted {size} bytes, got {len(data)}")
    return data


def read_u32(handle: BinaryIO) -> int:
    return struct.unpack("<I", read_exact(handle, 4))[0]


def read_u64(handle: BinaryIO) -> int:
    return struct.unpack("<Q", read_exact(handle, 8))[0]


def parse_header(handle: BinaryIO) -> PckHeader:
    handle.seek(0)
    header = read_exact(handle, HEADER_SIZE)
    if header[:4] != PCK_MAGIC:
        raise ValueError("not a GDPC/PCK archive")

    return PckHeader(
        format_version=struct.unpack_from("<I", header, 0x04)[0],
        engine_major=struct.unpack_from("<I", header, 0x08)[0],
        engine_minor=struct.unpack_from("<I", header, 0x0C)[0],
        engine_patch=struct.unpack_from("<I", header, 0x10)[0],
        flags=struct.unpack_from("<I", header, 0x14)[0],
        file_base=struct.unpack_from("<Q", header, 0x18)[0],
        directory_offset=struct.unpack_from("<Q", header, 0x20)[0],
    )


def parse_directory(handle: BinaryIO, header: PckHeader, archive_size: int) -> list[PckEntry]:
    if not (HEADER_SIZE <= header.directory_offset < archive_size):
        raise ValueError(f"directory offset looks invalid: 0x{header.directory_offset:x}")

    handle.seek(header.directory_offset)
    file_count = read_u32(handle)
    entries: list[PckEntry] = []

    for index in range(file_count):
        path_len = read_u32(handle)
        if path_len == 0 or path_len > archive_size:
            raise ValueError(f"entry {index} has invalid path length: {path_len}")

        path_bytes = read_exact(handle, path_len)
        path = path_bytes.decode("utf-8", errors="surrogateescape").rstrip("\x00")
        offset = read_u64(handle)
        size = read_u64(handle)
        md5 = read_exact(handle, 16).hex()
        flags = read_u32(handle)

        data_offset = header.file_base + offset
        end = data_offset + size
        extractable = data_offset >= header.file_base and end <= header.directory_offset
        if not extractable:
            raise ValueError(
                f"entry {index} has invalid data range: "
                f"path={path!r} offset=0x{offset:x} data_offset=0x{data_offset:x} size=0x{size:x}"
            )

        entries.append(
            PckEntry(
                path=path,
                offset=offset,
                data_offset=data_offset,
                size=size,
                md5=md5,
                flags=flags,
                extractable=extractable,
            )
        )

    return entries


def safe_output_path(output_root: Path, packed_path: str) -> Path:
    normalized = packed_path.replace("\\", "/")
    if normalized.startswith("res://"):
        normalized = normalized[len("res://") :]
    normalized = normalized.lstrip("/")

    parts = PurePosixPath(normalized).parts
    if not parts:
        raise ValueError("empty packed path")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"unsafe packed path: {packed_path!r}")
    if any(":" in part for part in parts):
        raise ValueError(f"packed path contains a drive or scheme marker: {packed_path!r}")

    candidate = output_root.joinpath(*parts).resolve()
    output_root_resolved = output_root.resolve()
    if os.path.commonpath([str(output_root_resolved), str(candidate)]) != str(output_root_resolved):
        raise ValueError(f"packed path escapes output directory: {packed_path!r}")
    return candidate


def copy_entry(handle: BinaryIO, entry: PckEntry, target: Path, verify: bool) -> bool:
    target.parent.mkdir(parents=True, exist_ok=True)
    remaining = entry.size
    hasher = hashlib.md5() if verify else None

    handle.seek(entry.data_offset)
    with target.open("wb") as out:
        while remaining:
            chunk = read_exact(handle, min(COPY_CHUNK_SIZE, remaining))
            out.write(chunk)
            if hasher is not None:
                hasher.update(chunk)
            remaining -= len(chunk)

    return hasher is None or hasher.hexdigest() == entry.md5


def write_manifest(
    manifest_path: Path,
    archive_path: Path,
    header: PckHeader,
    entries: list[PckEntry],
    mismatches: list[str],
    skipped: list[str],
) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "archive": str(archive_path.resolve()),
        "header": asdict(header),
        "file_count": len(entries),
        "hash_mismatches": mismatches,
        "skipped_non_extractable": skipped,
        "entries": [asdict(entry) for entry in entries],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def extract_archive(archive_path: Path, output_root: Path, verify: bool) -> int:
    archive_size = archive_path.stat().st_size
    with archive_path.open("rb") as handle:
        header = parse_header(handle)
        entries = parse_directory(handle, header, archive_size)

        print(
            "PCK: "
            f"format={header.format_version} "
            f"engine={header.engine_major}.{header.engine_minor}.{header.engine_patch} "
            f"files={len(entries)} "
            f"dir=0x{header.directory_offset:x}"
        )

        mismatches: list[str] = []
        skipped: list[str] = []
        for index, entry in enumerate(entries, start=1):
            if not entry.extractable:
                skipped.append(entry.path)
                if index == len(entries) or index % 250 == 0:
                    print(f"extracted {index - len(skipped)}/{len(entries)}")
                continue

            target = safe_output_path(output_root, entry.path)
            ok = copy_entry(handle, entry, target, verify=verify)
            if not ok:
                mismatches.append(entry.path)

            if index == len(entries) or index % 250 == 0:
                print(f"extracted {index}/{len(entries)}")

    manifest_path = output_root / "_pck_manifest.json"
    write_manifest(manifest_path, archive_path, header, entries, mismatches, skipped)
    print(f"manifest: {manifest_path}")

    if skipped:
        print(f"skipped non-extractable directory records: {len(skipped)}")

    if mismatches:
        print(f"warning: {len(mismatches)} MD5 mismatch(es)", file=sys.stderr)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract raw files from a Godot GDPC/PCK archive.")
    parser.add_argument("archive", type=Path, help="Path to the .pck file.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("unpacked_pck"),
        help="Output directory. Default: unpacked_pck",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip MD5 verification while extracting.",
    )
    args = parser.parse_args(argv)

    return extract_archive(args.archive, args.output, verify=not args.no_verify)


if __name__ == "__main__":
    raise SystemExit(main())
