r"""Check the corpus against the traps found by decompiling the engine.

    trap_audit.py <units.jsonl>

Every one of these is a failure ENGLISH can create and Japanese cannot, which
is the class that survives every text-level check. See `ENGINE-CODES.md` for
the decompiled evidence.

  1. A comma inside a bracketed code argument. `func()` in MessageReader always
     does `.Split(',')` and consumers read `array[0]`, so `\NPL[Smith, Jr.]`
     renders as `Smith`. Japanese writes 、 and ，, never U+002C, so the source
     never trips it and a translated name absolutely can.
  2. A TAB in the text. `GameMain.replaceForFormat` parks `\\` on a TAB while
     it parses, then converts every TAB back to a backslash - so a real TAB in
     the message becomes a visible `\` on screen.
  3. `\r[ruby]X` - the one-argument ruby form silently consumes the SINGLE
     character after the `]` as its base. Masking the code leaves that
     character in the visible text where the model can move it.
  4. `\H[castName]` resolves a Cast BY NAME, which would make cast names keys
     rather than translatable text.
"""

import collections
import json
import re
import sys

ARG = re.compile(r'\\([A-Za-z_#$]+)\[([^\]\r\n]*)\]')
RUBY1 = re.compile(r'\\r\[([^\],\r\n]*)\](.?)')
HCODE = re.compile(r'\\H\[')


def main(path):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    comma = collections.Counter()
    comma_ex = {}
    tabs = []
    ruby = []
    hcode = []
    n = 0
    for line in open(path, encoding='utf-8'):
        u = json.loads(line)
        n += 1
        s = u['src']
        for m in ARG.finditer(s):
            if ',' in m.group(2):
                comma[m.group(1)] += 1
                comma_ex.setdefault(m.group(1), m.group(0))
        if '\t' in s:
            tabs.append((u['key'], u['kind'], s[:70]))
        for m in RUBY1.finditer(s):
            ruby.append((u['key'], u['kind'], m.group(0), m.group(1), m.group(2)))
        if HCODE.search(s):
            hcode.append((u['key'], s[:70]))

    print('units scanned %d' % n)
    print()
    print('1. ASCII comma inside a code bracket (source side): %d'
          % sum(comma.values()))
    for k, v in comma.most_common(10):
        print('     %-24s %5d  e.g. %s' % (k, v, comma_ex[k][:50]))
    if not comma:
        print('     none - so every comma the shipped patch contains inside a '
              'bracket will be one WE introduced.')
    print()
    print('2. real TAB inside a player-facing unit: %d' % len(tabs))
    for k, kd, s in tabs[:10]:
        print('     %-40s %-8s %r' % (k[:40], kd, s))
    print()
    print('3. one-argument ruby `\\r[x]Y` occurrences: %d' % len(ruby))
    for k, kd, whole, rb, base in ruby[:10]:
        print('     %-40s %-8s %r ruby=%r base=%r' % (k[:40], kd, whole, rb, base))
    print()
    print('4. `\\H[castName]` (would make Cast names KEYS): %d' % len(hcode))
    for k, s in hcode[:5]:
        print('     %-40s %r' % (k[:40], s))
    if not hcode:
        print('     none - Cast names are safe to translate in THIS build. '
              'Re-check on a new version; do not carry the ruling across.')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
