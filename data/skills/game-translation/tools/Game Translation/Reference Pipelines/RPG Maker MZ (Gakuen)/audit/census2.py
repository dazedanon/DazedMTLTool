#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Second census pass: speaker mechanism, control codes, geometry, samples."""
import json, glob, os, re, sys, collections

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, "data")

def load_all():
    out = {}
    for fn in sorted(glob.glob(os.path.join(DATA, "*.json"))):
        with open(fn, encoding="utf-8-sig") as f:
            out[os.path.basename(fn)] = json.load(f)
    return out

def lists(d):
    if isinstance(d, list):
        for i, e in enumerate(d):
            if not isinstance(e, dict):
                continue
            if isinstance(e.get("list"), list):
                yield e["list"], e
            for pi, p in enumerate(e.get("pages") or []):
                if isinstance(p, dict) and isinstance(p.get("list"), list):
                    yield p["list"], e
    elif isinstance(d, dict):
        for i, e in enumerate(d.get("events") or []):
            if not isinstance(e, dict):
                continue
            for pi, p in enumerate(e.get("pages") or []):
                if isinstance(p, dict) and isinstance(p.get("list"), list):
                    yield p["list"], e

files = load_all()
P = print

# ---- blocks: 101 followed by 401 run -------------------------------------
blocks = []
for b, d in files.items():
    for L, owner in lists(d):
        for i, c in enumerate(L):
            if not isinstance(c, dict) or c["code"] != 101:
                continue
            j = i + 1
            parts = []
            while j < len(L) and isinstance(L[j], dict) and L[j]["code"] == 401:
                parts.append((L[j]["parameters"] or [""])[0])
                j += 1
            if parts:
                blocks.append((b, c["parameters"], "\n".join(parts)))

P("## message blocks (101 + 401 run): %d" % len(blocks))

# nameplate conventions on the FIRST line
conv = collections.Counter()
for b, p101, txt in blocks:
    first = txt.split("\n")[0]
    if re.match(r"^\s*\u3010[^\u3011]+\u3011", first):
        conv["fullwidth-brackets"] += 1
    if re.match(r"^\\+[cC]\[\d+\]", first):
        conv["leading-color"] += 1
    if re.match(r"^[^\u300c\u300d\s]{1,14}\u300c", first):
        conv["Name-kagi"] += 1
    if first.rstrip().endswith("\uff1a"):
        conv["trailing-fullwidth-colon"] += 1
    if re.match(r"^\s*\\+[A-Za-z]+\[", first):
        conv["leading-escape"] += 1
P("first-line conventions: %r" % dict(conv))

# ---- ALL escape codes, everywhere in data --------------------------------
esc = collections.Counter()
CODE = re.compile(r"\\+([A-Za-z]+)(\[[^\]]*\])?|\\+([^A-Za-z0-9\s])")
def scan(v, bag):
    if not isinstance(v, str):
        return
    for m in CODE.finditer(v):
        if m.group(1):
            bag["\\" + m.group(1).upper() + ("[..]" if m.group(2) else "")] += 1
        else:
            bag["\\" + m.group(3)] += 1

def walk(o, bag):
    if isinstance(o, str):
        scan(o, bag)
    elif isinstance(o, list):
        for x in o:
            walk(x, bag)
    elif isinstance(o, dict):
        for k, v in o.items():
            walk(v, bag)

for b, d in files.items():
    walk(d, esc)
P("")
P("## escape codes across ALL of data/")
for k, v in esc.most_common(60):
    P("    %7d  %s" % (v, k))

# ---- orphan backslashes --------------------------------------------------
P("")
P("## orphan backslash before a word char (401 only), samples:")
n = 0
for b, d in files.items():
    for L, owner in lists(d):
        for c in L:
            if isinstance(c, dict) and c["code"] == 401:
                v = (c["parameters"] or [""])[0]
                if isinstance(v, str) and re.search(r"\\+(?=[^\W\d_])", v):
                    n += 1
                    if n <= 25:
                        P("    %-18s %r" % (b, v[:110]))
P("    total %d" % n)

# ---- unusual codes SM / CM / SE ------------------------------------------
P("")
P("## \\SM \\CM \\SE \\{ usage samples:")
seen = collections.Counter()
for b, d in files.items():
    for L, owner in lists(d):
        for c in L:
            if isinstance(c, dict) and c["code"] in (401, 102):
                vs = c["parameters"][0]
                vs = vs if isinstance(vs, list) else [vs]
                for v in vs:
                    if isinstance(v, str) and re.search(r"\\+(SM|CM|SE)\[", v):
                        if seen[v[:80]] == 0 and sum(seen.values()) < 25:
                            P("    %-18s %r" % (b, v[:120]))
                        seen[v[:80]] += 1

# ---- longest / widest source lines ---------------------------------------
lens = []
for b, p101, txt in blocks:
    for line in txt.split("\n"):
        vis = re.sub(r"\\+[A-Za-z]+\[[^\]]*\]|\\+[.|!^<>{}$]", "", line)
        w = sum(2 if ord(ch) > 0x2000 else 1 for ch in vis)
        lens.append(w)
lens.sort()
P("")
P("## author's own 401 line widths (cells, halfwidth=1)")
P("    n=%d  max=%d  p99=%d  p95=%d  p90=%d  median=%d"
  % (len(lens), lens[-1], lens[int(len(lens) * .99)], lens[int(len(lens) * .95)],
     lens[int(len(lens) * .90)], lens[len(lens) // 2]))
hist = collections.Counter(lens)
P("    top of the histogram:")
for w in sorted(hist)[-18:]:
    P("       %3d cells : %d lines" % (w, hist[w]))

# rows per block
rows = collections.Counter(len(t.split("\n")) for b, p, t in blocks)
P("    rows per message block: %r" % dict(sorted(rows.items())))

# ---- System.json ---------------------------------------------------------
sysd = files["System.json"]
P("")
P("## System.json")
P("    gameTitle   : %r" % sysd.get("gameTitle"))
P("    currencyUnit: %r" % sysd.get("currencyUnit"))
adv = sysd.get("advanced") or {}
for k in sorted(adv):
    P("    advanced.%-22s = %r" % (k, adv[k]))
P("    locale      : %r" % sysd.get("locale"))
P("    terms keys  : %r" % list((sysd.get("terms") or {}).keys()))

# ---- sample dialogue -----------------------------------------------------
P("")
P("## sample dialogue blocks")
import random
random.seed(7)
for b, p101, txt in random.sample(blocks, 24):
    P("    --- %s  face=%r spk=%r" % (b, p101[0], p101[4] if len(p101) > 4 else None))
    for line in txt.split("\n"):
        P("        %s" % line)
