#!/usr/bin/env python3
"""Patch scenario speaker prefixes that should display in English.

The injector preserves original scenario speaker tokens such as `me:` and
Japanese names. The game displays `me` as the Japanese speaker name `自分`, so
this post-pass rewrites visible speaker prefixes in translated scenario text.
It also fixes a few common malformed `usa00` tags produced by machine output.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


PREFIX_REWRITES = {
    "me": "Me",
    "おっさん": "Old Man",
    "屋台のおっさん": "Stall Owner",
    "システム": "System",
    "道具屋さん": "Shopkeeper",
}

TAG_FIXES = {
    "usa0": "usa00",
    "usa": "usa00",
    "usaoO": "usa00",
}


PREFIX_RE = re.compile(r"^(?P<prefix>[^:#\s][^:]*?)(?P<colon>\s*:)")


def patch_line(line: str) -> tuple[str, bool]:
    if line[:1].isspace():
        return line, False

    match = PREFIX_RE.match(line)
    if not match:
        return line, False

    prefix = match.group("prefix")
    new_prefix = PREFIX_REWRITES.get(prefix)

    if new_prefix is None and "@" in prefix:
        name, suffix = prefix.split("@", 1)
        fixed_name = TAG_FIXES.get(name)
        if fixed_name is not None:
            new_prefix = f"{fixed_name}@{suffix}"

    if new_prefix is None or new_prefix == prefix:
        return line, False

    patched = new_prefix + line[match.start("colon") :]
    return patched, True


def patch_file(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    changed = 0
    out: list[str] = []
    for line in lines:
        body = line.rstrip("\r\n")
        newline = line[len(body) :]
        patched, did_change = patch_line(body)
        out.append(patched + newline)
        changed += int(did_change)

    if changed:
        path.write_text("".join(out), encoding="utf-8", newline="")
    return changed


def patch_tree(root: Path) -> dict[str, int]:
    report: dict[str, int] = {}
    for path in sorted(root.rglob("*.txt")):
        changed = patch_file(path)
        if changed:
            report[str(path.relative_to(root))] = changed
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Patch translated scenario speaker prefixes.")
    parser.add_argument("root", nargs="?", type=Path, default=Path("translated_assets") / "scenarios")
    args = parser.parse_args()

    report = patch_tree(args.root)
    for rel, count in report.items():
        sys.stdout.buffer.write(f"{rel}: {count}\n".encode("utf-8"))
    sys.stdout.buffer.write(f"patched files: {len(report)}\n".encode("utf-8"))
    sys.stdout.buffer.write(f"patched lines: {sum(report.values())}\n".encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
