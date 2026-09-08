#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Measure the number-drift check's false-positive rate on its first real run.

Prints, for every flagged unit, what each side canonicalised to - so the check
gets fixed on evidence instead of the count being waived.
"""
import os, sys, collections, argparse
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from mztl import config, store, validate, codes

ap = argparse.ArgumentParser()
ap.add_argument("--n", type=int, default=40)
args = ap.parse_args()

docs = store.load_docs(os.path.join(HERE, "tl"))
rows = []
for _d, u in store.all_units(docs):
    tl = (u.get("tl") or "").strip()
    if not tl:
        continue
    a = validate._visible_numbers(u["src"])
    b = validate._visible_numbers(tl)
    if a != b:
        rows.append((u, a, b))

print("## %d flagged" % len(rows))
shapes = collections.Counter()
for u, a, b in rows:
    if not a and b:
        shapes["src has none, tl invented one"] += 1
    elif a and not b:
        shapes["src has one, tl dropped it"] += 1
    elif sorted(a) == sorted(b):
        shapes["same multiset, different ORDER"] += 1
    else:
        shapes["different values"] += 1
for k, v in shapes.most_common():
    print("   %-34s %d" % (k, v))
print()
for u, a, b in rows[:args.n]:
    print("   %-36s src=%-16s tl=%s" % (u["id"], a, b))
    print("      SRC %r" % validate._canonical_numbers(codes.PH_RE.sub("", u["src"]))[:0] or "")
    print("      src %r" % u["src"][:150])
    print("      tl  %r" % (u.get("tl") or "")[:150])
    print()
