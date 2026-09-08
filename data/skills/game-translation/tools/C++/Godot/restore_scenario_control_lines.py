#!/usr/bin/env python3
"""Restore non-dialogue scenario control lines after machine translation.

Scenario files mix visible dialogue with engine commands such as:

    usa00:
      body: ひろげ
      手袋: なし

Those command labels/values are asset keys. If they are translated, pose and
visibility lookups fail. This pass copies only command-like lines back from the
original extracted scenarios while leaving translated dialogue/narration intact.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ORIGINAL_DEFAULT = Path("unpacked_pck") / "assets" / "scenarios"
TRANSLATED_DEFAULT = Path("translated_assets") / "scenarios"
REPORT_DEFAULT = Path("tooling") / "scenario_control_restore_report.json"

LINE_RE = re.compile(r"^(?P<indent>\s*)(?P<key>[^:\uff1a]+)(?P<colon>\s*[:\uff1a]\s*)(?P<payload>.*)$")
DIRECTIVE_KEYS = {
    "area_\u53e3",
    "bg",
    "bgm",
    "body",
    "camera_focus",
    "cg",
    "flash",
    "posure",
    "se",
    "\u4e0a\u7740",
    "\u4e0a\u8155",
    "\u53e3",
    "\u53f3\u624b",
    "\u53f3\u811a",
    "\u5de6\u624b",
    "\u5de6\u811a",
    "\u624b\u888b",
    "\u767a\u60c5",
    "\u76ee",
    "\u30ad\u30e3\u30df",
}


def split_newline(line: str) -> tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n"):
        return line[:-1], "\n"
    if line.endswith("\r"):
        return line[:-1], "\r"
    return line, ""


def is_control_line(original_body: str) -> bool:
    match = LINE_RE.match(original_body)
    if not match:
        return False

    indent = match.group("indent")
    key = match.group("key").strip()
    payload = match.group("payload").strip()

    if indent:
        return True
    if not payload:
        return True
    return key in DIRECTIVE_KEYS or key.startswith("area_")


def restore_file(original_path: Path, translated_path: Path) -> list[dict[str, str | int]]:
    original_lines = original_path.read_text(encoding="utf-8-sig").splitlines(keepends=True)
    translated_lines = translated_path.read_text(encoding="utf-8-sig").splitlines(keepends=True)
    if len(original_lines) != len(translated_lines):
        raise ValueError(
            f"Line count mismatch for {translated_path}: "
            f"{len(original_lines)} original vs {len(translated_lines)} translated"
        )

    changes: list[dict[str, str | int]] = []
    output = list(translated_lines)
    for index, original_line in enumerate(original_lines):
        original_body, _original_newline = split_newline(original_line)
        if not is_control_line(original_body):
            continue
        if translated_lines[index] == original_line:
            continue

        old_body, _old_newline = split_newline(translated_lines[index])
        output[index] = original_line
        changes.append({"line": index + 1, "from": old_body, "to": original_body})

    if changes:
        translated_path.write_text("".join(output), encoding="utf-8", newline="")

    return changes


def restore_tree(original_root: Path, translated_root: Path) -> dict[str, list[dict[str, str | int]]]:
    report: dict[str, list[dict[str, str | int]]] = {}
    for original_path in sorted(original_root.rglob("*.txt")):
        rel = original_path.relative_to(original_root)
        translated_path = translated_root / rel
        if not translated_path.exists():
            raise FileNotFoundError(f"Missing translated scenario: {translated_path}")
        changes = restore_file(original_path, translated_path)
        if changes:
            report[rel.as_posix()] = changes
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Restore scenario control lines from original assets.")
    parser.add_argument("--original-root", type=Path, default=ORIGINAL_DEFAULT)
    parser.add_argument("--translated-root", type=Path, default=TRANSLATED_DEFAULT)
    parser.add_argument("--report", type=Path, default=REPORT_DEFAULT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = restore_tree(args.original_root, args.translated_root)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("patched files:", len(report))
    print("restored lines:", sum(len(changes) for changes in report.values()))
    print("report:", args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
