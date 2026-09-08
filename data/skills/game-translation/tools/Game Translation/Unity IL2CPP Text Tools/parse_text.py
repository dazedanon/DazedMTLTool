#!/usr/bin/env python3
"""
Walk an AssetRipper-exported Unity project and extract Japanese strings from
TextMeshPro (m_text) and legacy UnityEngine.UI.Text (m_Text) components in
.unity / .prefab / .asset YAML files.

Output JSON shape:
    { "<japanese original>": "" }
Values are empty (translator fills them in). The runtime plugin loads this
file and uses it as a direct dict lookup.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_INPUT = Path(__file__).resolve().parent.parent / "ExportedProject" / "Assets"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "texts.json"

JP_RE = re.compile(r"[぀-ゟ゠-ヿ一-鿿　-〿]")

# matches: optional leading whitespace, m_text or m_Text, colon, value to EOL
# value group captures everything after the colon (incl. leading spaces)
TEXT_LINE_RE = re.compile(r"^\s*m_[Tt]ext:\s*(.*?)\s*$")

# YAML double-quoted escape sequences we care about. AssetRipper emits
# standard YAML double-quoted strings: \" \\ \n \r \t \uXXXX
_YAML_DQ_ESCAPES = {
    "\\": "\\",
    '"': '"',
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "0": "\0",
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "v": "\v",
    "/": "/",
}


def yaml_dq_unescape(s: str) -> str:
    """Decode a YAML double-quoted string body (no surrounding quotes)."""
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
    """Parse a single-line YAML scalar value. Returns None for empty."""
    if not raw:
        return None
    if raw.startswith('"'):
        # find matching closing quote (skip escaped \")
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
        # unterminated; bail
        return None
    if raw.startswith("'"):
        # YAML single-quoted; '' is escaped '
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
    # plain scalar
    return raw


def has_japanese(s: str) -> bool:
    return bool(s) and JP_RE.search(s) is not None


def extract_from_file(path: Path) -> list[str]:
    out: list[str] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    # quick reject: no m_text/m_Text token
    if "m_text:" not in text and "m_Text:" not in text:
        return out
    for line in text.splitlines():
        m = TEXT_LINE_RE.match(line)
        if not m:
            continue
        val = parse_yaml_value(m.group(1))
        if val is None:
            continue
        if has_japanese(val):
            out.append(val)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", "-i", type=Path, default=DEFAULT_INPUT,
                    help=f"Assets directory to scan (default: {DEFAULT_INPUT})")
    ap.add_argument("--output", "-o", type=Path, default=DEFAULT_OUTPUT,
                    help=f"output JSON path (default: {DEFAULT_OUTPUT})")
    ap.add_argument("--merge", action="store_true",
                    help="merge into existing output (preserve existing translations)")
    ap.add_argument("--exts", default=".unity,.prefab,.asset",
                    help="comma-separated extensions to scan")
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
    print(f"scanned {files_scanned} file(s), {files_with_hits} with JP m_text -> "
          f"{len(seen)} unique strings -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
