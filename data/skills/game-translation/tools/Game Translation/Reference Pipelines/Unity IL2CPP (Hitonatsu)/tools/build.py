#!/usr/bin/env python3
"""Emit the plugin's translation payload from workspace/units.json.

Delivery is a runtime dictionary, so the payload is plain {japanese: english}
keyed on the exact string the engine sets. Files are numbered to fix load order;
later files win, so 99_overrides.json is the last word.

The build refuses to run on a store that has not passed tools/qa.py, because
packaging packages what it is given and a green gate on stale input is the
easiest way to ship the previous build with every check passing.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hitonatsu import common as C  # noqa: E402

OVERRIDES = os.path.join(C.WORKSPACE, "overrides.json")
DEFAULT_OUT = os.path.join(C.PROJECT, "plugin", "HitonatsuTL", "translations")

# kind -> payload file. Numbered because the plugin loads them in name order and
# a later file overwrites an earlier key.
FILES = {
    "dialogue": "00_dialogue.json",
    "choice": "00_dialogue.json",
    "ui": "10_ui.json",
    "dropdown": "20_dropdown.json",
    "literal": "30_literal.json",
    "voice": "25_voice.json",
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--skip-qa", action="store_true",
                    help="build without re-running tools/qa.py (do not use for a release)")
    args = ap.parse_args()

    if not args.skip_qa:
        qa = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qa.py")
        r = subprocess.run([sys.executable, qa], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if r.returncode != 0:
            sys.stdout.write(r.stdout)
            sys.stderr.write(r.stderr)
            raise SystemExit("qa.py failed - refusing to build. Fix the findings, or "
                             "pass --skip-qa if you know what you are doing.")

    doc = json.load(open(C.UNITS, encoding="utf-8"))
    overrides = {}
    if os.path.exists(OVERRIDES):
        overrides = {k: v["en"]
                     for k, v in json.load(open(OVERRIDES, encoding="utf-8")).items()
                     if not k.startswith("_")}

    payload: dict[str, dict[str, str]] = {name: {} for name in set(FILES.values())}
    payload["99_overrides.json"] = {}
    conflicts = []

    for u in doc["units"]:
        en = u.get("tl")
        if not en:
            continue
        fname = FILES.get(u["kind"])
        if fname is None:
            raise SystemExit(f"unit {u['id']} has kind {u['kind']!r} with no payload file")
        bucket = payload[fname]
        # An overridden source is settled by the ruling in overrides.json, so it
        # is not a conflict any more - only report the ones nobody has ruled on.
        if (u["src"] in bucket and bucket[u["src"]] != en
                and u["src"] not in overrides):
            conflicts.append((u["src"], bucket[u["src"]], en))
        bucket[u["src"]] = overrides.get(u["src"], en)

    for src, en in overrides.items():
        payload["99_overrides.json"][src] = en

    if conflicts:
        for src, a, b in conflicts:
            print(f"CONFLICT {src!r}: {a!r} vs {b!r}")
        raise SystemExit(f"{len(conflicts)} same-source conflicts - resolve them in "
                         f"workspace/overrides.json first")

    os.makedirs(args.out, exist_ok=True)
    total = 0
    for fname in sorted(payload):
        data = payload[fname]
        path = os.path.join(args.out, fname)
        if not data:
            if os.path.exists(path):
                os.remove(path)
            continue
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
        total += len(data)
        print(f"  {len(data):>4}  {fname}")

    print(f"\n{total} entries -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
