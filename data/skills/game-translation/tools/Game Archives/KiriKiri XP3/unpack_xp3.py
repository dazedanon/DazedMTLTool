#!/usr/bin/env python3
import argparse
import shutil
import struct
import sys
import zlib
from pathlib import Path, PurePosixPath


XP3_MAGIC = b"XP3\r\n \n\x1a\x8b\x67\x01"


class XP3Error(Exception):
    pass


def read_u16(buf, off):
    return struct.unpack_from("<H", buf, off)[0]


def read_u32(buf, off):
    return struct.unpack_from("<I", buf, off)[0]


def read_u64(buf, off):
    return struct.unpack_from("<Q", buf, off)[0]


def read_index(fp):
    fp.seek(0)
    if fp.read(len(XP3_MAGIC)) != XP3_MAGIC:
        raise XP3Error("missing XP3 magic")

    index_offset = struct.unpack("<Q", fp.read(8))[0]
    fp.seek(index_offset)
    flag = fp.read(1)[0]

    # This archive uses an XP3 continuation marker at the header index pointer:
    # 0x80, zero, real_index_offset. Follow it before reading the zlib index.
    if flag & 0x80:
        first_offset = struct.unpack("<Q", fp.read(8))[0]
        next_offset = struct.unpack("<Q", fp.read(8))[0]
        if next_offset:
            index_offset = next_offset
        elif first_offset:
            index_offset = first_offset
        else:
            raise XP3Error("XP3 continuation marker has no target offset")
        fp.seek(index_offset)
        flag = fp.read(1)[0]

    method = flag & 0x7F
    if method == 0:
        size = struct.unpack("<Q", fp.read(8))[0]
        return fp.read(size)
    if method == 1:
        compressed_size = struct.unpack("<Q", fp.read(8))[0]
        original_size = struct.unpack("<Q", fp.read(8))[0]
        data = zlib.decompress(fp.read(compressed_size))
        if len(data) != original_size:
            raise XP3Error(
                f"index size mismatch: got {len(data)}, expected {original_size}"
            )
        return data
    raise XP3Error(f"unsupported XP3 index method {method}")


def parse_index(index):
    records = []
    pos = 0
    while pos < len(index):
        tag = index[pos : pos + 4]
        size = read_u64(index, pos + 4)
        body = index[pos + 12 : pos + 12 + size]
        if tag != b"File":
            raise XP3Error(f"unexpected top-level tag {tag!r} at 0x{pos:x}")

        record = {"name": None, "flags": 0, "original_size": 0, "archive_size": 0, "segments": [], "adler32": None}
        sub_pos = 0
        while sub_pos < len(body):
            sub_tag = body[sub_pos : sub_pos + 4]
            sub_size = read_u64(body, sub_pos + 4)
            sub = body[sub_pos + 12 : sub_pos + 12 + sub_size]

            if sub_tag == b"info":
                record["flags"] = read_u32(sub, 0)
                record["original_size"] = read_u64(sub, 4)
                record["archive_size"] = read_u64(sub, 12)
                name_len = read_u16(sub, 20)
                record["name"] = sub[22 : 22 + name_len * 2].decode("utf-16le")
            elif sub_tag == b"segm":
                if len(sub) % 28:
                    raise XP3Error(f"bad segment table length for {record['name']}")
                for seg_pos in range(0, len(sub), 28):
                    record["segments"].append(
                        {
                            "flags": read_u32(sub, seg_pos),
                            "offset": read_u64(sub, seg_pos + 4),
                            "original_size": read_u64(sub, seg_pos + 12),
                            "archive_size": read_u64(sub, seg_pos + 20),
                        }
                    )
            elif sub_tag == b"adlr":
                record["adler32"] = read_u32(sub, 0)

            sub_pos += 12 + sub_size

        if not record["name"]:
            raise XP3Error(f"file record at 0x{pos:x} has no name")
        records.append(record)
        pos += 12 + size
    return records


def output_path(root, xp3_name):
    normalized = xp3_name.replace("\\", "/")
    rel = PurePosixPath(normalized)
    if rel.is_absolute() or any(part in ("", ".", "..") for part in rel.parts):
        raise XP3Error(f"unsafe archive path {xp3_name!r}")
    return root.joinpath(*rel.parts)


def extract_file(src, dst, record, overwrite):
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and not overwrite:
        raise XP3Error(f"output exists: {dst}")

    checksum = 1
    total = 0
    with dst.open("wb") as out:
        for segment in record["segments"]:
            src.seek(segment["offset"])
            raw_size = segment["archive_size"]
            original_size = segment["original_size"]
            flags = segment["flags"]

            if flags == 0:
                remaining = raw_size
                while remaining:
                    chunk = src.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise XP3Error(f"unexpected EOF while reading {record['name']}")
                    out.write(chunk)
                    checksum = zlib.adler32(chunk, checksum)
                    total += len(chunk)
                    remaining -= len(chunk)
                if raw_size != original_size:
                    raise XP3Error(f"raw segment size mismatch for {record['name']}")
            elif flags == 1:
                data = zlib.decompress(src.read(raw_size))
                if len(data) != original_size:
                    raise XP3Error(f"compressed segment size mismatch for {record['name']}")
                out.write(data)
                checksum = zlib.adler32(data, checksum)
                total += len(data)
            else:
                raise XP3Error(f"unsupported segment flags {flags} for {record['name']}")

    if total != record["original_size"]:
        raise XP3Error(f"file size mismatch for {record['name']}")
    if record["adler32"] is not None and (checksum & 0xFFFFFFFF) != record["adler32"]:
        raise XP3Error(f"adler32 mismatch for {record['name']}")


def main():
    parser = argparse.ArgumentParser(description="Unpack a standard Kirikiri XP3 archive.")
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    with args.archive.open("rb") as src:
        records = parse_index(read_index(src))
        print(f"records: {len(records)}")
        print(f"output: {args.output}")
        for index, record in enumerate(records, 1):
            extract_file(src, output_path(args.output, record["name"]), record, args.overwrite)
            if index % 100 == 0 or index == len(records):
                print(f"extracted {index}/{len(records)}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except XP3Error as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
