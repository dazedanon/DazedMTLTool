#!/usr/bin/env python3
"""Validate the translated units. Exit non-zero on any hard failure.

Each check exists because of a specific way this game can ship broken:

  font-coverage   The TMP atlas is STATIC (m_AtlasPopulationMode: 0) with 7,129
                  baked glyphs and an EMPTY fallback table. A character outside
                  that set draws as nothing. Full ASCII is covered, so this only
                  ever fires on a typographic flourish - which is exactly the
                  kind of thing that slips in unnoticed.
  placeholders    Checked on the RESTORED string the engine will actually parse,
                  not on the masked form the model saw.
  same-source     One Japanese string translated two different ways. The delivery
                  is a dictionary keyed on the source, so a conflict means one of
                  the two silently wins everywhere.
  parallel-drift  Entries that are parallel by construction (Override01..06) that
                  drifted apart. Masking the varying index and grouping on the
                  remainder finds these; a same-source check cannot.
  residual-jp     Any Japanese left in an English string.
  brackets        The protagonist's lines are marked by fullwidth 「 」. Losing
                  them reattributes the line to the heroine.
  expansion       Reports how much longer the English is than the Japanese it
                  replaces. Purely informational: it bears on whether a line
                  still fits its box, NOT on lip sync. FacialLipSync's
                  character-count timing looks relevant and is not - both scene
                  instances serialize textUIName empty, so that code path never
                  runs and lip sync is driven by audio amplitude instead.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hitonatsu import common as C  # noqa: E402

FONT = os.path.join(C.WORKSPACE, "font_coverage.json")
OVERRIDES = os.path.join(C.WORKSPACE, "overrides.json")
DIGITS = re.compile(r"\d+")


def check(units: list[dict]) -> tuple[list[str], list[str]]:
    hard: list[str] = []
    soft: list[str] = []

    font = json.load(open(FONT, encoding="utf-8"))
    covered = set(font["codepoints"])

    # Hand rulings win, and QA must see the same text the build ships or it
    # reports conflicts the player will never meet.
    overrides = {}
    if os.path.exists(OVERRIDES):
        overrides = {k: v["en"] for k, v in json.load(open(OVERRIDES, encoding="utf-8")).items()
                     if not k.startswith("_")}

    translated = [u for u in units if u.get("tl")]
    for u in translated:
        if u["src"] in overrides:
            u["tl"] = overrides[u["src"]]

    for u in translated:
        tl = u["tl"]

        # Control characters are layout, not glyphs - the atlas never contains
        # them and TMP never asks it to. Flagging them accused every multi-line
        # label in the game of being unrenderable.
        missing = sorted({ch for ch in tl
                          if ord(ch) >= 0x20 and ord(ch) not in covered})
        if missing:
            hard.append(
                f"font-coverage {u['id']}: {''.join(missing)!r} "
                f"({', '.join('U+%04X' % ord(c) for c in missing)}) not in the atlas -> "
                f"draws blank. {tl!r}")

        if C.has_jp(tl):
            hard.append(f"residual-jp {u['id']}: {tl!r}")

        if C.placeholders(u["masked"]) != C.placeholders(C.mask(tl)[0]):
            # Compare against the masked source: tl is already unmasked, so mask
            # it back the same way to line the sentinel multisets up.
            src_codes = list((u.get("codes") or {}).values())
            tl_codes = list(C.mask(tl)[1].values())
            if sorted(src_codes) != sorted(tl_codes):
                hard.append(
                    f"placeholders {u['id']}: source has {sorted(src_codes)}, "
                    f"translation has {sorted(tl_codes)}")

        if "「" in u["src"] and "「" not in tl:
            hard.append(f"brackets {u['id']}: protagonist line lost its 「 」. {tl!r}")

        if u["kind"] == "dialogue":
            u["_ratio"] = len(tl) / max(1, len(u["src"]))

    # same-source conflicts
    by_src: dict[str, set[str]] = defaultdict(set)
    for u in translated:
        by_src[u["src"]].add(u["tl"])
    for src, tls in by_src.items():
        if len(tls) > 1:
            hard.append(f"same-source {src!r} has {len(tls)} translations: "
                        f"{sorted(tls)}")

    # parallel-construction drift: mask the varying index, group on the remainder
    groups: dict[str, list[dict]] = defaultdict(list)
    for u in translated:
        groups[DIGITS.sub("#", u["src"])].append(u)
    for key, members in groups.items():
        if len(members) < 2 or key == DIGITS.sub("#", members[0]["src"]) == members[0]["src"]:
            continue
        shapes = {DIGITS.sub("#", m["tl"]) for m in members}
        if len(shapes) > 1:
            soft.append(
                f"parallel-drift {key!r}: {len(members)} parallel entries produced "
                f"{len(shapes)} different shapes: " +
                "; ".join(f"{m['src']} -> {m['tl']}" for m in members))

    # How far the English runs past the Japanese. This decides whether a line
    # still fits its widget - and nothing else. It is deliberately NOT tied to
    # FacialLipSync: that component does size mouth time by character count, but
    # both scene instances ship with textUIName empty, GameObject.Find("")
    # returns null, and the whole text-driven path is dead. Lip sync runs off
    # audio amplitude and does not care how long the subtitle is.
    ratios = sorted(u["_ratio"] for u in translated if "_ratio" in u)
    if ratios:
        median = ratios[len(ratios) // 2]
        worst = [u for u in translated if u.get("_ratio", 0) > median * 1.8]
        soft.append(
            f"expansion: {len(ratios)} dialogue lines run {ratios[0]:.1f}x - "
            f"{ratios[-1]:.1f}x the Japanese, median {median:.2f}x. That is normal "
            f"for this language pair. {len(worst)} line(s) exceed "
            f"{median * 1.8:.1f}x and are the ones to eyeball for overflow:")
        for u in worst:
            soft.append(f"    {u['id']} {u['_ratio']:.1f}x  {u['src']!r} -> {u['tl']!r}")

    return hard, soft


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--units", default=C.UNITS)
    ap.add_argument("--strict", action="store_true",
                    help="treat soft findings as failures too")
    args = ap.parse_args()

    doc = json.load(open(args.units, encoding="utf-8"))
    units = doc["units"]
    translated = [u for u in units if u.get("tl")]
    hard, soft = check(units)

    print(f"units: {len(units)}  translated: {len(translated)}  "
          f"untranslated: {len(units) - len(translated)}")
    print(f"hard failures: {len(hard)}   soft findings: {len(soft)}\n")

    for line in hard:
        print("FAIL  " + line)
    if hard and soft:
        print()
    for line in soft:
        print("WARN  " + line)

    if len(translated) < len(units):
        print(f"\nFAIL  coverage: {len(units) - len(translated)} units still have no "
              f"translation")
        return 1
    if hard:
        return 1
    if soft and args.strict:
        return 1
    print("\nall hard checks passed" + (f" ({len(soft)} warnings)" if soft else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
