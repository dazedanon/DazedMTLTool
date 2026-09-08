#!/usr/bin/env python3
"""Extract files out of an Electron ASAR archive by path prefix.

Used to pull the TyranoScript project out of ``resources/app.asar`` without
duplicating the 745 MB of media the translation never touches.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

CHUNK = 8 * 1024 * 1024

TEXT_PREFIXES = ("data/scenario/", "data/others/plugin/", "data/system/", "tyrano/")
TEXT_FILES = ("index.html", "main.js", "package.json")
TEXT_SUFFIXES = (".ks", ".js", ".json", ".html", ".css", ".txt", ".csv", ".tjs", ".svg")

IMAGE_PREFIXES = ("data/image/", "data/fgimage/", "data/bgimage/", "tyrano/images/",
                  "data/others/plugin/")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".psd", ".ico", ".icns")


def read_header(archive: Path) -> tuple[dict, int]:
    with archive.open("rb") as fh:
        head = fh.read(8)
        if len(head) != 8 or struct.unpack_from("<I", head, 0)[0] != 4:
            raise SystemExit(f"not an ASAR archive: {archive}")
        header_size = struct.unpack_from("<I", head, 4)[0]
        pickle = fh.read(header_size)
    json_size = struct.unpack_from("<I", pickle, 4)[0]
    blob = pickle[8:8 + json_size].rstrip(b"\0")
    return json.loads(blob.decode("utf-8")), 8 + header_size


def iter_entries(node: dict, prefix: str = ""):
    for name, entry in node.get("files", {}).items():
        rel = f"{prefix}/{name}" if prefix else name
        if "files" in entry:
            yield from iter_entries(entry, rel)
        else:
            yield rel, entry


def wanted(rel: str, mode: str) -> bool:
    if mode == "all":
        return True
    if mode == "text":
        if rel in TEXT_FILES:
            return True
        return rel.startswith(TEXT_PREFIXES) and rel.endswith(TEXT_SUFFIXES)
    if mode == "images":
        return rel.lower().endswith(IMAGE_SUFFIXES)
    raise SystemExit(f"unknown mode: {mode}")


def safe_join(root: Path, rel: str) -> Path:
    target = (root / rel).resolve()
    if target != root.resolve() and root.resolve() not in target.parents:
        raise SystemExit(f"refusing path outside output root: {rel}")
    return target


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("archive", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--mode", choices=("text", "images", "all"), default="text")
    ap.add_argument("--force", action="store_true", help="rewrite files that already exist")
    args = ap.parse_args()

    header, data_offset = read_header(args.archive)
    entries = [(rel, e) for rel, e in iter_entries(header) if wanted(rel, args.mode)]
    if any(e.get("unpacked") or "link" in e for _, e in entries):
        raise SystemExit("Unsupported unpacked or linked entry")
    entries.sort(key=lambda t: int(t[1].get("offset", "0")))

    written = skipped = total = 0
    args.output.mkdir(parents=True, exist_ok=True)
    with args.archive.open("rb") as fh:
        for index, (rel, entry) in enumerate(entries, 1):
            out = safe_join(args.output, rel)
            if out.exists() and not args.force:
                skipped += 1
                continue
            size = int(entry.get("size", 0))
            fh.seek(data_offset + int(entry.get("offset", "0")))
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open("wb") as dst:
                left = size
                while left:
                    buf = fh.read(min(CHUNK, left))
                    if not buf:
                        raise SystemExit(f"unexpected EOF extracting {rel}")
                    dst.write(buf)
                    left -= len(buf)
            written += 1
            total += size
            if index % 200 == 0:
                print(f"  {index}/{len(entries)}  {total / 1048576:.0f} MiB", flush=True)

    print(f"archive : {args.archive}")
    print(f"output  : {args.output}")
    print(f"mode    : {args.mode}")
    print(f"written : {written}   skipped(existing): {skipped}   bytes: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
