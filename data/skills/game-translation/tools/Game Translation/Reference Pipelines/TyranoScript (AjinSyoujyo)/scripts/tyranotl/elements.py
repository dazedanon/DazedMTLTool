"""The engine's own element rules, from ``tyrano/plugins/kag/kag.parser.js``.

A TyranoScript save resumes by *element index* - an offset into the array a
scenario file parses to - and a macro is registered as ``{storage, index}`` into
the same array. So the element count of a file is part of its compatibility
surface: a patch that changes it moves every save and every macro after the
change. Answering "did this patch move anything" needs the engine's numbering,
not an approximation of it.

The rule that is easy to miss: inside ``[iscript]`` the parser stops treating
``[`` and ``]`` as tag delimiters, so each line of JavaScript becomes a single
``text`` element. ``exp.ks`` is mostly array literals, and a parser that splits
on brackets there invents hundreds of elements that do not exist.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Element:
    line: int          # 0-based, as the engine records it
    name: str
    val: str = ""


def parse(text: str) -> list[Element]:
    """Every element of a scenario, in the order the engine numbers them."""
    out: list[Element] = []
    in_comment = False
    in_script = False

    for number, row in enumerate(text.split("\n")):
        line = row.strip()
        first = line[:1]

        # the engine looks for the word anywhere on the line, not just as a tag
        if "endscript" in line:
            in_script = False

        if in_comment and line == "*/":
            in_comment = False
            continue
        if line == "/*":
            in_comment = True
            continue
        if in_comment or first == ";":
            continue
        if first == "#":
            out.append(Element(number, "chara_ptext", line))
            continue
        if first == "*":
            out.append(Element(number, "label", line))
            continue
        if first == "@":
            name = line[1:].split(" ")[0].strip()
            out.append(Element(number, name, line[1:]))
            if name == "iscript":
                in_script = True
            continue
        if first == "_":
            line = line[1:]

        buffer = tag = ""
        in_tag = False
        depth = 0
        for char in line:
            if in_tag:
                if char == "]" and not in_script:
                    depth -= 1
                    if depth == 0:
                        in_tag = False
                        name = tag.split(" ")[0].strip()
                        out.append(Element(number, name, tag))
                        if name == "iscript":
                            in_script = True
                        elif name == "endscript":
                            in_script = False
                        tag = ""
                    else:
                        tag += char
                elif char == "[" and not in_script:
                    depth += 1
                    tag += char
                else:
                    tag += char
            elif char == "[" and not in_script:
                depth += 1
                in_tag = True
                if buffer:
                    out.append(Element(number, "text", buffer))
                    buffer = ""
            else:
                buffer += char
        if buffer:
            out.append(Element(number, "text", buffer))
    return out


def read(path: Path) -> list[Element]:
    return parse(path.read_text(encoding="utf-8", errors="replace"))


def macros(elements: list[Element]) -> dict[str, int]:
    """``name -> element index`` for every ``[macro]``, as the engine registers it."""
    import re

    found: dict[str, int] = {}
    for index, element in enumerate(elements):
        if element.name != "macro":
            continue
        name = re.search(r"""\bname=("[^"]*"|'[^']*')""", element.val)
        if name:
            found[name.group(1)[1:-1]] = index
    return found


def shifts(new_root: Path, old_root: Path) -> list[tuple[str, int, int, int]]:
    """``[(file, old count, new count, macros moved)]`` for anything a patch moved.

    Saves resume by element index and macros are registered by element index, so
    a file whose element count changes breaks every save taken after the change
    and - if it defines macros - every macro defined after it. Run this against
    the build currently installed before shipping the next one: it is the
    difference between a layout tweak and a patch that voids everyone's saves.
    """
    moved = []
    for path in sorted(new_root.rglob("*.ks")):
        rel = path.relative_to(new_root).as_posix()
        previous = old_root / rel
        if not previous.exists():
            continue
        before, after = read(previous), read(path)
        if len(before) == len(after):
            continue
        was, now = macros(before), macros(after)
        drifted = sum(1 for name, at in was.items() if now.get(name, at) != at)
        moved.append((rel, len(before), len(after), drifted))
    return moved
