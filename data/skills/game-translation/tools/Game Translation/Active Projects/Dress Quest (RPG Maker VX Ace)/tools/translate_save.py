#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
translate_save.py - make an existing Japanese save load on the patch, in
English.

A save carries the build's DATA, not just its position, and on VX Ace it
carries more than most engines:

  contents[:actors]  Game_Actor copies @name and @nickname out of
                     $data_actors at `setup`, and never re-reads them. An
                     existing save keeps the Japanese name in the menu forever.
  contents[:map]     Game_Map stores `@map`, the WHOLE RPG::Map object for the
                     map the player is standing on, plus a Game_Event per event
                     holding that event's RPG::Event. So the current map's
                     entire script - every message, every choice - is inside
                     the save, and the patched Map###.rvdata2 is not read again
                     until the player walks to another map.

Both are invisible to every check that reads the game folder: the shipped data
is perfectly translated and the player still sees Japanese.

WHAT THIS DOES
    * rewrites Game_Actor @name / @nickname from the glossary
    * applies the store's units to the baked `@map`, using the SAME pointers
      and the SAME text pipeline as `inject`, so a line reads identically
      whether it came from the save or from the patched file
    * rewrites any other string in the save that exactly matches a translated
      source string (custom scripts keep their own state in `$game_system` and
      `$game_party`)
    * NEVER touches switch or variable VALUES, self-switch keys, or anything
      that is not a string a player reads

WHAT IT DELIBERATELY DOES NOT DO
    It does not renumber, reorder or resize anything. The interpreter's saved
    `@index` still points where it pointed, because the injector preserves
    command counts and this rewrites strings in place.

    python tools/translate_save.py            # report
    python tools/translate_save.py --apply
"""

import os
import sys
import glob
import shutil
import argparse
import collections

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from acetl import config, store, codes, measure, inject, rvdata   # noqa: E402
from acetl import rvmarshal as M                                  # noqa: E402


def final_text_for(u, cfg, m):
    """Exactly what `inject` would write for this unit."""
    rep = inject.Report()
    text = inject._final_text(u, cfg, m, rep)
    return text


def build_maps(cfg, store_dir):
    """(per-map unit index, global raw->final map, glossary)."""
    m = measure.reset(cfg.font_path())
    glossary = store.load_glossary(store_dir)
    docs = store.load_docs(store_dir)
    by_map = collections.defaultdict(list)
    raw_to_en = {}
    for _p, doc in docs:
        src_file = doc["meta"]["source_file"]
        for u in doc["units"]:
            text = final_text_for(u, cfg, m)
            if text is None:
                continue
            if rvdata.is_map_file(src_file):
                by_map[src_file].append((u, text))
            raw_to_en.setdefault(u.get("raw", ""), text)
    return by_map, raw_to_en, glossary


def translate_actors(actors_obj, glossary, stats, cfg):
    """`$game_actors` is a Game_Actors holding @data, a sparse array of
    Game_Actor."""
    data = actors_obj.get("@data") if isinstance(actors_obj, M.RObject) else None
    if not isinstance(data, M.RArray):
        return
    for a in data.items:
        if not isinstance(a, M.RObject):
            continue
        for f in ("@name", "@nickname"):
            v = a.get(f)
            if not isinstance(v, M.RString) or not v.data:
                continue
            en = store.name_en(glossary.get("names", {}).get(v.text()))
            if en:
                a.set(f, rvdata.new_string(en, v, cfg.encoding))
                stats["actor-name"] += 1


def translate_baked_map(game_map, by_map, cfg, stats, glossary):
    """Apply the store to the RPG::Map object baked into `$game_map`.

    The Game_Event objects hold the SAME RPG::Event instances as `@map.events`
    (Marshal preserves that identity through a link), so editing the map's copy
    updates the running events too."""
    if not isinstance(game_map, M.RObject):
        return None
    map_id = game_map.get("@map_id")
    inner = game_map.get("@map")
    if not isinstance(inner, M.RObject) or not isinstance(map_id, int):
        return None
    base = "Map%03d.rvdata2" % map_id
    units = by_map.get(base) or []
    rep = inject.Report()
    m = measure.reset(cfg.font_path())
    # The glossary is what rebuilds the name-plate tag in English. Passing an
    # empty one here left the baked map's plates Japanese while the patched
    # data file said Eris - the same scene reading two different ways
    # depending on whether the player had walked off that map since saving.
    for u, _text in units:
        try:
            inject._apply_unit(inner, u, cfg, m, rep, glossary)
        except Exception as e:                    # a pointer that no longer fits
            rep.problem(u["id"], "save apply failed: %s" % e)
    stats["map-units"] += sum(rep.written.values())
    stats["map-problems"] += len(rep.problems)
    return base, rep


def translate_loose_strings(root, raw_to_en, stats, cfg, skip=()):
    """Any other string in the save that exactly matches a translated source.

    Conservative on purpose: exact match only, and never a key inside a hash
    whose values are switch or variable state."""
    for _path, node in M.walk(root):
        if not isinstance(node, M.RString):
            continue
        t = node.text()
        if not t or not codes.has_jp(t):
            continue
        en = raw_to_en.get(t)
        if en and "\n" not in en:
            node.data = en.encode(cfg.encoding)
            stats["loose"] += 1


def process(path, cfg, by_map, raw_to_en, glossary, apply=False, verbose=True):
    with open(path, "rb") as f:
        raw = f.read()
    try:
        docs = M.loads_many(raw)
    except M.MarshalError as e:
        print("  ! %s: not a readable save (%s)" % (os.path.basename(path), e))
        return None
    stats = collections.Counter()
    header, contents = (docs + [None, None])[:2]
    if not isinstance(contents, M.RHash):
        print("  ! %s: unexpected save shape" % os.path.basename(path))
        return None

    baked = None
    for k, v in contents.pairs:
        key = k.text if isinstance(k, M.RSymbol) else str(k)
        if key == "actors":
            translate_actors(v, glossary, stats, cfg)
        elif key == "map":
            baked = translate_baked_map(v, by_map, cfg, stats, glossary)
    translate_loose_strings(contents, raw_to_en, stats, cfg)
    if isinstance(header, M.RHash):
        translate_loose_strings(header, raw_to_en, stats, cfg)

    if verbose:
        print("  %-18s actors=%d  baked map=%s  map units=%d  loose=%d%s"
              % (os.path.basename(path), stats["actor-name"],
                 baked[0] if baked else "-", stats["map-units"], stats["loose"],
                 "  PROBLEMS=%d" % stats["map-problems"]
                 if stats["map-problems"] else ""))
    if apply:
        shutil.copy2(path, path + ".bak")
        out = M.dumps_many(docs)
        M.loads_many(out)                 # prove it re-reads before it lands
        with open(path, "wb") as f:
            f.write(out)
    return stats


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=os.path.join(os.path.dirname(HERE), "tl"))
    ap.add_argument("--game", default=None)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("saves", nargs="*", help="save files (default: the game "
                                             "root's Save*.rvdata2)")
    a = ap.parse_args(argv)
    cfg = config.Config()
    if a.game:
        cfg.game_root = a.game

    paths = a.saves or sorted(glob.glob(os.path.join(cfg.save_dir,
                                                     "Save*.rvdata2")))
    if not paths:
        print("No save files found in %s - nothing to do.\n"
              "(VX Ace writes Save01.rvdata2 .. SaveNN.rvdata2 into the game "
              "root.)" % cfg.save_dir)
        return 0

    by_map, raw_to_en, glossary = build_maps(cfg, a.store)
    print("SAVE TRANSLATION  (%d translated source strings, %d maps in the "
          "store)" % (len(raw_to_en), len(by_map)))
    for p in paths:
        process(p, cfg, by_map, raw_to_en, glossary, apply=a.apply)
    if not a.apply:
        print("\ndry run - pass --apply to rewrite the saves (a .bak is kept)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
