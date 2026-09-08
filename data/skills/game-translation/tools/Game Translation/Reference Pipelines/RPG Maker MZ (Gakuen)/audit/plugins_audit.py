#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Inventory every Japanese string reachable from js/plugins.js parameters."""
import json, os, re, sys, collections

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
JS = os.path.join(ROOT, "js")
JP = re.compile(r"[一-鿿ぁ-ゖァ-ヺーｦ-ﾟＡ-ｚ０-９々〆]")

raw = open(os.path.join(JS, "plugins.js"), encoding="utf-8-sig").read()
start = raw.index("[", raw.index("$plugins"))
arr, _ = json.JSONDecoder().raw_decode(raw, start)

def leaves(v, path, out, depth=0):
    """Walk a parameter value, decoding JSON-in-string as deep as it goes."""
    if isinstance(v, str):
        s = v.strip()
        if s[:1] in "[{" and s[-1:] in "]}":
            try:
                dec = json.loads(s)
            except Exception:
                dec = None
            if dec is not None and depth < 8:
                leaves(dec, path, out, depth + 1)
                return
        if JP.search(v):
            out.append((path, v))
    elif isinstance(v, list):
        for i, x in enumerate(v):
            leaves(x, "%s[%d]" % (path, i), out, depth)
    elif isinstance(v, dict):
        for k, x in v.items():
            leaves(x, "%s.%s" % (path, k), out, depth)

total = 0
per_plugin = collections.Counter()
report = []
for p in arr:
    if not p.get("status"):
        continue
    nm = p.get("name", "")
    out = []
    for k, v in (p.get("parameters") or {}).items():
        leaves(v, k, out, 0)
    if not out:
        continue
    per_plugin[nm] = len(out)
    total += len(out)
    report.append((nm, out))

print("## enabled plugins with Japanese parameter leaves")
print("   total leaves: %d across %d plugins\n" % (total, len(report)))
for nm, cnt in per_plugin.most_common():
    print("   %5d  %s" % (cnt, nm))
print()
for nm, out in sorted(report, key=lambda x: -len(x[1])):
    print("=== %s  (%d)" % (nm, len(out)))
    seen = set()
    for path, v in out:
        key = (re.sub(r"\[\d+\]", "[]", path), v)
        if key in seen:
            continue
        seen.add(key)
        print("     %-46s %s" % (re.sub(r"\[\d+\]", "[]", path)[:46], repr(v)[:150]))
