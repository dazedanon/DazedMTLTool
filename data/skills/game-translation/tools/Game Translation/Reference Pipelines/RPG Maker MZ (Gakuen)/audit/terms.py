#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Candidate glossary TERMS: repeated katakana runs and repeated kanji compounds."""
import os, sys, re, collections
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from mztl import store

docs = store.load_docs(os.path.join(HERE, "tl"))
units = [u for _d, u in store.all_units(docs)]
corpus = "\n".join(u["src"] for u in units)

kata = collections.Counter(re.findall(r"[ァ-ヴー]{3,}", corpus))
kanji = collections.Counter(re.findall(r"[一-鿿々]{2,}", corpus))

print("## repeated katakana runs (>=8 occurrences)")
for k, v in kata.most_common(140):
    if v < 8:
        break
    print("   %5d  %s" % (v, k))

print("\n## repeated kanji compounds (>=25 occurrences)")
for k, v in kanji.most_common(320):
    if v < 25:
        break
    print("   %5d  %s" % (v, k))

# which kinds hold each
print("\n## per-kind unit counts")
c = collections.Counter(u["kind"] for u in units)
for k, v in c.most_common():
    print("   %-10s %d" % (k, v))

# source token estimate
def est(text):
    jp = sum(1 for ch in text if "぀" <= ch <= "ヿ" or "一" <= ch <= "鿿")
    return int(jp * 1.1 + (len(text) - jp) * 0.28) + 8

tot = sum(est(u["src"]) for u in units)
print("\n## source tokens (proxy): %d over %d units" % (tot, len(units)))
print("   mean %.1f tok/unit" % (tot / float(len(units))))
