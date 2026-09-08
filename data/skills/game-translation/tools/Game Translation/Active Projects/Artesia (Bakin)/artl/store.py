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

A UNIT is one translatable thing. On Bakin its write site is a single opaque
key that the catalog resolves, so there are no JSON pointers to walk:

    {
      "id":      "S:5efb9b10-...:41:0",
      "key":     "S:5efb9b10-...:41:0",    the BakinTL write-back address
      "kind":    "text",
      "owner":   "common:汎用セックス",
      "ctx":     "イベントシート#41.0",
      "order":   "2common|.../|00031|000|00041|0",
      "file":    "GameSettings.rbr",
      "speaker": "アルテシア",              peeled out of the nameplate code
      "plate":   "NPL",
      "codes":   {"[0]": "the masked control code"},
      "src":     "cleaned + masked Japanese, the ONLY thing the model sees",
      "raw":     "the original field value, byte-exact",
      "tl":      ""
    }

Two rules the shapes exist to enforce:

* `raw` is write-once and is the re-run source of truth. Feeding `tl` back to
  the model on pass 2 destroys honorifics and control codes with no recoverable
  original. The SKIP decision reads `tl`; the model INPUT reads `src`.
* A unit's `key` is stable across a re-extraction only while the command index
  does not move, which is why nothing in this pipeline ever inserts or removes
  a script command.
"""

import os
import re
import glob
import json
import tempfile

GLOSSARY_NAME = "glossary.json"
STATE_NAME = "_batch_state.json"
UNITS_DIR = "units"

# Kinds translated once per unique source string and fanned out to every unit
# that shares it.
DEDUPED_KINDS = {
    "choice", "name", "desc", "term", "title", "mapname", "message",
    "telop", "strvar", "sptext", "ui", "codearg",
}

# Dialogue is the interesting case, and the ruling here is MEASURED rather than
# inherited.
#
# The standing rule elsewhere is "never dedupe dialogue": the model needs a
# coherent run of lines with speakers, and one 「わかった」 rendered "I'll tell
# her" is correct in the scene it was translated in and wrong in every other
# place the engine reuses it.
#
# On this game `tools/dedup_risk.py` measures the actual surface. 83,999
# dialogue units are 22,914 distinct (speaker, body) pairs - a 3.7x factor that
# is most of the bill - and only 156 distinct bodies are ever spoken by more
# than one speaker, essentially all of them ellipses and moans. Keying the
# dedup on (speaker, body) rather than on body alone costs 275 extra units and
# removes the pronoun class outright.
#
# What remains is a line reused by the SAME speaker across two scenes, which
# `qa.py repeats` re-reviews after the fact. Setting `dedup_dialogue` False in
# the config restores the conservative default.
DIALOGUE_KIND = "text"


def dedup_key(u, dedup_dialogue=True):
    """The identity two units must share to be translated only once.

    None means the unit is translated on its own."""
    if u["kind"] in DEDUPED_KINDS:
        return (u["kind"], u["src"])
    if u["kind"] == DIALOGUE_KIND and dedup_dialogue:
        return (u["kind"], u.get("speaker") or "", u["src"])
    return None


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


def doc_stem(doc):
    return os.path.splitext(os.path.basename(doc["meta"]["source_file"]))[0]


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
            if old.get("locked"):
                u["locked"] = True
            # Waivers are hand-written and carry a reason; losing one on a
            # re-extraction re-opens a flag somebody already judged.
            if old.get("waive"):
                u["waive"] = old["waive"]
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


# The Batches API validates `custom_id` against exactly this, and rejects the
# whole submission with a 400 if any one request fails it. `:` and `.` are NOT
# allowed - a sanitiser that permits them looks careful and still fails every
# submit, which is a 400 you only see after the request builder has already
# done all its work.
CUSTOM_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def sanitize_id(s):
    """A custom_id the Batches API will accept: [A-Za-z0-9_-], 1-64 chars.

    Truncated from the LEFT when too long, because these ids end in the part
    that makes them unique (the chunk number) and start with a shard name that
    is often a long shared prefix."""
    out = re.sub(r"[^A-Za-z0-9_-]", "_", s)
    if len(out) > 64:
        out = out[-64:]
    return out or "_"
