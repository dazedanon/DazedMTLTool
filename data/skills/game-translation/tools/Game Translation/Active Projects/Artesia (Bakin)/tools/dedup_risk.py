"""Measure what deduplicating dialogue would actually risk.

    dedup_risk.py <units.jsonl>

The skill's standing rule is "dialogue is scene-grouped and NOT deduped",
because one line reused in another scene can be right where it was translated
and wrong everywhere else. That rule is a default, not a measurement, and on
this game the duplication factor is 3.6x - which is most of the bill.

So measure the risk surface instead of assuming it: how many distinct dialogue
bodies are reused across more than one owning scene, and how many are spoken by
more than one speaker. A body confined to a single scene family carries no
cross-scene risk at all, and a body with one speaker carries no pronoun risk.
"""

import collections
import json
import re
import sys

NPL = re.compile(r'^\\NPL\[([^\]]*)\]')


def main(path):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    owners = collections.defaultdict(set)
    speakers = collections.defaultdict(set)
    uses = collections.Counter()
    no_speaker = 0
    units = 0

    for line in open(path, encoding='utf-8'):
        u = json.loads(line)
        if u['kind'] != 'text':
            continue
        units += 1
        s = u['src']
        m = NPL.match(s)
        sp = m.group(1) if m else ''
        if not m:
            no_speaker += 1
        body = s[m.end():] if m else s
        owners[body].add(u['owner'])
        speakers[body].add(sp)
        uses[body] += 1

    multi_owner = [b for b in owners if len(owners[b]) > 1]
    multi_spk = [b for b in owners if len(speakers[b]) > 1]
    pairs = {(s, b) for b in owners for s in speakers[b]}

    print('dialogue units                 %8d' % units)
    print('distinct bodies (speaker off)  %8d' % len(owners))
    print('distinct (speaker, body) pairs %8d' % len(pairs))
    print('units with no nameplate code   %8d' % no_speaker)
    print('distinct body characters       %8d' % sum(len(b) for b in owners))
    print()
    print('bodies reused across >1 owner  %8d   (%d units)'
          % (len(multi_owner), sum(uses[b] for b in multi_owner)))
    print('bodies with >1 speaker         %8d   (%d units)'
          % (len(multi_spk), sum(uses[b] for b in multi_spk)))
    print('distinct speakers              %8d'
          % len({s for v in speakers.values() for s in v if s}))
    print()
    print('most-reused multi-speaker bodies:')
    for b in sorted(multi_spk, key=lambda x: -uses[x])[:10]:
        print('   x%-5d %-34s %s' % (uses[b], ','.join(sorted(speakers[b])[:3])[:34],
                                     b[:44].replace('\n', ' / ')))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
