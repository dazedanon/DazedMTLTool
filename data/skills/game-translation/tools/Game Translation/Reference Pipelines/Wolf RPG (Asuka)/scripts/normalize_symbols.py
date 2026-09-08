"""ASCII-normalize symbol-only display literals (prototypes `wolf normalize-symbols`).

strings-extract skips symbol-only rows (nakaguro runs, fullwidth punctuation,
<Lunch Break>, >[fullwidth 800]) so they never receive --en-punct and their
FULLWIDTH punctuation renders as tofu in a Latin font. This pass normalizes
fullwidth punctuation, fullwidth ASCII digits/letters, and model-glyph artifacts
on ALL depth-0 display literals regardless of extraction. Kana and kanji WORDS
are left intact (the CHARMAP never touches them), so a mixed literal keeps its
kanji while its fullwidth punctuation and digits are ASCII-folded.

Usage: python scripts/normalize_symbols.py SRC [DST] [--report-only]
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from wolfscript import DISPLAY_CMDS, literal_spans, command_name, unescape, escape, read_text

# Fullwidth punctuation + model-glyph artifacts -> ASCII. Fullwidth digits and
# fullwidth Latin letters are folded by range math in _translate_chars, not here.
CHARMAP = {
    "：": ":",   # fullwidth colon
    "？": "?",   # fullwidth question mark
    "！": "!",   # fullwidth exclamation
    "％": "%",   # fullwidth percent
    "￥": "¥",  # fullwidth yen -> yen sign
    "＜": "<",   # fullwidth less-than
    "＞": ">",   # fullwidth greater-than
    "（": "(",   # fullwidth left paren
    "）": ")",   # fullwidth right paren
    "，": ",",   # fullwidth comma
    "．": ".",   # fullwidth full stop
    "～": "~",   # fullwidth tilde
    "、": ",",   # ideographic comma
    "。": ".",   # ideographic full stop
    "＋": "+",   # fullwidth plus
    "－": "-",   # fullwidth hyphen-minus
    "―": "-",   # horizontal bar (dash artifact)
    "『": '"',   # left white corner bracket
    "』": '"',   # right white corner bracket
    "▶": "->",  # black right-pointing triangle (model glyph)
    "◀": "<-",  # black left-pointing triangle (model glyph)
    "≒": "~",   # approximately-equal-to-or-image-of (model glyph)
}

# A run of nakaguro (・) is an ellipsis. Absorb one trailing ideographic or
# ASCII/fullwidth period so ...。 folds to "..." rather than "...." (that period
# would otherwise map to its own dot).
_MULTI_NAKAGURO_RE = re.compile("・{2,}[。．.]?")


def _translate_chars(text):
    out = []
    for c in text:
        if c in CHARMAP:
            out.append(CHARMAP[c])
        elif "０" <= c <= "９":
            out.append(chr(ord(c) - 0xFF10 + ord("0")))
        elif "Ａ" <= c <= "Ｚ":
            out.append(chr(ord(c) - 0xFF21 + ord("A")))
        elif "ａ" <= c <= "ｚ":
            out.append(chr(ord(c) - 0xFF41 + ord("a")))
        else:
            out.append(c)
    return "".join(out)


def normalize_literal(text):
    text = _MULTI_NAKAGURO_RE.sub("...", text)
    return _translate_chars(text)


def _target_spans(line, cmd):
    spans = literal_spans(line)
    if not spans:
        return []
    if cmd in DISPLAY_CMDS:
        return spans
    if cmd == "Database":
        return spans[:1]
    return []


def process(src_text):
    changed = []
    out = []
    for lno, line in enumerate(src_text.splitlines(), 1):
        cmd = command_name(line)
        new = line
        for a, b in reversed(_target_spans(line, cmd)):
            lit = unescape(line[a + 1:b - 1])
            fixed = normalize_literal(lit)
            if fixed != lit:
                new = new[:a] + '"' + escape(fixed) + '"' + new[b:]
        if new != line:
            changed.append((lno, line.strip(), new.strip()))
        out.append(new)
    return "\n".join(out) + "\n", changed


def main():
    ap = argparse.ArgumentParser(
        description="ASCII-normalize symbol-only display literals in a .wscript.")
    ap.add_argument("src", help="source .wscript file")
    ap.add_argument("dst", nargs="?", help="output file (default: overwrite SRC in place)")
    ap.add_argument("--report-only", action="store_true", help="print changes without writing")
    args = ap.parse_args()

    src_path = Path(args.src)
    src_text = read_text(src_path)
    new_text, changed = process(src_text)

    if not args.report_only:
        dst_path = Path(args.dst) if args.dst else src_path
        dst_path.write_text(new_text, encoding="utf-8")

    print(f"{src_path.name}: {len(changed)} lines normalized")
    for lno, before, after in changed[:8]:
        print(f"  L{lno}: {before}  ->  {after}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
