"""Bakin's byte scramble.

Two variants of one algorithm, differing only in the multiplier used to build
the 16-byte code table:

  codes = [0..15]; for j in 0..15: swap(codes[j], codes[(j*M + 1) % 16])
  raw[i] = plain[i] + codes[i % 16] * (i % 16)   (mod 256)

M = 7  -- used by the launcher (Yukar_Engine_Launcher.Form1.getCodes) on the
          rbpack body and on the executable payloads it unpacks
          (.dll .dlp .dlp_d .exe .cg .cgh).
M = 13 -- used by the engine's file layer on every other packed file
          (.rbr .cs .png .txt .cfg ...). Recovered by solving the code table
          against the known "YUKAR" magic of an .rbr.

The index is the ABSOLUTE offset within the logical stream, which is why the
launcher threads a start_count through when it descrambles the rbpack body in
place.
"""


def make_codes(mult):
    a = list(range(16))
    for j in range(16):
        k = (j * mult + 1) % 16
        a[j], a[k] = a[k], a[j]
    return a


CODES_LAUNCHER = make_codes(7)
CODES_DATA = make_codes(13)

# Precomputed per-index deltas so the hot loop is a table lookup, not a mul.
_DELTA_LAUNCHER = bytes((CODES_LAUNCHER[i] * i) & 0xFF for i in range(16))
_DELTA_DATA = bytes((CODES_DATA[i] * i) & 0xFF for i in range(16))


def _apply(buf, start, delta, sign):
    out = bytearray(buf)
    for i in range(len(out)):
        out[i] = (out[i] + sign * delta[(start + i) % 16]) & 0xFF
    return bytes(out)


def descramble(buf, start=0, launcher=False):
    return _apply(buf, start, _DELTA_LAUNCHER if launcher else _DELTA_DATA, -1)


def scramble(buf, start=0, launcher=False):
    return _apply(buf, start, _DELTA_LAUNCHER if launcher else _DELTA_DATA, 1)
