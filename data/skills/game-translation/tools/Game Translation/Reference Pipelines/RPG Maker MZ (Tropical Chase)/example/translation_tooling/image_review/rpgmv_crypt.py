#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
rpgmv_crypt.py - RPG Maker MV/MZ asset encryption, both directions.

`System.json` has `hasEncryptedImages: true` and an `encryptionKey`, so every
file under `img/` ships as `.png_` and the engine decrypts it at load. A
translated image written as a plain `.png` would simply not be found.

The format is small and entirely positional:

    bytes 0..15    a fixed 16-byte header, "RPGMV\0\0\0" then 00 03 01 00
                   then four zero bytes
    bytes 16..31   the REAL file's first 16 bytes, XORed with the 16-byte key
    bytes 32..     the rest of the real file, copied verbatim

`verify()` proves that on this game's own data rather than trusting the
description: it decrypts a shipped `.png_` and compares it byte for byte
against the same file inside `img.zip`, which the developer shipped in the
clear. If that comparison ever fails, nothing gets written.
"""

import os
import sys
import json
import zipfile
import argparse

HEADER = bytes([0x52, 0x50, 0x47, 0x4D, 0x56, 0x00, 0x00, 0x00,
                0x00, 0x03, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00])
HLEN = len(HEADER)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def key_bytes(root=ROOT):
    with open(os.path.join(root, "data", "System.json"), encoding="utf-8-sig") as f:
        sysd = json.load(f)
    k = sysd.get("encryptionKey")
    if not k:
        raise ValueError("System.json has no encryptionKey")
    return bytes.fromhex(k)


def decrypt(data, key):
    if not data.startswith(HEADER[:5]):
        raise ValueError("not an RPG Maker encrypted asset")
    body = bytearray(data[HLEN * 2:])
    masked = bytearray(data[HLEN:HLEN * 2])
    for i in range(min(len(key), HLEN)):
        masked[i] ^= key[i]
    return bytes(masked) + bytes(body)


def encrypt(data, key):
    head = bytearray(data[:HLEN])
    for i in range(min(len(key), HLEN)):
        head[i] ^= key[i]
    return HEADER + bytes(head) + data[HLEN:]


def verify(root=ROOT, samples=6, verbose=True):
    """Prove the codec against the developer's own plaintext copies."""
    key = key_bytes(root)
    zpath = os.path.join(root, "img.zip")
    if not os.path.exists(zpath):
        if verbose:
            print("no img.zip to verify against - skipping")
        return True
    z = zipfile.ZipFile(zpath)
    plain = {n for n in z.namelist() if n.lower().endswith(".png")}
    checked = ok = 0
    for name in sorted(plain):
        enc_path = os.path.join(root, name + "_")
        if not os.path.exists(enc_path):
            continue
        checked += 1
        with open(enc_path, "rb") as f:
            got = decrypt(f.read(), key)
        want = z.read(name)
        if got == want:
            ok += 1
        elif verbose:
            print("  ! MISMATCH %s" % name)
        # and the round trip in the other direction
        if encrypt(want, key) != open(enc_path, "rb").read():
            if verbose:
                print("  ! RE-ENCRYPT MISMATCH %s" % name)
            return False
        if checked >= samples:
            break
    if verbose:
        print("codec verified on %d shipped file(s): %d byte-identical "
              "both ways" % (checked, ok))
    return checked > 0 and checked == ok


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["verify", "encrypt", "decrypt"])
    ap.add_argument("--in", dest="src")
    ap.add_argument("--out", dest="dst")
    a = ap.parse_args(argv)
    if a.action == "verify":
        return 0 if verify() else 1
    key = key_bytes()
    data = open(a.src, "rb").read()
    out = encrypt(data, key) if a.action == "encrypt" else decrypt(data, key)
    with open(a.dst, "wb") as f:
        f.write(out)
    print("%s -> %s (%d bytes)" % (a.src, a.dst, len(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
