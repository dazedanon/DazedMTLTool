#!/usr/bin/env python3
"""
Extract dialogue/bubble strings stored as YAML list items inside
MonoBehaviour-serialized arrays in scenes/prefabs/assets.

These don't appear in m_text (they're consumed at runtime by game scripts that
push them into TMP), so parse_text.py misses them. Patterns we catch:

    bubbleMessages:
    - charaID: 0
      messages:
      - "あっ・・・教主様\\nこんなところで・・・っ"

We grab any YAML scalar value — keyed (`foo: value`) or list-item (`- value`) —
that contains Japanese characters. The JP filter is the only filter; engine
config strings are English and won't trigger.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_INPUT = Path(__file__).resolve().parent.parent / "ExportedProject" / "Assets"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "messages.json"

JP_RE = re.compile(r"[぀-ゟ゠-ヿ一-鿿　-〿]")


def is_real_text(s: str) -> bool:
    """Reject TMP fallback character-range tables (mix many scripts)."""
    if len(s) > 4000:
        return False
    for c in s:
        cp = ord(c)
        if cp in (0x09, 0x0A, 0x0D):
            continue
        if 0x20 <= cp < 0x7F:
            continue
        if 0x3000 <= cp <= 0x9FFF:
            continue
        if 0x3400 <= cp <= 0x4DBF:
            continue
        if 0xFF00 <= cp <= 0xFFEF:
            continue
        if cp in (0xA0, 0xAD):
            continue
        return False
    return True


# captures key+value scalar OR list-item value
LINE_RE = re.compile(r"^\s*(?:[\w][\w.\-]*:\s*|-\s+)(.+?)\s*$")

_YAML_DQ_ESCAPES = {
    "\\": "\\", '"': '"', "n": "\n", "r": "\r", "t": "\t",
    "0": "\0", "a": "\a", "b": "\b", "f": "\f", "v": "\v", "/": "/",
}


def yaml_dq_unescape(s: str) -> str:
    out: list[str] = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n:
            nxt = s[i + 1]
            if nxt == "u" and i + 5 < n:
                try:
                    out.append(chr(int(s[i + 2 : i + 6], 16)))
                    i += 6
                    continue
                except ValueError:
                    pass
            if nxt == "x" and i + 3 < n:
                try:
                    out.append(chr(int(s[i + 2 : i + 4], 16)))
                    i += 4
                    continue
                except ValueError:
                    pass
            out.append(_YAML_DQ_ESCAPES.get(nxt, nxt))
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def parse_yaml_value(raw: str) -> str | None:
    if not raw:
        return None
    if raw.startswith('"'):
        i = 1
        n = len(raw)
        while i < n:
            c = raw[i]
            if c == "\\":
                i += 2
                continue
            if c == '"':
                return yaml_dq_unescape(raw[1:i])
            i += 1
        return None
    if raw.startswith("'"):
        i = 1
        n = len(raw)
        buf: list[str] = []
        while i < n:
            c = raw[i]
            if c == "'":
                if i + 1 < n and raw[i + 1] == "'":
                    buf.append("'")
                    i += 2
                    continue
                return "".join(buf)
            buf.append(c)
            i += 1
        return None
    return raw


def has_japanese(s: str) -> bool:
    return bool(s) and JP_RE.search(s) is not None


def extract_from_file(path: Path) -> list[str]:
    out: list[str] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        # drop YAML lines that are clearly references, not text
        if "guid:" in line or "fileID:" in line:
            continue
        m = LINE_RE.match(line)
        if not m:
            continue
        val = parse_yaml_value(m.group(1))
        if val is None:
            continue
        if not has_japanese(val):
            continue
        if not is_real_text(val):
            continue
        out.append(val)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", "-i", type=Path, default=DEFAULT_INPUT)
    ap.add_argument("--output", "-o", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--merge", action="store_true")
    ap.add_argument("--exts", default=".unity,.prefab,.asset")
    args = ap.parse_args()

    if not args.input.is_dir():
        print(f"input directory not found: {args.input}", file=sys.stderr)
        return 1

    exts = {e.strip().lower() for e in args.exts.split(",") if e.strip()}

    existing: dict[str, str] = {}
    if args.merge and args.output.exists():
        try:
            existing = json.loads(args.output.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"warning: could not read existing {args.output}: {e}", file=sys.stderr)

    seen: dict[str, str] = {}
    files_scanned = 0
    files_with_hits = 0
    for path in args.input.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in exts:
            continue
        files_scanned += 1
        strings = extract_from_file(path)
        if strings:
            files_with_hits += 1
        for s in strings:
            if s not in seen:
                seen[s] = existing.get(s, "")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(seen, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"scanned {files_scanned} file(s), {files_with_hits} with JP messages -> "
          f"{len(seen)} unique strings -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
