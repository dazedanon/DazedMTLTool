"""Minimal reader/writer for the .NET BinaryReader/BinaryWriter wire format."""

import struct
import uuid


class Reader:
    def __init__(self, buf, pos=0):
        self.b = buf
        self.p = pos

    def eof(self):
        return self.p >= len(self.b)

    def bytes(self, n):
        v = self.b[self.p:self.p + n]
        if len(v) != n:
            raise EOFError("want %d at %d, have %d" % (n, self.p, len(v)))
        self.p += n
        return v

    def u8(self):
        return self.bytes(1)[0]

    def i16(self):
        return struct.unpack("<h", self.bytes(2))[0]

    def i32(self):
        return struct.unpack("<i", self.bytes(4))[0]

    def i64(self):
        return struct.unpack("<q", self.bytes(8))[0]

    def f32(self):
        return struct.unpack("<f", self.bytes(4))[0]

    def boolean(self):
        return self.u8() != 0

    def string(self):
        n = shift = 0
        while True:
            b = self.u8()
            n |= (b & 0x7F) << shift
            if not b & 0x80:
                break
            shift += 7
        return self.bytes(n).decode("utf-8")

    def guid(self):
        return uuid.UUID(bytes_le=self.bytes(16))


class Writer:
    def __init__(self):
        self.b = bytearray()

    def bytes(self, v):
        self.b += v

    def u8(self, v):
        self.b.append(v & 0xFF)

    def i16(self, v):
        self.b += struct.pack("<h", v)

    def i32(self, v):
        self.b += struct.pack("<i", v)

    def i64(self, v):
        self.b += struct.pack("<q", v)

    def boolean(self, v):
        self.b.append(1 if v else 0)

    def string(self, s):
        e = s.encode("utf-8")
        n = len(e)
        while n >= 0x80:
            self.b.append((n & 0x7F) | 0x80)
            n >>= 7
        self.b.append(n)
        self.b += e

    def guid(self, g):
        self.b += g.bytes_le
