#!/usr/bin/env python3
"""
Parse SheepClicker dialogue TextAsset CSV files into a translation JSON.

Each CSV row:
    SpeakerName,TalkText,LeftChara,RightChara,SETag,Command1,Command2,Command3

Only SpeakerName (col 0) and TalkText (col 1) are kept. Both are Japanese.
Output JSON shape:
    { "<japanese original>": "" }
Values are empty strings; a translator (or LLM) fills them in. The runtime
plugin loads this file and uses it as a direct dict lookup.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

DEFAULT_INPUT = Path(__file__).resolve().parent.parent / "ExportedProject" / "Assets" / "TextAsset"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "dialogues.json"

JP_RE = re.compile(r"[぀-ゟ゠-ヿ一-鿿　-〿＀-￯]")


def has_japanese(s: str) -> bool:
    return bool(s) and JP_RE.search(s) is not None


def extract_from_file(path: Path) -> list[str]:
    out: list[str] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if not header:
            return out
        # locate columns by name; fall back to indices 0/1
        name_idx = 0
        text_idx = 1
        for i, col in enumerate(header):
            c = col.strip()
            if c == "SpeakerName":
                name_idx = i
            elif c == "TalkText":
                text_idx = i
        for row in reader:
            if not row:
                continue
            speaker = row[name_idx].strip() if len(row) > name_idx else ""
            text = row[text_idx] if len(row) > text_idx else ""
            # CSV stores literal \n; preserve it for in-game match
            if has_japanese(speaker):
                out.append(speaker)
            if has_japanese(text):
                out.append(text)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", "-i", type=Path, default=DEFAULT_INPUT,
                    help=f"directory of dialogue *.txt files (default: {DEFAULT_INPUT})")
    ap.add_argument("--output", "-o", type=Path, default=DEFAULT_OUTPUT,
                    help=f"output JSON path (default: {DEFAULT_OUTPUT})")
    ap.add_argument("--merge", action="store_true",
                    help="merge into existing output (preserve existing translations)")
    args = ap.parse_args()

    if not args.input.is_dir():
        print(f"input directory not found: {args.input}", file=sys.stderr)
        return 1

    existing: dict[str, str] = {}
    if args.merge and args.output.exists():
        try:
            existing = json.loads(args.output.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"warning: could not read existing {args.output}: {e}", file=sys.stderr)

    seen: dict[str, str] = {}
    files_count = 0
    for path in sorted(args.input.glob("*.txt")):
        files_count += 1
        for s in extract_from_file(path):
            if s not in seen:
                seen[s] = existing.get(s, "")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(seen, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"parsed {files_count} CSV file(s) -> {len(seen)} unique strings -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
