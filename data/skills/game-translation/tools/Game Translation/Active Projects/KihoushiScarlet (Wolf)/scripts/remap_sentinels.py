#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
remap_sentinels.py - rewrite {Wn} tokens in a glossary source file from one
`mt-export` legend to another.

    python scripts/remap_sentinels.py tl/_sources/ui_terms.json \
        --from build/_old_batch.json --to batch.json

Why this exists. `wolf mt-export --sentinel-mask` numbers sentinels in the order
it meets them, so the numbering is a property of the FILE LIST, not of the game.
Adding `out/names.json` to the export re-ordered it: only 36 of 86 tokens kept
their meaning, and `{W49}` went from `\\i[126]` (an icon, never padded) to
`\\cself[34]` (a value insert, which English must put a space around).

A glossary written against the old numbering does not fail loudly. Its keys simply
stop matching the corpus, so the rules go silently unused - and any key that DOES
still match now teaches the model the wrong thing about that token. Remap by the
CODE the token stands for, never by the number.
"""

import os
import re
import sys
import json
import argparse

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN_RE = re.compile(r"\{W\d+\}")


def legend(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)["_sentinel_legend"]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", help="JSON file whose string values carry {Wn} tokens")
    ap.add_argument("--from", dest="src", required=True, help="batch.json it was written against")
    ap.add_argument("--to", dest="dst", required=True, help="batch.json it must match now")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    old, new = legend(args.src), legend(args.dst)
    rev = {}
    for tok, code in new.items():
        rev.setdefault(code, tok)
    mapping, unmapped = {}, []
    for tok, code in old.items():
        if code in rev:
            mapping[tok] = rev[code]
        else:
            unmapped.append((tok, code))

    moved = sum(1 for k, v in mapping.items() if k != v)
    print(f"legend: {len(old)} old, {len(new)} new -> {len(mapping)} mapped "
          f"({moved} change number), {len(unmapped)} unmappable")
    for tok, code in unmapped[:10]:
        print(f"  ! {tok} = {code!r} has no counterpart in the new legend")

    with open(args.target, encoding="utf-8") as f:
        doc = json.load(f)

    stats = {"rewritten": 0, "unknown": 0}

    def fix(s):
        def sub(m):
            t = m.group(0)
            if t in mapping:
                if mapping[t] != t:
                    stats["rewritten"] += 1
                return mapping[t]
            stats["unknown"] += 1
            return t
        return TOKEN_RE.sub(sub, s)

    def walk(o):
        if isinstance(o, str):
            return fix(o)
        if isinstance(o, list):
            return [walk(v) for v in o]
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        return o

    out = walk(doc)
    print(f"{args.target}: {stats['rewritten']} token occurrence(s) renumbered, "
          f"{stats['unknown']} left alone (not in the old legend)")
    if args.dry_run:
        print("dry run - nothing written")
        return 0
    with open(args.target, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("written")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
