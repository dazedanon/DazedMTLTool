#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""check_scripts_syntax.py - run `ruby -c` over every section of Scripts.rvdata2.

The write-back in `scripts_rb.apply` proves each section holds the exact text
intended, which catches a corrupted write. It cannot catch a translation or a
code patch that produces text which is not valid Ruby - an apostrophe closing a
single-quoted literal, an anchor spliced at the wrong indent. This does.

Ruby is optional and not a pipeline dependency: without it the check reports
SKIPPED rather than failing, so the release path still runs on a bare machine.
A portable RubyInstaller build is enough - point `--ruby` at its `bin/ruby.exe`,
or set RUBY_EXE.

    python tools/check_scripts_syntax.py
    python tools/check_scripts_syntax.py --file "...\Data\Scripts.rvdata2"
"""

import io
import os
import sys
import glob
import shutil
import tempfile
import argparse
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from acetl import config, scripts_rb                       # noqa: E402


def find_ruby(explicit=None):
    for cand in (explicit, os.environ.get("RUBY_EXE"), shutil.which("ruby")):
        if cand and os.path.exists(cand):
            return cand
    scratch = os.environ.get("TEMP") or tempfile.gettempdir()
    hits = glob.glob(os.path.join(scratch, "**", "ruby*", "bin", "ruby.exe"),
                     recursive=True)
    return hits[0] if hits else None


def check(scripts_file, ruby, verbose=True):
    _arr, rows = scripts_rb.load_sections(scripts_file)
    work = tempfile.mkdtemp(prefix="rbsyntax_")
    bad, checked, empty = [], 0, 0
    try:
        for i, _sid, name, src, _blob in rows:
            label = name or "<section %d>" % i
            if src is None:
                bad.append((label, "does not inflate"))
                continue
            if not src.strip():
                empty += 1
                continue
            f = os.path.join(work, "s%03d.rb" % i)
            # the magic comment so the parser never guesses at the Japanese
            io.open(f, "w", encoding="utf-8", newline="\n").write(
                "# encoding: utf-8\n" + src.replace("\r\n", "\n"))
            r = subprocess.run([ruby, "-c", f], capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            checked += 1
            if r.returncode != 0:
                msg = (r.stderr or r.stdout).strip().splitlines()
                bad.append((label, "; ".join(msg[:2])))
    finally:
        shutil.rmtree(work, ignore_errors=True)

    if verbose:
        print("ruby -c  sections=%d checked=%d empty=%d errors=%d"
              % (len(rows), checked, empty, len(bad)))
        for label, why in bad:
            print("   ! %s: %s" % (label, why))
    return 1 if bad else 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="a Scripts.rvdata2 (default: the game's)")
    ap.add_argument("--ruby", help="path to ruby.exe")
    args = ap.parse_args(argv)

    target = args.file or config.Config().scripts_file
    ruby = find_ruby(args.ruby)
    if not ruby:
        print("ruby -c  SKIPPED - no ruby found (pass --ruby or set RUBY_EXE)")
        return 0
    print("ruby   : %s" % ruby)
    print("target : %s" % target)
    return check(target, ruby)


if __name__ == "__main__":
    sys.exit(main())
