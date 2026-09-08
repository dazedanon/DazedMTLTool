#!/usr/bin/env python3
"""Translate display-only scenario speaker prefixes.

Do not use this for engine/control speakers such as `me`, `usa00`, or `bg`.
Those are parser/game tokens. This pass is only for named NPC/system labels
that the scenario UI displays directly.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ROOT_DEFAULT = Path("translated_assets") / "scenarios"
REPORT_DEFAULT = Path("tooling") / "display_speaker_prefix_patch_report.json"

PREFIX_REWRITES = {
    "おっさん": "Old Man",
    "屋台のおっさん": "Stall Owner",
    "システム": "System",
    "道具屋さん": "Shopkeeper",
}

PREFIX_RE = re.compile(r"^(?P<prefix>[^:#\s][^:]*?)(?P<colon>\s*:)")


def patch_file(path: Path) -> list[dict[str, object]]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    changes: list[dict[str, object]] = []

    for line_number, line in enumerate(lines, start=1):
        body = line.rstrip("\r\n")
        newline = line[len(body) :]
        match = PREFIX_RE.match(body)
        if not match:
            out.append(line)
            continue

        prefix = match.group("prefix")
        replacement = PREFIX_REWRITES.get(prefix)
        if replacement is None:
            out.append(line)
            continue

        patched = replacement + body[match.start("colon") :] + newline
        out.append(patched)
        changes.append({"line": line_number, "from": prefix, "to": replacement})

    if changes:
        path.write_text("".join(out), encoding="utf-8", newline="")

    return changes


def patch_tree(root: Path) -> dict[str, list[dict[str, object]]]:
    report: dict[str, list[dict[str, object]]] = {}
    for path in sorted(root.rglob("*.txt")):
        changes = patch_file(path)
        if changes:
            report[path.relative_to(root).as_posix()] = changes
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=ROOT_DEFAULT)
    parser.add_argument("--report", type=Path, default=REPORT_DEFAULT)
    args = parser.parse_args()

    report = patch_tree(args.root)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"patched files: {len(report)}")
    print(f"patched prefixes: {sum(len(items) for items in report.values())}")
    print(f"report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
