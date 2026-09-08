"""Second-pass display scan: depth-0 literals of Message/Picture/SetString/
Choices/case PLUS the Database command's first trailing literal (the written
display value - the other trailing literals are type/data/field lookup names
and are protected). Reports JP words and residual full-width symbols.

Usage: python scripts/scan_display2.py relayout/ws
"""
import re
import sys
import glob
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from relayout import unescape, _WORD_JP_RE
from fix_ui_strings import literal_spans

FW = re.compile(r"[＀-￯・。、！？：；～―─「」『』〓±≒≠÷]")
ALWAYS = {"Message", "Picture", "SetString", "choose", "case", "Choices"}

rows = []
for fn in sorted(glob.glob(sys.argv[1] + "/*.wscript")):
    base = Path(fn).stem
    for lno, line in enumerate(open(fn, encoding="utf-8"), 1):
        line = line.rstrip("\n")
        cmd = line.strip().split(" ", 1)[0].split("(", 1)[0]
        spans = literal_spans(line)
        if not spans:
            continue
        if cmd in ALWAYS:
            check = spans
        elif cmd == "Database":
            check = spans[:1]      # written value only; names are lookup keys
        else:
            continue
        for a, b in check:
            t = unescape(line[a + 1:b - 1])
            if re.search(r"\.(png|jpg|bmp|mp3|wav|ogg|mid|mps)$", t):
                continue
            if _WORD_JP_RE.search(t):
                rows.append(("JP", base, lno, cmd, t))
            elif FW.search(t.replace("　", "")):
                rows.append(("FW", base, lno, cmd, t))

seen = set()
for cat in ("JP", "FW"):
    items = [r for r in rows if r[0] == cat]
    print(f"===== {cat}: {len(items)}")
    for _c, base, lno, cmd, t in items:
        k = (cmd, t[:80])
        if k in seen:
            continue
        seen.add(k)
        print(f"  [{cmd}] {base}:{lno}  {t[:120]!r}")
