#!/usr/bin/env python3
"""Byte-level scanner for additional WOLF command structures the structured
parser misses on this game's CommonEvent.dat.

Scans each .dat / .mps for plausible commands of:
  - CID 122 (SetString) string slot
  - CID 150 (Picture) string slot when args[0] subtype == 2 (text picture)
  - CID 102 (Show Choice) string slots

The scanner walks byte by byte; at each position it tries to interpret the
bytes as a complete WOLF command. When the parse succeeds and lands on a
clean terminator the command is recorded. False positives are rare because
WOLF strings are length-prefixed UTF-8 with a trailing null terminator.

Output: a CSV with rows of
    file, command_offset_hex, command_id, string_index, string_offset_hex, text, picture_subtype
"""

import argparse
import csv
import os
import struct
import sys
from pathlib import Path


def read_lz4_block(src: bytes, decoded_size: int) -> bytes:
    out = bytearray()
    sp = 0
    while sp < len(src):
        token = src[sp]
        sp += 1
        lit = token >> 4
        if lit == 15:
            while True:
                b = src[sp]; sp += 1
                lit += b
                if b != 255:
                    break
        out.extend(src[sp:sp+lit]); sp += lit
        if sp >= len(src):
            break
        offset = struct.unpack_from("<H", src, sp)[0]; sp += 2
        ml = token & 0xF
        if ml == 15:
            while True:
                b = src[sp]; sp += 1
                ml += b
                if b != 255:
                    break
        ml += 4
        for _ in range(ml):
            out.append(out[-offset])
    if len(out) != decoded_size:
        raise ValueError(f"lz4 decoded {len(out)} != {decoded_size}")
    return bytes(out)


def maybe_decode(path: Path) -> bytes:
    raw = path.read_bytes()
    suffix = path.suffix.lower()
    if suffix == ".mps":
        if len(raw) >= 25 and raw[10:16] == b"WOLFM\0" and raw[20] >= 0x65:
            decoded_size = struct.unpack_from("<I", raw, 25)[0]
            encoded_size = struct.unpack_from("<I", raw, 29)[0]
            payload = read_lz4_block(raw[33:33+encoded_size], decoded_size)
            return raw[:25] + payload
    if suffix == ".dat":
        if len(raw) >= 12 and raw[1:10] == b"\x57\x00\x00\x4f\x4c\x55\x46\x43\x00" and raw[10] in (0x93, 0xCC):
            decoded_size = struct.unpack_from("<I", raw, 11)[0]
            encoded_size = struct.unpack_from("<I", raw, 15)[0]
            payload = read_lz4_block(raw[19:19+encoded_size], decoded_size)
            return raw[:11] + payload
        if len(raw) >= 12 and raw[10] in (0x93, 0xC4, 0xCC):
            decoded_size = struct.unpack_from("<I", raw, 11)[0]
            encoded_size = struct.unpack_from("<I", raw, 15)[0]
            payload = read_lz4_block(raw[19:19+encoded_size], decoded_size)
            return raw[:11] + payload
    return raw


def try_read_string(data: bytes, off: int) -> tuple[int, str] | None:
    if off + 4 > len(data):
        return None
    length = struct.unpack_from("<I", data, off)[0]
    if length == 0 or length > 16 * 1024:
        return None
    if off + 4 + length > len(data):
        return None
    raw = data[off + 4:off + 4 + length]
    if raw[-1] != 0:
        return None
    if 0 in raw[:-1]:
        return None
    try:
        text = raw[:-1].decode("utf-8")
    except UnicodeDecodeError:
        return None
    return (off + 4 + length, text)


def try_parse_command(data: bytes, off: int):
    """Try to parse a WOLF command starting at `off`. Returns
    ((cid, [(slot_idx, slot_off, text)], int_args, end_off), arg0_value or None)
    or None on failure.
    """
    if off + 6 > len(data):
        return None
    int_count_plus = data[off]
    if int_count_plus == 0 or int_count_plus > 32:
        return None
    cid = struct.unpack_from("<I", data, off + 1)[0]
    if cid > 1000:
        return None
    int_count = int_count_plus - 1
    pos = off + 1 + 4
    if pos + 4 * int_count + 2 > len(data):
        return None
    int_args = []
    for _ in range(int_count):
        int_args.append(struct.unpack_from("<I", data, pos)[0])
        pos += 4
    indent = data[pos]; pos += 1
    if indent > 32:
        return None
    string_count = data[pos]; pos += 1
    if string_count > 16:
        return None
    strings = []
    for i in range(string_count):
        result = try_read_string(data, pos)
        if not result:
            return None
        new_pos, text = result
        strings.append((i, pos, text))
        pos = new_pos
    if pos >= len(data):
        return None
    terminator = data[pos]; pos += 1
    if terminator == 0x01 or cid == 201:
        if pos + 6 + 4 > len(data):
            return None
        pos += 6
        route_count = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        if route_count > 1024:
            return None
        for _ in range(route_count):
            if pos + 2 > len(data):
                return None
            _route_id = data[pos]; pos += 1
            arg_count = data[pos]; pos += 1
            if arg_count > 32:
                return None
            if pos + 4 * arg_count + 2 > len(data):
                return None
            pos += 4 * arg_count
            if data[pos] != 0x01 or data[pos + 1] != 0x00:
                return None
            pos += 2
    elif terminator != 0x00:
        return None
    return cid, strings, int_args, pos


def scan_file(path: Path):
    decoded = maybe_decode(path)
    rows = []
    off = 0
    rel = str(path).replace("\\", "/")
    while off < len(decoded) - 6:
        # Quick filter: only positions where bytes-look-like-a-command-header.
        # The CID is at off+1..+5. WOLF CIDs are small numbers.
        head = decoded[off]
        cid_low = decoded[off + 1]
        cid_hi = decoded[off + 2]
        if head == 0 or head > 32 or cid_low == 0 or cid_hi != 0:
            off += 1
            continue
        result = try_parse_command(decoded, off)
        if result is None:
            off += 1
            continue
        cid, strings, int_args, end_off = result
        if cid in (122, 150, 102, 101):
            arg0 = int_args[0] if int_args else 0
            subtype = (arg0 >> 4) & 0x07 if cid == 150 else None
            for slot_idx, slot_off, text in strings:
                rows.append({
                    "file": rel,
                    "command_offset_hex": hex(off),
                    "command_id": str(cid),
                    "string_index": str(slot_idx),
                    "string_offset_hex": hex(slot_off),
                    "text": text,
                    "picture_subtype": "" if subtype is None else str(subtype),
                })
            off = end_off
        else:
            off += 1
    return rows


def write_csv(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "file", "command_offset_hex", "command_id", "string_index",
            "string_offset_hex", "text", "picture_subtype",
        ])
        writer.writeheader()
        writer.writerows(rows)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path, help="Directory or single file to scan.")
    ap.add_argument("-o", "--output", type=Path, required=True)
    args = ap.parse_args()

    paths = []
    if args.input.is_file():
        paths = [args.input]
    else:
        for root, dirs, files in os.walk(args.input):
            for fn in files:
                p = Path(root) / fn
                if p.suffix.lower() in (".dat", ".mps"):
                    paths.append(p)

    rows = []
    for p in paths:
        rel = p.relative_to(args.input) if args.input.is_dir() else p.name
        print(f"  scan {rel}")
        try:
            rows.extend(scan_file(p))
        except Exception as e:
            print(f"    skipped: {e}")

    # rebase the file column to match relative paths from input root
    if args.input.is_dir():
        prefix = str(args.input).replace("\\", "/").rstrip("/")
        for r in rows:
            f = r["file"]
            if f.startswith(prefix):
                r["file"] = f[len(prefix) + 1:]

    write_csv(args.output, rows)
    print(f"wrote {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
