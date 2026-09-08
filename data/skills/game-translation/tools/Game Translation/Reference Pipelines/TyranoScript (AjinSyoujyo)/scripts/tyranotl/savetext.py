"""Static text the build owns, for saves that were written before it existed.

A TyranoScript save stores the whole of ``f``, and this game keeps its tables
there: ``f.task``, ``f.item`` and the rest are filled in from ``exp.ks`` when a
game is *started* and then travel with the save forever. Translate a name after
that and every existing save keeps the old one - which is why a finished task
still reads 完了したタスク in a save begun before that string was translated.

So the build's own copy of those strings ships alongside the patch, and
``save_compat.js`` writes them back over the save's copy as it loads. Only
fields that are purely display text are listed. A task name is also its own
jump target, so replacing one would send an old save to a label that does not
exist in its build - those stay exactly as the save has them.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

#: variable -> the field indices that are display text and nothing else.
#: f.task[0] is the name, [1] the text shown once complete, [7] the briefing;
#: [11] is the jump target and is deliberately absent. f.item[1] is the name,
#: while [3] is how many the player is holding - state, not text.
OWNED: dict[str, tuple[int, ...]] = {
    "task": (0, 1, 7),
    # a Nemo task's name IS its jump target - *ネモタスク1 is a real label - so
    # field 0 stays whatever the save has, or an old save jumps to a label its
    # own build never had
    "nemo_task": (1, 7),
    "item": (1,),
}

TABLE = re.compile(r"^[ 	]*f\.(\w+)\s*=\s*\[", re.M)


def _rows(text: str, start: int) -> list[str] | None:
    """The top-level rows of an array literal that opens at ``start``."""
    depth = 0
    quote = ""
    rows: list[str] = []
    current = ""
    index = start
    while index < len(text):
        char = text[index]
        if quote:
            current += char
            if char == "\\":
                if index + 1 < len(text):
                    current += text[index + 1]
                    index += 2
                    continue
            elif char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
            current += char
        elif char == "/" and text[index:index + 2] == "//":
            # a row comment sits between rows and would otherwise be swept into
            # the next one, which then no longer starts with its own bracket
            newline = text.find("\n", index)
            index = len(text) if newline < 0 else newline
            continue
        elif char == "[":
            depth += 1
            if depth > 1:
                current += char
        elif char == "]":
            depth -= 1
            if depth == 0:
                if current.strip():
                    rows.append(current)
                return rows
            current += char
        elif char == "," and depth == 1:
            if current.strip():
                rows.append(current)
            current = ""
        else:
            current += char
        index += 1
    return None


def _fields(row: str) -> list[str | None]:
    """A row's values in order; ``None`` where the value is not a string."""
    opened, closed = row.find("["), row.rfind("]")
    row = row[opened + 1:closed] if 0 <= opened < closed else row.strip()
    out: list[str | None] = []
    quote = ""
    current = ""
    literal = False
    depth = 0
    index = 0
    while index < len(row):
        char = row[index]
        if quote:
            if char == "\\" and index + 1 < len(row):
                current += row[index + 1]
                index += 2
                continue
            if char == quote:
                quote = ""
            else:
                current += char
        elif char in "\"'":
            quote = char
            literal = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
        elif char == "," and depth == 0:
            out.append(current if literal else None)
            current = ""
            literal = False
        index += 1
    out.append(current if literal else None)
    return out


def collect(scenario_root: Path) -> dict[str, dict[str, list[str | None]]]:
    """``{variable: {field: [value per row]}}`` for every owned field."""
    source = scenario_root / "system" / "exp.ks"
    if not source.exists():
        return {}
    text = source.read_text(encoding="utf-8", errors="replace")

    owned: dict[str, dict[str, list[str | None]]] = {}
    for match in TABLE.finditer(text):
        name = match.group(1)
        if name not in OWNED:
            continue
        rows = _rows(text, match.end() - 1)
        if rows is None:
            continue
        table: dict[str, list[str | None]] = {}
        for field in OWNED[name]:
            column = []
            for row in rows:
                values = _fields(row)
                column.append(values[field] if field < len(values) else None)
            if any(value is not None for value in column):
                table[str(field)] = column
        if table:
            owned[name] = table
    return owned


def build(scenario_root: Path) -> str:
    """The data file that ships with the patch."""
    data = collect(scenario_root)
    body = json.dumps(data, ensure_ascii=False, indent=1)
    return (
        "// Generated by tl.py - the build's own copy of the text that a save\n"
        "// keeps its own version of. save_compat.js writes it back on load.\n"
        "// Do not edit: regenerate with `tl.py deploy`.\n"
        "window.__saveText = " + body + ";\n"
    )
