#!/usr/bin/env python3
"""
Extract Japanese string literals from a Unity IL2CPP global-metadata.dat.

BepInEx's Cpp2IL output stubs out string literals in the regenerated managed
DLL (every ldstr is empty), so we can't use Mono.Cecil. Instead we scan the
metadata file directly: walk byte-by-byte through valid UTF-8, treat
non-printable / invalid bytes as run terminators, and keep runs that
contain at least one Japanese character.

This is a heuristic dumper — not a parser. It captures the user-visible
string literal table cleanly because those literals sit back-to-back as
length-prefixed UTF-8 blobs (the length bytes break runs naturally).
False positives are rare; the JP filter at the end is strict.

Output: { "<japanese>": "" } JSON, mergeable with existing translations.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_META = Path(
    r"C:\Users\sw\Desktop\SheepClicker\SheepClicker_Data\il2cpp_data\Metadata\global-metadata.dat"
)
DEFAULT_OUT = Path(__file__).resolve().parent / "il2cpp_strings.json"

# CJK + kana + full-width punctuation. Match parse_text.py's filter.
JP_RE = re.compile(r"[぀-ゟ゠-ヿ一-鿿　-〿]")


def in_run(cp: int) -> bool:
    """Codepoints we consider valid 'inside a string'."""
    if cp == 0x09 or cp == 0x0A or cp == 0x0D:
        return True
    if 0x20 <= cp < 0x7F:
        return True
    # CJK / kana / full-width punctuation / halfwidth katakana
    if 0x3000 <= cp <= 0x9FFF:
        return True
    if 0xFF00 <= cp <= 0xFFEF:
        return True
    # rich text needs <, >, # etc. already covered by ASCII range above
    return False


def extract_jp_runs(data: bytes, min_chars: int = 1) -> list[str]:
    """Walk UTF-8 codepoints; emit each maximal printable run that contains JP."""
    out: list[str] = []
    seen: set[str] = set()
    buf: list[str] = []
    i = 0
    n = len(data)

    def flush() -> None:
        nonlocal buf
        if not buf:
            return
        s = "".join(buf).strip()
        buf = []
        if not s or len(s) < min_chars:
            return
        if not JP_RE.search(s):
            return
        if s in seen:
            return
        seen.add(s)
        out.append(s)

    while i < n:
        b = data[i]
        if b < 0x80:
            cp = b
            sz = 1
        elif b < 0xC2:  # continuation byte or invalid 2-byte start (overlong)
            flush()
            i += 1
            continue
        elif b < 0xE0:
            if i + 1 >= n:
                break
            b1 = data[i + 1]
            if (b1 & 0xC0) != 0x80:
                flush(); i += 1; continue
            cp = ((b & 0x1F) << 6) | (b1 & 0x3F)
            sz = 2
        elif b < 0xF0:
            if i + 2 >= n:
                break
            b1, b2 = data[i + 1], data[i + 2]
            if (b1 & 0xC0) != 0x80 or (b2 & 0xC0) != 0x80:
                flush(); i += 1; continue
            cp = ((b & 0x0F) << 12) | ((b1 & 0x3F) << 6) | (b2 & 0x3F)
            # surrogate halves are invalid in UTF-8
            if 0xD800 <= cp <= 0xDFFF:
                flush(); i += 1; continue
            sz = 3
        elif b < 0xF5:
            if i + 3 >= n:
                break
            b1, b2, b3 = data[i + 1], data[i + 2], data[i + 3]
            if ((b1 & 0xC0) != 0x80 or (b2 & 0xC0) != 0x80 or (b3 & 0xC0) != 0x80):
                flush(); i += 1; continue
            cp = (((b & 0x07) << 18) | ((b1 & 0x3F) << 12)
                  | ((b2 & 0x3F) << 6) | (b3 & 0x3F))
            if cp > 0x10FFFF:
                flush(); i += 1; continue
            sz = 4
        else:
            flush(); i += 1; continue

        if in_run(cp):
            buf.append(chr(cp))
            i += sz
        else:
            flush()
            i += sz

    flush()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", "-i", type=Path, default=DEFAULT_META,
                    help=f"path to global-metadata.dat (default: {DEFAULT_META})")
    ap.add_argument("--output", "-o", type=Path, default=DEFAULT_OUT,
                    help=f"output JSON (default: {DEFAULT_OUT})")
    ap.add_argument("--merge", action="store_true",
                    help="preserve existing translations in output")
    ap.add_argument("--min-chars", type=int, default=1,
                    help="drop strings shorter than N codepoints (default: 1)")
    args = ap.parse_args()

    if not args.input.is_file():
        print(f"not found: {args.input}", file=sys.stderr)
        return 1

    existing: dict[str, str] = {}
    if args.merge and args.output.exists():
        try:
            existing = json.loads(args.output.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"warning: could not load existing {args.output}: {e}", file=sys.stderr)

    data = args.input.read_bytes()
    runs = extract_jp_runs(data, min_chars=args.min_chars)

    out = {s: existing.get(s, "") for s in runs}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"scanned {len(data):,} bytes -> {len(out)} unique JP strings -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
