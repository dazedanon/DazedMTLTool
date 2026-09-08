#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_portable_save.py — make a PORTABLE build whose saves live next to the game
(in .\save\) instead of %APPDATA%\Trois\natuiso\.

The engine builds the save root as:
    <CSIDL_APPDATA path>  +  <pix.xml save folder>  +  "SaveData\\"  +  <lang>\\
The AppData path comes from sub_44B9B0 (RVA 0x44B9B0 / file off 0x4ADB0), which
loads shfolder.dll and calls SHGetSpecialFolderPathA(CSIDL_APPDATA). We patch that
function to instead return an EMPTY base string (success), so the root collapses to
just the pix.xml save folder. Combined with a RELATIVE <save folder="save\\"> in the
loose pix.xml, saves resolve to .\save\SaveData\<lang>\ — portable.

This is save-only (temp/cache use GetTempPathA separately), so nothing else moves.

  python tooling/patch_portable_save.py
      --in natuiso_loosepatch.exe --out natuiso_portable.exe

Outputs a patched COPY (original untouched) and rewrites pix.xml's save folder.
A start.bat (cd to its own dir, launch) is recommended so CWD is always correct.
"""
import argparse, os, re, shutil, sys

# sub_44B9B0 entry, file offset (verified via PE section math for this build)
PATCH_OFF = 0x4ADB0
EXPECT = bytes.fromhex("558BEC83EC34A100")          # prologue we expect to find
# *edx = 0 ; eax = 1 ; ret   (edx = out buffer; caller is cdecl/cleans stack)
STUB   = bytes.fromhex("C602 00 B801000000 C3".replace(" ", ""))


def patch_exe(src, dst):
    data = bytearray(open(src, "rb").read())
    cur = bytes(data[PATCH_OFF:PATCH_OFF + len(EXPECT)])
    if cur == STUB[:len(EXPECT)]:
        print("  already patched")
    elif cur != EXPECT:
        sys.exit("  UNEXPECTED bytes at %#x: %s (expected %s) — wrong exe/offset, aborting"
                 % (PATCH_OFF, cur.hex(), EXPECT.hex()))
    else:
        data[PATCH_OFF:PATCH_OFF + len(STUB)] = STUB
        print("  patched sub_44B9B0 @ file %#x -> empty AppData base" % PATCH_OFF)
    open(dst, "wb").write(data)
    print("  wrote %s" % dst)


def patch_pixxml(path):
    if not os.path.exists(path):
        print("  (pix.xml not found at %s)" % path); return
    txt = open(path, encoding="utf-8").read()
    m = re.search(r'(<save\s+folder=")([^"]*)(")', txt)
    if not m:
        print("  (no <save folder> in pix.xml)"); return
    if m.group(2) == "save\\":
        print("  pix.xml save folder already 'save\\'"); return
    bak = path + ".saveloc.bak"
    if not os.path.exists(bak):
        shutil.copy2(path, bak)
    new = txt[:m.start(2)] + "save\\" + txt[m.end(2):]
    open(path, "w", encoding="utf-8").write(new)
    print("  pix.xml save folder: %r -> 'save\\\\' (backup %s)" % (m.group(2), os.path.basename(bak)))


def main():
    here = os.path.normpath(os.path.dirname(os.path.abspath(__file__)) + "/..")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="src", default=os.path.join(here, "natuiso_loosepatch.exe"))
    ap.add_argument("--out", dest="dst", default=os.path.join(here, "natuiso_portable.exe"))
    ap.add_argument("--pixxml", default=os.path.join(here, "pix.xml"))
    ap.add_argument("--no-pixxml", action="store_true", help="don't touch pix.xml")
    args = ap.parse_args()

    print("1) patch exe copy")
    patch_exe(args.src, args.dst)
    if not args.no_pixxml:
        print("2) set relative save folder in pix.xml")
        patch_pixxml(args.pixxml)
    print("\nSaves will now resolve to .\\save\\SaveData\\<lang>\\ next to the exe.")
    print("Ship a start.bat (cd /d \"%~dp0\" & start natuiso_portable.exe) to guarantee CWD.")


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        try: s.reconfigure(encoding="utf-8", errors="replace")
        except Exception: pass
    main()
