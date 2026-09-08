#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DXArchive (DxLib) v8 unpacker for "夏とプールとイソギンチャク" (PIX GAME STUDIO).

The game ships its assets in DxLib DXArchive containers (natuiso.bin, pix.bin).
Header magic is "DX", version 8. The format was confirmed by reverse-engineering
natuiso.exe in IDA (DxArchive_.cpp), and cross-checked against the canonical DxLib
source. Pipeline per encoded blob:

    on-disk bytes  --KeyConv(XOR)-->  --Huffman_Decode-->  --LZ Decode-->  original

Crypto / format facts recovered from the binary:
  * Hash = standard CRC32 (poly 0xEDB88320, init/final 0xFFFFFFFF).      [sub_755920]
  * Key  = LE32(CRC32(even-index chars)) ++ LE24(CRC32(odd-index chars)) [sub_752EE0 / KeyCreate]
           where the key string is split into even/odd byte positions.
  * KeyConv: data[i] ^= key[(position + i) % 7].                         [sub_752C70 / KeyConv]
  * Default key string = "DXBDXARC".                                     [aDxbdxarc_0]
  * The directory tables: keyed with the GLOBAL key, position 0, then
    Huffman-decoded then LZ-decoded.                                     [sub_753350]
  * Each FILE: key string = "DXBDXARC" + UPPERCASE filename
    + parent directory names (child->parent, excluding root); keyconv
    position = DataSize. Large huffman blobs only compress head+tail
    (HuffmanEncodeKB*1024 each), middle stored raw.                      [sub_754140 / sub_7521B0]

Usage:
    python dxa_unpack.py <archive.bin> [-o OUTDIR] [--list] [--key "DXBDXARC"]
"""

import os
import sys
import zlib
import struct
import argparse

try:
    import numpy as np
except ImportError:
    np = None

DEFAULT_KEY_STRING = b"DXBDXARC"          # DxLib built-in fallback (used by KeyCreate when key < 4 chars)
GAME_KEY_STRING = "_ppiixxeell_"          # this game's SetDXArchiveKeyString value (from natuiso.exe)
DXA_KEY_BYTES = 7
MIN_COMPRESS = 4
NONE64 = 0xFFFFFFFFFFFFFFFF
NAME_CODEPAGE = "cp932"  # Shift-JIS (CodePage 932)

FILE_ATTRIBUTE_DIRECTORY = 0x10


# ---------------------------------------------------------------------------
# Crypto
# ---------------------------------------------------------------------------
def key_create(source: bytes) -> bytes:
    """DXArchive::KeyCreate -> 7 byte key."""
    if len(source) < 4:
        source = source + DEFAULT_KEY_STRING
    even = source[0::2]
    odd = source[1::2]
    c0 = zlib.crc32(even) & 0xFFFFFFFF
    c1 = zlib.crc32(odd) & 0xFFFFFFFF
    return bytes([
        (c0 >> 0) & 0xFF, (c0 >> 8) & 0xFF, (c0 >> 16) & 0xFF, (c0 >> 24) & 0xFF,
        (c1 >> 0) & 0xFF, (c1 >> 8) & 0xFF, (c1 >> 16) & 0xFF,
    ])


def key_conv(data: bytes, position: int, key: bytes) -> bytes:
    """XOR data[i] ^= key[(position + i) % 7]. Returns a new bytes object."""
    if not data:
        return b""
    phase = position % DXA_KEY_BYTES
    rotated = key[phase:] + key[:phase]  # so rotated[i % 7] == key[(phase + i) % 7]
    if np is not None:
        arr = np.frombuffer(data, dtype=np.uint8)
        ks = np.frombuffer(rotated, dtype=np.uint8)
        ks = np.resize(ks, arr.shape[0])  # tiles the 7-byte cycle
        return np.bitwise_xor(arr, ks).tobytes()
    # pure-python fallback
    full = (rotated * (len(data) // DXA_KEY_BYTES + 1))[:len(data)]
    return bytes(a ^ b for a, b in zip(data, full))


# ---------------------------------------------------------------------------
# LZ decode  (DXArchive::Decode)
# ---------------------------------------------------------------------------
def lz_decode(src: bytes) -> bytearray:
    destsize = struct.unpack_from("<I", src, 0)[0]
    srcsize = struct.unpack_from("<I", src, 4)[0] - 9
    keycode = src[8]

    dest = bytearray(destsize)
    dp = 0
    sp = 9
    while srcsize > 0:
        c = src[sp]
        if c != keycode:
            dest[dp] = c
            dp += 1
            sp += 1
            srcsize -= 1
            continue
        if src[sp + 1] == keycode:
            dest[dp] = keycode
            dp += 1
            sp += 2
            srcsize -= 2
            continue

        code = src[sp + 1]
        if code > keycode:
            code -= 1
        sp += 2
        srcsize -= 2

        conbo = code >> 3
        if code & 0x4:
            conbo |= src[sp] << 5
            sp += 1
            srcsize -= 1
        conbo += MIN_COMPRESS

        indexsize = code & 0x3
        if indexsize == 0:
            index = src[sp]
            sp += 1
            srcsize -= 1
        elif indexsize == 1:
            index = struct.unpack_from("<H", src, sp)[0]
            sp += 2
            srcsize -= 2
        else:  # 2
            index = struct.unpack_from("<H", src, sp)[0] | (src[sp + 2] << 16)
            sp += 3
            srcsize -= 3
        index += 1

        # overlapping copy from dp-index, conbo bytes
        start = dp - index
        if index >= conbo:
            dest[dp:dp + conbo] = dest[start:start + conbo]
            dp += conbo
        else:
            num = index
            while conbo > num:
                dest[dp:dp + num] = dest[dp - num:dp]
                dp += num
                conbo -= num
                num += num
            if conbo:
                dest[dp:dp + conbo] = dest[dp - num:dp - num + conbo]
                dp += conbo
    return dest


# ---------------------------------------------------------------------------
# Bit stream + Huffman decode  (Huffman_Decode)
# ---------------------------------------------------------------------------
class BitStream:
    __slots__ = ("buf", "bytes", "bits")

    def __init__(self, buf):
        self.buf = buf
        self.bytes = 0
        self.bits = 0

    def read(self, bitnum):
        result = 0
        buf = self.buf
        by = self.bytes
        bi = self.bits
        for i in range(bitnum):
            result |= ((buf[by] >> (7 - bi)) & 1) << (bitnum - 1 - i)
            bi += 1
            if bi == 8:
                by += 1
                bi = 0
        self.bytes = by
        self.bits = bi
        return result

    def get_bytes(self):
        return self.bytes + (1 if self.bits != 0 else 0)


def huffman_decode(press: bytes, dest_known_size=None) -> bytearray:
    bs = BitStream(press)

    original_size = bs.read(bs.read(6) + 1)
    press_size = bs.read(bs.read(6) + 1)  # noqa: F841 (unused, present in stream)

    weight = [0] * 256
    bitnum = (bs.read(3) + 1) * 2
    bs.read(1)  # sign of weight[0] (ignored)
    weight[0] = bs.read(bitnum) & 0xFFFF
    for i in range(1, 256):
        bitnum = (bs.read(3) + 1) * 2
        minus = bs.read(1)
        save = bs.read(bitnum)
        if minus == 1:
            weight[i] = (weight[i - 1] - save) & 0xFFFF
        else:
            weight[i] = (weight[i - 1] + save) & 0xFFFF

    head_size = bs.get_bytes()

    dest_size = original_size
    dest = bytearray(dest_size)
    if dest_size == 0:
        return dest

    # ---- build huffman tree (256 leaves + 255 internal = 511 nodes) ----
    N = 256 + 255
    weight_n = [0] * N
    child0 = [-1] * N
    child1 = [-1] * N
    parent = [-1] * N
    index_bit = [0] * N
    for i in range(256):
        weight_n[i] = weight[i]

    data_num = 256
    node_num = 256
    while data_num > 1:
        min1 = -1
        min2 = -1
        ni = 0
        cnt = 0
        while cnt < data_num:
            if parent[ni] != -1:
                ni += 1
                continue
            cnt += 1
            if min1 == -1 or weight_n[min1] > weight_n[ni]:
                min2 = min1
                min1 = ni
            elif min2 == -1 or weight_n[min2] > weight_n[ni]:
                min2 = ni
            ni += 1
        parent[node_num] = -1
        weight_n[node_num] = weight_n[min1] + weight_n[min2]
        child0[node_num] = min1
        child1[node_num] = min2
        index_bit[min1] = 0
        index_bit[min2] = 1
        parent[min1] = node_num
        parent[min2] = node_num
        node_num += 1
        data_num -= 1

    # ---- derive per-symbol bit arrays ----
    bit_num = [0] * N
    bit_array = [None] * N  # each: bytes of length ceil(bitnum/8)
    for i in range(256 + 254):
        # walk up collecting index bits
        temp = bytearray(32)
        t_idx = 0
        t_cnt = 0
        bn = 0
        ni = i
        while parent[ni] != -1:
            if t_cnt == 8:
                t_cnt = 0
                t_idx += 1
                temp[t_idx] = 0
            temp[t_idx] = ((temp[t_idx] << 1) & 0xFF) | (index_bit[ni] & 1)
            t_cnt += 1
            bn += 1
            ni = parent[ni]
        bit_num[i] = bn
        # reverse into final bit array
        out = bytearray(32)
        b_cnt = 0
        b_idx = 0
        ti = t_idx
        tc = t_cnt
        while ti >= 0:
            if b_cnt == 8:
                b_cnt = 0
                b_idx += 1
                out[b_idx] = 0
            out[b_idx] |= (temp[ti] & 1) << b_cnt
            temp[ti] >>= 1
            tc -= 1
            if tc == 0:
                ti -= 1
                tc = 8
            b_cnt += 1
        bit_array[i] = bytes(out)

    # ---- build 9-bit lookup table ----
    bitmask = [((1 << (k + 1)) - 1) for k in range(9)]
    node_index_table = [-1] * 512
    for i in range(512):
        for j in range(256 + 254):
            bnj = bit_num[j]
            if bnj > 9 or bnj == 0:
                continue
            ba = bit_array[j]
            ba01 = ba[0] | (ba[1] << 8)
            m = bitmask[bnj - 1]
            if (i & m) == (ba01 & m):
                node_index_table[i] = j
                break

    # ---- decode ----
    press_data = press
    pd_base = head_size
    press_counter = 0
    press_bit_counter = 0
    press_bit_data = press_data[pd_base + press_counter]
    threshold = dest_size - 17

    for dsc in range(dest_size):
        if dsc >= threshold:
            node_index = 510
        else:
            if press_bit_counter == 8:
                press_counter += 1
                press_bit_data = press_data[pd_base + press_counter]
                press_bit_counter = 0
            press_bit_data = (press_bit_data | (press_data[pd_base + press_counter + 1] << (8 - press_bit_counter))) & 0x1FF
            node_index = node_index_table[press_bit_data]
            press_bit_counter += bit_num[node_index]
            if press_bit_counter >= 16:
                press_counter += 2
                press_bit_counter -= 16
                press_bit_data = press_data[pd_base + press_counter] >> press_bit_counter
            elif press_bit_counter >= 8:
                press_counter += 1
                press_bit_counter -= 8
                press_bit_data = press_data[pd_base + press_counter] >> press_bit_counter
            else:
                press_bit_data >>= bit_num[node_index]

        while node_index > 255:
            if press_bit_counter == 8:
                press_counter += 1
                press_bit_data = press_data[pd_base + press_counter]
                press_bit_counter = 0
            idx = press_bit_data & 1
            press_bit_data >>= 1
            press_bit_counter += 1
            node_index = child0[node_index] if idx == 0 else child1[node_index]

        dest[dsc] = node_index

    return dest


def huffman_decoded_size(press: bytes) -> int:
    bs = BitStream(press)
    return bs.read(bs.read(6) + 1)


# ---------------------------------------------------------------------------
# Archive structures
# ---------------------------------------------------------------------------
class Header:
    SIZE = 64

    def __init__(self, raw):
        (self.head, self.version) = struct.unpack_from("<HH", raw, 0)
        self.head_size = struct.unpack_from("<I", raw, 4)[0]
        self.data_start = struct.unpack_from("<Q", raw, 8)[0]
        self.name_table_start = struct.unpack_from("<Q", raw, 16)[0]
        self.file_table_start = struct.unpack_from("<Q", raw, 24)[0]
        self.dir_table_start = struct.unpack_from("<Q", raw, 32)[0]
        self.code_page = struct.unpack_from("<I", raw, 40)[0]
        self.flags = raw[44]
        self.huffman_kb = raw[48]

    @property
    def no_key(self):
        return bool(self.flags & 1)

    @property
    def table_uncompressed(self):
        return bool(self.flags & 2)


class FileHead:
    SIZE = 72

    def __init__(self, tbl, off):
        v = struct.unpack_from("<9Q", tbl, off)
        self.name_addr = v[0]
        self.attributes = v[1]
        self.data_addr = v[5]
        self.data_size = v[6]
        self.press_size = v[7]
        self.huff_size = v[8]

    @property
    def is_dir(self):
        return bool(self.attributes & FILE_ATTRIBUTE_DIRECTORY)


class DirInfo:
    SIZE = 32

    def __init__(self, tbl, off):
        v = struct.unpack_from("<4Q", tbl, off)
        self.dir_addr = v[0]            # FileTable offset of this dir's FileHead
        self.parent_addr = v[1]         # DirTable offset of parent (NONE64 = root)
        self.file_head_num = v[2]
        self.file_head_addr = v[3]      # FileTable offset of first FileHead


def read_name(name_table, name_addr):
    """Returns (upper_bytes, real_name_str)."""
    pack_num = struct.unpack_from("<H", name_table, name_addr)[0]
    upper_off = name_addr + 4
    end = name_table.find(b"\x00", upper_off)
    upper = name_table[upper_off:end]
    real_off = name_addr + 4 + pack_num * 4
    rend = name_table.find(b"\x00", real_off)
    real_bytes = name_table[real_off:rend]
    try:
        real = real_bytes.decode(NAME_CODEPAGE)
    except Exception:
        real = real_bytes.decode("latin-1")
    return upper, real


# ---------------------------------------------------------------------------
# Per-file decode
# ---------------------------------------------------------------------------
def decode_file(mm, header, fh, key, huff_kb):
    """Return the decoded original bytes for a FileHead."""
    enc_bytes = huff_kb * 1024
    data_off = header.data_start + fh.data_addr
    D = fh.data_size
    P = fh.press_size
    H = fh.huff_size
    has_lz = (P != NONE64)
    has_huff = (H != NONE64)

    if has_huff:
        S = P if has_lz else D  # size of the stream that huffman compressed
        if huff_kb != 0xFF and S > enc_bytes * 2:
            blob_size = H + (S - enc_bytes * 2)
        else:
            blob_size = H
    elif has_lz:
        blob_size = P
    else:
        blob_size = D

    blob = mm[data_off:data_off + blob_size]
    if not header.no_key:
        blob = key_conv(blob, D, key)  # position = DataSize

    if has_huff:
        S = P if has_lz else D
        huff_in = blob[:H]
        huff_out = huffman_decode(huff_in)
        if huff_kb != 0xFF and S > enc_bytes * 2:
            stream = bytearray(S)
            stream[0:enc_bytes] = huff_out[0:enc_bytes]
            mid_len = S - enc_bytes * 2
            stream[enc_bytes:enc_bytes + mid_len] = blob[H:H + mid_len]
            stream[S - enc_bytes:S] = huff_out[enc_bytes:enc_bytes * 2]
        else:
            stream = huff_out
        if has_lz:
            out = lz_decode(bytes(stream))
        else:
            out = stream
    elif has_lz:
        out = lz_decode(blob)
    else:
        out = blob

    return bytes(out[:D])


# ---------------------------------------------------------------------------
# Archive walker
# ---------------------------------------------------------------------------
class Archive:
    def __init__(self, path):
        self.path = path
        self.f = open(path, "rb")
        import mmap
        self.mm = mmap.mmap(self.f.fileno(), 0, access=mmap.ACCESS_READ)
        self.header = Header(self.mm[:Header.SIZE])
        if self.header.head != 0x5844 or self.header.version != 8:
            raise ValueError("Not a DXArchive v8 file (head=0x%04X ver=%d)"
                             % (self.header.head, self.header.version))

    def close(self):
        self.mm.close()
        self.f.close()

    def load_tables(self, key_string):
        h = self.header
        global_key = key_create(key_string)
        disk_blob = self.mm[h.name_table_start:]  # to EOF
        if not h.no_key:
            disk_blob = key_conv(disk_blob, 0, global_key)  # position 0
        if h.table_uncompressed:
            table = bytes(disk_blob[:h.head_size])
        else:
            huff_out = huffman_decode(bytes(disk_blob))
            table = bytes(lz_decode(bytes(huff_out)))
        if len(table) < h.head_size:
            raise ValueError("table decode short: %d < %d" % (len(table), h.head_size))
        self.name_table = table[:h.file_table_start]
        self.file_table = table[h.file_table_start:h.dir_table_start]
        self.dir_table = table[h.dir_table_start:h.head_size]
        self.key_string = key_string
        self.global_key = global_key

    def iter_files(self):
        """Yield (path_str, FileHead, key_string_bytes) for every file."""
        h = self.header
        # walk from root dir (offset 0); key_dirs = uppercase dir-name chain (excl root)
        stack = []  # list of (real_name, upper_bytes); root excluded

        def walk(dir_off):
            d = DirInfo(self.dir_table, dir_off)
            base = d.file_head_addr
            for i in range(d.file_head_num):
                fh = FileHead(self.file_table, base + i * FileHead.SIZE)
                upper, real = read_name(self.name_table, fh.name_addr)
                if fh.is_dir:
                    stack.append((real, upper))
                    walk(fh.data_addr)  # data_addr = DirTable offset of subdir
                    stack.pop()
                else:
                    path = "/".join(s[0] for s in stack)
                    path = (path + "/" + real) if path else real
                    # key string: password + upper(file) + upper(dirs child->parent)
                    ks = bytearray(self.key_string)
                    ks += upper
                    for _real, _upper in reversed(stack):
                        ks += _upper
                    yield_item.append((path, fh, bytes(ks)))

        yield_item = []
        walk(0)
        return yield_item


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="DXArchive v8 unpacker (natuiso / PIX engine)")
    ap.add_argument("archive")
    ap.add_argument("-o", "--out", default=None, help="output directory (default: <archive>_extracted)")
    ap.add_argument("--list", action="store_true", help="only list files, don't extract")
    ap.add_argument("--key", default=GAME_KEY_STRING,
                    help="archive key string (default: %s)" % GAME_KEY_STRING)
    ap.add_argument("--limit", type=int, default=0, help="extract only first N files (debug)")
    args = ap.parse_args()

    arc = Archive(args.archive)
    h = arc.header
    print("Archive : %s" % args.archive)
    print("  version=%d flags=0x%02X codepage=%d huffmanKB=%d" % (h.version, h.flags, h.code_page, h.huffman_kb))
    print("  data_start=0x%X name_table_start=0x%X head_size=0x%X" % (h.data_start, h.name_table_start, h.head_size))
    print("  no_key=%s table_uncompressed=%s" % (h.no_key, h.table_uncompressed))

    arc.load_tables(args.key.encode("ascii"))
    files = arc.iter_files()
    print("  files=%d" % len(files))

    if args.list:
        for path, fh, ks in files:
            tag = []
            if fh.huff_size != NONE64:
                tag.append("H")
            if fh.press_size != NONE64:
                tag.append("L")
            print("  %10d  [%s]  %s" % (fh.data_size, "".join(tag) or "-", path))
        arc.close()
        return

    outdir = args.out or (os.path.splitext(args.archive)[0] + "_extracted")
    os.makedirs(outdir, exist_ok=True)

    n = 0
    errs = 0
    for path, fh, ks in files:
        if args.limit and n >= args.limit:
            break
        try:
            data = decode_file(arc.mm, h, fh, key_create(ks), h.huffman_kb)
            if len(data) != fh.data_size:
                print("  ! size mismatch %s: got %d want %d" % (path, len(data), fh.data_size))
                errs += 1
            dest = os.path.join(outdir, path.replace("/", os.sep))
            os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
            with open(dest, "wb") as fo:
                fo.write(data)
            n += 1
            if n % 200 == 0:
                print("  ... %d files" % n)
        except Exception as e:
            print("  ! error %s: %s" % (path, e))
            errs += 1
    print("Extracted %d files to %s (%d errors)" % (n, outdir, errs))
    arc.close()


if __name__ == "__main__":
    main()
