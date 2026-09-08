#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
skilltree_config.py - the `js/plugins/SkillTreeConfig.js` track.

A THIRD track, separate from both `data/*.json` and `js/plugins.js`: this is a
hand-written JS config file the SkillTree plugin reads directly, and nothing
else in the pipeline touches it. It holds the skill-tree tab labels and the
help line under them, which shipped in Japanese over an otherwise English
screen.

The shape that matters:

    skillTreeTypes: [
      { actorId: 1,
        types: [
          ["攻撃魔法", "攻撃魔法",     "攻撃魔法を取得します。",   true, 79],
          ["回復魔法", "回復,防御魔法", "回復、防御魔法を取得します。", true, 72],
          ["剣技",    "パッシブ",     "パッシブスキルを取得します。", true, 76],
        ]}, ... ]

    [0] the TYPE KEY.  `skt_learn(actorId, typeName, ...)`,
        `skt_enableType` and `skt_disableType` all match it with
        `types.find(t => t.skillTreeName() === typeName)` - SkillTree.js:429,
        440, 452. Translating it breaks every skill unlock in the game, with
        no error.
    [1] the TAB LABEL.      drawn.
    [2] the HELP LINE.      drawn under the tree.

The third row proves [0] and [1] are independent: the key is `剣技`
("swordplay") while the tab reads `パッシブ` ("passive").

Node names in `skillTreeInfo` are NOT touched either - `drawText(skill.name...)`
(SkillTree.js:1931) draws the name out of `$dataSkills`, which the main
pipeline already translated, so the strings here are only lookup keys.

Writing is a span splice on the exact quoted literal, so every byte outside the
two translated fields is preserved. `--check` proves the round trip.

    python tools/skilltree_config.py --report
    python tools/skilltree_config.py --apply
"""

import os
import re
import sys
import shutil
import datetime
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from mztl import codes, config  # noqa: E402

# Only the two DISPLAY fields of a `types:` row. Anchored on the whole row so a
# bare `"攻撃魔法"` appearing anywhere else in the file cannot match.
ROW_RE = re.compile(
    r"""\[\s*
        (?P<q0>["'])(?P<key>(?:\\.|(?!(?P=q0)).)*)(?P=q0)\s*,\s*
        (?P<q1>["'])(?P<label>(?:\\.|(?!(?P=q1)).)*)(?P=q1)\s*,\s*
        (?P<q2>["'])(?P<help>(?:\\.|(?!(?P=q2)).)*)(?P=q2)\s*,\s*
        (?:true|false)\s*,\s*\d+\s*,?\s*\]""",
    re.VERBOSE)

# Chosen against the tab window, which SkillTree draws at a fixed width on the
# right of the screen; the longest Japanese tab is `回復,防御魔法` (6 glyphs).
TRANSLATIONS = {
    # tab labels
    "攻撃魔法": "Attack Magic",
    "回復,防御魔法": "Healing / Defense",
    "回復魔法": "Healing Magic",
    "パッシブ": "Passive",
    "剣技": "Swordplay",
    "格闘技": "Martial Arts",
    # help lines
    "攻撃魔法を取得します。": "Learn attack magic.",
    "回復、防御魔法を取得します。": "Learn healing and defensive magic.",
    "回復魔法を取得します。": "Learn healing magic.",
    "パッシブスキルを取得します。": "Learn passive skills.",
    "剣技を取得します。": "Learn sword skills.",
    "格闘技を取得します。": "Learn martial arts.",
}


def path_of(cfg):
    return os.path.join(cfg.js_dir, "plugins", "SkillTreeConfig.js")


def rows(text):
    return list(ROW_RE.finditer(text))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args(argv)

    cfg = config.Config()
    p = path_of(cfg)
    if not os.path.exists(p):
        sys.exit("not found: %s" % p)
    text = open(p, encoding="utf-8").read()

    ms = rows(text)
    print("skill-tree type rows: %d" % len(ms))
    missing, edits = [], []
    for m in ms:
        for field in ("label", "help"):
            val = m.group(field)
            if not codes.has_jp(val):
                continue
            en = TRANSLATIONS.get(val)
            if en is None:
                missing.append(val)
                continue
            edits.append((m.start(field), m.end(field), val, en, field))

    seen = set()
    for m in ms:
        k = (m.group("key"), m.group("label"), m.group("help"))
        if k in seen:
            continue
        seen.add(k)
        if a.report:
            print("   key %-14r  tab %-16r -> %-20r  help %r -> %r"
                  % (k[0][:12], k[1][:14], TRANSLATIONS.get(k[1], "?"),
                     k[2][:20], TRANSLATIONS.get(k[2], "?")))

    if missing:
        print("\n!! %d display string(s) with no translation - add them to "
              "TRANSLATIONS before applying:" % len(set(missing)))
        for v in sorted(set(missing)):
            print("     %r" % v)
        return 1

    print("  fields to rewrite: %d" % len(edits))
    if not a.apply:
        print("\ndry run - pass --apply to write")
        return 0

    # Span splice, right to left so earlier offsets stay valid.
    out = text
    for start, end, val, en, _f in sorted(edits, key=lambda e: -e[0]):
        assert out[start:end] == val, "span moved - refusing to write"
        out = out[:start] + en + out[end:]

    # The splice must not have disturbed the structure around it.
    if len(rows(out)) != len(ms):
        sys.exit("row count changed after the splice - nothing written")
    # And every KEY must be byte-identical, since that is what breaks the game.
    if [m.group("key") for m in rows(out)] != [m.group("key") for m in ms]:
        sys.exit("a type KEY changed - nothing written")

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = p + ".bak_" + stamp
    if not os.path.exists(bak):
        shutil.copy2(p, bak)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(out)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)
    print("wrote %d field(s) (backup: %s)" % (len(edits), os.path.basename(bak)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
