#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Show the actual units behind each validation category, so a check is fixed
or a translation is fixed on evidence rather than on the count."""
import os, sys, collections, argparse
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from mztl import config, store, validate, measure, codes

ap = argparse.ArgumentParser()
ap.add_argument("--only", default=None)
ap.add_argument("--n", type=int, default=12)
args = ap.parse_args()

cfg = config.Config()
m = measure.reset(cfg.font_path)
docs = store.load_docs(os.path.join(HERE, "tl"))
by_cat = collections.defaultdict(list)
for _d, u in store.all_units(docs):
    for c in validate.hard_issues(u, cfg, m):
        by_cat[c].append(u)

print("## categories")
for c, us in sorted(by_cat.items(), key=lambda kv: -len(kv[1])):
    print("   %-24s %d" % (c, len(us)))
print()
for c, us in sorted(by_cat.items(), key=lambda kv: -len(kv[1])):
    if args.only and c != args.only:
        continue
    print("=== %s  (%d)" % (c, len(us)))
    for u in us[:args.n]:
        print("   id    %s   [%s]" % (u["id"], u["kind"]))
        print("   src   %r" % u["src"][:200])
        print("   tl    %r" % (u.get("tl") or "")[:200])
        if u.get("codes"):
            print("   codes %r" % u["codes"])
        print()
