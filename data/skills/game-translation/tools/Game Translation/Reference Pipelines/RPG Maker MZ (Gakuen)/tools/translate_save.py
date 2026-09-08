#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
translate_save.py - make an EXISTING Japanese save load correctly on the patch.

A save carries the build's DATA, not just its position. RPG Maker copies actor
names, the message backlog and any string the game stashed in a variable into
the save file and never re-reads them from the database, so a name translated
later stays Japanese in every save that already exists - while the shipped
`data/*.json` greps perfectly clean.

What this does, in increasing order of how much it could go wrong:

1. **Structural.** Re-sync `$gameActors._data[i]._name` / `._nickname` by
   `_actorId` from the TRANSLATED Actors.json. No string matching at all, so
   this one cannot mis-fire.
2. **Exact whole-string replace**, and only inside the safe sections
   (`map`, `messageLog`, `party`, `player`, `actors`). `variables`, `switches`,
   `selfSwitches`, `system` and `screen` are excluded on purpose: those hold
   logic keys and saved BGM/SE/picture FILENAMES, and one translated key breaks
   a quest gate or a music cue with no error.
3. **Partial glossary-name substitution**, allowed ONLY inside a string that
   already carries a control code (`\\C[`, `\\N[`, `\\I[`, `\\V[`, `\\F[`).
   A bare label is a key until proven otherwise.

A key (`$` `+` `<` `@` prefix) or an asset path (`.png` `.ogg` `.m4a`) is never
touched at any tier.

Every write asserts `decode(encode(data)) == data` first, and the original is
copied to `save_backup/` before anything is replaced.

    python tools/translate_save.py                 # dry run, report coverage
    python tools/translate_save.py --apply
"""

import os
import re
import sys
import json
import glob
import shutil
import argparse
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from mztl import config, store, codes, fileio  # noqa: E402

SAFE_SECTIONS = {"map", "messageLog", "party", "player", "actors"}
KEYLIKE = re.compile(r"^[\$\+<@]|\.(png|jpg|jpeg|ogg|m4a|webm|json|js)$", re.I)
HAS_CODE = re.compile(r"\\+[CNIVFP]\[", re.I)


# --------------------------------------------------------------------------
# codec - MV only (.rpgsave = LZString base64)
# --------------------------------------------------------------------------
def _lz():
    try:
        from lzstring import LZString
    except ImportError:
        sys.exit("ERROR: pip install lzstring  (MV saves are LZString base64)")
    return LZString()


def decode(path):
    blob = open(path, "rb").read().decode("utf-8")
    js = _lz().decompressFromBase64(blob)
    if not js:
        raise ValueError("%s: LZString decompress failed" % path)
    return json.loads(js)


def encode(data):
    js = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return _lz().compressToBase64(js).encode("utf-8")


def write(path, data):
    blob = encode(data)
    check = json.loads(_lz().decompressFromBase64(blob.decode("utf-8")))
    if check != data:
        raise RuntimeError("save round-trip mismatch - refusing to write %s" % path)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(blob)
        f.flush()
        os.fsync(f.fileno())
    store._replace_retry(tmp, path)


# --------------------------------------------------------------------------
def build_map(cfg, store_dir):
    """{japanese: english} from the store plus the glossary."""
    m = {}
    for _p, doc in store.load_docs(store_dir):
        for u in doc["units"]:
            tl = (u.get("tl") or "").strip()
            raw = u.get("raw") or ""
            if not tl or not raw or not codes.has_jp(raw):
                continue
            if raw == tl:
                continue
            final = codes.unmask_codes(codes.clean_translation(tl),
                                       u.get("codes") or {})
            m.setdefault(raw, final)
    g = store.load_glossary(store_dir)
    for jp, v in g.get("names", {}).items():
        en = store.name_en(v)
        if en and codes.has_jp(jp):
            m.setdefault(jp, en)
    for jp, en in (g.get("terms") or {}).items():
        if en and codes.has_jp(jp):
            m.setdefault(jp, en)
    return m


def name_forms(store_dir):
    g = store.load_glossary(store_dir)
    out = []
    for jp, v in g.get("names", {}).items():
        en = store.name_en(v)
        if not en:
            continue
        for f in [jp] + list(v.get("aliases") or []) if isinstance(v, dict) else [jp]:
            if codes.has_jp(f) and len(f) >= 2:
                out.append((f, en))
    out.sort(key=lambda x: -len(x[0]))
    return out


# --------------------------------------------------------------------------
def resync_actors(save, en_actors, stats):
    """Tier 1 - by actor id, no string matching."""
    actors = (save.get("actors") or {}).get("_data")
    if not isinstance(actors, dict):
        return
    payload = actors.get("@a") if "@a" in actors else actors
    if not isinstance(payload, (dict, list)):
        return
    entries = payload.values() if isinstance(payload, dict) else payload
    for a in entries:
        if not isinstance(a, dict):
            continue
        aid = a.get("_actorId")
        if not isinstance(aid, int) or aid >= len(en_actors):
            continue
        src = en_actors[aid]
        if not src:
            continue
        for save_key, db_key in (("_name", "name"), ("_nickname", "nickname")):
            if save_key in a and isinstance(src.get(db_key), str) and src[db_key]:
                if a[save_key] != src[db_key]:
                    a[save_key] = src[db_key]
                    stats["actor"] += 1


def substitute(node, tmap, forms, stats, path=""):
    """Tiers 2 and 3, in the safe sections only."""
    if isinstance(node, dict):
        for k, v in node.items():
            node[k] = substitute(v, tmap, forms, stats, path + "/" + str(k))
        return node
    if isinstance(node, list):
        return [substitute(v, tmap, forms, stats, path + "/%d" % i)
                for i, v in enumerate(node)]
    if not isinstance(node, str) or not node:
        return node
    if KEYLIKE.search(node) or not codes.has_jp(node):
        return node
    hit = tmap.get(node)
    if hit is not None:
        stats["exact"] += 1
        return hit
    if HAS_CODE.search(node):
        out = node
        for jp, en in forms:
            if jp in out:
                out = out.replace(jp, en)
        if out != node:
            stats["partial"] += 1
            return out
    stats["uncovered"].append(node)
    return node


def convert(save, tmap, forms, en_actors, stats):
    resync_actors(save, en_actors, stats)
    for section in SAFE_SECTIONS:
        if section in save:
            save[section] = substitute(save[section], tmap, forms, stats,
                                       "/" + section)
    return save


# --------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", default=os.path.join(os.path.dirname(HERE), "tl"))
    ap.add_argument("--save-dir", default=None)
    ap.add_argument("--en-data", default=None,
                    help="translated data folder (default: the injected out/)")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--show-uncovered", type=int, default=15)
    args = ap.parse_args(argv)

    cfg = config.Config()
    save_dir = args.save_dir or os.path.join(cfg.www, "save")
    if not os.path.isdir(save_dir):
        print("no save folder at %s - nothing to convert "
              "(the game creates it on the first save)" % save_dir)
        return 0

    en_data = args.en_data or os.path.join(os.path.dirname(HERE), "out",
                                           "www", "data")
    actors_path = os.path.join(en_data, "Actors.json")
    if not os.path.exists(actors_path):
        actors_path = os.path.join(cfg.data_dir, "Actors.json")
    en_actors, _ = fileio.load(actors_path)

    tmap = build_map(cfg, args.store)
    forms = name_forms(args.store)
    print("replacement map: %d exact string(s), %d glossary name form(s)"
          % (len(tmap), len(forms)))

    files = sorted(glob.glob(os.path.join(save_dir, "*.rpgsave")))
    if not files:
        print("no .rpgsave files in %s" % save_dir)
        return 0

    backup = os.path.join(save_dir, "save_backup_" +
                          datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
    total = {"actor": 0, "exact": 0, "partial": 0, "uncovered": []}
    for p in files:
        base = os.path.basename(p)
        if base.startswith("config"):
            continue
        try:
            data = decode(p)
        except Exception as e:
            print("  ! %s: %s" % (base, e))
            continue
        stats = {"actor": 0, "exact": 0, "partial": 0, "uncovered": []}
        convert(data, tmap, forms, en_actors, stats)
        print("  %-16s actors=%d exact=%d partial=%d uncovered=%d"
              % (base, stats["actor"], stats["exact"], stats["partial"],
                 len(stats["uncovered"])))
        for k in ("actor", "exact", "partial"):
            total[k] += stats[k]
        total["uncovered"].extend(stats["uncovered"])
        if args.apply:
            os.makedirs(backup, exist_ok=True)
            shutil.copy2(p, os.path.join(backup, base))
            write(p, data)

    print("\ntotal: actors=%d exact=%d partial=%d uncovered=%d"
          % (total["actor"], total["exact"], total["partial"],
             len(total["uncovered"])))
    seen = []
    for s in total["uncovered"]:
        if s not in seen:
            seen.append(s)
    for s in seen[:args.show_uncovered]:
        print("   ? still Japanese: %r" % s[:90])
    if args.apply:
        print("\napplied. originals in %s" % backup)
    else:
        print("\ndry run - pass --apply to convert")
    return 0


if __name__ == "__main__":
    sys.exit(main())
