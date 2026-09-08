r"""Bucket the number-drift flags by SHAPE, which is what decides the response.

    numbuckets.py [--show N]

A total is not progress. The skill's rule is that a real quantity error has to
land in the CONFLICT bucket - both sides carry numbers and they disagree - and
that the other three buckets are usually the comparison being wrong rather than
the translation:

    invented   the source has no number, the English does
    dropped    the source has one, the English does not
    reordered  same multiset, different order
    CONFLICT   both have numbers and they differ

Tracking the total instead of the buckets is how a tuning pass churns: every
one-sided fix converts a false positive in one bucket into a false positive in
the other, and the count goes 246 -> 80 -> 95 -> 146 -> 47.
"""

import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from artl import config, measure, store, validate                # noqa: E402


def bucket(src_nums, tl_nums):
    s, t = collections.Counter(src_nums), collections.Counter(tl_nums)
    if s == t:
        return "reordered"
    if not s and t:
        return "invented"
    if s and not t:
        return "dropped"
    return "CONFLICT"


def main(*argv):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    show = 10
    if "--show" in argv:
        show = int(argv[argv.index("--show") + 1])
    cfg = config.load()
    m = measure.reset(cfg)
    docs = store.load_docs(cfg["store_dir"])
    validate.load_budgets(cfg, docs)

    buckets = collections.defaultdict(list)
    seen = set()
    for _p, u in store.all_units(docs):
        if u.get("locked") or not (u.get("tl") or "").strip():
            continue
        a = validate._visible_numbers(u["src"])
        b = validate._visible_numbers(u["tl"])
        if a == b:
            continue
        k = (u["kind"], u["src"])
        if k in seen:
            continue
        seen.add(k)
        buckets[bucket(a, b)].append((u, a, b))

    total = sum(len(v) for v in buckets.values())
    print("number-drift by shape, over DISTINCT sources (%d)" % total)
    for name in ("CONFLICT", "invented", "dropped", "reordered"):
        print("   %-10s %5d" % (name, len(buckets.get(name, []))))
    print()
    print("A real quantity error has to be in CONFLICT. The other three are")
    print("usually the comparison, not the translation - read them before")
    print("paying for a retry that can only restructure the sentence.")

    for name in ("CONFLICT", "invented", "dropped", "reordered"):
        rows = buckets.get(name) or []
        if not rows:
            continue
        print("\n---- %s (%d) ----" % (name, len(rows)))
        for u, a, b in rows[:show]:
            print("   %-46s [%s]" % (u["id"][:46], u["kind"]))
            print("      JP  %s" % u["src"].replace("\n", " / ")[:92])
            print("      EN  %s" % (u["tl"] or "").replace("\n", " / ")[:92])
            print("      src=%s  tl=%s" % (a, b))
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
