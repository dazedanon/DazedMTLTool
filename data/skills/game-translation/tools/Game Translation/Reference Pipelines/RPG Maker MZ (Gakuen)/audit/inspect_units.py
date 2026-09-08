#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Eyeball the extracted store: a sample of every kind, plus the speaker list."""
import os, sys, json, random, collections
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from mztl import store, config, measure

cfg = config.Config()
sd = os.path.join(HERE, "tl")
docs = store.load_docs(sd)
units = [u for _d, u in store.all_units(docs)]
g = store.load_glossary(sd)

by_kind = collections.defaultdict(list)
for u in units:
    by_kind[u["kind"]].append(u)

print("## %d units" % len(units))
random.seed(11)
for k in sorted(by_kind):
    lst = by_kind[k]
    print("\n=== %s  (%d)" % (k, len(lst)))
    for u in random.sample(lst, min(6, len(lst))):
        print("   id      %s" % u["id"])
        print("   ctx     %s" % (u.get("ctx") or "")[:100])
        if u.get("speaker"):
            print("   speaker %s   raw=%r" % (u["speaker"], u.get("speaker_raw")))
        if u.get("codes"):
            print("   codes   %r" % u["codes"])
        if u.get("note"):
            print("   note    %s" % u["note"][:100])
        print("   src     %r" % u["src"][:220])
        print("   raw     %r" % u["raw"][:220])
        print()

print("\n## glossary names: %d" % len(g["names"]))
print("   %s" % ", ".join(sorted(g["names"])[:200]))

# locked units
lk = [u for u in units if u.get("locked")]
print("\n## locked (pre-filled) units: %d" % len(lk))
for u in lk[:8]:
    print("   %-40s spk=%-10s src=%r" % (u["id"], u.get("speaker"), u["src"][:60]))

# widest source, to sanity-check the wrap budget
m = measure.reset(cfg.font_path)
print("\n## measurer exact=%s half_px=%.2f" % (m.exact, m.half_px))
worst = sorted(((m.cells(l), u["id"], l)
                for u in by_kind["text"] for l in u["raw"].split("\n")),
               reverse=True)[:8]
for c, i, l in worst:
    print("   %3d cells  %-34s %r" % (c, i, l[:80]))
