"""Width budget per content-getter code.

    budgets.py <layout.tsv> [out.tsv]

Most Bakin layout slots do not hold literal text - they hold a code like
`\\skillname` and draw whatever the getter returns at runtime. So the budget for
a rom field is not a property of the field: it is the NARROWEST slot that draws
it, and it is hard only if that slot clips.

This reports, per code: how many slots draw it, the narrowest clipping slot (the
hard budget), the narrowest non-clipping slot, and whether any slot wraps.
"""

import collections
import csv
import io
import re
import sys

CODE = re.compile(r'\\+([A-Za-z_$#][A-Za-z0-9_]*)')


def unesc(s):
    out, i = [], 0
    while i < len(s):
        if s[i] == '\\' and i + 1 < len(s):
            out.append({'n': '\n', 'r': '\r', 't': '\t'}.get(s[i + 1], s[i + 1]))
            i += 2
        else:
            out.append(s[i])
            i += 1
    return ''.join(out)


def main(layout_path, out_path='budgets.tsv'):
    rows = list(csv.DictReader(io.open(layout_path, encoding='utf-8'), delimiter='\t'))
    agg = collections.defaultdict(lambda: {'n': 0, 'hard': [], 'soft': [], 'wrap': 0})
    for r in rows:
        text = unesc(r['text'])
        if not text or float(r['sizeX']) <= 0:
            continue
        codes = set(CODE.findall(text))
        if not codes:
            continue
        w = float(r['sizeX']) * float(r['scaleX'])
        for c in codes:
            a = agg[c]
            a['n'] += 1
            if r['wordWrap'] == '1':
                a['wrap'] += 1
            elif r['clipping'] == '1':
                a['hard'].append(w)
            else:
                a['soft'].append(w)

    out = []
    for code, a in agg.items():
        out.append((code, a['n'], min(a['hard']) if a['hard'] else None,
                    min(a['soft']) if a['soft'] else None, a['wrap']))
    out.sort(key=lambda x: (x[2] is None, x[2] if x[2] is not None else 1e9))

    with io.open(out_path, 'w', encoding='utf-8') as w:
        w.write('code\tslots\thardBudgetPx\tsoftBudgetPx\twrappingSlots\n')
        for code, n, hard, soft, wrap in out:
            w.write('%s\t%d\t%s\t%s\t%d\n' % (code, n,
                    '' if hard is None else '%.0f' % hard,
                    '' if soft is None else '%.0f' % soft, wrap))

    print('%-34s %6s %10s %10s %8s' % ('code', 'slots', 'hard px', 'soft px', 'wrapping'))
    for code, n, hard, soft, wrap in out[:30]:
        print('%-34s %6d %10s %10s %8d' % (code, n,
              '-' if hard is None else '%.0f' % hard,
              '-' if soft is None else '%.0f' % soft, wrap))
    print('\ncodes: %d -> %s' % (len(out), out_path))
    print('hard budget = narrowest CLIPPING slot; text longer than that is cut.')
    return 0


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:3]))
