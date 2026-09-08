#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
translate_save.py — convert RPG Maker MV/MZ save files from the original
Japanese to the translated English, so EXISTING saves match the patched game
(no need to replay to test).

WHY: a save bakes in strings the engine does NOT re-resolve from the database at
load time — chiefly $gameActors names (\\N[n] reads the SAVED name, not
$dataActors), nicknames/profiles, and text the game stored in $gameVariables or
the message backlog. After translating the database those stay Japanese in old
saves.

WHAT it does (all safe / reversible; saves are backed up first):
  1. Structural actor _name/_nickname re-sync by _actorId from the translated
     Actors.json  (never string-matching — the reliable fix).
  2. Exact whole-string replace: any save string EQUAL to a known JP source is
     swapped for its EN translation. The map is built from the database diff
     (JP backup vs translated data), the translation store, glossary names/terms,
     and an optional hand-written save_map.json. Exact-match only, so it won't
     touch internal keys (portrait-expression names, <TE:..> template tags, etc.)
     that don't appear verbatim as a translated field.
  3. Glossary-NAME substring replace ONLY inside display strings (those carrying a
     control code like \\C[ \\N[ \\I[), never bare label/key/asset strings.

SAVE FORMATS:
  * MZ  (*.rmmzsave): pako.deflate(level 1) stored as a UTF-8 string. Read/written
    in BINARY (Windows text mode would mangle the deflate bytes).
  * MV  (*.rpgsave) : LZString Base64.  (requires `pip install lzstring`)
  config.* and any file with no translatable text are skipped.

Usage:
  python tooling/translate_save.py                 # dry-run: report coverage
  python tooling/translate_save.py --apply         # convert in place (backs up first)
  options: --save-dir --jp-data --en-data --store --map --show-uncovered N
"""
import os, sys, json, glob, re, zlib, shutil, argparse

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tooling"))

_JP_RE = re.compile(r"[぀-ゟ゠-ヿㇰ-ㇿ㐀-䶿一-鿿々〆〇]")
# strings we must NEVER touch: keys/handles (start with $ + < @) or asset paths.
_KEYLIKE = re.compile(r"^[\$\+<@]|\.(png|jpg|jpeg|ogg|m4a|webm)$", re.I)

# Only these top-level save sections get the string-replace pass. The others —
# variables/switches/selfSwitches (logic keys like the portrait-expression "通常")
# and system/screen (saved BGM/SE/picture FILENAMES) — must stay byte-exact or the
# game breaks. Actor names are handled structurally regardless of this set.
_SAFE_SECTIONS = {"map", "messageLog", "party", "player", "actors"}


def has_jp(s):
    return isinstance(s, str) and bool(_JP_RE.search(s))


# --------------------------------------------------------------------------
# save codec — MZ (zlib/binary) and MV (LZString)
# --------------------------------------------------------------------------
def _is_mz(path):
    return path.lower().endswith(".rmmzsave")


def _decode_blob(is_mz, blob):
    """Decode raw save file bytes -> Python object, per format."""
    if is_mz:                                                # zlib(level1) as a UTF-8 string
        s = blob.decode("utf-8")
        d = zlib.decompressobj(15)
        raw = d.decompress(s.encode("latin-1")) + d.flush()
        return json.loads(raw.decode("utf-8"))
    from lzstring import LZString                            # MV: LZString Base64
    js = LZString().decompressFromBase64(blob.decode("utf-8"))
    if not js:
        raise ValueError("LZString decompress failed")
    return json.loads(js)


def _encode_blob(is_mz, data):
    """Encode a Python object -> raw save file bytes, per format."""
    js = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    if is_mz:
        comp = zlib.compress(js.encode("utf-8"), 1)          # level 1, like pako
        return comp.decode("latin-1").encode("utf-8")        # binary string -> UTF-8 bytes
    from lzstring import LZString
    return LZString().compressToBase64(js).encode("utf-8")


def save_decode(path):
    return _decode_blob(_is_mz(path), open(path, "rb").read())   # binary read (no newline xlate)


def save_write(path, data):
    is_mz = _is_mz(path)
    blob = _encode_blob(is_mz, data)
    # round-trip safety: the blob must decode back to exactly `data` (same format)
    assert _decode_blob(is_mz, blob) == data, "save round-trip mismatch — aborting write"
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(blob)
    os.replace(tmp, path)


# --------------------------------------------------------------------------
# build the JP -> EN replacement map
# --------------------------------------------------------------------------
def _walk_pairs(a, b, out):
    if isinstance(a, str) and isinstance(b, str):
        if a != b and a.strip():
            out.setdefault(a, b)
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for x, y in zip(a, b):
            _walk_pairs(x, y, out)
    elif isinstance(a, dict) and isinstance(b, dict):
        for k in a:
            if k in b:
                _walk_pairs(a[k], b[k], out)


def build_map(jp_data, en_data, store, map_file):
    m = {}
    # 1. database/event diff (the bulk of every translation)
    for f in glob.glob(os.path.join(en_data, "*.json")):
        jf = os.path.join(jp_data, os.path.basename(f))
        if os.path.exists(jf):
            try:
                _walk_pairs(json.load(open(jf, encoding="utf-8-sig")),
                            json.load(open(f, encoding="utf-8-sig")), m)
            except Exception:
                pass
    # 2. translation store (unmasked src -> tl) — catches runtime-form strings
    try:
        from rpgmvtl import codes
        for f in glob.glob(os.path.join(store, "*.json")):
            if os.path.basename(f) == "glossary.json":
                continue
            for u in json.load(open(f, encoding="utf-8")).get("units", []):
                cd = u.get("codes", {})
                jp = codes.unmask_codes(u.get("src", ""), cd)
                en = codes.unmask_codes(u.get("tl", "") or "", cd)
                if jp and en and jp != en:
                    m.setdefault(jp, en)
    except Exception as e:
        print(f"  (store map skipped: {e})")
    # 3. glossary names + terms
    names = {}
    gpath = os.path.join(store, "glossary.json")
    if os.path.exists(gpath):
        g = json.load(open(gpath, encoding="utf-8"))
        for jp, info in g.get("names", {}).items():
            en = info["en"] if isinstance(info, dict) else info
            if en:
                m.setdefault(jp, en); names[jp] = en
        for jp, en in g.get("terms", {}).items():
            if en:
                m.setdefault(jp, en); names[jp] = en
    # 4. EventLabel <LB:..> labels are now auto-extracted 'label' units, so step 2
    #    already added them to the map; they fix the value CACHED in the save as
    #    Game_Event._labelText (in $gameMap) for old saves.
    # 5. manual save_map.json (game terms not in the DB) — explicit override wins
    if map_file and os.path.exists(map_file):
        for jp, en in json.load(open(map_file, encoding="utf-8")).items():
            m[jp] = en; names[jp] = en
    return m, names


# --------------------------------------------------------------------------
# conversion
# --------------------------------------------------------------------------
def _actor_list(data):
    """The Game_Actor list inside the save — MZ keeps _data as a plain list;
    older JsonEx wraps it as {"@a": [...]}."""
    try:
        d = data["actors"]["_data"]
    except Exception:
        return []
    if isinstance(d, dict) and "@a" in d:
        return d["@a"]
    return d if isinstance(d, list) else []


def convert(data, m, names, stats):
    name_keys = sorted([k for k in names if has_jp(k)], key=len, reverse=True)

    def sub_names(s):
        for jp in name_keys:
            if jp in s:
                s = s.replace(jp, names[jp])
        return s

    def rec(o):
        if isinstance(o, str):
            s = o
            if has_jp(s):
                if s in m:                          # exact whole-string match
                    s = m[s]; stats["exact"] += 1
                # name substring ONLY inside display strings (carry a control code
                # like \c[ \n[ \i[ \{), never bare label/key/asset strings — so we
                # can't corrupt switch/state/picture/expression keys.
                elif "\\" in s and not _KEYLIKE.search(s):
                    s2 = sub_names(s)
                    if s2 != s:
                        stats["partial"] += 1; s = s2
                if has_jp(s):
                    stats["uncovered"].add(s)
            return s
        if isinstance(o, list):
            return [rec(v) for v in o]
        if isinstance(o, dict):
            return {k: rec(v) for k, v in o.items()}
        return o

    # 1. actor names/nicknames — translate JP -> EN via the map ONLY. We never
    #    overwrite with a database default, so a heroine's baked Japanese name
    #    (アインアイク -> Einaike) and a bred unit's Japanese race name (ゴブリン ->
    #    Goblin) are fixed, while an already-English or player-set name is untouched.
    for a in _actor_list(data):
        if isinstance(a, dict):
            for fld in ("_name", "_nickname"):
                v = a.get(fld)
                if has_jp(v) and v in m:
                    a[fld] = m[v]; stats["actor"] += 1

    # 2. string-replace pass — ONLY within the safe display sections.
    if isinstance(data, dict):
        return {k: (rec(v) if k in _SAFE_SECTIONS else v) for k, v in data.items()}
    return rec(data)


def process(path, m, names, apply):
    try:
        data = save_decode(path)
    except Exception as e:
        print(f"  !! {os.path.basename(path)}: {e}")
        return []
    stats = {"exact": 0, "partial": 0, "actor": 0, "uncovered": set()}
    data = convert(data, m, names, stats)
    unc = sorted(s for s in stats["uncovered"] if has_jp(s))
    print(f"  {os.path.basename(path):22s} actor={stats['actor']} "
          f"exact={stats['exact']} name-sub={stats['partial']} "
          f"| JP remaining: {len(unc)}")
    if apply:
        save_write(path, data)
    return unc


def _default_dir(*rel):
    p = os.path.join(ROOT, *rel)
    if os.path.isdir(p):
        return p
    alt = os.path.join(ROOT, "www", *rel)        # MV layout fallback
    return alt if os.path.isdir(alt) else p


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--save-dir", default=_default_dir("save"))
    ap.add_argument("--jp-data", default=None, help="original JP data dir (a data backup)")
    ap.add_argument("--en-data", default=_default_dir("data"))
    ap.add_argument("--store", default=os.path.join(ROOT, "tooling", "tl"))
    ap.add_argument("--map", default=os.path.join(ROOT, "tooling", "save_map.json"))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--show-uncovered", type=int, default=0)
    a = ap.parse_args()

    jp = a.jp_data
    if not jp:
        bks = sorted(glob.glob(os.path.join(ROOT, "data_backup_*")) +
                     glob.glob(os.path.join(ROOT, "www", "data_backup_*")))
        jp = bks[-1] if bks else a.en_data
    print(f"JP data: {os.path.relpath(jp, ROOT)}   EN data: {os.path.relpath(a.en_data, ROOT)}")

    m, names = build_map(jp, a.en_data, a.store, a.map)
    print(f"map: {len(m)} JP->EN pairs, {len(names)} names/terms\n")

    if a.apply:
        bdir = a.save_dir.rstrip("/\\") + "_backup"
        if not os.path.exists(bdir):
            shutil.copytree(a.save_dir, bdir)
            print(f"backed up saves -> {os.path.relpath(bdir, ROOT)}")

    all_unc = {}
    files = sorted(glob.glob(os.path.join(a.save_dir, "*.rmmzsave")) +
                   glob.glob(os.path.join(a.save_dir, "*.rpgsave")))
    for p in files:
        if os.path.basename(p).startswith("config."):
            continue
        for s in process(p, m, names, a.apply) or []:
            all_unc[s] = all_unc.get(s, 0) + 1

    print(f"\n{'APPLIED' if a.apply else 'DRY RUN'}. Distinct JP strings still uncovered: {len(all_unc)}")
    if a.show_uncovered:
        for s, _c in sorted(all_unc.items(), key=lambda kv: -kv[1])[:a.show_uncovered]:
            print(f"   x{_c}  {s[:70]!r}")
    if not a.apply:
        print("Re-run with --apply to write (saves backed up first).")


if __name__ == "__main__":
    main()
