#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import struct
import sys
import time


CHUNK_SIZE = 8 * 1024 * 1024


def read_u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def read_header(archive: Path) -> tuple[dict, int]:
    with archive.open("rb") as handle:
        size_pickle = handle.read(8)
        if len(size_pickle) != 8:
            raise ValueError("ASAR archive is too small")
        payload_size = read_u32(size_pickle, 0)
        if payload_size != 4:
            raise ValueError(f"unexpected ASAR size-pickle payload: {payload_size}")
        header_size = read_u32(size_pickle, 4)
        header_pickle = handle.read(header_size)
        if len(header_pickle) != header_size:
            raise ValueError("ASAR header is truncated")

    if len(header_pickle) < 8:
        raise ValueError("ASAR header pickle is too small")
    json_size = read_u32(header_pickle, 4)
    json_blob = header_pickle[8 : 8 + json_size].rstrip(b"\0")
    return json.loads(json_blob.decode("utf-8")), 8 + header_size


def safe_join(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    root = root.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"refusing path outside output root: {relative}")
    return candidate


def iter_entries(node: dict, prefix: str = ""):
    for name, entry in sorted(node.get("files", {}).items()):
        rel = f"{prefix}/{name}" if prefix else name
        if "files" in entry:
            yield from iter_entries(entry, rel)
        else:
            yield rel, entry


def copy_range(handle, out_path: Path, offset: int, size: int):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    remaining = size
    handle.seek(offset)
    with out_path.open("wb") as out:
        while remaining:
            chunk = handle.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                raise EOFError(f"unexpected EOF while extracting {out_path}")
            out.write(chunk)
            remaining -= len(chunk)


def extract(archive: Path, output: Path, unpacked_dir: Path | None = None) -> int:
    header, data_offset = read_header(archive)
    entries = list(iter_entries(header))
    output.mkdir(parents=True, exist_ok=True)

    start = time.time()
    extracted = 0
    skipped_unpacked = 0
    copied_bytes = 0
    with archive.open("rb") as handle:
        for index, (rel, entry) in enumerate(entries, 1):
            out_path = safe_join(output, rel)
            if "link" in entry:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(str(entry["link"]), encoding="utf-8")
                extracted += 1
                continue
            if entry.get("unpacked"):
                if unpacked_dir:
                    src = unpacked_dir / rel
                    if src.exists():
                        out_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, out_path)
                        extracted += 1
                        continue
                skipped_unpacked += 1
                continue
            size = int(entry.get("size", 0))
            offset = data_offset + int(entry.get("offset", "0"))
            copy_range(handle, out_path, offset, size)
            extracted += 1
            copied_bytes += size
            if index % 250 == 0 or index == len(entries):
                elapsed = max(time.time() - start, 0.1)
                mib = copied_bytes / (1024 * 1024)
                print(
                    f"progress {index}/{len(entries)} files | {mib:.1f} MiB | "
                    f"{mib / elapsed:.1f} MiB/s",
                    flush=True,
                )

    print(f"archive: {archive}")
    print(f"output: {output}")
    print(f"files_extracted: {extracted}")
    print(f"unpacked_entries_skipped: {skipped_unpacked}")
    return 0 if skipped_unpacked == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline ASAR extractor.")
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--unpacked-dir", type=Path, default=None)
    args = parser.parse_args()

    archive = args.archive.resolve()
    output = args.output.resolve()
    unpacked_dir = args.unpacked_dir.resolve() if args.unpacked_dir else None
    if not archive.exists():
        raise SystemExit(f"archive not found: {archive}")
    return extract(archive, output, unpacked_dir)


if __name__ == "__main__":
    raise SystemExit(main())
