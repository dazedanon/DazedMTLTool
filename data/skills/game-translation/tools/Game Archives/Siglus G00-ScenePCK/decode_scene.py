"""Decoder for Siglus Scene.pck chunks.

From SiglusEngine_unpacked.exe / sub_6984D0:
  - Each chunk is XORed with a 16-byte key (KEY1) [conditional flag]
  - Then XORed with a 256-byte key (KEY2)
  - Then LZSS-decompressed via sub_71DD60

LZSS layout (from sub_71DD60):
  bytes [0..3]:  unused/reserved  (a1+0)
  bytes [4..7]:  decompressed_size (uint32, a1+4)
  bytes [8..]:   LZSS data
    - flag byte (8 bits)
    - for each bit (LSB first):
        bit=1: literal byte (1 byte)
        bit=0: back-ref (2 bytes LE):
          length = (word & 0xF) + 2
          distance = word >> 4
          copy <length> bytes from <output_pos - distance>
"""

import struct, os, sys

# Key extracted from byte_B5CA16, B5C9E1, ... (in v134 slot order)
KEY1 = bytes([
    0xA4, 0x8C, 0x8A, 0x28, 0x61, 0x58, 0x08, 0x05,
    0xE7, 0xD2, 0xF3, 0x48, 0xA3, 0x07, 0xED, 0x8B,
])

# Key extracted from byte_ADBBB0 (256 bytes)
KEY2 = bytes([
    0x70, 0xF8, 0xA6, 0xB0, 0xA1, 0xA5, 0x28, 0x4F, 0xB5, 0x2F, 0x48, 0xFA, 0xE1, 0xE9, 0x4B, 0xDE,
    0xB7, 0x4F, 0x62, 0x95, 0x8B, 0xE0, 0x03, 0x80, 0xE7, 0xCF, 0x0F, 0x6B, 0x92, 0x01, 0xEB, 0xF8,
    0xA2, 0x88, 0xCE, 0x63, 0x04, 0x38, 0xD2, 0x6D, 0x8C, 0xD2, 0x88, 0x76, 0xA7, 0x92, 0x71, 0x8F,
    0x4E, 0xB6, 0x8D, 0x01, 0x79, 0x88, 0x83, 0x0A, 0xF9, 0xE9, 0x2C, 0xDB, 0x67, 0xDB, 0x91, 0x14,
    0xD5, 0x9A, 0x4E, 0x79, 0x17, 0x23, 0x08, 0x96, 0x0E, 0x1D, 0x15, 0xF9, 0xA5, 0xA0, 0x6F, 0x58,
    0x17, 0xC8, 0xA9, 0x46, 0xDA, 0x22, 0xFF, 0xFD, 0x87, 0x12, 0x42, 0xFB, 0xA9, 0xB8, 0x67, 0x6C,
    0x91, 0x67, 0x64, 0xF9, 0xD1, 0x1E, 0xE4, 0x50, 0x64, 0x6F, 0xF2, 0x0B, 0xDE, 0x40, 0xE7, 0x47,
    0xF1, 0x03, 0xCC, 0x2A, 0xAD, 0x7F, 0x34, 0x21, 0xA0, 0x64, 0x26, 0x98, 0x6C, 0xED, 0x69, 0xF4,
    0xB5, 0x23, 0x08, 0x6E, 0x7D, 0x92, 0xF6, 0xEB, 0x93, 0xF0, 0x7A, 0x89, 0x5E, 0xF9, 0xF8, 0x7A,
    0xAF, 0xE8, 0xA9, 0x48, 0xC2, 0xAC, 0x11, 0x6B, 0x2B, 0x33, 0xA7, 0x40, 0x0D, 0xDC, 0x7D, 0xA7,
    0x5B, 0xCF, 0xC8, 0x31, 0xD1, 0x77, 0x52, 0x8D, 0x82, 0xAC, 0x41, 0xB8, 0x73, 0xA5, 0x4F, 0x26,
    0x7C, 0x0F, 0x39, 0xDA, 0x5B, 0x37, 0x4A, 0xDE, 0xA4, 0x49, 0x0B, 0x7C, 0x17, 0xA3, 0x43, 0xAE,
    0x77, 0x06, 0x64, 0x73, 0xC0, 0x43, 0xA3, 0x18, 0x5A, 0x0F, 0x9F, 0x02, 0x4C, 0x7E, 0x8B, 0x01,
    0x9F, 0x2D, 0xAE, 0x72, 0x54, 0x13, 0xFF, 0x96, 0xAE, 0x0B, 0x34, 0x58, 0xCF, 0xE3, 0x00, 0x78,
    0xBE, 0xE3, 0xF5, 0x61, 0xE4, 0x87, 0x7C, 0xFC, 0x80, 0xAF, 0xC4, 0x8D, 0x46, 0x3A, 0x5D, 0xD0,
    0x36, 0xBC, 0xE5, 0x60, 0x77, 0x68, 0x08, 0x4F, 0xBB, 0xAB, 0xE2, 0x78, 0x07, 0xE8, 0x73, 0xBF,
])
assert len(KEY2) == 256


def xor_with(buf: bytes, key: bytes) -> bytes:
    out = bytearray(buf)
    klen = len(key)
    for i in range(len(out)):
        out[i] ^= key[i % klen]
    return bytes(out)


def lzss_decompress(data: bytes) -> bytes:
    """Decompress LZSS as in sub_71DD60.
    Header: 8 bytes (4 reserved, 4 uint32 decompressed size).
    Then bit-flagged stream: 1=literal, 0=back-ref (2-byte LE, low4=len-2, high12=distance).
    """
    if len(data) < 8:
        return b""
    reserved = struct.unpack_from("<I", data, 0)[0]
    out_size = struct.unpack_from("<I", data, 4)[0]
    pos = 8
    out = bytearray()
    while len(out) < out_size:
        if pos >= len(data):
            break
        flag = data[pos]
        pos += 1
        for _ in range(8):
            if len(out) >= out_size:
                break
            if pos >= len(data):
                break
            if flag & 1:
                out.append(data[pos])
                pos += 1
            else:
                if pos + 1 >= len(data):
                    break
                w = data[pos] | (data[pos + 1] << 8)
                pos += 2
                length = (w & 0xF) + 2
                distance = w >> 4
                if distance == 0 or distance > len(out):
                    # malformed -- give up
                    return bytes(out)
                start = len(out) - distance
                for k in range(length):
                    out.append(out[start + k])
            flag >>= 1
    return bytes(out)


def decode(chunk: bytes, use_key1: bool) -> bytes:
    work = chunk
    if use_key1:
        work = xor_with(work, KEY1)
    work = xor_with(work, KEY2)
    return lzss_decompress(work)


def main():
    raw_dir = r"c:\Users\sw\Desktop\Games\Inmon Tougi Toshi Sodom Daikan\StartData\GameData\_workspace\out\scenes_raw"
    out_dir = r"c:\Users\sw\Desktop\Games\Inmon Tougi Toshi Sodom Daikan\StartData\GameData\_workspace\out\scenes_decoded"
    os.makedirs(out_dir, exist_ok=True)

    target = sys.argv[1] if len(sys.argv) > 1 else None
    files = sorted(os.listdir(raw_dir))
    if target is not None:
        files = [f for f in files if target in f]
    print(f"Decoding {len(files)} chunks…")

    success = 0
    for fname in files:
        path = os.path.join(raw_dir, fname)
        chunk = open(path, "rb").read()
        for use_k1 in (False, True):
            try:
                # Inspect putative LZSS header before decompressing
                header = xor_with(chunk[:8], KEY1 if use_k1 else b"") if use_k1 else chunk[:8]
                header = xor_with(header, KEY2)
                _reserved = struct.unpack_from("<I", header, 0)[0]
                size = struct.unpack_from("<I", header, 4)[0]
                if size <= 0 or size > 256 * 1024 * 1024:
                    continue
                decoded = decode(chunk, use_key1=use_k1)
                tag = "k1k2" if use_k1 else "k2"
                if decoded:
                    base = fname.removesuffix(".bin")
                    out_path = os.path.join(out_dir, f"{base}.{tag}.bin")
                    with open(out_path, "wb") as f:
                        f.write(decoded)
                    if fname == files[0]:
                        head = decoded[:64]
                        printable = "".join(
                            chr(b) if 32 <= b <= 126 else "." for b in head
                        )
                        print(
                            f"  [{tag}] {fname} -> {len(decoded):,} bytes  "
                            f"head_hex={head[:16].hex()}  text='{printable}'"
                        )
                    success += 1
                    break
            except Exception as e:
                if fname == files[0]:
                    print(f"  [{ 'k1k2' if use_k1 else 'k2' }] {fname} FAILED: {e}")
                continue
    print(f"\n{success}/{len(files)} chunks decoded successfully.")


if __name__ == "__main__":
    main()
