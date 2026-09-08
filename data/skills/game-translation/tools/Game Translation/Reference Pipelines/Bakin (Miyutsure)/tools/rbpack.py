"""RPG Developer Bakin data.rbpack reader.

Format recovered from Yukar_Engine_Launcher.Form1 (bakinplayer_launcher).

  "BKNPAK"            6 bytes magic
  version             uint16 big-endian (max supported 1)
  (int64)             read and discarded
  hasLabel            bool (1 byte)
    labelLen          byte, then labelLen bytes UTF-8 (splash label)
  drmNum              int32 LE
  hashLen             byte, then hashLen bytes = MD5(int32le(drmNum + 2525))
                      fallback MD5(int32le(drmNum + 5252)) -> Steam DRM path
  zipLen              int64 LE   (total size of the reconstructed zip)
  <body>              zipLen - 8 bytes, scrambled

The zip's first 8 bytes are not stored; the launcher synthesises them as
PK\x03\x04\x14\x00\x00\x00. Everything from `position` (the file offset where
the body starts) onward is descrambled with

  plain[off] = raw[off] - codes[off % 16] * (off % 16)   (mod 256)

where `off` is the ABSOLUTE file offset, and `codes` is the fixed 16-byte
permutation built by Form1.getCodes().

Bytes after the zip body are the resource region addressed by
Yukar.Common.FSEx.initializeResourceFileInfo.
"""

import hashlib
import struct

MAGIC = b"BKNPAK"
ZIP_HEAD = b"PK\x03\x04\x14\x00\x00\x00"


def make_codes():
    a = list(range(16))
    for j in range(16):
        k = (j * 7 + 1) % 16
        a[j], a[k] = a[k], a[j]
    return a


CODES = make_codes()


def unscramble(buf, start_count):
    out = bytearray(buf)
    for i in range(len(out)):
        n = (start_count + i) % 16
        out[i] = (out[i] - CODES[n] * n) & 0xFF
    return bytes(out)


class RbPack:
    def __init__(self, path):
        self.path = path
        with open(path, "rb") as f:
            head = f.read(64)
        if head[:6] != MAGIC:
            raise ValueError("not a BKNPAK file")
        self.version = struct.unpack_from(">H", head, 6)[0]
        self.unknown64 = struct.unpack_from("<q", head, 8)[0]
        p = 16
        self.label = None
        if head[p]:
            p += 1
            n = head[p]
            p += 1
            self.label = head[p:p + n].decode("utf-8")
            p += n
        else:
            p += 1
        self.drm_num = struct.unpack_from("<i", head, p)[0]
        p += 4
        n = head[p]
        p += 1
        self.drm_hash = head[p:p + n]
        p += n
        self.zip_len = struct.unpack_from("<q", head, p)[0]
        p += 8
        self.body_offset = p
        self.res_offset = p + self.zip_len - 8

    def check_drm(self):
        for salt in (2525, 5252):
            h = hashlib.md5(struct.pack("<i", self.drm_num + salt)).digest()
            if h == self.drm_hash:
                return salt
        return None

    def read_zip(self):
        with open(self.path, "rb") as f:
            f.seek(self.body_offset)
            body = f.read(self.zip_len - 8)
        return ZIP_HEAD + unscramble(body, self.body_offset)


if __name__ == "__main__":
    import sys

    pk = RbPack(sys.argv[1])
    print("version    ", pk.version)
    print("label      ", pk.label)
    print("drm_num    ", pk.drm_num, "salt", pk.check_drm())
    print("zip_len    ", pk.zip_len)
    print("body_offset", pk.body_offset)
    print("res_offset ", pk.res_offset)
    if len(sys.argv) > 2:
        with open(sys.argv[2], "wb") as f:
            f.write(pk.read_zip())
        print("wrote", sys.argv[2])
