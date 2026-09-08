#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_loose_files.py — flip natuiso.exe (DxLib) to LOOSE-FILE-FIRST priority so
files on disk override the ones inside natuiso.bin / pix.bin (no repack needed).

DxLib's FileRead_open (sub_751240) branches on dword_F0D584:
    F0D584 == 0  -> archive first  (default; loose only used if not in archive)
    F0D584 != 0  -> loose file first, archive as fallback
The flag is never written by the game, so we force the loose-first branch by
turning the `jnz loc_7513F9` at VA 0x751330 into an unconditional `jmp`.

  patch:  0F 85 C3 00 00 00   (jnz  loc_7513F9)
  ->      E9 C4 00 00 00 90   (jmp  loc_7513F9 ; nop)

Usage:
  python patch_loose_files.py natuiso.exe                 # -> natuiso.loose.exe
  python patch_loose_files.py natuiso.exe -o out.exe
  python patch_loose_files.py natuiso.exe --revert in.exe # sanity: show/verify
"""
import os, sys, argparse, shutil

FILE_OFFSET = 0x350730
ORIG = bytes.fromhex("0f85c3000000")
NEW = bytes.fromhex("e9c400000090")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("exe")
    ap.add_argument("-o", "--out", default=None, help="output path (default: <exe>.loose.exe)")
    ap.add_argument("--offset", type=lambda x: int(x, 0), default=FILE_OFFSET)
    ap.add_argument("--orig", default=ORIG.hex())
    ap.add_argument("--new", default=NEW.hex())
    ap.add_argument("--revert", action="store_true", help="write NEW->ORIG instead (undo)")
    args = ap.parse_args()

    orig = bytes.fromhex(args.orig)
    new = bytes.fromhex(args.new)
    if args.revert:
        orig, new = new, orig

    data = bytearray(open(args.exe, "rb").read())
    cur = bytes(data[args.offset:args.offset + len(orig)])
    if cur == new:
        print("Already patched (bytes at 0x%X == %s). Nothing to do." % (args.offset, new.hex()))
        return
    if cur != orig:
        sys.exit("ERROR: bytes at 0x%X are %s, expected %s. Wrong file/offset — aborting."
                 % (args.offset, cur.hex(), orig.hex()))

    out = args.out or (os.path.splitext(args.exe)[0] + ".loose.exe")
    data[args.offset:args.offset + len(new)] = new
    with open(out, "wb") as f:
        f.write(data)
    print("Patched %s -> %s" % (args.exe, out))
    print("  offset 0x%X: %s -> %s  (loose files now override the archive)"
          % (args.offset, orig.hex(), new.hex()))


if __name__ == "__main__":
    main()
