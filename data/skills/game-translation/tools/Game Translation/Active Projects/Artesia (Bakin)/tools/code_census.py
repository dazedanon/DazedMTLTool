"""Census the control codes actually present in an exported unit set.

    code_census.py <units.jsonl> [codes_raw.txt]

The engine's own table (`GameContentParser.keyWords`, 541 regex entries dumped by
`BakinApi static`) says what the parser *can* match. This says what the game
*does* use, which is the list the masker has to get right - and it is two orders
of magnitude shorter.

Shapes are grouped by replacing every bracket body with `[]`, so `\\NPL[A]` and
`\\NPL[B]` land in one row and the bracket argument can be judged once.
"""

import collections
import json
import os
import re
import sys

# A backslash run: letters/#/$ optionally followed by bracketed arguments, or a
# single non-letter escape. Deliberately greedy on the letter run, because that
# is what the engine's own lexer does and the point is to see what it would eat.
SEQ = re.compile(r'\\(?:[A-Za-z_#$]+(?:\[[^\]\r\n]*\])*|.)')
BRACKET = re.compile(r'\[[^\]]*\]')


def main(units_path, codes_path=None):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    known = []
    if codes_path and os.path.exists(codes_path):
        for line in open(codes_path, encoding='utf-8'):
            if '\t' in line:
                known.append(line.split('\t', 1)[1].rstrip('\n'))
        print('engine keyword table: %d patterns' % len(known))

    uses = collections.Counter()
    kinds = collections.defaultdict(collections.Counter)
    sample = {}
    args = collections.defaultdict(collections.Counter)
    n_units = 0
    for line in open(units_path, encoding='utf-8'):
        u = json.loads(line)
        n_units += 1
        for m in SEQ.finditer(u['src']):
            tok = m.group()
            shape = BRACKET.sub('[]', tok)
            uses[shape] += 1
            kinds[shape][u['kind']] += 1
            sample.setdefault(shape, tok)
            for b in BRACKET.findall(tok):
                args[shape][b[1:-1]] += 1

    print('%-30s%9s%9s   %-30s %s' % ('code shape', 'uses', 'distArg', 'example', 'kinds'))
    for shape, n in uses.most_common():
        ks = ','.join('%s:%d' % (k.split('.')[-1], v) for k, v in kinds[shape].most_common(3))
        print('%-30s%9d%9d   %-30s %s' % (shape, n, len(args[shape]), sample[shape][:30], ks))
    print('\ndistinct shapes %d, total occurrences %d, over %d units'
          % (len(uses), sum(uses.values()), n_units))

    # Bracket arguments, so the key-vs-display-text call is made on evidence.
    print('\n--- bracket arguments per shape (up to 8 each) ---')
    for shape, n in uses.most_common():
        if not args[shape]:
            continue
        vals = ['%s(%d)' % (v[:40], c) for v, c in args[shape].most_common(8)]
        print('%-30s %d distinct: %s' % (shape, len(args[shape]), '; '.join(vals)))
    return 0


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:3]))
