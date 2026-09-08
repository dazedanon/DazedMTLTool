"""Budgets for strings that live in the game's data arrays.

A lot of this game's on-screen text is not a tag attribute at all - it is a
literal inside a table declared in an ``[iscript]`` block:

    f.item = [ ["pk_t", "ピンクの注射器", "", 5, "tansakuui/pk_t.png", ...], ... ]
    f.koko_status = [ ["隠れてオナニーした回数", 0], ... ]

Each row is drawn by a layout macro that puts one column at a fixed ``x`` and
the next at another, so a column that grows runs straight into its neighbour:
"Times masturbated in se0cret", "Painting of a Cracked0Egg and a Woman".

Finding every draw site for every column is a lot of archaeology for a moving
target. The reliable bound is the shipped Japanese: **whatever room the widest
Japanese entry in a column had, the English has too**, and no more. So budgets
are computed per (array, column), not per array - a table holding both a short
label and a long description would otherwise let the label grow to the
description's width.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import codes, layout

ASSIGN_RE = re.compile(r"^\s*(f\.\w+)\s*=\s*\[")
#: nominal size for comparing widths; only the ratio between JP and EN matters
NOMINAL_SIZE = 27


def find_arrays(app_root: Path) -> list[tuple[str, str, int, int]]:
    """``(file, variable, first_line, last_line)`` for every ``f.x = [ ... ]``."""
    found: list[tuple[str, str, int, int]] = []
    for path in sorted((app_root / "data" / "scenario").rglob("*.ks")):
        rel = path.relative_to(app_root).as_posix()
        start: int | None = None
        name = ""
        depth = 0
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if start is None:
                m = ASSIGN_RE.match(line)
                if m:
                    name, start = m.group(1), number
                    depth = line.count("[") - line.count("]")
                    if depth <= 0:
                        found.append((rel, name, start, number))
                        start = None
            else:
                depth += line.count("[") - line.count("]")
                if depth <= 0:
                    found.append((rel, name, start, number))
                    start = None
    return found


def array_at(arrays, file: str, line: int) -> str | None:
    for rel, name, first, last in arrays:
        if rel == file and first <= line <= last:
            return name
    return None


def column_of(site) -> int | None:
    """Which comma-separated slot of its row this literal occupies."""
    row = site.context or ""
    inner = site.raw[1:-1] if site.raw[:1] in "\"'" else site.raw
    if not row or not inner:
        return None
    position = row.find(inner)
    if position < 0:
        return None
    return row[:position].count(",")


def columns(store, app_root: Path) -> dict[tuple[str, int], list]:
    """Group the ``code`` units by the (array, column) they were declared in."""
    arrays = find_arrays(app_root)
    grouped: dict[tuple[str, int], list] = {}
    for unit in store.all_units():
        if unit.kind != "code" or unit.en is None:
            continue
        site = unit.sites[0]
        name = array_at(arrays, site.file, site.line)
        column = column_of(site)
        if name is None or column is None:
            continue
        grouped.setdefault((name, column), []).append(unit)
    return grouped


#: Containers measured out of the layout macros rather than inferred.
#:
#: item name  itemstorage_sto2 indents the name by 8 nbsp, then draws the count
#:            after 19 nbsp and 7 full-width underscores - about 265px of room
#:            at 27px before the name runs under the underscore rule.
#: stat label status.ks draws the label and the number at the *same* x, with the
#:            number right-aligned in a 320px box, so the label has to clear it.
ITEM_BUDGET, ITEM_SIZE = 265, 27
STAT_BUDGET, STAT_SIZE = 295, 26

#: a stat row is ["label", <number>]; the same array also holds long prose in
#: other rows, and that prose is drawn somewhere else entirely
STAT_ROW_RE = re.compile(r'^\s*\["(?:[^"\\]|\\.)*",\s*-?\d+\s*\]')


def overflowing(store, app_root: Path):
    """``[(what, unit, width_px, budget_px, size)]`` for the fixed-column labels.

    Only the two columns whose container has actually been measured. Everything
    else in these tables is prose in a wide box, where a width bound derived from
    the widest sibling means nothing.
    """
    jobs = []
    seen: set[str] = set()
    for (name, column), units in columns(store, app_root).items():
        is_item = name.startswith(("f.item", "f.tansaku_item")) and column == 1
        is_stat = name == "f.koko_status" and column == 0
        if not (is_item or is_stat):
            continue
        what = "item name" if is_item else "stat label"
        budget, size = (ITEM_BUDGET, ITEM_SIZE) if is_item else (STAT_BUDGET, STAT_SIZE)
        for unit in units:
            if unit.id in seen or not unit.en:
                continue
            if is_stat and not STAT_ROW_RE.match(unit.sites[0].context or ""):
                continue
            width = layout.measure(codes.SENTINEL_RE.sub("", unit.en), size, app_root)
            if width > budget:
                jobs.append((what, unit, width, budget, size))
                seen.add(unit.id)
    jobs.sort(key=lambda job: (job[0], -job[2]))
    return jobs


def budgets(store, app_root: Path, headroom: float = 1.05, minimum: int = 3):
    """``[(array, column, units, budget_px, overflowing)]``, widest first.

    ``budget_px`` is the widest Japanese in that column plus a little headroom.
    Columns with fewer than ``minimum`` entries are skipped - one or two samples
    are not enough evidence of what the layout allows.
    """
    out = []
    for (name, column), units in columns(store, app_root).items():
        if len(units) < minimum:
            continue
        widest = max(layout.measure(codes.SENTINEL_RE.sub("", u.src), NOMINAL_SIZE, app_root)
                     for u in units)
        budget = widest * headroom
        over = [(layout.measure(codes.SENTINEL_RE.sub("", u.en), NOMINAL_SIZE, app_root), u)
                for u in units]
        over = sorted(((w, u) for w, u in over if w > budget), key=lambda t: -t[0])
        out.append((name, column, units, budget, over))
    out.sort(key=lambda row: -len(row[4]))
    return out
