"""Prove that every backslash in the corpus belongs to a recognised code.

    backslash_audit.py <units.jsonl>

The masker can only be trusted if nothing is left over: an orphan backslash
that survives into English can form a NEW control code once Latin letters
follow it, and the engine draws whatever it then thinks the code is instead of
the word. This counts every backslash, subtracts the ones the code pattern
claims, and prints what is left with context.
"""

import collections
import json
import re
import sys

CODE = re.compile(r'\\(?:[A-Za-z_#$]+(?:\[[^\]\r\n]*\])*|.)')


def main(path):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    total = 0
    claimed = 0
    leftovers = collections.Counter()
    doubled = 0
    for line in open(path, encoding='utf-8'):
        u = json.loads(line)
        s = u['src']
        n = s.count('\\')
        if not n:
            continue
        total += n
        doubled += len(re.findall(r'\\\\', s))
        rest = s
        for m in CODE.finditer(s):
            claimed += m.group().count('\\')
        rest = CODE.sub('', s)
        for i, ch in enumerate(rest):
            if ch == '\\':
                leftovers[rest[max(0, i - 8):i + 8]] += 1
    print('backslashes total      %d' % total)
    print('claimed by the pattern %d' % claimed)
    print('literal "\\\\" pairs     %d' % doubled)
    print('unclaimed              %d' % sum(leftovers.values()))
    for ctx, n in leftovers.most_common(20):
        print('   %5d  %r' % (n, ctx))
    return 0 if not leftovers else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
