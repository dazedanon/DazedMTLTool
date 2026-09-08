#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
zero_glyph_width.py -- set the advance width of one codepoint's glyph to 0 in an
OpenType/CFF or TrueType font, so prefixing text with that character is invisible.

We use this to make U+3000 (IDEOGRAPHIC SPACE) render with zero width in the
English font. The engine classifies a script line as DISPLAY TEXT only if its
first character is non-ASCII; English narration starts with an ASCII letter and
is mis-parsed as a command (hang). Prefixing narration with U+3000 (first UTF-8
byte 0xE3, non-ASCII) makes it parse as text -- and with this width patch it adds
no visible indent.

Both the hmtx advance and (for CFF) the charstring width are zeroed so GDI/DxLib
text rendering shows no gap regardless of which metric it reads.

  python tooling/zero_glyph_width.py <font.otf> --cp 0x3000 -o <out.otf>
"""
import argparse, sys
from fontTools.ttLib import TTFont


def zero_cp(in_path, out_path, cp):
    f = TTFont(in_path)
    cmap = f.getBestCmap()
    if cp not in cmap:
        sys.exit("U+%04X not in font cmap" % cp)
    g = cmap[cp]
    shared = [c for c, gg in cmap.items() if gg == g]
    print("U+%04X -> glyph %s (shared with %s)" % (cp, g, ", ".join("U+%04X" % c for c in shared)))

    # hmtx advance -> 0 (keep left side bearing 0). GDI/DxLib text rendering reads
    # the hmtx advance for spacing, so this alone makes the prefix invisible.
    f["hmtx"][g] = (0, 0)

    f.save(out_path)
    print("wrote %s" % out_path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("font")
    ap.add_argument("--cp", default="0x3000")
    ap.add_argument("-o", "--out", required=True)
    args = ap.parse_args()
    zero_cp(args.font, args.out, int(args.cp, 0))


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        try: s.reconfigure(encoding="utf-8", errors="replace")
        except Exception: pass
    main()
