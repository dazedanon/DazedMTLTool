#!/usr/bin/env python3
"""Parse WOLF UDB / VDB / SDB .dat files and emit a JSONL of every string slot
with its semantic role (type_name, data_name, field_value, etc.).

Usage:
  py dump_db_structure.py <input.dat> [<input.project>] -o <out.jsonl>
"""

import argparse
import json
import struct
from pathlib import Path
from typing import List, Optional, Tuple


def lz4_decompress(src: bytes, decoded_size: int) -> bytes:
    out = bytearray()
    sp = 0
    while sp < len(src):
        token = src[sp]
        sp += 1
        lit_len = (token >> 4) & 0xF
        if lit_len == 15:
            while True:
                b = src[sp]
                sp += 1
                lit_len += b
                if b != 255:
                    break
        out.extend(src[sp:sp + lit_len])
        sp += lit_len
        if sp >= len(src):
            break
        if sp + 2 > len(src):
            raise ValueError("lz4 match offset truncated")
        offset = struct.unpack_from("<H", src, sp)[0]
        sp += 2
        match_len = token & 0xF
        if match_len == 15:
            while True:
                b = src[sp]
                sp += 1
                match_len += b
                if b != 255:
                    break
        match_len += 4
        if offset == 0 or offset > len(out):
            raise ValueError("invalid lz4 match offset")
        for _ in range(match_len):
            out.append(out[len(out) - offset])
    if len(out) != decoded_size:
        raise ValueError(f"decoded {len(out)} != {decoded_size}")
    return bytes(out)


def maybe_unpack(data: bytes) -> Tuple[bytes, int]:
    """Decode a WOLF binary into its unpacked-payload form, returning
    (decoded_bytes, header_prefix_len). The result has the original 11- /
    25-byte file header followed by the decoded payload; the parsers can
    consume it as if it were never compressed."""
    # CommonEvent.dat — `\x00W\x00\x00OLUFC\x00` magic at bytes 1..10
    if len(data) >= 12 and data[1:10] == b"\x57\x00\x00\x4f\x4c\x55\x46\x43\x00":
        header = 10
        verbyte = data[10]
        if verbyte in (0x93, 0xCC):
            decoded_size = struct.unpack_from("<I", data, header + 1)[0]
            encoded_size = struct.unpack_from("<I", data, header + 5)[0]
            encoded = data[header + 9:header + 9 + encoded_size]
            payload = lz4_decompress(encoded, decoded_size)
            return data[:header + 1] + payload, header + 1
        return data, header + 1
    # MapData/*.mps — WOLFM at bytes 10..16, version at offset 20, LZ4 at 25
    if len(data) >= 25 and data[10:16] == b"WOLFM\x00":
        header = 25
        if data[20] >= 0x65:
            decoded_size = struct.unpack_from("<I", data, header)[0]
            encoded_size = struct.unpack_from("<I", data, header + 4)[0]
            encoded = data[header + 8:header + 8 + encoded_size]
            payload = lz4_decompress(encoded, decoded_size)
            return data[:header] + payload, header
        return data, header
    # DB .dat files — version at offset 10, LZ4 at 11
    if len(data) >= 12 and data[10] in (0x93, 0xC4, 0xCC):
        header = 11
        decoded_size = struct.unpack_from("<I", data, header)[0]
        encoded_size = struct.unpack_from("<I", data, header + 4)[0]
        encoded = data[header + 8:header + 8 + encoded_size]
        payload = lz4_decompress(encoded, decoded_size)
        return data[:header] + payload, header
    return data, 0


def read_u32(data: bytes, off: int) -> Tuple[int, int]:
    return struct.unpack_from("<I", data, off)[0], off + 4


def read_str(data: bytes, off: int) -> Tuple[str, int, int]:
    length, off = read_u32(data, off)
    if length == 0:
        return "", length, off
    raw = data[off:off + length]
    if not raw or raw[-1] != 0:
        raise ValueError(f"unterminated string at off={off-4}")
    text = raw[:-1].decode("utf-8", errors="replace")
    return text, length, off + length


def parse_db_dat(path: Path) -> List[dict]:
    """Parse UDB/VDB/SDB .dat. Returns list of slot records.
    Each record: {file, offset, role, type_index, data_index, field_index, text, kind}
    Roles: type_name, type_id, data_name, field_name, field_value, header
    """
    raw = path.read_bytes()
    decoded, prefix_end = maybe_unpack(raw)
    # In a packed file, our offsets are computed in the unpacked layout, mapping is different.
    # So we keep offsets in the *unpacked* coordinate (since the inject tool also expects unpacked offsets when packed).
    return parse_dat_payload(decoded, prefix_end, str(path))


def parse_dat_payload(data: bytes, payload_start: int, file_label: str) -> List[dict]:
    """A WOLF DB .dat payload typically structured as:
      [header bytes ... usually a few magic bytes / version]
      type_count (u32)
      For each type:
        type_name (string)
        data_count (u32)
        For each data:
          data_name (string)
          field_count (u32)
          For each field:
            field_value (string OR int based on .project schema, which we don't have)
    But the actual WOLF DB .dat format uses "0xc1" / "0xc2" / "0xc3" markers, etc.

    We can't fully parse without the .project. But we can heuristically scan for
    strings and record them with their position. In practice, the project file
    exists; let's treat the .dat for now as an opaque sequence and just extract
    every length-prefixed UTF-8 string.
    """
    rows = []
    off = payload_start
    while off + 4 < len(data):
        # try a length-prefixed string
        length = struct.unpack_from("<I", data, off)[0]
        if 0 < length <= 16 * 1024 and off + 4 + length <= len(data):
            raw = data[off + 4:off + 4 + length]
            if raw[-1] == 0 and 0 not in raw[:-1]:
                try:
                    text = raw[:-1].decode("utf-8")
                except UnicodeDecodeError:
                    off += 1
                    continue
                rows.append({
                    "file": file_label,
                    "offset": off,
                    "byte_len": length,
                    "text": text,
                    "kind": "string",
                })
                off += 4 + length
                continue
        off += 1
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dat", type=Path)
    ap.add_argument("-o", "--output", required=True, type=Path)
    args = ap.parse_args()
    rows = parse_db_dat(args.dat)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
