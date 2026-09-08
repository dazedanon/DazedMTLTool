#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
build_release.py - ship a build for PLAYERS, not for you.

    <out>/patch/          the loose files a player drops over their own copy
    <out>/MANIFEST.txt    what is in it, where each file goes, what was left out

A full repack of the game is a licensing question, not a technical one, and
this script deliberately does not build one.

HOW THE PATCH REACHES THE GAME
    The opposite of what this file assumed until it was tested: with
    `Game.rgss3a` present, RGSS3 serves `Data\*.rvdata2` FROM THE ARCHIVE and
    a loose file of the same name is ignored. Measured by running the game with
    a fully translated `Data\` in place - it came up in Japanese.

    So the install has three steps, not one: extract the archive to loose
    files, copy this patch's `Data\` over the extracted one, and REMOVE
    `Game.rgss3a`. `Tools\Game Archives\RPG Maker RGSSAD\rgssad.py` does the
    extraction. Keeping the archive is what makes it reversible - put it back
    and delete `Data\` and `Graphics\` to return to Japanese.

    `Data\Scripts.rvdata2` is part of the patch because the UI strings baked
    into the RGSS3 source are edited in place there.

GATES
    * the structural verify must pass, or the patch could move an index that a
      save file stores;
    * the residual-language scan runs through the SAME code the QA step uses,
      so what it reports is the same notion of player-facing text that
      extraction used. A separate, simpler "find Japanese" walk would report
      hundreds of picture filenames and jump labels, and a number that size
      reads as a broken patch, so nobody would read the list;
    * the denylist is verified by ABSENT FILES, not by intention.
"""

import os
import sys
import shutil
import fnmatch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from acetl import config, store, qa                       # noqa: E402

# Anywhere in the tree: developer state, never game content.
DENY_ANY = [
    "*.bak", "*.bak_*", "*.backup", "*.orig", "*.tmp", "*.log",
    "__pycache__", ".git", ".hg", ".svn", ".pytest_cache", ".mypy_cache",
    "desktop.ini", "Thumbs.db", ".DS_Store",
    "Save*.rvdata2", "*.rvsave", "*.sav",
    "Data_backup_*",
]
# At the ROOT of the patch only: a real game legitimately ships folders with
# these names deeper in its tree.
DENY_ROOT = [
    "tl", "out", "docs", "tests", "tools", "acetl", "logs", "log",
    ".env*", "*.md", "*.py", "requirements.txt", ".gitignore",
]


def _denied(rel):
    rel = rel.replace("\\", "/")
    name = os.path.basename(rel)
    if any(fnmatch.fnmatch(name, p) or fnmatch.fnmatch(rel, p)
           for p in DENY_ANY):
        return "denylisted anywhere: %s" % name
    top = rel.split("/")[0]
    if any(fnmatch.fnmatch(top, p) for p in DENY_ROOT) and "/" not in rel:
        return "denylisted at the root: %s" % top
    return ""


def main(cfg=None, out=None, store_dir=None):
    cfg = cfg or config.Config()
    store_dir = store_dir or os.path.join(os.path.dirname(HERE), "tl")
    if not out:
        print("ERROR: -o/--out is required")
        return 1

    src_data = os.path.join(os.path.dirname(HERE), "out", "Data")
    if not os.path.isdir(src_data):
        print("ERROR: no injected data at %s - run `tl.py inject` first" % src_data)
        return 1

    patch = os.path.join(out, "patch")
    if os.path.isdir(patch):
        shutil.rmtree(patch)
    os.makedirs(patch, exist_ok=True)

    # --- Data ---------------------------------------------------------------
    dest_data = os.path.join(patch, "Data")
    os.makedirs(dest_data, exist_ok=True)
    copied = 0
    for name in sorted(os.listdir(src_data)):
        if _denied(name) or not name.endswith(".rvdata2"):
            continue
        shutil.copy2(os.path.join(src_data, name), os.path.join(dest_data, name))
        copied += 1

    # Scripts.rvdata2 is the IN-PLACE track: the release copy comes from the
    # game folder, never from out/, or the UI strings edited there are lost.
    scripts_from_game = 0
    if os.path.exists(cfg.scripts_file):
        shutil.copy2(cfg.scripts_file, os.path.join(dest_data, "Scripts.rvdata2"))
        scripts_from_game = 1

    # --- translated images --------------------------------------------------
    img_src = os.path.join(os.path.dirname(HERE), "out", "Graphics")
    img_n = 0
    if os.path.isdir(img_src):
        for root, _dirs, files in os.walk(img_src):
            for fn in files:
                if _denied(fn):
                    continue
                rel = os.path.relpath(os.path.join(root, fn), img_src)
                dst = os.path.join(patch, "Graphics", rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(os.path.join(root, fn), dst)
                img_n += 1

    # --- gate 1: the save-safety proof --------------------------------------
    import verify_structure
    if verify_structure.main(["--out", dest_data, "--game", cfg.game_root]) != 0:
        print("\nRELEASE ABORTED: the structural verify failed above. The "
              "patch would move an index that a save file stores.")
        return 1

    # --- gate 2: residual language, through the QA scanner ------------------
    leaked, jp_left, never_unit = qa.scan_output(cfg, dest_data, verbose=False)

    # --- gate 3: the denylist, verified by absent files ---------------------
    problems = []
    for root, dirs, files in os.walk(patch):
        for d in list(dirs):
            rel = os.path.relpath(os.path.join(root, d), patch)
            why = _denied(rel)
            if why:
                problems.append("directory present: %s (%s)" % (rel, why))
        for fn in files:
            rel = os.path.relpath(os.path.join(root, fn), patch)
            why = _denied(rel)
            if why:
                problems.append("file present: %s (%s)" % (rel, why))

    man = os.path.join(out, "MANIFEST.txt")
    with open(man, "w", encoding="utf-8", newline="\n") as f:
        f.write("%s - English patch\n" % cfg.game_en)
        f.write("original: %s (RPG Maker VX Ace)\n\n" % cfg.game_jp)
        f.write("INSTALL - three steps, and the third one matters\n")
        f.write("  1. Extract Game.rgss3a into the game folder, so Data/ and\n")
        f.write("     Graphics/ exist as loose files.\n")
        f.write("  2. Copy the contents of patch/ over them, overwriting.\n")
        f.write("  3. MOVE Game.rgss3a out of the game folder (keep it).\n")
        f.write("\n")
        f.write("  Step 3 is not optional. RGSS3 reads Data/*.rvdata2 from the\n")
        f.write("  archive whenever the archive is present, and ignores the\n")
        f.write("  loose file of the same name - the game starts in Japanese\n")
        f.write("  with a fully translated Data/ sitting right there.\n")
        f.write("  To revert: put Game.rgss3a back and delete Data/ and\n")
        f.write("  Graphics/.\n\n")
        f.write("CONTENTS\n")
        f.write("  Data/*.rvdata2      %d file(s) - dialogue, items, skills,\n"
                % copied)
        f.write("                      states, map names, choices, UI terms\n")
        if scripts_from_game:
            f.write("  Data/Scripts.rvdata2  the RGSS3 scripts, for the UI\n")
            f.write("                      strings baked into Ruby source\n")
        if img_n:
            f.write("  Graphics/**         %d translated image(s)\n" % img_n)
        f.write("\nSAVE COMPATIBILITY\n")
        f.write("  Every event command list keeps its exact length, codes and\n")
        f.write("  indents, so an existing save resumes on the same line.\n")
        f.write("  A save made before the patch still holds the Japanese text\n")
        f.write("  of the map it was saved on, plus the actor's Japanese name:\n")
        f.write("  run tools/translate_save.py --apply against it once.\n")
        f.write("\nNOT INCLUDED\n")
        f.write("  Save*.rvdata2       player saves\n")
        f.write("  Data_backup_*, *.bak_*   working backups\n")
        f.write("  the pipeline itself (tl/, acetl/, tools/, out/)\n")

    print("RELEASE -> %s" % patch)
    print("  data files      : %d" % copied)
    print("  scripts         : %s" % ("Data/Scripts.rvdata2 (from the game "
                                      "folder)" if scripts_from_game else "none"))
    print("  images          : %d" % img_n)
    print("  manifest        : %s" % man)
    print("  leaked sentinels: %d" % len(leaked))
    print("  player-facing Japanese remaining : %d" % len(jp_left))
    print("  byte-identical to source         : %d distinct (codes this "
          "pipeline never translates)" % len(never_unit))
    for b, w, v in jp_left[:10]:
        print("      ? %s %s %r" % (b, w, v))
    if problems:
        print("  !! %d denylist violation(s):" % len(problems))
        for p in problems[:10]:
            print("      ! " + p)
        return 1
    print("  denylist        : clean (verified by absent files, not by config)")
    return 0


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--store", default=None)
    a = ap.parse_args()
    sys.exit(main(None, a.out, a.store))
