"""Sweep EVERY string in the deployed data - all wscript command string args
(Message, Picture, SetString, Choices, conditions...) plus all DB fields - for
remaining Japanese words and full-width/symbol characters that tofu in the
menus' Latin font.

Operand annotations like CSelf[0 "label"] are compiler symbol labels, not game
strings - bracketed segments are stripped before extraction.

Usage: python scripts/scan_all_strings.py <wscript-dir> <db-json>...
"""
import json
import re
import sys
import glob
import collections
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from relayout import unescape, _WORD_JP_RE

BRACKET_RE = re.compile(r'\[(?:[^\[\]"]|"(?:\\.|[^"\\])*")*\]')
STR_RE = re.compile(r'"((?:\\.|[^"\\])*)"')
FW_RISK = re.compile(r"[＀-￯・。、！？：；～―─｢｣「」『』●■◆▲▼〓±≒≠×÷]")
SAFE = set("　★☆※♪♡♥○◎△▽é¥·①②③④⑤⑥⑦⑧⑨—–")


def classify(t):
    if _WORD_JP_RE.search(t):
        return "JP_WORDS"
    risk = [c for c in t if FW_RISK.match(c) and c not in SAFE]
    if risk:
        return "FW_SYMBOLS"
    return None


DISPLAY_CMDS = {"Message", "Picture", "Choices", "case", "SetString", "StringCondition"}


def main():
    display_only = "--display" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--display"]
    rows = []
    for fn in sorted(glob.glob(args[0] + "/*.wscript")):
        base = Path(fn).stem
        for lno, line in enumerate(open(fn, encoding="utf-8"), 1):
            line = line.rstrip("\n")
            cmd = line.strip().split(" ", 1)[0].split("(", 1)[0]
            if display_only and cmd not in DISPLAY_CMDS:
                continue
            stripped = line
            prev = None
            while prev != stripped:
                prev = stripped
                stripped = BRACKET_RE.sub("", stripped)
            for m in STR_RE.finditer(stripped):
                t = unescape(m.group(1))
                cat = classify(t)
                if cat:
                    rows.append((cat, f"{base}:{lno}", cmd, t))
    for fn in args[1:]:
        db = json.load(open(fn, encoding="utf-8"))
        for t_i, typ in enumerate(db.get("types") or []):
            for r in typ.get("rows") or []:
                for field, val in (r.get("values") or {}).items():
                    if isinstance(val, str) and val:
                        cat = classify(val)
                        if cat:
                            rows.append((cat, f"{Path(fn).stem}:T{t_i}:{r.get('id')}",
                                         f"{typ.get('name','')[:20]}/{field[:20]}", val))
                nm = r.get("name") or ""
                cat = classify(nm)
                if cat:
                    rows.append((cat, f"{Path(fn).stem}:T{t_i}:{r.get('id')}", "row-name", nm))

    bycat = collections.defaultdict(list)
    for cat, loc, cmd, t in rows:
        bycat[cat].append((loc, cmd, t))
    for cat, items in bycat.items():
        print(f"\n===== {cat}: {len(items)}")
        seen = collections.Counter()
        for loc, cmd, t in items:
            key = t[:60]
            seen[key] += 1
            if seen[key] == 1:
                print(f"  [{cmd}] {loc}\n      {t[:110]!r}")
        dups = sum(n - 1 for n in seen.values())
        if dups:
            print(f"  (+{dups} duplicate occurrences)")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
