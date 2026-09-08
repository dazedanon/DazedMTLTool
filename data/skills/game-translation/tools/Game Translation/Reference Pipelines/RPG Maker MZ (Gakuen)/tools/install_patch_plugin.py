#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
install_patch_plugin.py - register `GakuenTL_Patch.js` in `js/plugins.js`.

A structural edit to plugins.js is the one change that can stop the game
booting outright, so this goes through the same `raw_decode` path as every
other write to that file and re-parses its own output before it lands:

  * the plugin file must already exist - a plugins.js entry pointing at a
    missing file makes RPG Maker throw at boot;
  * the entry is appended LAST, so it loads after EventLabel and can alias it;
  * idempotent: a second run updates the existing entry rather than adding a
    duplicate;
  * the rewritten file is re-parsed and every other entry's name and status is
    compared before `os.replace`, and a backup is kept.

    python tools/install_patch_plugin.py            # report
    python tools/install_patch_plugin.py --apply
"""

import os
import sys
import json
import shutil
import datetime
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from mztl import config, plugins_js, store  # noqa: E402

NAME = "GakuenTL_Patch"
ENTRY = {
    "name": NAME,
    "status": True,
    "description": ("English patch support - refreshes display text a save "
                    "cached from the build it was made on"),
    "parameters": {},
}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)

    cfg = config.Config()
    js = os.path.join(cfg.js_dir, "plugins", NAME + ".js")
    if not os.path.exists(js):
        sys.exit("the plugin file is missing: %s\n"
                 "  Registering an entry for a file that is not there makes "
                 "RPG Maker throw at boot." % js)

    prefix, arr, suffix, _s, _e = plugins_js.parse_plugins(cfg.plugins_js)
    before = [(e.get("name"), bool(e.get("status"))) for e in arr]
    idx = next((i for i, e in enumerate(arr) if e.get("name") == NAME), None)

    if idx is None:
        arr.append(dict(ENTRY))
        what = "appended (last, so it loads after EventLabel)"
    else:
        arr[idx].update(ENTRY)
        if idx != len(arr) - 1:
            arr.append(arr.pop(idx))
            what = "already present - moved to LAST and re-enabled"
        else:
            what = "already present and last - refreshed"

    print("plugins.js entries: %d -> %d" % (len(before), len(arr)))
    print("  %s: %s" % (NAME, what))
    others = [(e.get("name"), bool(e.get("status")))
              for e in arr if e.get("name") != NAME]
    kept = [x for x in before if x[0] != NAME]
    if others != kept:
        sys.exit("ERROR: another entry changed - refusing to write")
    print("  every other entry unchanged: yes")

    if not a.apply:
        print("\ndry run - pass --apply to write")
        return 0

    body = json.dumps(arr, ensure_ascii=False, indent=2)
    out = prefix + body + suffix
    tmp = cfg.plugins_js + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(out)
        f.flush()
        os.fsync(f.fileno())
    # Re-parse OUR OWN output before it can be seen by the game.
    _p, check, _s2, _a, _b = plugins_js.parse_plugins(tmp)
    if [e.get("name") for e in check] != [e.get("name") for e in arr]:
        os.unlink(tmp)
        sys.exit("re-parse of the rewritten plugins.js disagrees - nothing written")
    if check[-1].get("name") != NAME or not check[-1].get("status"):
        os.unlink(tmp)
        sys.exit("the new entry is not last-and-enabled - nothing written")

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = cfg.plugins_js + ".bak_" + stamp
    if not os.path.exists(bak):
        shutil.copy2(cfg.plugins_js, bak)
    store._replace_retry(tmp, cfg.plugins_js)
    print("wrote plugins.js (backup: %s)" % os.path.basename(bak))
    return 0


if __name__ == "__main__":
    sys.exit(main())
