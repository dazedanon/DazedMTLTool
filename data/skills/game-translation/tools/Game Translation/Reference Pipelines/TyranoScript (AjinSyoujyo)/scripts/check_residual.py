#!/usr/bin/env python3
"""Japanese still reaching the screen in the injected tree.

Run after every `tl.py inject`, and especially after taking a new game build:
an update adds strings that no earlier pass ever saw.

Only counts text the player reads. Labels, jump targets and the names of
`[macro]`/`[iscript]` identifiers are engine keys and are meant to stay as they
are, and a `//` or `;` comment is never drawn.

    python tools/scripts/check_residual.py [tree]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tyranotl import codes  # noqa: E402

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else "tools/translated/data/scenario")

#: attributes whose value is drawn
SHOWN = ("text", "name1", "name2", "caption", "title")

ISCRIPT = re.compile(r"\[(i?script)\]|\[end(?:script)\]")


def visible_japanese(line: str, in_script: bool) -> list[tuple[str, str]]:
    stripped = line.strip()
    if not stripped or stripped[0] in (";", "*", "@"):
        return []
    if in_script:
        # inside [iscript] the only drawn text is a string literal, and the
        # comments are thick with Japanese the player never sees
        code = line.split("//", 1)[0]
        return [("iscript literal", m.group(1)) for m in
                re.finditer(r"['\"]([^'\"]*)['\"]", code)
                if codes.has_jp(m.group(1))]

    out: list[tuple[str, str]] = []
    if not stripped.startswith("["):
        bare = codes.TAG_RE.sub("", stripped)
        if codes.has_jp(bare):
            out.append(("message", bare))
        return out

    for match in codes.TAG_RE.finditer(line):
        tag = match.group()
        for name in SHOWN:
            found = re.search(rf'\b{name}="([^"]*)"', tag)
            if found and codes.has_jp(found.group(1)):
                out.append((f"{match.group(1)} {name}=", found.group(1)))
    return out


def main() -> int:
    total = 0
    for path in sorted(ROOT.rglob("*.ks")):
        rows = []
        in_script = False
        for number, line in enumerate(
                path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            marker = ISCRIPT.search(line)
            for where, text in visible_japanese(line, in_script):
                rows.append((number, where, text[:78]))
            if marker:
                in_script = marker.group(1) is not None
        if rows:
            total += len(rows)
            print(f"== {path.relative_to(ROOT).as_posix()}")
            for number, where, text in rows[:8]:
                print(f"   line {number:<5} {where:22} {text}")
            if len(rows) > 8:
                print(f"   ... and {len(rows) - 8} more")
    print(f"\nvisible Japanese strings: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
