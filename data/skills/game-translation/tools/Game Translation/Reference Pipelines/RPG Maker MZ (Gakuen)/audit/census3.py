#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Third pass: speaker-mode scoring, plugin config, orphan backslashes."""
import json, glob, os, re, sys, collections

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, "data")
JS = os.path.join(ROOT, "js")

def load_all():
    out = {}
    for fn in sorted(glob.glob(os.path.join(DATA, "*.json"))):
        with open(fn, encoding="utf-8-sig") as f:
            out[os.path.basename(fn)] = json.load(f)
    return out

def lists(d):
    if isinstance(d, list):
        for e in d:
            if not isinstance(e, dict):
                continue
            if isinstance(e.get("list"), list):
                yield e["list"]
            for p in (e.get("pages") or []):
                if isinstance(p, dict) and isinstance(p.get("list"), list):
                    yield p["list"]
    elif isinstance(d, dict):
        for e in (d.get("events") or []):
            if not isinstance(e, dict):
                continue
            for p in (e.get("pages") or []):
                if isinstance(p, dict) and isinstance(p.get("list"), list):
                    yield p["list"]

JP = re.compile(r"[\u4e00-\u9fff\u3041-\u3096\u30a1-\u30fa\u30fc\uff66-\uff9f\uff21-\uff5a\uff10-\uff19\u3005\u3006]")
P = print
files = load_all()

blocks = []
for b, d in files.items():
    for L in lists(d):
        for i, c in enumerate(L):
            if not isinstance(c, dict) or c["code"] != 101:
                continue
            j = i + 1
            parts = []
            while j < len(L) and isinstance(L[j], dict) and L[j]["code"] == 401:
                parts.append((L[j]["parameters"] or [""])[0])
                j += 1
            if parts:
                blocks.append((b, "\n".join(parts)))

# ---- FIRSTLINESPEAKERS scoring, exactly the skill's three gates ----------
STRIP = re.compile(r"^((?:\\+[^cCnNiIkKvVSs{}]+?\[[\d\w\W]+?\]?\])+)")
BARE = re.compile(r"^\\+[\W]+?")
OPENERS = "\u300c\"'(\uff08*[.\uff02\u300e\uff08\uff5e\u2026\u3010"

def strip_codes(s):
    s = re.sub(r"\\+[A-Za-z]+\[[^\]]*\]", "", s)
    s = re.sub(r"\\+[A-Za-z]", "", s)
    s = re.sub(r"\\+[.|!^<>{}$]", "", s)
    return s.lstrip()

hit = miss = 0
examples_hit, examples_miss = [], []
namecount = collections.Counter()
for b, txt in blocks:
    lines = txt.split("\n")
    if len(lines) < 2:
        miss += 1
        continue
    cand = strip_codes(lines[0]).strip()
    nxt = strip_codes(lines[1]).strip()
    ok = (0 < len(cand) <= 40 and JP.search(cand)
          and nxt and nxt[0] in OPENERS)
    if ok:
        hit += 1
        namecount[cand] += 1
        if len(examples_hit) < 6:
            examples_hit.append((b, lines[0], lines[1]))
    else:
        miss += 1
        if len(examples_miss) < 10 and cand:
            examples_miss.append((b, lines[0][:60], lines[1][:60] if len(lines) > 1 else ""))

P("## FIRSTLINESPEAKERS gate over %d blocks" % len(blocks))
P("   hit  : %d  (%.1f%%)" % (hit, 100.0 * hit / len(blocks)))
P("   miss : %d" % miss)
P("   distinct candidate names: %d" % len(namecount))
P("   top 60 candidates:")
for k, v in namecount.most_common(60):
    P("      %6d  %s" % (v, k))
P("   singletons (appear once): %d" % sum(1 for v in namecount.values() if v == 1))
P("   examples HIT:")
for b, a, c in examples_hit:
    P("      %-18s %r / %r" % (b, a, c))
P("   examples MISS:")
for b, a, c in examples_miss:
    P("      %-18s %r / %r" % (b, a, c))

# how many candidates would be lost if we required <=20 chars
P("   candidates over 20 chars: %d" % sum(v for k, v in namecount.items() if len(k) > 20))
for k, v in namecount.items():
    if len(k) > 20:
        P("        %r x%d" % (k, v))

# ---- genuine orphan backslashes (not a known code) -----------------------
KNOWN = re.compile(r"\\+(?:[A-Za-z]+\[[^\]]*\]|[A-Za-z]\b|[.|!^<>{}$])")
orph = collections.Counter()
for b, d in files.items():
    for L in lists(d):
        for c in L:
            if not isinstance(c, dict):
                continue
            vs = c.get("parameters") or []
            for v in vs:
                items = v if isinstance(v, list) else [v]
                for s in items:
                    if not isinstance(s, str):
                        continue
                    masked = KNOWN.sub("", s)
                    for m in re.finditer(r"\\+(?=[^\W\d_])", masked):
                        orph[masked[m.start():m.start() + 12]] += 1
P("")
P("## genuine orphan backslashes (after masking known codes): %d" % sum(orph.values()))
for k, v in orph.most_common(20):
    P("      %5d %r" % (v, k))

# ---- plugins.js ----------------------------------------------------------
raw = open(os.path.join(JS, "plugins.js"), encoding="utf-8-sig").read()
start = raw.index("[", raw.index("$plugins"))
arr, end = json.JSONDecoder().raw_decode(raw, start)
P("")
P("## plugins.js: %d entries, %d enabled" % (len(arr), sum(1 for p in arr if p.get("status"))))
INTEREST = ("Message", "Window", "Choice", "Name", "Menu", "Text", "Font",
            "Help", "Galge", "Standing", "CharacterPicture", "EroStatus",
            "Achievement", "Notify", "DText", "Variable", "Shop", "Poker",
            "BlackJack", "HighAndLow", "EnemyBook", "Kidoku", "Recollection",
            "Save", "Title", "Option", "Config", "Quest", "Ability", "Status")
for p in arr:
    if not p.get("status"):
        continue
    nm = p.get("name", "")
    if not any(k.lower() in nm.lower() for k in INTEREST):
        continue
    params = p.get("parameters") or {}
    jp = {k: v for k, v in params.items() if isinstance(v, str) and JP.search(v)}
    P("   --- %s   (%d params, %d with JP)" % (nm, len(params), len(jp)))
    for k, v in list(params.items())[:40]:
        mark = " <JP>" if isinstance(v, str) and JP.search(v) else ""
        P("        %-30s = %s%s" % (k, repr(v)[:110], mark))
