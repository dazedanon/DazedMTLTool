#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_no_serial.py — skip natuiso.exe's serial-number / support-code prompt entirely.

At startup, sub_599980 validates the saved serial via sub_5EEA60 and only shows the
"enter serial" input loop when that check FAILS:

    599D67  call sub_5EEA60          ; validate saved serial
    599D6C  test al, al
    599D6E  jnz  loc_599E5C          ; if valid -> skip the whole input-dialog loop
    599D74  ...                      ; else -> show "enter serial" prompt

We force the skip unconditionally by turning the `jnz loc_599E5C` at VA 0x599D6E
into an unconditional `jmp` (then a NOP to fill the 6th byte). The prompt never
appears; execution always jumps straight to the post-success path.

  patch:  0F 85 E8 00 00 00   (jnz  loc_599E5C)
  ->      E9 E9 00 00 00 90   (jmp  loc_599E5C ; nop)

(The serial algorithm itself, if you want a keygen instead of a patch, is:
 8 chars from [0-9A-Z]; sum the base-36 value of the first 6; the last 2 chars
 must equal that sum in base-36, e.g. NATUIS3U, ZZZZZZ5U.)

Usage:
  python patch_no_serial.py crackme.exe                 # -> crackme.noserial.exe
  python patch_no_serial.py crackme.exe -o out.exe
  python patch_no_serial.py out.exe --revert            # undo (NEW -> ORIG)
"""
import os, sys, argparse

FILE_OFFSET = 0x19916E
ORIG = bytes.fromhex("0f85e8000000")
NEW = bytes.fromhex("e9e9000000" "90")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("exe")
    ap.add_argument("-o", "--out", default=None, help="output path (default: <exe>.noserial.exe)")
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

    out = args.out or (os.path.splitext(args.exe)[0] + ".noserial.exe")
    data[args.offset:args.offset + len(new)] = new
    with open(out, "wb") as f:
        f.write(data)
    print("Patched %s -> %s" % (args.exe, out))
    print("  offset 0x%X: %s -> %s  (serial prompt now skipped)"
          % (args.offset, orig.hex(), new.hex()))


if __name__ == "__main__":
    main()
