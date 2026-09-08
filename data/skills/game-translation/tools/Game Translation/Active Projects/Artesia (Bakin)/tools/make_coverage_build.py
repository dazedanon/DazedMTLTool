"""Generate a coverage-test translation: every Japanese run replaced by filler.

    make_coverage_build.py <units.jsonl> <codes.txt> <out.jsonl> [widthRatio]

Anything still Japanese on screen in the resulting build is text the extractor
never saw - which is the only way to find that class of gap, because a string
that was never a unit cannot fail any per-unit check.

Two properties make this build playable rather than just loud:

* **The filler is a pure function of the source run.** Identical Japanese maps
  to identical filler everywhere, so string-variable comparisons (a value
  assigned in one command and tested against a literal in another) still match
  and the game stays progressable.
* **Control codes are preserved exactly.** Codes are matched longest-first
  against the engine's own table; key arguments (`\\$[var]`, `\\f[font]`, colour,
  size) pass through untouched, and only the arguments the engine actually draws
  (`\\r[base,ruby]`, `\\NPL[name]`, the skill-cost templates) get filled - which
  doubles as a test of that masking spec.

Latin runs, digits and `{0}`-style placeholders are left alone, so anything
non-Japanese that appears on screen is the game's own.
"""

import hashlib
import io
import json
import re
import sys

WORDS = ('lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod '
         'tempor incididunt labore magna aliqua enim minim veniam quis nostrud '
         'exercitation ullamco laboris nisi aliquip commodo consequat duis aute '
         'irure reprehenderit voluptate velit esse cillum eu fugiat nulla pariatur').split()

JP = re.compile(r'[぀-ヿ㐀-䶿一-鿿豈-﫿ｦ-ﾝ'
                r'　-〿！-｠]+')

# Codes whose bracket argument the engine draws. Everything else keeps its
# argument verbatim, because those are variable names, fonts, colours and sizes.
TEXT_ARG = re.compile(r'^(r|NPL|NPC|NPR|.*consumption.*)$', re.IGNORECASE)

# Substitutions inside a drawn argument that must survive: format placeholders.
KEEP = re.compile(r'\{\d+\}')


def width(s):
    """Display cells: full-width characters count double."""
    n = 0
    for c in s:
        n += 2 if ('ᄀ' <= c <= 'ᅟ' or '⺀' <= c <= '꓏'
                   or '가' <= c <= '힣' or '豈' <= c <= '﫿'
                   or '︰' <= c <= '﹯' or '＀' <= c <= '｠'
                   or '￠' <= c <= '￦') else 1
    return n


def filler(run, ratio):
    """Deterministic filler of roughly the same display width as `run`."""
    target = max(2, int(round(width(run) * ratio)))
    h = hashlib.sha1(run.encode('utf-8')).digest()
    out, i = [], 0
    used = 0
    while used < target:
        w = WORDS[h[i % len(h)] % len(WORDS)]
        i += 1
        out.append(w)
        used += len(w) + 1
    s = ' '.join(out)
    return s[:target] if len(s) > target else s


def fill_text(s, ratio):
    return JP.sub(lambda m: filler(m.group(), ratio), s)


def fill_arg(arg, ratio):
    """Fill a drawn argument, leaving {0}-style placeholders in place."""
    parts, last = [], 0
    for m in KEEP.finditer(arg):
        parts.append(fill_text(arg[last:m.start()], ratio))
        parts.append(m.group())
        last = m.end()
    parts.append(fill_text(arg[last:], ratio))
    return ''.join(parts)


def build_tokenizer(codes_path):
    names = set()
    for line in io.open(codes_path, encoding='utf-8'):
        line = line.strip()
        if line:
            names.add(line.lstrip('\\'))
    names.update(['NPL', 'NPC', 'NPR', 'Variable', 'map', 'time', 'money', 'H', 'h',
                  'v', 'b', 'c', 'f', 'i', 'n', 'r', 's', 'u', 'w', 'z', 'R', 'I',
                  '$L', '$', '#'])
    alt = '|'.join(re.escape(n) for n in sorted(names, key=len, reverse=True) if n)
    return re.compile(r'\\(' + alt + r')(\[([^\[\]]*)\])?')


def convert(src, tok, ratio):
    out, i = [], 0
    while i < len(src):
        if src[i] == '\\':
            if src[i:i + 2] == '\\\\':          # escaped literal backslash
                out.append('\\\\')
                i += 2
                continue
            m = tok.match(src, i)
            if m:
                name, arg = m.group(1), m.group(3)
                if arg is not None and TEXT_ARG.match(name):
                    out.append('\\' + name + '[' + fill_arg(arg, ratio) + ']')
                else:
                    out.append(m.group(0))
                i = m.end()
                # Japanese terminates a bare code for free; Latin filler does not,
                # so keep a space between the two rather than trusting every
                # lexer in the engine to stop at the right character.
                if arg is None and i < len(src) and JP.match(src[i]):
                    out.append(' ')
                continue
            # A backslash the table does not know (\^ and friends): emit it and
            # step past, or the scan below cannot advance and spins forever.
            out.append('\\')
            i += 1
            continue
        j = i
        while j < len(src) and src[j] != '\\':
            j += 1
        out.append(fill_text(src[i:j], ratio))
        i = j
    return ''.join(out)


def main(units_path, codes_path, out_path, ratio='1.0'):
    ratio = float(ratio)
    tok = build_tokenizer(codes_path)
    n = same = 0
    with io.open(out_path, 'w', encoding='utf-8') as w:
        for line in io.open(units_path, encoding='utf-8'):
            u = json.loads(line)
            en = convert(u['src'], tok, ratio)
            if en == u['src']:
                same += 1
            w.write(json.dumps({'key': u['key'], 'en': en}, ensure_ascii=False) + '\n')
            n += 1
    print('units %d, unchanged %d, width ratio %.2f -> %s' % (n, same, ratio, out_path))
    if same:
        print('  (unchanged units are ones whose Japanese sits only in a key argument)')
    return 0


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:5]))
