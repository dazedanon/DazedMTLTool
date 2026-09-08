r"""Measure the kana-numeral rule on THIS corpus instead of inheriting a ruling.

    kana_ablate.py

`validate._KANA_NUM` is empty, and the comment above it records an ablation on
a DIFFERENT game where the full table fixed 3 units and created 23. That is a
per-game ruling, and the skill is explicit that those do not travel: this game
writes `ふたりの動きが止まった` where the English says "the two of them", so the
rule that was net-negative there may be net-positive here.

Turns each candidate group on in turn and reports the four shape buckets, so
the answer is a measurement rather than an opinion.
"""

import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from artl import config, store, validate                          # noqa: E402
from audit.numbuckets import bucket                               # noqa: E402

GROUPS = {
    "tsu-series (ふたつ..ここのつ)": {
        "ふたつ": 2, "みっつ": 3, "よっつ": 4, "いつつ": 5, "むっつ": 6,
        "ななつ": 7, "やっつ": 8, "ここのつ": 9, "とお": 10,
    },
    "people (ふたり, さんにん)": {
        "ふたり": 2, "三人": 3, "さんにん": 3, "四人": 4, "よにん": 4,
    },
    "hitori/hitotsu (the risky pair)": {
        "ひとり": 1, "ひとつ": 1,
    },
}


def measure(table):
    old = dict(validate._KANA_NUM)
    import re
    validate._KANA_NUM.clear()
    validate._KANA_NUM.update(table)
    validate._KANA_NUM_RE = re.compile(
        "|".join(sorted(validate._KANA_NUM, key=len, reverse=True))
        or r"(?!x)x")
    cfg = config.load()
    docs = store.load_docs(cfg["store_dir"])
    seen = set()
    counts = collections.Counter()
    for _p, u in store.all_units(docs):
        if u.get("locked") or not (u.get("tl") or "").strip():
            continue
        k = (u["kind"], u["src"])
        if k in seen:
            continue
        seen.add(k)
        a = validate._visible_numbers(u["src"])
        b = validate._visible_numbers(u["tl"])
        if a != b:
            counts[bucket(a, b)] += 1
    validate._KANA_NUM.clear()
    validate._KANA_NUM.update(old)
    return counts


def show(label, counts):
    total = sum(counts.values())
    print("  %-34s total %4d   CONFLICT %3d  invented %4d  dropped %3d"
          % (label, total, counts["CONFLICT"], counts["invented"],
             counts["dropped"]))
    return total


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("kana-numeral ablation, over DISTINCT sources")
    base = measure({})
    base_total = show("OFF (current)", base)

    cumulative = {}
    for name, tbl in GROUPS.items():
        c = measure(tbl)
        t = show("only " + name, c)
        print("       -> %+d against OFF" % (t - base_total))
        cumulative.update(tbl)
    c = measure(cumulative)
    t = show("ALL groups together", c)
    print("       -> %+d against OFF" % (t - base_total))
    print("\nA group only earns its place if it lowers the total AND does not")
    print("raise CONFLICT, which is the bucket a real quantity error lands in.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
