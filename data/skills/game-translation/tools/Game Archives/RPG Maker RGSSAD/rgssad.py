"""RGSSAD / RGSS2A / RGSS3A archive reader for RPG Maker XP, VX and VX Ace.

Format notes (little-endian throughout):

  header      "RGSSAD\0" + version byte (1 = XP/VX, 3 = VX Ace)

  v1/v2       entries follow immediately, each XOR-decrypted with a running
              key that starts at 0xDEADCAFE and advances key = key*7+3 after
              every 4-byte field and after every name byte.
              entry: u32 name_len, name_len bytes (one key step per byte),
                     u32 data_size, then data_size bytes of payload
                     encrypted with the key value reached at that point.

  v3          u32 seed, then key = seed*9+3 (mod 2^32) for the whole table.
              entry: u32 offset, u32 size, u32 data_key, u32 name_len,
                     name_len bytes XOR'd with the key's 4 LE bytes cycled.
              offset == 0 terminates the table. Payload is XOR'd with
              data_key, advancing key = key*7+3 after each 4-byte block.
"""

import argparse
import os
import struct
import sys

MASK = 0xFFFFFFFF


def _advance(key):
    return (key * 7 + 3) & MASK


def _decrypt_data(blob, key):
    out = bytearray(blob)
    for i in range(0, len(out), 4):
        chunk = key.to_bytes(4, "little")
        for j in range(min(4, len(out) - i)):
            out[i + j] ^= chunk[j]
        key = _advance(key)
    return bytes(out)


class Entry:
    __slots__ = ("name", "offset", "size", "key")

    def __init__(self, name, offset, size, key):
        self.name = name
        self.offset = offset
        self.size = size
        self.key = key


def _read_v3(f):
    seed = struct.unpack("<I", f.read(4))[0]
    key = (seed * 9 + 3) & MASK
    kb = key.to_bytes(4, "little")
    entries = []
    while True:
        head = f.read(16)
        if len(head) < 16:
            break
        offset, size, data_key, name_len = (v ^ key for v in struct.unpack("<4I", head))
        if offset == 0:
            break
        if name_len > 0x1000:
            raise ValueError("implausible name length %d - not a v3 archive?" % name_len)
        raw = f.read(name_len)
        name = bytes(b ^ kb[i % 4] for i, b in enumerate(raw)).decode("utf-8")
        entries.append(Entry(name.replace("\\", "/"), offset, size, data_key))
    return entries


def _read_v1(f):
    key = 0xDEADCAFE
    entries = []
    while True:
        head = f.read(4)
        if len(head) < 4:
            break
        name_len = struct.unpack("<I", head)[0] ^ key
        key = _advance(key)
        if name_len > 0x1000:
            raise ValueError("implausible name length %d - corrupt archive?" % name_len)
        raw = bytearray(f.read(name_len))
        for i in range(name_len):
            raw[i] ^= key & 0xFF
            key = _advance(key)
        size = struct.unpack("<I", f.read(4))[0] ^ key
        key = _advance(key)
        entries.append(Entry(bytes(raw).decode("utf-8").replace("\\", "/"),
                             f.tell(), size, key))
        f.seek(size, os.SEEK_CUR)
    return entries


def read_index(path):
    with open(path, "rb") as f:
        magic = f.read(8)
        if magic[:7] != b"RGSSAD\0":
            raise ValueError("not an RGSSAD archive: %r" % magic[:7])
        version = magic[7]
        if version == 3:
            return version, _read_v3(f)
        if version in (1, 2):
            return version, _read_v1(f)
        raise ValueError("unsupported RGSSAD version %d" % version)


def extract(archive, outdir, listing_only=False, verbose=False):
    version, entries = read_index(archive)
    print("RGSSAD v%d, %d files" % (version, len(entries)))
    if listing_only:
        for e in sorted(entries, key=lambda e: e.name):
            print("%10d  %s" % (e.size, e.name))
        return entries

    with open(archive, "rb") as f:
        for e in entries:
            dest = os.path.join(outdir, *e.name.split("/"))
            # Reject any entry that would escape the output directory.
            if not os.path.abspath(dest).startswith(os.path.abspath(outdir) + os.sep):
                raise ValueError("unsafe entry path: %s" % e.name)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            f.seek(e.offset)
            blob = f.read(e.size)
            if len(blob) != e.size:
                raise ValueError("truncated archive at %s" % e.name)
            with open(dest, "wb") as out:
                out.write(_decrypt_data(blob, e.key))
            if verbose:
                print("%10d  %s" % (e.size, e.name))
    print("extracted to %s" % os.path.abspath(outdir))
    return entries


def main(argv=None):
    # Archive names are Japanese; a cp932/cp1252 console must not abort the run.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="Extract RPG Maker RGSSAD/RGSS2A/RGSS3A archives.")
    ap.add_argument("archive")
    ap.add_argument("-o", "--outdir", default=".", help="output directory (default: cwd)")
    ap.add_argument("-l", "--list", action="store_true", help="list contents, extract nothing")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    extract(a.archive, a.outdir, a.list, a.verbose)
    return 0


if __name__ == "__main__":
    sys.exit(main())
