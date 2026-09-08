"""Re-fit the labelled plates that are sized in the script, not by the engine.

The room-expansion screen draws each label twice: a ``[ptext]`` for the words and
an ``[image storage="ho.png"]`` at the same x/y for the black plate behind them,
with the plate's ``width`` written out as a number. Those numbers were measured
against the Japanese, so English spills past the plate - and ``Storage Lv:`` at
x=1850 runs 78px off a 1920px screen, because ``[ptext]`` does not wrap or clip,
it just draws.

So the plate is re-measured against the English and its ``width`` rewritten. That
is enough for five of the six; the sixth has no room to the right of it at all -
its own icon occupies 1697..1813 - so the label moves to the *left* of the icon,
which is the only free space on that row. That one placement is a judgement call
and is listed in ``MOVES`` rather than derived.

Runs as part of ``inject``, and only rewrites the two numbers, so re-running it
is idempotent: the second pass measures the same text and writes the same width.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import codes, layout

SCREEN_W = 1920

#: the plate is drawn from the text's own x, so all the slack is on the right
PLATE_PAD = 12

#: plate art, drawn behind a [ptext] at the same x and y
PLATE = "ho.png"

#: (file, first word of the label) -> new x, for labels with no room to grow
#: into. Storage sits at the right edge with its icon at 1697..1813, so its
#: label goes to the left of the icon instead.
MOVES: dict[tuple[str, str], int] = {
    ("data/scenario/home/hideout.ks", "Storage"): 1516,
}

LITERAL = re.compile(r"'((?:[^'\\]|\\.)*)'")


#: an attribute value, either quote style. A value containing a double quote is
#: written with single quotes - `text='Can now enter the "Bath"'` - and a reader
#: that knows only one style skips those tags without saying so.
ATTR = """\\b{name}=("[^"]*"|'[^']*')"""


def _attr(tag: str, name: str) -> str | None:
    found = re.search(ATTR.format(name=name), tag)
    return found.group(1)[1:-1] if found else None


def _set_attr(tag: str, name: str, value) -> str:
    text = str(value)

    def swap(found):
        quote = found.group(1)[0]
        if quote in text:
            # the value now needs the other delimiter; if it needs both, the
            # tag cannot express it and is better left as it was
            other = "'" if quote == '"' else '"'
            quote = other if other not in text else None
        return found.group(0) if quote is None else f"{name}={quote}{text}{quote}"

    return re.sub(ATTR.format(name=name), swap, tag, count=1)


def _visible(tag: str) -> str:
    """What the label reads once the expression is evaluated.

    A counter is a single digit at level 0 and could reach two; measuring one
    digit matches what the screen shows for all but a very long game, and the
    plate padding covers the difference.
    """
    raw = _attr(tag, "text") or ""
    if not raw.startswith("&"):
        return codes.unprotect_spaces(raw)
    out: list[str] = []
    position = 0
    for match in LITERAL.finditer(raw):
        if "f." in raw[position:match.start()] or "tf." in raw[position:match.start()]:
            out.append("0")
        out.append(match.group(1))
        position = match.end()
    if "f." in raw[position:] or "tf." in raw[position:]:
        out.append("0")
    return codes.unprotect_spaces("".join(out))


def fit(root: Path, app_root: Path) -> list[tuple[str, str, int, int, int]]:
    """``[(file, label, plate width, x, moved_to)]`` for everything re-fitted."""
    changed = []
    for path in sorted(root.rglob("*.ks")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if PLATE not in text:
            continue
        rel = path.relative_to(root).as_posix()

        # a plate is identified by the x/y it shares with its label
        plates: dict[tuple[str, str], tuple[int, int, str]] = {}
        for match in codes.TAG_RE.finditer(text):
            tag = match.group()
            if match.group(1) != "image" or f'storage="{PLATE}"' not in tag:
                continue
            plates[(_attr(tag, "x"), _attr(tag, "y"))] = (match.start(), match.end(), tag)

        edits: list[tuple[int, int, str]] = []
        for match in codes.TAG_RE.finditer(text):
            if match.group(1) != "ptext":
                continue
            tag = match.group()
            key = (_attr(tag, "x"), _attr(tag, "y"))
            if key not in plates:
                continue
            label = _visible(tag)
            size = int(_attr(tag, "size") or 25)
            width = int(layout.measure(label, size, app_root)) + PLATE_PAD

            x = int(key[0])
            moved = MOVES.get((rel, label.split(" ")[0]))
            if moved is None and x + width > SCREEN_W:
                moved = SCREEN_W - width - PLATE_PAD

            start, end, plate_tag = plates[key]
            new_plate = _set_attr(plate_tag, "width", width)
            new_label = tag
            if moved is not None and moved != x:
                new_plate = _set_attr(new_plate, "x", moved)
                new_label = _set_attr(new_label, "x", moved)
            if new_plate != plate_tag or new_label != tag:
                edits.append((start, end, new_plate))
                edits.append((match.start(), match.end(), new_label))
                changed.append((rel, label, width, x, moved if moved is not None else x))

        for start, end, replacement in sorted(edits, key=lambda e: -e[0]):
            text = text[:start] + replacement + text[end:]
        if edits:
            path.write_bytes(text.encode("utf-8"))
    return changed


#: the blue "+N" on an upgrade screen's bonus row. Its x was measured to clear
#: the Japanese description on its left, so a longer English one runs into it.
#: Only hideout.ks uses this colour, and only on that row, so it names these
#: values exactly.
VALUE_COLOR = "0x00a2ff"

#: the value finishes the description's sentence, so a word space is the right
#: gap. The Japanese had a wide column, but English descriptions vary too much
#: in length for a column to survive.
VALUE_GAP = 16


def _blocks(text: str) -> list[tuple[int, str]]:
    """``(offset, name)`` for every screen, so a row can be scoped to one.

    A screen is a ``*label``, or a ``[macro]`` in macro.ks, which has no labels
    at all - its screens are macro bodies.
    """
    found, offset = [], 0
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith("*") or stripped.startswith("[macro "):
            found.append((offset, line.strip()[:60]))
        offset += len(line)
    return found


def _block_at(blocks: list[tuple[int, str]], offset: int) -> str:
    name = ""
    for start, label in blocks:
        if start > offset:
            break
        name = label
    return name


def _space_values(text: str, app_root: Path) -> tuple[str, list]:
    """Push each value clear of the description on its left.

    Rows are scoped to the enclosing ``*label``. Six upgrade screens all draw
    their bonus row at y=910 and are never on screen together, so grouping by y
    alone would measure a label against one it can never meet.
    """
    edits, changed = [], []
    for items in _rows_of(text).values():
        items.sort(key=lambda item: item[0])
        for position, (x, match) in enumerate(items):
            if _attr(match.group(), "color") != VALUE_COLOR:
                continue
            # the nearest thing on the left that is a description, not another
            # value: a row can carry several values, one per condition branch
            left = None
            for back in range(position - 1, -1, -1):
                if _attr(items[back][1].group(), "color") != VALUE_COLOR:
                    left = items[back]
                    break
            if left is None:
                continue
            left_x, left_match = left
            size = int(_attr(left_match.group(), "size") or 25)
            label = _visible(left_match.group())
            end = left_x + int(layout.measure(label, size, app_root))
            wanted = max(x, end + VALUE_GAP)
            if wanted != x:
                edits.append((match.start(), match.end(),
                              _set_attr(match.group(), "x", wanted)))
                changed.append((label, x, wanted))
    for start, end, replacement in sorted(edits, key=lambda edit: -edit[0]):
        text = text[:start] + replacement + text[end:]
    return text, changed


def space(root: Path, app_root: Path) -> list[tuple[str, str, int, int]]:
    """``[(file, description, was x, now x)]`` for every value moved."""
    moved = []
    for path in sorted(root.rglob("*.ks")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if VALUE_COLOR not in text:
            continue
        text, changed = _space_values(text, app_root)
        if changed:
            path.write_bytes(text.encode("utf-8"))
            rel = path.relative_to(root).as_posix()
            moved.extend((rel, label, was, now) for label, was, now in changed)
    return moved


#: two or more spaces inside a label are a column separator, not words: the
#: value for that column is drawn into the gap at its own fixed x. The Japanese
#: sized the words and placed the values by hand, so English - which is wider -
#: pushes every column to the right of its value and the row reads as mush.
GAP_RUN = re.compile("[ \u00a0\u3000]{2,}")

#: a variable in a label stands in at two digits when measuring. Every value
#: that shares a row with words here is a counter that reaches two.
STANDIN = "00"


def _expand(text: str) -> str:
    """``&nbsp;`` is a space to the engine, so it has to be one when measuring."""
    return text.replace("&nbsp;", "\u00a0")


def _tokens(raw: str) -> list[tuple[str, str]]:
    """A ``text`` attribute as ``("lit", words)`` and ``("expr", code)`` parts."""
    if not raw.startswith("&"):
        return [("lit", raw)]
    body = raw[1:]
    out: list[tuple[str, str]] = []
    position = 0
    for match in LITERAL.finditer(body):
        between = body[position:match.start()].strip(" +")
        if between:
            out.append(("expr", between))
        out.append(("lit", match.group(1)))
        position = match.end()
    tail = body[position:].strip(" +")
    if tail:
        out.append(("expr", tail))
    return out


def _split_columns(tokens):
    """``(columns, gaps)`` - the words of each column, and the gaps between."""
    columns, gaps, current = [], [], []
    for kind, value in tokens:
        if kind != "lit":
            current.append((kind, value))
            continue
        expanded = _expand(value)
        pieces = GAP_RUN.split(expanded)
        runs = GAP_RUN.findall(expanded)
        for index, piece in enumerate(pieces):
            if piece:
                current.append(("lit", piece))
            if index < len(runs):
                columns.append(current)
                gaps.append(runs[index])
                current = []
    columns.append(current)
    return columns, gaps


def _render(parts) -> str:
    """The parts back as a ``text`` attribute, still an expression if it was one."""
    if all(kind == "lit" for kind, _ in parts):
        return "".join(value for _, value in parts)
    return "&" + " + ".join(
        f"'{value}'" if kind == "lit" else value for kind, value in parts)


def _plain(parts) -> str:
    return "".join(value if kind == "lit" else STANDIN for kind, value in parts)


def _columns_at(x, columns, gaps, size, app_root):
    """``[(kind, start, end)]`` for each column and gap in turn, drawn from ``x``."""
    spans = []
    for index, column in enumerate(columns):
        width = layout.measure(_plain(column), size, app_root)
        spans.append(("col", x, x + width))
        x += width
        if index < len(gaps):
            width = layout.measure(gaps[index], size, app_root)
            spans.append(("gap", x, x + width))
            x += width
    return spans


#: the values were placed against the column edge by eye and land a pixel or
#: three inside the words rather than dead on the gap, so a value counts as
#: belonging to the gap it is all but touching.
SLOT_SLACK = 8


def _slot(spans, value_x):
    """``(gap index, offset into it)``; index is ``None`` when it follows the row."""
    for index, (kind, start, end) in enumerate(spans):
        if kind == "gap" and start - SLOT_SLACK <= value_x < end:
            return index, value_x - start
    return None, value_x - spans[-1][2]


def _rows_of(source: str) -> dict[tuple, list]:
    """``(block, layer, y) -> [(x, match)]`` for every positioned ``[ptext]``.

    A tag on a line the parser treats as a comment is not on screen, so it is
    not on a row either - one of these sits in the trade header, and counting it
    would place the row's columns around something nothing draws.
    """
    blocks = _blocks(source)
    rows: dict[tuple, list] = {}
    for match in codes.TAG_RE.finditer(source):
        tag = match.group()
        if match.group(1) != "ptext":
            continue
        x, y = _attr(tag, "x"), _attr(tag, "y")
        if x is None or y is None or not x.isdigit():
            continue
        line_start = source.rfind("\n", 0, match.start()) + 1
        if source[line_start:match.start()].lstrip().startswith(";"):
            continue
        key = (_block_at(blocks, match.start()), _attr(tag, "layer"), y)
        rows.setdefault(key, []).append((int(x), match))
    return rows


def _is_label(match) -> bool:
    """A row's words: its *literal* text carries a column separator.

    Only literals count. ``&'+' +  f.hide[7]`` has two spaces between its
    operators and reads as a gap if the raw attribute is searched, but nothing
    is drawn there.
    """
    return any(kind == "lit" and GAP_RUN.search(_expand(value))
               for kind, value in _tokens(_attr(match.group(), "text") or ""))


def _rebuild(text: str, japanese: str, app_root: Path):
    """Re-place every column and every value of a fill-in-the-blanks row."""
    rows = _rows_of(text)
    japanese_rows = _rows_of(japanese)

    edits, changed = [], []
    for key, items in rows.items():
        labels = [(x, m) for x, m in items if _is_label(m)]
        if len(labels) != 1:
            continue
        label_x, label = labels[0]
        was = [(x, m) for x, m in japanese_rows.get(key, [])
               if x == label_x and _is_label(m)]
        if len(was) != 1:
            continue

        tag = label.group()
        size = int(_attr(tag, "size") or 25)
        old_columns, old_gaps = _split_columns(_tokens(_attr(was[0][1].group(), "text")))
        columns, gaps = _split_columns(_tokens(_attr(tag, "text")))
        if len(gaps) != len(old_gaps):
            continue

        # the gaps keep their Japanese width: each was cut to hold its value, and
        # it is the words around them that have grown
        old_spans = _columns_at(label_x, old_columns, old_gaps, size, app_root)

        # a gap only holds a column if something is drawn into it. Wide spacing
        # inside a label that nothing is threaded through is just padding, and
        # re-cutting it would move words that were never in anyone's way.
        threaded = [x for x, m in items
                    if m is not label and _slot(old_spans, x)[0] is not None]
        if not threaded:
            continue

        spans = _columns_at(label_x, columns, old_gaps, size, app_root)
        pieces = []
        for index, column in enumerate(columns):
            if not column:
                continue
            landed = int(spans[index * 2][1])
            pieces.append(_set_attr(_set_attr(tag, "x", landed), "text", _render(column)))
            if landed != label_x:
                changed.append((key[0], key[2], "column", label_x, landed))
        edits.append((label.start(), label.end(), "".join(pieces)))

        for x, match in items:
            if match is label:
                continue
            slot, offset = _slot(old_spans, x)
            base = spans[slot][1] if slot is not None else spans[-1][2]
            # the Japanese placed some values a pixel or three inside the words
            # they follow; keeping the offset would carry that overlap over
            wanted = int(base + max(offset, 0))
            if wanted != x:
                edits.append((match.start(), match.end(),
                              _set_attr(match.group(), "x", wanted)))
                changed.append((key[0], key[2], "value", x, wanted))

    for start, end, replacement in sorted(edits, key=lambda edit: -edit[0]):
        text = text[:start] + replacement + text[end:]
    return text, changed


def columns(root: Path, app_root: Path, japanese_root: Path):
    """``[(file, block, y, was x, now x)]`` for every column and value re-placed."""
    moved = []
    for path in sorted(root.rglob("*.ks")):
        rel = path.relative_to(root).as_posix()
        source = japanese_root / rel
        if not source.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        text, changed = _rebuild(
            text, source.read_text(encoding="utf-8", errors="replace"), app_root)
        if changed:
            path.write_bytes(text.encode("utf-8"))
            moved.extend((rel, block, y, what, was, now)
                         for block, y, what, was, now in changed)
    return moved


#: a hard line break inside a label. Where the author put one, the words after
#: it are a second line - the engine does not wrap, so this is the only wrapping
#: a [ptext] gets.
BREAK = re.compile(r"<br\s*/?>")


def _words(text: str) -> list[str]:
    return [word for word in re.split(r"[\s ]+", text) if word]


def _wrap(words: list[str], budget: float, size: int, app_root: Path) -> list[str]:
    lines, current = [], ""
    for word in words:
        trial = f"{current} {word}" if current else word
        if current and layout.measure(trial, size, app_root) > budget:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


def _narrowest(words, count, size, app_root):
    """The tightest box the words still fit in ``count`` lines, or ``None``.

    Narrowest rather than merely "fits": it keeps the block the same shape the
    author drew, and a balanced break reads better than a greedy one that runs
    every line to the margin and leaves the last with two words on it.
    """
    low = max(layout.measure(word, size, app_root) for word in words)
    high = layout.measure(" ".join(words), size, app_root)
    if len(_wrap(words, high, size, app_root)) > count:
        return None
    while low < high:
        middle = (low + high) / 2
        if len(_wrap(words, middle, size, app_root)) <= count:
            high = middle
        else:
            low = middle + 1
    return low


def _rebreak(text: str, japanese: str, app_root: Path):
    """Re-place the hard breaks in a label whose English outgrew its box."""
    japanese_rows: dict[tuple, list[str]] = {}
    for match in codes.TAG_RE.finditer(japanese):
        tag = match.group()
        if match.group(1) != "ptext" or not BREAK.search(_attr(tag, "text") or ""):
            continue
        key = (_attr(tag, "layer"), _attr(tag, "x"), _attr(tag, "y"))
        japanese_rows.setdefault(key, []).append(_attr(tag, "text"))

    seen: dict[tuple, int] = {}
    edits, changed = [], []
    for match in codes.TAG_RE.finditer(text):
        tag = match.group()
        raw = _attr(tag, "text") or ""
        if match.group(1) != "ptext" or not BREAK.search(raw) or raw.startswith("&"):
            continue
        key = (_attr(tag, "layer"), _attr(tag, "x"), _attr(tag, "y"))
        ordinal = seen.get(key, 0)
        seen[key] = ordinal + 1
        originals = japanese_rows.get(key, [])
        if ordinal >= len(originals):
            continue

        size = int(_attr(tag, "size") or 25)
        # a trailing <br> leaves an empty line that is not a line: one label
        # ends with one, and counting it would licence splitting the English
        # in two when the Japanese was only ever one line
        was = [part for part in BREAK.split(originals[ordinal]) if part.strip()]
        if not was:
            continue
        box = max(layout.measure(_expand(part), size, app_root) for part in was)
        lines = [_expand(part) for part in BREAK.split(raw)]
        widest = max(layout.measure(line, size, app_root) for line in lines)
        if widest <= box:
            continue

        words = _words(" ".join(lines))
        budget = _narrowest(words, len(was), size, app_root)
        if budget is None or budget >= widest:
            changed.append((key, int(widest), int(box), None))
            continue

        # an attribute value needs its spaces protected or the tag
        # parser eats them
        rebroken = codes.protect_spaces("<br>".join(
            " ".join(_words(line))
            for line in _wrap(words, budget, size, app_root)))
        edits.append((match.start(), match.end(), _set_attr(tag, "text", rebroken)))
        changed.append((key, int(widest), int(box), int(budget)))

    for start, end, replacement in sorted(edits, key=lambda edit: -edit[0]):
        text = text[:start] + replacement + text[end:]
    return text, changed


def rebreak(root: Path, app_root: Path, japanese_root: Path):
    """``[(file, x, y, was widest, japanese box, new widest)]`` for every label."""
    touched = []
    for path in sorted(root.rglob("*.ks")):
        rel = path.relative_to(root).as_posix()
        source = japanese_root / rel
        if not source.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "<br" not in text:
            continue
        text, changed = _rebreak(
            text, source.read_text(encoding="utf-8", errors="replace"), app_root)
        if any(budget is not None for _, _, _, budget in changed):
            path.write_bytes(text.encode("utf-8"))
        touched.extend((rel, key[1], key[2], widest, box, budget)
                       for key, widest, box, budget in changed)
    return touched


#: Panel art drawn at x=0 on the room-expansion screens, with its width. The
#: [image] tag gives no width, so this is the size of the file itself. Everything
#: the player reads on those screens sits on this slab, and a [ptext] neither
#: wraps nor clips - a line wider than the slab runs off the UI onto the lit
#: background behind it.
PANEL_WIDTH = {"houp.png": 650}

#: keep the last glyph off the very edge of the slab
PANEL_MARGIN = 14

#: A line box, as a multiple of the font size. Measured off the screen at 28px,
#: where two lines of one [ptext] sit 41px apart. Rounded up, because this is
#: used to decide whether a block has grown into the button below it and an
#: overestimate only makes it move out of the way sooner.
LINE_HEIGHT = 1.5

#: clearance between the bottom of a label and whatever is drawn under it
BELOW_PAD = 8


def _panel_macros(root: Path) -> dict[str, int]:
    """Macros whose body draws a panel, so a screen that calls one has it too.

    Most upgrade screens never name the slab: they call ``[upgr_bo]``, which
    draws it. Looking only for the image in the screen's own block finds five
    of them and silently passes over the rest.
    """
    source = root / "data" / "scenario" / "system" / "macro.ks"
    if not source.exists():
        return {}
    text = source.read_text(encoding="utf-8", errors="replace")
    blocks = _blocks(text)
    found: dict[str, int] = {}
    for match in codes.TAG_RE.finditer(text):
        if match.group(1) != "image":
            continue
        storage = _attr(match.group(), "storage")
        if storage not in PANEL_WIDTH:
            continue
        name = _attr(_block_at(blocks, match.start()), "name")
        if name:
            found[name] = PANEL_WIDTH[storage]
    return found


def _panel_of(text: str, blocks, offset: int, macros: dict[str, int]) -> int | None:
    """The width of the panel drawn on the screen this offset belongs to."""
    block = _block_at(blocks, offset)
    for match in codes.TAG_RE.finditer(text):
        if _block_at(blocks, match.start()) != block:
            continue
        if match.group(1) in macros:
            return macros[match.group(1)]
        if match.group(1) == "image":
            storage = _attr(match.group(), "storage")
            if storage in PANEL_WIDTH:
                return PANEL_WIDTH[storage]
    return None


def _floor_under(text: str, blocks, label, y: int) -> int:
    """The top of the nearest thing drawn below the label, on the same screen."""
    block = _block_at(blocks, label.start())
    lowest = 1080
    for match in codes.TAG_RE.finditer(text):
        if match.span() == label.span() or match.group(1) not in ("ptext", "button", "image"):
            continue
        if _block_at(blocks, match.start()) != block:
            continue
        other = _attr(match.group(), "y")
        if other is None or not other.isdigit():
            continue
        if y < int(other) < lowest:
            lowest = int(other)
    return lowest


def _fit_panel(text: str, app_root: Path, macros: dict[str, int]):
    """Pull every label back inside the panel it is drawn on."""
    blocks = _blocks(text)
    edits, changed = [], []
    for match in codes.TAG_RE.finditer(text):
        tag = match.group()
        raw = _attr(tag, "text") or ""
        if match.group(1) != "ptext" or raw.startswith("&") or not raw.strip():
            continue
        x, y = _attr(tag, "x"), _attr(tag, "y")
        if x is None or y is None or not x.isdigit() or not y.isdigit():
            continue
        line_start = text.rfind("\n", 0, match.start()) + 1
        if text[line_start:match.start()].lstrip().startswith(";"):
            continue

        # a screen with no slab of its own is still bounded by the screen: a
        # [ptext] neither wraps nor clips, so anything past the edge is simply
        # not readable
        panel = _panel_of(text, blocks, match.start(), macros) or SCREEN_W
        if int(x) >= panel:
            continue

        size = int(_attr(tag, "size") or 25)
        budget = panel - int(x) - PANEL_MARGIN
        lines = [_expand(part) for part in BREAK.split(raw)]
        if max(layout.measure(line, size, app_root) for line in lines) <= budget:
            continue

        words = _words(" ".join(lines))
        wrapped = _wrap(words, budget, size, app_root)
        if max(layout.measure(line, size, app_root) for line in wrapped) > budget:
            changed.append((int(x), int(y), len(lines), None, "a word is wider than the panel"))
            continue
        # filling each line to the panel edge leaves the last one holding an
        # orphan; once the line count is known, balance them within it
        balanced = _narrowest(words, len(wrapped), size, app_root)
        if balanced is not None:
            wrapped = _wrap(words, balanced, size, app_root)

        # a block that gained a line grows downward; move it up out of the way
        top = int(y)
        grew = (len(wrapped) - len(lines)) * size * LINE_HEIGHT
        if grew > 0:
            floor = _floor_under(text, blocks, match, int(y))
            bottom = int(y) + len(wrapped) * size * LINE_HEIGHT
            if bottom > floor - BELOW_PAD:
                top = int(y) - int(bottom - (floor - BELOW_PAD))

        rebuilt = _set_attr(tag, "text", codes.protect_spaces(
            "<br>".join(" ".join(_words(line)) for line in wrapped)))
        if top != int(y):
            rebuilt = _set_attr(rebuilt, "y", top)
        edits.append((match.start(), match.end(), rebuilt))
        changed.append((int(x), int(y), len(wrapped), top, lines[0][:40]))

    for start, end, replacement in sorted(edits, key=lambda edit: -edit[0]):
        text = text[:start] + replacement + text[end:]
    return text, changed


def panels(root: Path, app_root: Path):
    """``[(file, x, y, lines, moved to, what)]`` for every label pulled inside."""
    touched = []
    macros = _panel_macros(root)
    for path in sorted(root.rglob("*.ks")):
        text = path.read_text(encoding="utf-8", errors="replace")
        text, changed = _fit_panel(text, app_root, macros)
        if any(top is not None for _, _, _, top, _ in changed):
            path.write_bytes(text.encode("utf-8"))
            rel = path.relative_to(root).as_posix()
            touched.extend((rel, x, y, count, top, what)
                           for x, y, count, top, what in changed)
    return touched


#: Rows laid out by a cursor variable rather than by numbers: a [foreach] draws
#: the item name at ``tf.x`` and each value at a fixed offset along, then steps
#: the cursor by the row pitch. Nothing in the tag says the column to the left
#: holds an item name, and the x is an expression, so neither the row pass nor
#: the panel pass can see these rows at all.
#:
#: file -> (name expression, [value expressions, left to right], pitch). The
#: offsets are derived from the item table, so they follow the translation
#: rather than being numbers that go stale next time a name gets longer.
CURSOR_ROWS: dict[str, tuple[str, tuple[str, ...], int]] = {
    "data/scenario/home/tansaku.ks": (
        "&tf.item[1]", ("&tf.item[3]", "&tf.view_val + '%'"), 450),
}

#: how wide a value column has to be. A chance reads "100%"; everything else on
#: these rows is a recovered count, which the item table never takes past two
#: digits. Reserving the wider of the two for both would push the last column
#: into the next row's icon.
CURSOR_VALUE = "99"
CURSOR_PERCENT = "100%"


def _reserve(expression: str) -> str:
    return CURSOR_PERCENT if "%" in expression else CURSOR_VALUE

#: space between the end of one column and the start of the next
CURSOR_GAP = 12

#: the icon of the *next* row sits this far left of its own cursor, so the row
#: has to finish before it
CURSOR_ICON = 70

OFFSET = re.compile(r"^&\s*(\w+(?:\.\w+)*)\s*\+\s*(\d+)$")


def _item_names(root: Path) -> list[str]:
    """Every item display name, which is what a name column has to hold."""
    source = root / "data" / "scenario" / "system" / "exp.ks"
    if not source.exists():
        return []
    text = source.read_text(encoding="utf-8", errors="replace")
    block = re.search(r"f\.item=\[(.*?)^\]", text, re.S | re.M)
    if not block:
        return []
    names = []
    for line in block.group(1).splitlines():
        fields = re.findall(r'"((?:[^"\\]|\\.)*)"', line)
        if len(fields) >= 2 and fields[1].strip():
            names.append(codes.unprotect_spaces(fields[1]))
    return names


def _cursor_columns(text: str, plan, names, app_root: Path):
    """Push each value column clear of the widest name that can precede it."""
    name_expr, values, pitch = plan
    edits, changed = [], []

    sizes = set()
    for match in codes.TAG_RE.finditer(text):
        if match.group(1) == "ptext" and _attr(match.group(), "text") == name_expr:
            sizes.add(int(_attr(match.group(), "size") or 25))
    if not sizes or not names:
        return text, changed
    size = max(sizes)

    # lay the columns out left to right from the widest name the row can show
    at = max(layout.measure(name, size, app_root) for name in names)
    wanted = {}
    for expression in values:
        at = int(at) + CURSOR_GAP
        wanted[expression] = at
        at += layout.measure(_reserve(expression), size, app_root)

    room = pitch - CURSOR_ICON
    for match in codes.TAG_RE.finditer(text):
        tag = match.group()
        if match.group(1) != "ptext":
            continue
        expression = _attr(tag, "text")
        if expression not in wanted:
            continue
        found = OFFSET.match((_attr(tag, "x") or "").strip())
        if not found:
            continue
        was, now = int(found.group(2)), wanted[expression]
        if now <= was:
            continue
        if now + layout.measure(_reserve(expression), size, app_root) > room:
            changed.append((expression, was, None))
            continue
        edits.append((match.start(), match.end(),
                      _set_attr(tag, "x", f"&{found.group(1)} + {now}")))
        changed.append((expression, was, now))

    for start, end, replacement in sorted(edits, key=lambda edit: -edit[0]):
        text = text[:start] + replacement + text[end:]
    return text, changed


def cursors(root: Path, app_root: Path):
    """``[(file, expression, was, now)]`` for every cursor column moved."""
    names = _item_names(root)
    moved = []
    for rel, plan in CURSOR_ROWS.items():
        path = root / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        text, changed = _cursor_columns(text, plan, names, app_root)
        if any(now is not None for _, _, now in changed):
            path.write_bytes(text.encode("utf-8"))
        moved.extend((rel, expression, was, now) for expression, was, now in changed)
    return moved


#: A number dropped into a sentence takes a space in front of it in English and
#: none in Japanese, so the source has none and a faithful translation keeps
#: none: ``&'Add a fair amount' + f.koko_status[45][2] + ' used'`` reads "Add a
#: fair amount3 used". The give-away is a letter with a value straight after it.
GLUE_TAIL = re.compile(r"[A-Za-z]$")

#: ``&nbsp`` without its semicolon ends in a letter but is not a word. The
#: author left several like that; they are a separate fault and putting a space
#: after one would only make the entity harder to spot.
ENTITY_TAIL = re.compile(r"&[A-Za-z]+$")


def _unglue(text: str):
    """Give every value the space the sentence around it needs."""
    edits, changed = [], []
    for match in codes.TAG_RE.finditer(text):
        tag = match.group()
        raw = _attr(tag, "text") or ""
        if not raw.startswith("&"):
            continue

        parts = _tokens(raw)
        touched = False
        for index, (kind, value) in enumerate(parts):
            # only a literal *followed* by a value: a value followed by a
            # literal is usually a prefix variable - tf.tag holds the lock
            # marker on the request list - and wants no space at all
            if kind != "lit" or index + 1 >= len(parts):
                continue
            if parts[index + 1][0] != "expr":
                continue
            shown = codes.unprotect_spaces(_expand(value))
            if not GLUE_TAIL.search(shown) or ENTITY_TAIL.search(shown):
                continue
            parts[index] = ("lit", value + codes.NBSP)
            touched = True

        if not touched:
            continue
        rebuilt = _set_attr(tag, "text", _render(parts))
        if rebuilt == tag:
            continue                      # the value cannot be quoted; leave it
        edits.append((match.start(), match.end(), rebuilt))
        changed.append((text.count("\n", 0, match.start()) + 1,
                        codes.unprotect_spaces(_render(parts))[:56]))

    for start, end, replacement in sorted(edits, key=lambda edit: -edit[0]):
        text = text[:start] + replacement + text[end:]
    return text, changed


def unglue(root: Path):
    """``[(file, line, label)]`` for every value given room to breathe."""
    touched = []
    for path in sorted(root.rglob("*.ks")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if '="&' not in text:
            continue
        text, changed = _unglue(text)
        if changed:
            path.write_bytes(text.encode("utf-8"))
            rel = path.relative_to(root).as_posix()
            touched.extend((rel, line, label) for line, label in changed)
    return touched
