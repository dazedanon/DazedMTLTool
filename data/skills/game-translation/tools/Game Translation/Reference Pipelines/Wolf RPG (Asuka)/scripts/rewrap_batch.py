"""Rewrap translated message text to the Wolf message-box column.

Only dialogue and narration lines (CommonEvent + maps) are touched. The @N
portrait row and [Name] speaker row are preserved verbatim. Body rows wider
than WRAP_CELLS visible cells (codes count as zero width) are split at spaces;
rows already narrow enough keep their existing break.

A pre-wrap backup of batch.json is written once to tl/batch_prewrap.json.
Re-running is idempotent (already-wrapped rows are within budget).
"""
import re
import shutil
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from claude_translate import load_batch, save_batch, line_kind, WOLF_CODE_RE

WS = Path(__file__).resolve().parents[1]
BACKUP = WS / "tl" / "batch_prewrap.json"
WRAP_CELLS = 48
_HEADER_RE = re.compile(r"^(?:@\d+|\[[^\[\]\n]{1,40}\])$")


def cells(s):
    vis = WOLF_CODE_RE.sub("", s)
    w = 0
    for ch in vis:
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


def wrap_row(row):
    if cells(row) <= WRAP_CELLS:
        return [row]
    indent = "　" if row.startswith("　") else ""
    words = row.split(" ")
    out, cur = [], ""
    for word in words:
        cand = word if not cur else cur + " " + word
        if cur and cells(cand) > WRAP_CELLS:
            out.append(cur)
            cur = word
        else:
            cur = cand
    if cur:
        out.append(cur)
    # a single unbreakable run longer than the budget stays as-is (nothing to split on)
    return [(indent + r if i and indent and not r.startswith("　") else r)
            for i, r in enumerate(out)]


def rewrap(text):
    rows = text.split("\n")
    out = []
    for i, row in enumerate(rows):
        if i < 2 and _HEADER_RE.match(row.strip()):
            out.append(row)
            continue
        out.extend(wrap_row(row))
    return "\n".join(out)


def main():
    if not BACKUP.exists():
        shutil.copyfile(WS / "batch.json", BACKUP)
        print(f"backup: {BACKUP}")
    batch = load_batch()
    changed = tall = 0
    for l in batch["lines"]:
        tl = l.get("text") or ""
        if not tl or line_kind(l) not in ("dialogue", "narration"):
            continue
        if not ("CommonEvent" in l["file"] or "map_" in l["file"]):
            continue
        new = rewrap(tl)
        if new != tl:
            l["text"] = new
            changed += 1
            body = [r for r in new.split("\n") if not _HEADER_RE.match(r.strip())]
            if len(body) > 4:
                tall += 1
    save_batch(batch)
    print(f"rewrapped: {changed} lines ({tall} now taller than 4 body rows - review)")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
