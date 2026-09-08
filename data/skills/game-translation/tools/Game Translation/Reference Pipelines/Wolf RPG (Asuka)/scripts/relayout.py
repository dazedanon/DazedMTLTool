"""Relayout injected Message text to the real box geometry: 60 cells x 4 rows.

Fixes two problems found in-game:
  * lines break early (model kept JP break positions; earlier wrap was 48 cells)
    -> body rows are MERGED and refilled greedily to WIDTH cells, so a line only
       ends when the next word would not fit;
  * messages taller than 4 rows overflow the box
    -> the surplus rows are PAGE-SPLIT into continuation Message commands,
       repeating the @N window prefix and [Name] header so the speaker stays
       visible. Done via WolfDawn decompile -> edit -> compile (jump targets are
       reconstructed from block structure, so inserting commands is safe).

Deliberate-layout messages (blank rows, code-only rows, full-width-space
indents - title cards, tutorials) are never merged; their rows are only
hard-wrapped if they exceed WIDTH.

Usage:
  python scripts/relayout.py simulate         # stats only, from batch.json
  python scripts/relayout.py wscript IN OUT   # transform one decompiled file
"""
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from claude_translate import WOLF_CODE_RE

WIDTH = 68        # no portrait: full box width (user-measured in-game)
WIDTH_FACE = 60   # portrait shown: usable width before the bust (user-measured in-game)
MAX_ROWS = 4

# @N indexes SysDatabase type 24 顔グラフィック名. Ids 0-9 are window-style selectors
# (No Window / Window Only / Right / Left / Center / No Border / Mini Char) with an
# EMPTY 顔画像ファイル - no portrait is drawn for them. Only ids with a real image
# file show a bust and need the narrow width.
FACE_IDS = frozenset((10, 11, 12, 13, 14, 15, 16, 18, 19, 20, 21, 22, 23,
                      25, 26, 27, 28, 29, 30, 31))

# Stateful display codes that persist from where they appear to the end of the
# message: color, font size, font face, draw speed. A page split resets them, so
# the last-seen token of each family is re-emitted at the top of continuations.
_STATE_CODE_RE = re.compile(r"\\(c|f|font|s)\[[^\]]*\]")

_WINDOW_RE = re.compile(r"^@\d+\n")
_NAME_RE = re.compile(r"^\[[^\[\]\n]{1,40}\]$")
_MSG_LINE_RE = re.compile(r'^(\s*)Message "((?:\\.|[^"\\])*)"\s*$')


def cells(s):
    vis = WOLF_CODE_RE.sub("", s)
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in vis)


def wrap_row(row, width=WIDTH):
    """Greedy space-wrap of one overlong row; codes are zero-width."""
    if cells(row) <= width:
        return [row]
    out, cur = [], ""
    for word in row.split(" "):
        cand = word if not cur else cur + " " + word
        if cur and cells(cand) > width:
            out.append(cur)
            cur = word
        else:
            cur = cand
    if cur:
        out.append(cur)
    return out


def _row_pages(rows, budget):
    return [rows[i:i + budget] for i in range(0, len(rows), budget)] or [[]]


def layout_message(text, width=None, width_face=None, max_rows=None):
    """Return a list of box texts (1 = unchanged/refit, >1 = page-split).

    Width is dynamic: a message with an @N face prefix renders a bust portrait
    over the right side of the box, so its usable width is `width_face`; a
    message without one gets the full `width`. All three params fall back to the
    module defaults (WIDTH / WIDTH_FACE / MAX_ROWS) when None, so a caller can
    override any subset without passing the others."""
    plain_w = WIDTH if width is None else width
    face_w = WIDTH_FACE if width_face is None else width_face
    max_rows = MAX_ROWS if max_rows is None else max_rows
    window = ""
    m = _WINDOW_RE.match(text)
    if m:
        window = m.group(0)
        text = text[m.end():]
    face = bool(window) and int(window[1:-1]) in FACE_IDS
    width = face_w if face else plain_w
    trailing_nl = text.endswith("\n")
    body = text.rstrip("\n")
    rows = body.split("\n")

    header = ""
    if rows and _NAME_RE.match(rows[0].strip()):
        header = rows[0]
        rows = rows[1:]

    def deliberate(r):
        return (not r.strip()) or (not WOLF_CODE_RE.sub("", r).strip()) or r.startswith("　")

    # The [Name] header renders inside the textbox and counts toward the 4-line
    # budget (user-confirmed in-game), so dialogue gets 3 body rows.
    budget = max(1, max_rows - (1 if header else 0))

    if any(deliberate(r) for r in rows):
        new_rows = []
        for r in rows:
            if not r.strip() or not WOLF_CODE_RE.sub("", r).strip():
                new_rows.append(r)          # blank / code-only: untouched
            elif r.startswith("　"):
                # indented layout row: wrap but keep the indent on every row
                body_r = r.lstrip("　")
                pad = "　" * (len(r) - len(body_r))
                new_rows.extend(pad + w for w in wrap_row(body_r, width - 2 * len(pad)))
            else:
                new_rows.extend(wrap_row(r, width))
        pages = [new_rows[i:i + budget] for i in range(0, len(new_rows), budget)] or [[]]
    else:
        merged = " ".join(r.strip() for r in rows if r.strip())
        merged = re.sub(r"  +", " ", merged)
        new_rows = wrap_row(merged, width) if merged else list(rows)
        if len(new_rows) <= budget:
            pages = [new_rows]
        else:
            # pack whole sentences per box so a page never breaks mid-sentence;
            # a single sentence larger than the box falls back to row-splitting
            sentences = re.split(r"(?<=[.!?…♪♥])\s+", merged)
            pages, cur = [], ""
            for sent in sentences:
                cand = sent if not cur else cur + " " + sent
                if cur and len(wrap_row(cand, width)) > budget:
                    pages.extend(_row_pages(wrap_row(cur, width), budget))
                    cur = sent
                else:
                    cur = cand
            if cur:
                pages.extend(_row_pages(wrap_row(cur, width), budget))

    boxes = []
    seen = header  # text emitted so far, for stateful-code tracking
    for i, page in enumerate(pages):
        body = "\n".join(page)
        if i > 0:
            # re-arm color/size/font/speed state that was active at the split
            active = {}
            for mm in _STATE_CODE_RE.finditer(seen):
                active[mm.group(1)] = mm.group(0)
            first_fams = {mm.group(1) for mm in _STATE_CODE_RE.finditer(body[:12])}
            prefix = "".join(tok for fam, tok in active.items() if fam not in first_fams)
            body = prefix + body
        parts = [window if window else ""]
        if header:
            parts.append(header + "\n")
        parts.append(body)
        boxes.append("".join(parts))
        seen += "\n" + body
    if trailing_nl:
        boxes[-1] += "\n"
    return boxes


def unescape(s):
    out = []
    it = iter(range(len(s)))
    i = 0
    while i < len(s):
        c = s[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue
        nxt = s[i + 1] if i + 1 < len(s) else None
        if nxt == "n":
            out.append("\n")
        elif nxt == "r":
            out.append("\r")
        elif nxt == "t":
            out.append("\t")
        elif nxt == '"':
            out.append('"')
        elif nxt == "\\":
            out.append("\\")
        elif nxt is None:
            out.append("\\")
            i += 1
            continue
        else:
            out.append("\\")
            out.append(nxt)
        i += 2
    return "".join(out)


def escape(s):
    return (s.replace("\\", "\\\\").replace('"', '\\"')
             .replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t"))


# Real kana/kanji words (the interpunct ・ and prolonged mark ー are punctuation).
_WORD_JP_RE = re.compile(r"[぀-ゟ゠-ヺヽ-ヿ一-鿿]")

# WolfDawn's strings-extract skips symbol-only strings (no translatable words), so
# they bypass both translation and --en-punct - and full-width punctuation renders
# as tofu in windows that use the Latin SubFont (Arial Black). Normalize them.
_FW_MAP = str.maketrans(
    "０１２３４５６７８９ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ"
    "ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ"
    "！？：；～＜＞（）［］｛｝，．＆％＋－＝／＊＠＃￥、。―─・ー–『』",
    "0123456789abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "!?:;~<>()[]{},.&%+-=/*@#¥,.-----\"\"")

# model glitches: visually/phonetically identical foreign letters inside English
_CYR_MAP = str.maketrans("кисеаорухКИСЕАОРУХ", "kiceaopyxKICEAOPYX")


def fixup_text(t):
    if re.search(r"[Ѐ-ӿ]", t):
        t = t.translate(_CYR_MAP)
    t = t.replace("석", "seki")        # hangul glitch: Higashi Man석 -> Manseki
    if _WORD_JP_RE.search(t):
        return t                       # real Japanese words: not ours to touch here
    t = re.sub(r"・{2,}", "...", t)
    t = t.replace("▶", "->").replace("◀", "<-").replace("≒", "~")
    t = t.translate(_FW_MAP)
    t = t.replace("....", "...").replace("...。", "...")
    return t


def transform_wscript(src_path, dst_path, do_layout=True,
                      width=None, width_face=None, max_rows=None):
    changed = split_boxes = 0
    out_lines = []
    for line in Path(src_path).read_text(encoding="utf-8").splitlines():
        m = _MSG_LINE_RE.match(line)
        if not m:
            out_lines.append(line)
            continue
        indent, lit = m.group(1), m.group(2)
        text = unescape(lit)
        fixed = fixup_text(text)
        boxes = layout_message(fixed, width, width_face, max_rows) if do_layout else [fixed]
        if len(boxes) == 1 and boxes[0] == text:
            out_lines.append(line)
            continue
        changed += 1
        split_boxes += len(boxes) - 1
        for b in boxes:
            out_lines.append(f'{indent}Message "{escape(b)}"')
    Path(dst_path).write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    return changed, split_boxes


def simulate():
    from claude_translate import load_batch, line_kind
    batch = load_batch()
    total = refit = split = boxes_added = 0
    for l in batch["lines"]:
        if line_kind(l) not in ("dialogue", "narration"):
            continue
        if not ("CommonEvent" in l["file"] or "map_" in l["file"]):
            continue
        tl = l.get("text") or ""
        if not tl:
            continue
        total += 1
        boxes = layout_message(tl)
        if len(boxes) > 1:
            split += 1
            boxes_added += len(boxes) - 1
        elif boxes[0] != tl:
            refit += 1
    print(f"messages: {total} | refilled/rewrapped: {refit} | page-split: {split} "
          f"(+{boxes_added} boxes)")


def check_wscript(path, width=None, width_face=None, max_rows=None):
    """Report Message strings violating the box geometry (post-transform gate)."""
    plain_w = WIDTH if width is None else width
    face_w = WIDTH_FACE if width_face is None else width_face
    max_rows = MAX_ROWS if max_rows is None else max_rows
    bad = 0
    for ln, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        m = _MSG_LINE_RE.match(line)
        if not m:
            continue
        raw = unescape(m.group(2))
        wm = _WINDOW_RE.match(raw)
        limit = face_w if (wm and int(wm.group(0)[1:-1]) in FACE_IDS) else plain_w
        text = _WINDOW_RE.sub("", raw)
        rows = text.rstrip("\n").split("\n")
        if len(rows) > max_rows:
            print(f"  line {ln}: {len(rows)} rows incl. header")
            bad += 1
        for r in rows:
            if cells(r) > limit and " " in r.strip():
                print(f"  line {ln}: row {cells(r)} cells (limit {limit}): {r[:60]!r}")
                bad += 1
    return bad


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(
        description="Relayout WOLF Message text to box geometry (reflow + page-split).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_geom(p):
        # all optional; omitted -> module default (WIDTH/WIDTH_FACE/MAX_ROWS)
        p.add_argument("--width", type=int, default=None,
                       help=f"plain box width in cells (default {WIDTH})")
        p.add_argument("--width-face", type=int, default=None, dest="width_face",
                       help=f"portrait box width in cells (default {WIDTH_FACE})")
        p.add_argument("--max-rows", type=int, default=None, dest="max_rows",
                       help=f"rows per box incl. name header (default {MAX_ROWS})")

    p = sub.add_parser("wscript", help="reflow + page-split a decompiled file")
    p.add_argument("src")
    p.add_argument("dst")
    add_geom(p)

    p = sub.add_parser("fixup", help="symbol/glyph fixups only, no reflow")
    p.add_argument("src")
    p.add_argument("dst")

    p = sub.add_parser("check", help="report boxes over the geometry")
    p.add_argument("src")
    add_geom(p)

    sub.add_parser("simulate", help="stats from batch.json (no write)")

    a = ap.parse_args(argv)
    if a.cmd == "wscript":
        ch, sp = transform_wscript(a.src, a.dst, True, a.width, a.width_face, a.max_rows)
        print(f"{Path(a.src).name}: {ch} messages changed, {sp} continuation boxes")
    elif a.cmd == "fixup":
        ch, _sp = transform_wscript(a.src, a.dst, do_layout=False)
        print(f"{Path(a.src).name}: {ch} messages fixed")
    elif a.cmd == "check":
        n = check_wscript(a.src, a.width, a.width_face, a.max_rows)
        print(f"{Path(a.src).name}: {n} violations")
        return 1 if n else 0
    elif a.cmd == "simulate":
        simulate()
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
