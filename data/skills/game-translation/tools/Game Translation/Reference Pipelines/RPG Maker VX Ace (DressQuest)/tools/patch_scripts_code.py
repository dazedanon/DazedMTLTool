#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""patch_scripts_code.py - anchored CODE patches to Scripts.rvdata2.

The string ledger (`tl/scripts_rb.json`) can only swap one quoted literal for
another. Some defects are in the Ruby itself, so they need a separate, equally
paranoid path: exact anchor match, only the edited sections recompressed, a
timestamped backup, and a read-back that proves every section is exactly what
was intended.

Patches are defined as LISTS OF LINES, never as one blob with embedded
newlines: this game's script sections use CRLF, and an anchor built with LF
silently matches nothing.

Idempotent - a patch whose `new` is already present and whose `old` is gone is
reported as applied and skipped, so this is safe to re-run before every release.
"""

import io
import os
import sys
import zlib
import shutil
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from acetl import config, scripts_rb                       # noqa: E402
from acetl import rvmarshal as M                           # noqa: E402


PATCHES = [
    {
        "section": "\u56de\u60f3",
        "name": "usable_event?-returns-p",
        "why": (
            "The recollection gallery is empty on any Ruby whose `p` returns "
            "nil. `usable_event?` has no explicit return on its success path, "
            "so the method's value is the value of the trailing `if add_event` "
            "branch - which ends in `p debug`. Desktop RGSS3 (Ruby 1.9.2) "
            "returns the argument from `p`, so it happens to work; JoiPlay "
            "stubs the console print and every event is rejected. The gallery "
            "then holds only its dummy entry, `limit` still clamps "
            "@select_no to 1, and `@event_array[1].event_id` raises "
            "NoMethodError on nil. Making both returns explicit is a no-op on "
            "desktop and a fix everywhere else."),
        "old": [
            "    if add_event",
            "      debug = sprintf(\"\u30a4\u30d9\u30f3\u30c8ID %d:\u56de\u60f3\u306b\u8ffd\u52a0\u3057\u307e\u3057\u305f\u3002\",event.id)",
            "      p debug",
            "    else",
            "      return true unless cg_check #CG\u30c1\u30a7\u30c3\u30af\u7121\u3057\u306e\u5834\u5408",
            "    end",
        ],
        "new": [
            "    if add_event",
            "      debug = sprintf(\"\u30a4\u30d9\u30f3\u30c8ID %d:\u56de\u60f3\u306b\u8ffd\u52a0\u3057\u307e\u3057\u305f\u3002\",event.id)",
            "      p debug",
            "      return true",
            "    else",
            "      return true unless cg_check #CG\u30c1\u30a7\u30c3\u30af\u7121\u3057\u306e\u5834\u5408",
            "      return false",
            "    end",
        ],
    },
    {
        "section": "\u56de\u60f3",
        "name": "confirm-on-empty-gallery",
        "why": (
            "The author guarded `update_help` with `return if "
            "@event_array.size == 1` but left the confirm handler "
            "unguarded, so pressing OK on an empty gallery crashes instead of "
            "buzzing. Defence in depth: with the fix above the gallery is not "
            "empty, but a player should never get a NoMethodError for pressing "
            "a button."),
        "old": [
            "    if Input.trigger?(:C)",
            "      if $game_system_data[@event_array[@select_no].event_id]",
        ],
        "new": [
            "    if Input.trigger?(:C)",
            "      if @event_array[@select_no] &&",
            "         $game_system_data[@event_array[@select_no].event_id]",
        ],
    },
]


def sep_of(src):
    return "\r\n" if "\r\n" in src else "\n"


def run(scripts_file, dry_run=False):
    arr, sections = scripts_rb.load_sections(scripts_file)
    by_name = {}
    for i, _sid, name, src, _blob in sections:
        if src is not None:
            by_name.setdefault(name, (i, src))

    expected = {}
    applied, already, problems = [], [], []

    for p in PATCHES:
        hit = by_name.get(p["section"])
        if hit is None:
            problems.append("%s: section %r not found" % (p["name"], p["section"]))
            continue
        idx, src = hit
        src = expected.get(idx, src)
        sep = sep_of(src)
        old = sep.join(p["old"])
        new = sep.join(p["new"])

        if new in src and old not in src:
            already.append(p["name"])
            continue
        n = src.count(old)
        if n == 0:
            problems.append("%s: anchor not found (neither applied nor "
                            "matchable) - REFUSED" % p["name"])
            continue
        if n > 1:
            problems.append("%s: anchor matches %d times - REFUSED"
                            % (p["name"], n))
            continue
        expected[idx] = src.replace(old, new, 1)
        applied.append(p["name"])

    print("patch_scripts_code%s" % (" (dry run)" if dry_run else ""))
    for n in applied:
        print("   + %s" % n)
    for n in already:
        print("   = %s (already applied)" % n)
    for s in problems:
        print("   ! " + s)
    if problems:
        print("REFUSED - nothing written")
        return 1
    if not applied:
        print("   nothing to do")
        return 0
    if dry_run:
        return 0

    for idx, new_src in expected.items():
        row = arr.items[idx]
        blob = zlib.compress(new_src.encode("utf-8"), 9)
        row.items[2] = M.RString(blob, list(row.items[2].ivars))

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(scripts_file, scripts_file + ".bak_" + stamp)
    M.save_file(scripts_file, arr)

    _arr2, after = scripts_rb.load_sections(scripts_file)
    broken = []
    for i, _sid, name, src, _blob in after:
        want = expected.get(i)
        if src is None:
            broken.append("%s: does not inflate" % name)
        elif want is not None and src != want:
            broken.append("%s: content is not what was written" % name)
    if broken:
        shutil.copy2(scripts_file + ".bak_" + stamp, scripts_file)
        for b in broken:
            print("   ! " + b)
        print("ROLLED BACK")
        return 1
    print("   sections written: %d   backup: %s"
          % (len(expected), os.path.basename(scripts_file + ".bak_" + stamp)))
    return 0


def main(argv):
    cfg = config.Config()
    target = cfg.scripts_file
    dry = "--dry-run" in argv
    for i, a in enumerate(argv):
        if a == "--file" and i + 1 < len(argv):
            target = argv[i + 1]
    print("target: %s" % target)
    return run(target, dry)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
