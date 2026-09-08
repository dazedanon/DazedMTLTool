#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_slashes.py — remove the translation's in-bubble line-break artifact " / " from
deployed scripts, including the cases where it landed at a word-wrap boundary
(one physical line ends with ' /', the next starts with '/ ', often after a U+3000
indent). Command lines (asset paths, URLs) are skipped. Line endings preserved.

  python tooling/fix_slashes.py --dir natuiso/scripts            # fix in place
  python tooling/fix_slashes.py --dir natuiso/scripts --dry-run
"""
import argparse, glob, os, re, sys

IDEO = "　"
SKIP = ("\\", "http", ".ogg", ".png", ".wav")   # command/asset lines never have prose slashes


def fixline(l):
    if any(tok in l for tok in SKIP):
        return l
    new = l
    new = re.sub(r'\s+/\s*$', '', new)                       # trailing " /"
    new = re.sub(r'^(' + re.escape(IDEO) + r'?)\s*/\s+', r'\1', new)  # leading "/ " (after optional U+3000)
    new = new.replace(' / ', ' ')                            # inline " / "
    return new


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default="natuiso/scripts")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    total = files = 0
    for f in sorted(glob.glob(os.path.join(args.dir, "*.txt"))):
        raw = open(f, "rb").read().decode("utf-8")
        nl = "\r\n" if "\r\n" in raw else "\n"
        lines = raw.split(nl)
        n = 0
        for i, l in enumerate(lines):
            nw = fixline(l)
            if nw != l:
                lines[i] = nw
                n += 1
        if n:
            if not args.dry_run:
                open(f, "w", encoding="utf-8", newline="").write(nl.join(lines))
            print("  %-22s %d" % (os.path.basename(f), n))
            total += n
            files += 1
    print("%s %d lines in %d files" % ("DRY-RUN would fix" if args.dry_run else "fixed", total, files))

    # audit
    rem = 0
    for f in glob.glob(os.path.join(args.dir, "*.txt")):
        for l in open(f, encoding="utf-8", errors="replace").read().split("\n"):
            if any(tok in l for tok in SKIP):
                continue
            if l.rstrip().endswith(" /") or l.lstrip().startswith("/ ") or " / " in l:
                rem += 1
    print("remaining slash artifacts: %d" % rem)


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        try: s.reconfigure(encoding="utf-8", errors="replace")
        except Exception: pass
    main()
