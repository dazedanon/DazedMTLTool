#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
window_title.py - the window caption, which lives OUTSIDE data/ and js/.

Three files carry the game's title and only one of them was in the pipeline:

  data/System.json  gameTitle     -> a translation unit; `Scene_Boot.update-
                                     DocumentTitle` assigns it to
                                     `document.title` once the game has booted
  package.json      window.title  -> the NW.js window title, used from the
                                     moment the window is created
  index.html        <title>       -> the page title before the engine runs

So the taskbar and window caption show the JAPANESE title for the whole splash
and boot, then flip to English. All three must agree, and the two outside
data/ are on the IN-PLACE track like `js/plugins.js`.

The English is taken from the STORE, never retyped, so the three cannot drift.

    python tools/window_title.py            # report
    python tools/window_title.py --apply
"""

import os
import re
import io
import sys
import json
import shutil
import datetime
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from mztl import config, store  # noqa: E402


def english_title(store_dir):
    for _p, doc in store.load_docs(store_dir):
        if doc["meta"]["source_file"] != "System.json":
            continue
        for u in doc["units"]:
            if u["id"] == "System:gameTitle":
                return (u.get("tl") or "").strip()
    return ""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=os.path.join(os.path.dirname(HERE), "tl"))
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)

    cfg = config.Config()
    title = english_title(a.store)
    if not title:
        sys.exit("System:gameTitle has no translation in the store")
    print("title from the store:\n   %r\n" % title)

    pkg = os.path.join(cfg.game_root, "package.json")
    idx = os.path.join(cfg.game_root, "index.html")
    changed = []

    # --- package.json -----------------------------------------------------
    # A real JSON file, but keep the author's formatting: read, edit the one
    # leaf, re-dump with the same 4-space indent it ships with.
    raw = open(pkg, encoding="utf-8-sig").read()
    data = json.loads(raw)
    cur = (data.get("window") or {}).get("title", "")
    print("package.json window.title:\n   %r" % cur)
    if cur != title:
        changed.append("package.json")
        if a.apply:
            m = re.search(r"\n([ \t]+)\"", raw)
            indent = len(m.group(1)) if m and "\t" not in m.group(1) else 4
            data.setdefault("window", {})["title"] = title
            out = json.dumps(data, ensure_ascii=False, indent=indent)
            _write(pkg, out)

    # --- index.html -------------------------------------------------------
    # NOT parsed as HTML - a span splice on the one <title> element, so every
    # other byte of the page is untouched.
    html = open(idx, encoding="utf-8-sig").read()
    m = re.search(r"(<title>)(.*?)(</title>)", html, re.S)
    if not m:
        sys.exit("index.html has no <title> element")
    print("index.html <title>:\n   %r" % m.group(2))
    if m.group(2) != title:
        changed.append("index.html")
        if a.apply:
            safe = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            _write(idx, html[:m.start(2)] + safe + html[m.end(2):])

    print()
    if not changed:
        print("both already match the store - nothing to do")
        return 0
    if not a.apply:
        print("would update: %s\n\ndry run - pass --apply to write" % ", ".join(changed))
        return 0
    print("updated: %s" % ", ".join(changed))
    return 0


def _write(path, text):
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = path + ".bak_" + stamp
    if not os.path.exists(bak):
        shutil.copy2(path, bak)
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    # package.json is parsed by NW.js before the window exists; a malformed one
    # means the game does not start at all.
    if path.endswith(".json"):
        with io.open(tmp, encoding="utf-8-sig") as f:
            json.load(f)
    store._replace_retry(tmp, path)
    print("   wrote %s (backup: %s)" % (os.path.basename(path),
                                        os.path.basename(bak)))


if __name__ == "__main__":
    sys.exit(main())
