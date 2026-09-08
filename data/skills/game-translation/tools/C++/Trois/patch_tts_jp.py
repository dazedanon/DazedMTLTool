#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_tts_jp.py -- make the auto-voice (Open JTalk) speak the original Japanese
while English shows on screen.

Two effects:
  1) Add `tts_jp.dll` to the exe's import table (via LIEF 0.17) so the companion
     DLL loads automatically at startup. The DLL hooks the synth entry and swaps
     the on-screen English text for the original Japanese (from tts_jp_table.bin)
     before it reaches mecab / Open JTalk.
  2) Turn auto-voice ON in both configs (loose pix.pixsettings + AppData
     globalconfig.pixsettings) so the (now JP-fed) TTS actually runs.

Outputs natuiso_ttsjp.exe (keeps the source exe untouched). The DLL, table, and a
runtime log all live next to the exe.

  python tooling/patch_tts_jp.py
  python tooling/patch_tts_jp.py --in natuiso_loosepatch.exe --out natuiso_ttsjp.exe --no-config

This does NOT touch any serial/DRM/licensing code -- it only redirects the text
handed to the text-to-speech engine and toggles the auto-voice setting.
"""
import argparse, os, re, shutil, sys
import lief

ROOT = os.path.normpath(os.path.dirname(os.path.abspath(__file__)) + "/..")
DLL_NAME = "tts_jp.dll"


def add_import(src_exe, dst_exe):
    b = lief.PE.parse(src_exe)
    if any(i.name.lower() == DLL_NAME for i in b.imports):
        print("  import already present")
    else:
        imp = b.add_import(DLL_NAME)
        imp.add_entry("ping")          # need >=1 symbol; the DLL exports `ping`
        print("  added import %s (ping)" % DLL_NAME)

    cfg = lief.PE.Builder.config_t()
    cfg.imports = True                  # rebuild the import directory
    builder = lief.PE.Builder(b, cfg)
    builder.build()
    builder.write(dst_exe)
    # verify
    chk = lief.PE.parse(dst_exe)
    ok = any(i.name.lower() == DLL_NAME for i in chk.imports)
    print("  wrote %s  (tts_jp.dll imported: %s)" % (dst_exe, ok))
    return ok


def set_autovoice_true(path):
    if not os.path.exists(path):
        print("  (config not found: %s)" % path)
        return
    txt = open(path, encoding="utf-8-sig").read()
    orig = txt
    for key in ("enableAutoVoice", "enableAutoVoice1", "enableAutoVoice2"):
        txt = re.sub(r'("%s"\s*:\s*)false' % re.escape(key), r"\1true", txt)
    if txt != orig:
        bak = path + ".bak"
        if not os.path.exists(bak):
            shutil.copy2(path, bak)
        open(path, "w", encoding="utf-8").write(txt)
        print("  auto-voice enabled in %s (backup .bak)" % os.path.basename(path))
    else:
        print("  no auto-voice flags changed in %s" % os.path.basename(path))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="src", default=os.path.join(ROOT, "natuiso_loosepatch.exe"))
    ap.add_argument("--out", dest="dst", default=os.path.join(ROOT, "natuiso_ttsjp.exe"))
    ap.add_argument("--no-config", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(args.src):
        alt = os.path.join(ROOT, "natuiso.exe")
        print("source %s missing; using %s" % (args.src, alt))
        args.src = alt

    print("1) import-patch exe")
    if not add_import(args.src, args.dst):
        sys.exit("import patch FAILED")

    print("2) place DLL + table next to the exe")
    exedir = os.path.dirname(os.path.abspath(args.dst))
    pairs = [
        (os.path.join(ROOT, "tooling", "tts_jp", DLL_NAME), os.path.join(exedir, DLL_NAME)),
        (os.path.join(ROOT, "tooling", "tts_jp_table.bin"), os.path.join(exedir, "tts_jp_table.bin")),
    ]
    for srcf, dstf in pairs:
        if os.path.exists(srcf):
            shutil.copy2(srcf, dstf)
            print("   %s" % dstf)
        else:
            print("   MISSING %s (build it first)" % srcf)

    if not args.no_config:
        print("3) enable auto-voice in configs")
        set_autovoice_true(os.path.join(ROOT, "pix", "settings", "pix.pixsettings"))
        set_autovoice_true(os.path.join(os.environ.get("APPDATA", ""), "Trois", "natuiso", "globalconfig.pixsettings"))

    print("\nDone -> run %s" % args.dst)
    print("Runtime log: %s" % os.path.join(exedir, "tts_jp.log"))


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        try: s.reconfigure(encoding="utf-8", errors="replace")
        except Exception: pass
    main()
