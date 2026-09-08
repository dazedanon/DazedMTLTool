r"""Ablate the English ordinal-WORD rule on this corpus.

    ordinal_ablate.py

Adding it made every individual ordinal case line up and made the AGGREGATE
worse, which is the sideways churn the skill warns about: a one-sided fix turns
a false positive in one bucket into a false positive in the other. The bucket
that decides is CONFLICT, because that is where a real quantity error has to
land.
"""

import collections
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from artl import config, store, validate                          # noqa: E402
from audit.numbuckets import bucket                               # noqa: E402

NEVER = re.compile(r"(?!x)x")


def measure(on):
    old = validate._ORDINAL_WORD_RE
    if not on:
        validate._ORDINAL_WORD_RE = NEVER
    cfg = config.load()
    docs = store.load_docs(cfg["store_dir"])
    seen, counts = set(), collections.Counter()
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
    validate._ORDINAL_WORD_RE = old
    return counts


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("English ordinal-word rule, over DISTINCT sources")
    for label, on in (("OFF", False), ("ON", True)):
        c = measure(on)
        print("  %-4s total %4d   CONFLICT %3d   invented %4d   dropped %3d"
              % (label, sum(c.values()), c["CONFLICT"], c["invented"],
                 c["dropped"]))
    print("\nKeep it only if CONFLICT does not grow. An ordinal that reads")
    print("right in isolation is not worth a bucket that hides a real error.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
