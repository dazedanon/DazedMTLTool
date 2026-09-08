#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
store.py - the intermediate translation store and the glossary.

Layout (default `tl/`):

    glossary.json        characters + terms + do_not_translate
    game_prompt.md       the game bible, appended to the cached system prefix
    quirks.md            cross-cutting voice rules (optional)
    units/<Stem>.json    one doc per source file
    _batch_state.json    transient batch bookkeeping

A UNIT is one translatable thing. It carries every write-back site inside its
own file, so injection is a pure function of (pristine source, store):

    {
      "id":      "Map029:ev7:p0:c1",
      "kind":    "text",
      "sites":   [{"ptr": ["events",7,"pages",0,"list"], "start":1, "count":2}],
      "speaker": "ミネリア",
      "ctx":     "Map029 名もなき村 / event 7 'EV007'",
      "nametag": "\\\\F[C_Fun3]",
      "codes":   {"⟦0⟧": "\\\\V[66]"},
      "src":     "cleaned + masked Japanese, the ONLY thing the model sees",
      "raw":     "the original joined string, byte-exact",
      "tl":      ""
    }

Two rules the shapes exist to enforce:

* `raw` is write-once and is the re-run source of truth. Feeding `tl` back to
  the model on pass 2 destroys honorifics and control codes with no recoverable
  original. The SKIP decision reads `tl`; the model INPUT reads `src`.
* A unit never stores a site in another file. Cross-file dedup happens when
  requests are built and when results are applied, not in the store, so a
  store doc always injects into exactly one file.
"""

import os
import re
import glob
import json
import tempfile

GLOSSARY_NAME = "glossary.json"
STATE_NAME = "_batch_state.json"
UNITS_DIR = "units"

# Kinds that are translated once per unique source string and fanned out.
# Dialogue is NOT here: the model needs a coherent run of lines with speakers,
# and one 「わかった」 is "I'll tell her" in one scene and wrong in every other.
DEDUPED_KINDS = {
    "choice", "name", "desc", "note", "term", "title", "currency",
    "mapname", "message", "type", "ptext", "plugin",
}


# --------------------------------------------------------------------------
# JSON pointer
# --------------------------------------------------------------------------
def ptr_get(data, ptr):
    cur = data
    for k in ptr:
        cur = cur[k]
    return cur


def ptr_set(data, ptr, value):
    cur = data
    for k in ptr[:-1]:
        cur = cur[k]
    cur[ptr[-1]] = value


# --------------------------------------------------------------------------
# atomic IO
# --------------------------------------------------------------------------
def read_json(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def write_json(path, obj):
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".",
                               suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        _replace_retry(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _replace_retry(src, dst, attempts=5):
    """os.replace with the Windows antivirus/indexer retry. Not a workaround
    for a bug in our code - the file really is briefly locked by a scanner."""
    import time
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(0.1 * (i + 1))


# --------------------------------------------------------------------------
# docs
# --------------------------------------------------------------------------
def units_dir(store_dir):
    return os.path.join(store_dir, UNITS_DIR)


def doc_path(store_dir, source_file):
    stem = os.path.splitext(os.path.basename(source_file))[0]
    return os.path.join(units_dir(store_dir), stem + ".json")


def save_doc(store_dir, source_file, units, meta=None):
    obj = {"meta": dict(meta or {}, source_file=source_file), "units": units}
    write_json(doc_path(store_dir, source_file), obj)
    return obj


def load_docs(store_dir):
    out = []
    for p in sorted(glob.glob(os.path.join(units_dir(store_dir), "*.json"))):
        out.append((p, read_json(p)))
    return out


def save_docs(docs):
    for p, doc in docs:
        write_json(p, doc)


def all_units(docs):
    for _p, doc in docs:
        for u in doc["units"]:
            yield doc, u


def merge_translations(old_units, new_units):
    """Carry existing translations onto a fresh extraction.

    Matched by unit id first (survives a game update that re-orders events),
    then by (kind, raw) so a re-numbered event keeps its work."""
    by_id = {u["id"]: u for u in old_units}
    by_src = {}
    for u in old_units:
        if u.get("tl", "").strip():
            by_src.setdefault((u["kind"], u.get("raw", "")), u["tl"])
    kept = 0
    for u in new_units:
        old = by_id.get(u["id"])
        if old and old.get("tl", "").strip() and old.get("raw") == u.get("raw"):
            u["tl"] = old["tl"]
            u["locked"] = old.get("locked", False)
            kept += 1
            continue
        tl = by_src.get((u["kind"], u.get("raw", "")))
        if tl:
            u["tl"] = tl
            kept += 1
    return kept


# --------------------------------------------------------------------------
# glossary
# --------------------------------------------------------------------------
def glossary_path(store_dir):
    return os.path.join(store_dir, GLOSSARY_NAME)


def load_glossary(store_dir):
    p = glossary_path(store_dir)
    g = read_json(p) if os.path.exists(p) else {}
    g.setdefault("meta", {})
    g.setdefault("names", {})
    g.setdefault("terms", {})
    g.setdefault("do_not_translate", [])
    return g


def save_glossary(store_dir, glossary):
    write_json(glossary_path(store_dir), glossary)


def name_en(value):
    if isinstance(value, dict):
        return (value.get("en") or "").strip()
    return value.strip() if isinstance(value, str) else ""


def name_needs_tl(value):
    return not name_en(value)


def name_lookup(glossary, jp):
    return name_en(glossary.get("names", {}).get(jp)) or jp


def set_name(glossary, jp, en, gender=None):
    cur = glossary["names"].get(jp)
    if isinstance(cur, dict):
        if en:
            cur["en"] = en
        if gender and not cur.get("gender"):
            cur["gender"] = gender
    elif gender:
        glossary["names"][jp] = {"en": en, "gender": gender}
    else:
        glossary["names"][jp] = en


# --------------------------------------------------------------------------
# batch state
# --------------------------------------------------------------------------
def state_path(store_dir):
    return os.path.join(store_dir, STATE_NAME)


def save_state(store_dir, state):
    write_json(state_path(store_dir), state)


def load_state(store_dir):
    p = state_path(store_dir)
    return read_json(p) if os.path.exists(p) else None


def sanitize_id(s):
    return re.sub(r"[^A-Za-z0-9_:.\-]", "_", s)
