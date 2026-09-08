#!/usr/bin/env python3
"""Enumerate the Addressables addresses that become dropdown labels at runtime.

VoiceFaceOverrideController builds the voice dropdown by taking each loaded
clip's Addressables ADDRESS and passing it to GetBaseSituationName (RVA
0x795200), which returns the substring before whichever of 喘ぎ / 絶頂 / 余韻 it
finds. That prefix is what the player sees.

The addresses live in StreamingAssets/aa/catalog.bin as length-prefixed
**UTF-16LE** - a UTF-8 scan of that file returns zero Japanese, which is exactly
why this pool looked unknowable and got deferred to the runtime harvester.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hitonatsu import common as C  # noqa: E402

CATALOG = os.path.join(C.GAME, "Hitonatsu_Data", "StreamingAssets", "aa", "catalog.bin")

# The three markers GetBaseSituationName truncates at, in its own order.
MARKERS = ("喘ぎ", "絶頂", "余韻")


# A "readable" run: ASCII printable, kana, CJK, fullwidth forms, common marks.
RUN_RE = re.compile(r"[ -~　-ヿ㐀-鿿！-ﾟ]{2,}")


def utf16_strings(blob: bytes, min_len: int = 2) -> list[str]:
    """Every readable UTF-16LE run, decoded at BOTH byte parities.

    Hand-walking the blob and guessing where a string starts gets the alignment
    wrong one byte in two, which silently turns `ogg` (6F 00 67 00 67 00) into
    `漀最最` - CJK-looking mojibake that passes a Japanese test and poisons the
    result. Decoding the whole blob at each parity and pulling readable runs out
    of the text cannot make that mistake.
    """
    seen: list[str] = []
    for parity in (0, 1):
        text = blob[parity:].decode("utf-16-le", errors="replace")
        seen.extend(m.group(0) for m in RUN_RE.finditer(text)
                    if len(m.group(0)) >= min_len)
    return seen


def base_situation_name(address: str) -> str:
    """Reimplements GetBaseSituationName (RVA 0x795200)."""
    for m in MARKERS:
        k = address.find(m)
        if k >= 0:
            return address[:k]
    return address


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--catalog", default=CATALOG)
    ap.add_argument("--json", action="store_true", help="emit a {jp: ''} stub")
    args = ap.parse_args()

    blob = open(args.catalog, "rb").read()
    runs = utf16_strings(blob)
    jp = sorted({s for s in runs if C.has_jp(s)})

    print(f"catalog.bin: {len(blob):,} bytes, {len(runs):,} UTF-16LE runs, "
          f"{len(jp)} containing Japanese\n")
    for s in jp:
        print(f"  {s!r}")

    labels = sorted({base_situation_name(s) for s in jp if any(m in s for m in MARKERS)})
    print(f"\nDropdown labels GetBaseSituationName would produce ({len(labels)}):")
    for s in labels:
        print(f"  {s!r}")

    if args.json:
        out = os.path.join(C.WORKSPACE, "catalog_labels.json")
        json.dump({s: "" for s in labels}, open(out, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"\n-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
