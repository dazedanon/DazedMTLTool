#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_narration_prefix.py — make translated English narration/monologue lines parse
as DISPLAY TEXT (not engine commands), fixing the dialogue-advance hang.

The PIX engine classifies a *bare* script line (not inside an ＠speaker message
body) as on-screen TEXT only if its first character is NON-ASCII; a bare line that
starts with an ASCII letter is parsed as a command. Japanese narration starts with
kana/kanji, so it is text. After translation, English narration starts with an
ASCII letter -> mis-parsed -> the script stalls and dialogue won't advance.

Fix: prefix each physical line of every BARE text line with U+3000 (IDEOGRAPHIC
SPACE). Its first UTF-8 byte is 0xE3 (non-ASCII) so the line parses as text, and we
ship an EN font whose U+3000 advance is 0 (zero_glyph_width.py) so it adds no
visible indent. Lines inside an ＠ message body already parse as text (the ＠ opened
the message) and are left untouched, so dialogue keeps its normal look.

Oracle (no positional alignment needed): engine COMMANDS are byte-identical between
the original JP script and the deployed EN script (they were never translated), so a
deployed line is TRANSLATED TEXT iff it does not occur verbatim in the JP file.
Blank / comment / ＠ lines are handled explicitly. ＠-body state is tracked so only
bare narration/monologue get the prefix.

  python tooling/fix_narration_prefix.py --en natuiso/scripts --jp natuiso_extracted/scripts [--dry-run]
"""
import argparse, os, sys, glob

IDEO = "　"
SPEAKER = ("＠", "@")


def process(en_path, jp_path, dry):
    raw = open(en_path, "rb").read().decode("utf-8")
    nl = "\r\n" if "\r\n" in raw else "\n"          # preserve original line endings
    en = raw.split(nl)
    jp_lines = set(open(jp_path, "rb").read().decode("utf-8").replace("\r\n", "\n").split("\n"))

    out = []
    in_body = False
    changed = 0
    for ln in en:
        s = ln.strip()
        if not s:
            in_body = False
            out.append(ln); continue
        if s.startswith(SPEAKER):
            in_body = True
            out.append(ln); continue
        if s.startswith("//"):
            out.append(ln); continue
        # command / untranslated -> appears verbatim in JP
        if ln in jp_lines:
            out.append(ln); continue
        # here: a translated TEXT line (not in JP, not blank/comment/＠)
        if in_body:
            out.append(ln); continue          # dialogue body: already parses as text
        # bare narration/monologue: prefix if it currently starts ASCII and not already IDEO
        first = ln.lstrip()[:1]
        if ln[:1] != IDEO and first and ord(first) < 128:
            out.append(IDEO + ln.lstrip())
            changed += 1
        else:
            out.append(ln)

    if changed and not dry:
        open(en_path, "w", encoding="utf-8", newline="").write(nl.join(out))
    return changed


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--en", required=True)
    ap.add_argument("--jp", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    total = 0
    for ef in sorted(glob.glob(os.path.join(args.en, "*.txt"))):
        name = os.path.basename(ef)
        jf = os.path.join(args.jp, name)
        if not os.path.exists(jf):
            print("  skip %s (no JP oracle)" % name); continue
        c = process(ef, jf, args.dry_run)
        total += c
        if c:
            print("  %-22s +%d" % (name, c))
    print("%s %d lines" % ("DRY-RUN would prefix" if args.dry_run else "prefixed", total))


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        try: s.reconfigure(encoding="utf-8", errors="replace")
        except Exception: pass
    main()
