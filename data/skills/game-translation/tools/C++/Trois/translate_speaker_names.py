#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
translate_speaker_names.py — rewrite remaining Japanese ＠speaker names to English
IN PLACE in the deployed scripts, preserving the ,VoiceID suffix and any leading
whitespace. Runs directly on natuiso/scripts so it does NOT disturb the U+3000
narration prefix already applied there (re-running the JSON injector would).

The 4 voiced characters were left in Japanese earlier (voice.xml matches by name);
that turned out unnecessary — recorded voices play by the V01_..V04_ keyword in the
＠line regardless of the displayed name. So we can show English names everywhere.

  python tooling/translate_speaker_names.py            # apply
  python tooling/translate_speaker_names.py --dry-run
"""
import argparse, glob, os, re, sys

# JP display name -> English. Only names that may still be JP in the scripts.
NAME_MAP = {
    "愛梨":   "Airi",
    "千佳":   "Chika",
    "智":     "Tomo",
    "愛梨母": "Airi's Mother",
}

SPK_RE = re.compile(r'^(\s*[＠@])([^,\r\n\t]*)(.*)$')


def rewrite_line(line):
    m = SPK_RE.match(line)
    if not m:
        return line, False
    name = m.group(2).strip()
    en = NAME_MAP.get(name)
    if not en:
        return line, False
    return m.group(1) + en + m.group(3), True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default="natuiso/scripts")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    total = 0
    per_name = {}
    for f in sorted(glob.glob(os.path.join(args.dir, "*.txt"))):
        raw = open(f, "rb").read().decode("utf-8")
        nl = "\r\n" if "\r\n" in raw else "\n"      # preserve original line endings
        lines = raw.split(nl)
        n = 0
        for i, l in enumerate(lines):
            new, changed = rewrite_line(l)
            if changed:
                jp = SPK_RE.match(l).group(2).strip()
                per_name[jp] = per_name.get(jp, 0) + 1
                lines[i] = new
                n += 1
        if n and not args.dry_run:
            open(f, "w", encoding="utf-8", newline="").write(nl.join(lines))
        if n:
            print("  %-22s %d" % (os.path.basename(f), n))
        total += n
    print("%s %d speaker lines" % ("DRY-RUN would rewrite" if args.dry_run else "rewrote", total))
    for jp, c in sorted(per_name.items(), key=lambda x: -x[1]):
        print("   %s -> %s : %d" % (jp, NAME_MAP[jp], c))


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        try: s.reconfigure(encoding="utf-8", errors="replace")
        except Exception: pass
    main()
