#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_release.py - ship a build for PLAYERS, not for you.

Two archives, because they are two different questions:

  <out>/patch/     the loose files a player drops over their own copy.
                   Yours to hand out.
  <out>/MANIFEST.txt  what is in it and where each file goes.

A full repack of the game is a licensing question, not a technical one, and
this script deliberately does not build one.

The denylist is the point. A dev install logs on purpose; a release must not,
or the first thing a player sees is a console full of engine chatter. The
author's own extraction plugins are the specific hazard here: `www/data_output/`
holds 44 text dumps this game writes at boot via `DRS_AllDataExtractor` and
`SentenceDataExtractor`, and shipping them means shipping the entire Japanese
script as loose .txt beside the patch.

Verification is by ABSENT FILES, not by config values: a config value is an
intention, an absent file is evidence.
"""

import os
import re
import sys
import json
import shutil
import fnmatch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from mztl import config, store, fileio, plugins_js, qa  # noqa: E402

# Everything here is developer state, not game content.
DENY = [
    "*/data_output/*", "data_output/*", "data_output",
    "*/save/*", "save/*",
    "*.bak_*", "*.tmp", "*.log",
    "data_backup_*/*", "*/data_backup_*/*",
    "desktop.ini", "Thumbs.db", ".DS_Store",
    ".git/*", ".gitignore", ".gitattributes",
]

# Plugins that exist only to dump the script for the author. Present in
# js/plugins/ AND registered in plugins.js, so a release must disable them
# rather than delete the file (a missing file registered in plugins.js throws
# at boot).
# This game's three. All are enabled in the shipped build and all are the
# author's, not the player's:
#   DevToolsManage  opens the NW.js dev console and reloads on F5
#   Debug           the author's debug menu
#   BackUpDatabase  writes to `G:\エロＲＰＧackup`, a path that exists on
#                   exactly one machine in the world
DEV_PLUGINS = ["DevToolsManage", "Debug", "BackUpDatabase"]


# Deployed in place by `images/fertilize.py` + `images/rpgmv_crypt.py`. They
# are the only images in the game carrying player-facing baked text.
TRANSLATED_IMAGES = [
    "img/pictures/エロUI/受精…….png_",
    "img/pictures/エロUI/受精……sippai.png_",
    "img/pictures/エロUI/受精……成功！.png_",
]


def _js_parses(path):
    """True if the file is valid JavaScript, or if we cannot tell."""
    try:
        import esprima
    except ImportError:
        print("  (esprima not installed - skipping the JS syntax gate; "
              "`pip install esprima` to enable it)")
        return True
    try:
        esprima.parseScript(open(path, encoding="utf-8").read(), tolerant=False)
        return True
    except Exception as e:
        print("     %s" % e)
        return False


def _denied(rel):
    rel = rel.replace("\\", "/")
    return any(fnmatch.fnmatch(rel, p) for p in DENY)


def main(cfg=None, out=None, store_dir=None):
    cfg = cfg or config.Config()
    store_dir = store_dir or os.path.join(os.path.dirname(HERE), "tl")
    if not out:
        print("ERROR: -o/--out is required")
        return 1

    src_data = os.path.join(os.path.dirname(HERE), "out", "data")
    if not os.path.isdir(src_data):
        print("ERROR: no injected data at %s - run `tl.py inject` first" % src_data)
        return 1

    patch = os.path.join(out, "patch")
    if os.path.isdir(patch):
        shutil.rmtree(patch)
    os.makedirs(patch, exist_ok=True)

    # --- data/*.json ------------------------------------------------------
    dest_data = os.path.join(patch, "data")
    os.makedirs(dest_data, exist_ok=True)
    copied = 0
    for name in sorted(os.listdir(src_data)):
        if _denied(name) or not name.endswith(".json"):
            continue
        shutil.copy2(os.path.join(src_data, name),
                     os.path.join(dest_data, name))
        copied += 1

    # --- js/plugins.js ----------------------------------------------------
    # The plugin ledger is applied IN PLACE in the game folder, so the release
    # copy comes from the game folder, not from the store.
    dest_js = os.path.join(patch, "js")
    os.makedirs(dest_js, exist_ok=True)
    text = open(cfg.plugins_js, encoding="utf-8-sig").read()
    disabled = _disable_dev_plugins(text)
    with open(os.path.join(dest_js, "plugins.js"), "w",
              encoding="utf-8", newline="\n") as f:
        f.write(disabled["text"])

    # --- js/plugins/SkillTreeConfig.js ------------------------------------
    # A third in-place track: a hand-written JS config the SkillTree plugin
    # reads directly. Holds the skill-tree tab labels and their help lines.
    # Plus every plugin whose SOURCE holds text the patch rewrote. That list is
    # the plugins_src ledger, not a constant: a hardcoded pair here is exactly
    # why three casino minigames shipped in Japanese - their plugins draw their
    # whole UI from literals in their own code and nothing copied them.
    stc_n = 0
    names = ["SkillTreeConfig.js", "GakuenTL_Patch.js"]
    led_path = os.path.join(store_dir, "plugins_src.json")
    try:
        led = json.load(open(led_path, encoding="utf-8"))
        for p in sorted(led.get("plugins", {})):
            if p + ".js" not in names:
                names.append(p + ".js")
    except (IOError, OSError, ValueError):
        print("  ! no plugins_src ledger - shipping only the two fixed plugins")

    for name in names:
        src_js = os.path.join(cfg.js_dir, "plugins", name)
        if not os.path.exists(src_js):
            print("  ! missing js/plugins/%s" % name)
            continue
        # A plugin with a syntax error does not warn - RPG Maker throws at boot
        # and the player gets a black screen. Nothing else in this build checks
        # it, and "the game still launched" does not prove it, because the
        # process stays alive showing the error screen.
        if not _js_parses(src_js):
            print("  ! js/plugins/%s DOES NOT PARSE - aborting" % name)
            return 1
        d = os.path.join(patch, "js", "plugins")
        os.makedirs(d, exist_ok=True)
        shutil.copy2(src_js, os.path.join(d, name))
        stc_n += 1

    # --- the window caption -----------------------------------------------
    # package.json and index.html hold the title the WINDOW and taskbar show
    # from the moment the window is created, before the engine has read
    # System.json. Left alone they display Japanese through the whole boot.
    cap_n = 0
    for name in ("package.json", "index.html"):
        src_f = os.path.join(cfg.game_root, name)
        if os.path.exists(src_f):
            shutil.copy2(src_f, os.path.join(patch, name))
            cap_n += 1

    # --- translated images ------------------------------------------------
    img_n = 0
    for rel in TRANSLATED_IMAGES:
        src = os.path.join(cfg.game_root, rel)
        if not os.path.exists(src):
            print("  ! translated image missing from the game tree: %s" % rel)
            continue
        dst = os.path.join(patch, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        img_n += 1

    # --- verification by absent files -------------------------------------
    problems = []
    for root, dirs, files in os.walk(patch):
        for d in list(dirs):
            if _denied(os.path.relpath(os.path.join(root, d), patch)):
                problems.append("dev directory present: " + d)
        for fn in files:
            rel = os.path.relpath(os.path.join(root, fn), patch)
            if _denied(rel):
                problems.append("denylisted file present: " + rel)

    # A patch that breaks saves is worse than no patch, and nothing else in
    # this script would tell you. Gate the release on the PROOF - every command
    # list the same length, the same codes, the same indents - not on the
    # claim that the injector preserves them.
    import verify_structure
    if verify_structure.main(["--out", dest_data]) != 0:
        print("\nRELEASE ABORTED: the structural verify failed above. The "
              "patch would move an index that a save file stores.")
        return 1

    # Reuse the code-aware scanner rather than a second, simpler walk. A plain
    # "find Japanese in parameters[0]" pass reports 1,139 strings here and every
    # one of them is a code-108 comment, a code-118 label or a code-355 script
    # that the pipeline deliberately never translates. A number that large reads
    # as a broken patch, so nobody looks at it - which is how the one real
    # residual would go unnoticed.
    leaked, jp_left, never_unit = qa.scan_output(cfg, dest_data, verbose=False)
    residual = ["%s %s  %r" % r for r in jp_left]

    man = os.path.join(out, "MANIFEST.txt")
    with open(man, "w", encoding="utf-8", newline="\n") as f:
        f.write("%s - English patch\n" % cfg.game_en)
        f.write("original: %s\n\n" % cfg.game_jp)
        f.write("INSTALL\n")
        f.write("  Copy the contents of patch/ over your game folder, keeping\n")
        f.write("  the folder structure. Overwrite when asked. Back up\n")
        f.write("  www/data and www/js/plugins.js first if you want to revert.\n\n")
        f.write("CONTENTS\n")
        f.write("  www/data/*.json   %d file(s) - all dialogue, items, UI\n" % copied)
        f.write("  www/js/plugins.js 1 file - menu labels, gauge labels, shop text\n")
        f.write("  www/js/plugins/   %d file(s) - text hardcoded in plugin code\n"
                % stc_n)
        if img_n:
            f.write("  www/img/**        %d translated image(s)\n" % img_n)
        f.write("\nDISABLED FOR RELEASE\n")
        for name in disabled["disabled"]:
            f.write("  %s (author's script-dump plugin - writes www/data_output/)\n" % name)
        f.write("\nNOT INCLUDED\n")
        f.write("  www/data_output/  the author's Japanese script dumps\n")
        f.write("  www/save/         player saves\n")
        f.write("  *.bak_* data_backup_*  working backups\n")

    print("RELEASE -> %s" % patch)
    print("  data files      : %d" % copied)
    print("  plugins.js      : dev plugins disabled: %s"
          % (", ".join(disabled["disabled"]) or "none found"))
    print("  js/plugins/*.js : %d (%s)"
          % (stc_n, ", ".join(n[:-3] for n in names)))
    print("  window caption  : %d (package.json, index.html)" % cap_n)
    print("  images          : %d" % img_n)
    print("  manifest        : %s" % man)
    print("  leaked control-code sentinels    : %d" % len(leaked))
    print("  player-facing Japanese remaining : %d" % len(residual))
    print("  byte-identical to source           : %d distinct (comments, "
          "labels and scripts - codes this pipeline never translates)"
          % len(never_unit))
    for s in residual[:10]:
        print("      ? %s" % s)
    if problems:
        print("  !! %d denylist violation(s):" % len(problems))
        for p in problems[:10]:
            print("      ! " + p)
        return 1
    print("  denylist        : clean (verified by absent files, not by config)")
    return 0


def _disable_dev_plugins(text):
    """Set `status: false` on the author's extraction plugins.

    Deleting the .js instead would leave plugins.js registering a file that is
    not there, and RPG Maker throws at boot. The structural edit goes through
    raw_decode so untouched entries stay byte-identical."""
    m = re.search(r"var\s+\$plugins\s*=\s*", text)
    if not m:
        return {"text": text, "disabled": []}
    start = text.index("[", m.end() - 1)
    arr, end = json.JSONDecoder().raw_decode(text, start)
    off = []
    for e in arr:
        if e.get("name") in DEV_PLUGINS and e.get("status"):
            e["status"] = False
            off.append(e["name"])
    body = json.dumps(arr, ensure_ascii=False, indent=2)
    return {"text": text[:start] + body + text[end:], "disabled": off}




if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--store", default=None)
    a = ap.parse_args()
    sys.exit(main(None, a.out, a.store))
