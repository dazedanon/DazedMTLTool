#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
deploy_loose.py — copy translated assets into the game as LOOSE OVERRIDE files.

The engine (DxLib, SetDXArchiveExtension("bin")) treats each archive as a virtual
folder named after the archive stem:  natuiso.bin -> "natuiso\\",  pix.bin -> "pix\\".
With the loose-first patch (tooling/patch_loose_files.py), a file on disk at
  <game>\\natuiso\\<internal path>     overrides natuiso.bin\\<internal path>
  <game>\\pix\\<internal path>         overrides pix.bin\\<internal path>

So translated files mirror each archive's internal layout under a folder named after
that archive. This tool copies one or more source trees to <game>\<prefix>\... .

  # images we rendered (they live in natuiso.bin) -> <game>\natuiso\system\...
  python deploy_loose.py --game .. --map images_en natuiso

  # later, translated scripts -> <game>\natuiso\scripts\...
  python deploy_loose.py --game .. --map scripts_en natuiso/scripts

  --clean removes each destination subtree first; --dry-run just lists.
"""
import argparse, os, shutil, sys


def copytree(src, dst, dry):
    n = 0
    for root, _dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        for f in files:
            s = os.path.join(root, f)
            d = os.path.normpath(os.path.join(dst, rel, f))
            if dry:
                print("   %s -> %s" % (os.path.relpath(s), d))
            else:
                os.makedirs(os.path.dirname(d), exist_ok=True)
                shutil.copy2(s, d)
            n += 1
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", required=True, help="game folder (where natuiso.bin / the exe live)")
    ap.add_argument("--map", action="append", nargs=2, metavar=("SRCDIR", "PREFIX"), required=True,
                    help="copy SRCDIR/* into <game>/PREFIX/...  (PREFIX e.g. 'natuiso' or 'pix' "
                         "or 'natuiso/scripts')")
    ap.add_argument("--clean", action="store_true", help="delete each <game>/PREFIX subtree first")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    total = 0
    for src, prefix in args.map:
        if not os.path.isdir(src):
            sys.exit("source not found: %s" % src)
        dst = os.path.join(args.game, prefix.replace("/", os.sep))
        if args.clean and os.path.isdir(dst) and not args.dry_run:
            shutil.rmtree(dst)
        print("%s/  ->  %s/" % (src, dst))
        total += copytree(src, dst, args.dry_run)
    print("%s %d files%s" % ("Would copy" if args.dry_run else "Copied", total,
                             "" if not args.dry_run else " (dry run)"))


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        try: s.reconfigure(encoding="utf-8", errors="replace")
        except Exception: pass
    main()
