#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Per-game event-code census. Evidence for every ruling in mztl/config.py."""
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
    """(ptr_label, list) for every event command list."""
    if isinstance(d, list):
        for i, e in enumerate(d):
            if not isinstance(e, dict):
                continue
            if isinstance(e.get("list"), list):
                yield ("[%d].list" % i, e["list"], e)
            for pi, p in enumerate(e.get("pages") or []):
                if isinstance(p, dict) and isinstance(p.get("list"), list):
                    yield ("[%d].pages[%d].list" % (i, pi), p["list"], e)
    elif isinstance(d, dict):
        for i, e in enumerate(d.get("events") or []):
            if not isinstance(e, dict):
                continue
            for pi, p in enumerate(e.get("pages") or []):
                if isinstance(p, dict) and isinstance(p.get("list"), list):
                    yield ("events[%d].pages[%d].list" % (i, pi), p["list"], e)

def all_commands(files):
    for b, d in files.items():
        for label, L, owner in lists(d):
            for i, c in enumerate(L):
                if isinstance(c, dict):
                    yield b, label, L, i, c, owner

JP = re.compile(r"[\u4e00-\u9fff\u3041-\u3096\u30a1-\u30fa\u30fc\uff66-\uff9f\uff21-\uff5a\uff10-\uff19\u3005\u3006]")

def has_jp(s):
    return isinstance(s, str) and bool(JP.search(s))

def main():
    files = load_all()
    cmds = list(all_commands(files))
    out = []
    P = out.append

    # ---------------- 101 ----------------
    ar = collections.Counter(); spk = collections.Counter(); fac = collections.Counter()
    for b, lb, L, i, c, o in cmds:
        if c["code"] == 101:
            p = c["parameters"]; ar[len(p)] += 1
            if len(p) > 4 and p[4]:
                spk[p[4]] += 1
            if p and p[0]:
                fac[p[0]] += 1
    P("## 101 Show Text header")
    P("arity: %r" % dict(ar))
    P("with parameters[4] speaker: %d   distinct: %d" % (sum(spk.values()), len(spk)))
    for k, v in spk.most_common(30):
        P("    %6d  %s" % (v, k))
    P("with face graphic: %d   distinct: %r" % (sum(fac.values()), dict(fac)))

    # ---------------- escape codes over all display text ----------------
    esc = collections.Counter()
    CODE = re.compile(r"\\+([A-Za-z]+)(\[[^\]]*\])?|\\+([^A-Za-z0-9\s])")
    def scan(v):
        if not isinstance(v, str):
            return
        for m in CODE.finditer(v):
            if m.group(1):
                esc[("\\" + m.group(1).upper() + ("[..]" if m.group(2) else ""))] += 1
            else:
                esc["\\" + m.group(3)] += 1
    for b, lb, L, i, c, o in cmds:
        if c["code"] in (401, 405):
            scan((c["parameters"] or [""])[0])
        elif c["code"] == 102 and c["parameters"] and isinstance(c["parameters"][0], list):
            for x in c["parameters"][0]:
                scan(x)
    P("")
    P("## escape codes in 401/405/102")
    for k, v in esc.most_common(60):
        P("    %7d  %s" % (v, k))

    # orphan backslash before a word char
    orphan = 0
    for b, lb, L, i, c, o in cmds:
        if c["code"] in (401, 405):
            v = (c["parameters"] or [""])[0]
            if isinstance(v, str) and re.search(r"\\+(?=[^\W\d_])", v):
                orphan += 1
    P("    401 lines with an orphan backslash before a word char: %d" % orphan)

    # ---------------- 122 ----------------
    op = collections.Counter(); s122 = []
    for b, lb, L, i, c, o in cmds:
        if c["code"] == 122:
            p = c["parameters"]
            t = p[3] if len(p) > 3 else None
            op[t] += 1
            if t == 4 and len(p) > 4:
                s122.append((b, p[0], p[1], p[4]))
    P("")
    P("## 122 Control Variables - operand types: %r" % dict(op))
    P("   string-operand (type 4) count: %d" % len(s122))
    for b, a, z, v in s122[:60]:
        P("    %-20s var %s..%s = %r" % (b, a, z, v))

    # ---------------- 111 ----------------
    t111 = collections.Counter(); gv = []
    for b, lb, L, i, c, o in cmds:
        if c["code"] == 111:
            p = c["parameters"]
            t111[p[0] if p else None] += 1
            if p and p[0] == 12 and len(p) > 1 and isinstance(p[1], str):
                if "$gameVariables" in p[1]:
                    gv.append((b, p[1]))
    P("")
    P("## 111 Conditional Branch - condition types: %r" % dict(t111))
    P("   script conditions touching $gameVariables: %d" % len(gv))
    for b, v in gv[:40]:
        P("    %-20s %r" % (b, v))

    # ---------------- 355/655 ----------------
    blocks = []
    for b, lb, L, i, c, o in cmds:
        if c["code"] == 355:
            j = i; parts = []
            while j < len(L) and isinstance(L[j], dict) and L[j]["code"] in (355, 655):
                parts.append((L[j]["parameters"] or [""])[0])
                j += 1
            blocks.append((b, "\n".join(parts)))
    jpblocks = [(b, t) for b, t in blocks if has_jp(t)]
    P("")
    P("## 355/655 script blocks: %d total, %d containing Japanese" % (len(blocks), len(jpblocks)))
    seen = set()
    for b, t in jpblocks:
        k = re.sub(r"[\u3000-\u9fff\uff00-\uffef]+", "*", t)[:120]
        if k in seen:
            continue
        seen.add(k)
        P("    --- %s" % b)
        for line in t.split("\n")[:8]:
            P("        %s" % line[:160])
        if len(seen) > 40:
            break

    # ---------------- 356 / 357 / 657 ----------------
    p357 = collections.Counter(); ex357 = {}
    for b, lb, L, i, c, o in cmds:
        if c["code"] == 357:
            p = c["parameters"]
            key = (p[0] if len(p) > 0 else "", p[1] if len(p) > 1 else "")
            p357[key] += 1
            ex357.setdefault(key, p)
    P("")
    P("## 357 MZ plugin commands: %d" % sum(p357.values()))
    for k, v in p357.most_common(60):
        P("    %5d  %s :: %s" % (v, k[0], k[1]))
        args = ex357[k][3] if len(ex357[k]) > 3 else {}
        if isinstance(args, dict):
            for ak, av in list(args.items())[:12]:
                mark = " <JP>" if has_jp(str(av)) else ""
                P("            %-24s = %r%s" % (ak, str(av)[:80], mark))
        P("            parameters[2] = %r%s" % (ex357[k][2] if len(ex357[k]) > 2 else None,
                                                " <JP>" if has_jp(str(ex357[k][2] if len(ex357[k]) > 2 else "")) else ""))

    # 657 - what precedes it
    pre657 = collections.Counter(); ex657 = collections.Counter()
    for b, lb, L, i, c, o in cmds:
        if c["code"] == 657:
            ctx = tuple(L[k]["code"] for k in range(max(0, i - 3), i) if isinstance(L[k], dict))
            pre657[ctx] += 1
            v = (c["parameters"] or [""])[0]
            ex657[str(v)[:100]] += 1
    P("")
    P("## 657: %d   preceded by:" % sum(pre657.values()))
    for k, v in pre657.most_common(10):
        P("    %5d  %r" % (v, k))
    P("   distinct values (top 40):")
    for k, v in ex657.most_common(40):
        P("    %5d  %s%s" % (v, k, "   <JP>" if has_jp(k) else ""))

    p356 = collections.Counter()
    for b, lb, L, i, c, o in cmds:
        if c["code"] == 356:
            p356[(c["parameters"] or [""])[0].split(" ")[0]] += 1
    P("")
    P("## 356 MV-style plugin commands: %r" % dict(p356))

    # ---------------- 108 / 408 ----------------
    com = collections.Counter()
    for b, lb, L, i, c, o in cmds:
        if c["code"] == 108:
            j = i; parts = []
            while j < len(L) and isinstance(L[j], dict) and L[j]["code"] in (108, 408):
                parts.append((L[j]["parameters"] or [""])[0])
                j += 1
            com["\n".join(parts)[:120]] += 1
    P("")
    P("## 108/408 comment blocks: %d distinct" % len(com))
    for k, v in com.most_common(50):
        P("    %4d  %s%s" % (v, k.replace("\n", " | ")[:140], "   <JP>" if has_jp(k) else ""))

    # ---------------- 118/119 ----------------
    labels = collections.Counter()
    for b, lb, L, i, c, o in cmds:
        if c["code"] in (118, 119):
            labels[(c["parameters"] or [""])[0]] += 1
    P("")
    P("## 118/119 labels (NEVER translate): %d distinct" % len(labels))
    for k, v in labels.most_common(20):
        P("    %4d  %r" % (v, k))

    # ---------------- 320/324/325/205/231 etc ----------------
    for code, name in ((320, "Change Actor Name"), (324, "Change Nickname"),
                       (325, "Change Profile"), (405, "Scrolling Text")):
        n = sum(1 for b, lb, L, i, c, o in cmds if c["code"] == code)
        P("## %d %s: %d" % (code, name, n))

    sys.stdout.write("\n".join(out) + "\n")

if __name__ == "__main__":
    main()
