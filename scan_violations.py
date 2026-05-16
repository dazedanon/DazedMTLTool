#!/usr/bin/env python3
"""Scan a folder of JSON files and write violations.json listing every over-limit message.

Usage:
    python scan_violations.py [--folder FOLDER] [--output OUTPUT]

Defaults:
    --folder translated
    --output violations.json
"""

import json
import sys
import argparse
from pathlib import Path

MAX_LINES = 3
MAX_LINE_LEN = 60
NEWLINE = "\r\n"


def is_violation(text: str) -> bool:
    lines = text.split(NEWLINE)
    if len(lines) > MAX_LINES:
        return True
    return any(len(line) > MAX_LINE_LEN for line in lines)


def scan_folder(folder: Path) -> list[dict]:
    violations = []
    for f in sorted(folder.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"Warning: could not read {f.name}: {e}", file=sys.stderr)
            continue
        if not isinstance(data, list):
            continue
        for i, entry in enumerate(data):
            if not isinstance(entry, dict):
                continue
            m = entry.get("message")
            if isinstance(m, str) and is_violation(m):
                violations.append({"file": f.name, "index": i, "original": m})
    return violations


def main():
    parser = argparse.ArgumentParser(description="Scan JSON files for over-limit messages")
    parser.add_argument("--folder", default="translated", help="Folder to scan (default: translated)")
    parser.add_argument("--output", default="violations.json", help="Output file (default: violations.json)")
    args = parser.parse_args()

    folder = Path(args.folder)
    if not folder.exists():
        print(f"Error: folder '{folder}' does not exist", file=sys.stderr)
        sys.exit(1)

    violations = scan_folder(folder)

    Path(args.output).write_text(
        json.dumps(violations, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Found {len(violations)} violations → {args.output}")


if __name__ == "__main__":
    main()
