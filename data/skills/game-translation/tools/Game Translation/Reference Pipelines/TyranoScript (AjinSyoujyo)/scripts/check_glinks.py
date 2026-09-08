"""Measure every [glink] against the column it sits in and the screen edge."""
import re
import sys
from pathlib import Path

sys.path.insert(0, "tools/scripts")
from tyranotl import layout  # noqa: E402

APP = Path("tools/extracted/app")
OUT = Path("tools/translated/data/scenario")
PAD, SCREEN = 50, 1920
LITERAL = re.compile(r"'((?:[^'\\]|\\.)*)'")
COLUMNS = (20, 650, 1280)


def render(expr: str) -> str:
    """The literal text of a glink expression, with a wide number where a
    variable goes - the requirement counters reach four digits."""
    out = []
    pos = 0
    for m in LITERAL.finditer(expr):
        gap = expr[pos:m.start()]
        if "f." in gap or "tf." in gap:
            out.append("4800")
        out.append(m.group(1).replace("\\'", "'"))
        pos = m.end()
    if "f." in expr[pos:] or "tf." in expr[pos:]:
        out.append("4800")
    return "".join(out)


#: only the request screens are laid out as a three-column grid; everywhere
#: else a glink has the screen from its x to the right edge
GRID = ("home/youbou.ks", "explain.ks")


def column_width(x: int, rel: str) -> int:
    if rel in GRID:
        later = [c for c in COLUMNS if c > x]
        return (min(later) if later else SCREEN) - x - PAD
    return SCREEN - x - PAD


rows = []
for path in sorted(OUT.rglob("*.ks")):
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if "[glink" not in line or line.lstrip().startswith(";"):
            continue
        mx = re.search(r'\bx="(\d+)"', line)
        mt = re.search(r'\btext="&?(.*?)"\s', line)
        ms = re.search(r'\bsize="(\d+)"', line)
        mw = re.search(r'\bwidth="(\d+)"', line)
        if not mt:
            continue
        x = int(mx.group(1)) if mx else 0
        size = int(ms.group(1)) if ms else 27
        text = render(mt.group(1)) if mt.group(0).startswith('text="&') else mt.group(1)
        rel = path.relative_to(OUT).as_posix()
        limit = int(mw.group(1)) - 24 if mw else column_width(x, rel)
        for seg in re.split(r"<br\s*/?>", text):
            seg = seg.strip()
            if not seg:
                continue
            w = layout.measure(seg, size, APP)
            if w > limit:
                rows.append((w - limit, w, limit, x, rel, n, seg[:56]))

rows.sort(reverse=True)
print(f"glink labels wider than the room they have: {len(rows)}")
for over, w, limit, x, rel, n, seg in rows[:20]:
    print("  +%4.0f  %4.0f/%-4d x=%-5d %-26s :%-5d %s" % (over, w, limit, x, rel, n, seg))
