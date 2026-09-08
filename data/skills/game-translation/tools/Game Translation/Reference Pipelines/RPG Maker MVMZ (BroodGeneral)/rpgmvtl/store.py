#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
store.py — the intermediate translation store and glossary.

The store is a directory (default: tooling/tl/) holding:

  glossary.json          { "names": {jp: en}, "terms": {jp: en}, "meta": {...} }
  <SourceName>.json      { "meta": {...}, "units": [ unit, ... ] }   (one per data file)
  _batch_state.json      transient Anthropic batch bookkeeping

A *unit* is one translatable thing:

  {
    "id":   "CommonEvents:ev12:p0:c1",   # informational, stable, human-readable
    "kind": "text",                       # text|choice|name|nickname|profile|
                                          #   desc|message|term|title|currency|
                                          #   mapname|note
    "ptr":  ["events", 3, "pages", 0, "list"],   # JSON pointer into the file data
    "block": {"start": 1, "count": 2},    # text blocks only: span within the list
    "speaker": "クロア",                   # raw speaker (text only)
    "ctx":  "ショップ選択画面処理",         # context label for the model
    "codes": {"⟦0⟧": "\\i[327]"},          # placeholder -> original control code
    "prefix": "\\kw[{name}]",              # speaker markup template (text only)
    "src":  "なにか交換できたかしら？",      # cleaned+masked JP shown to the model
    "raw":  "\\kw[クロア]なにか…",          # original string(s) for verification
    "tl":   ""                             # translation (filled by batch step)
  }

Character names are NOT stored as units; they live in glossary["names"] and are
the single source of truth for consistency across dialogue, name windows, and
the Actors file.
"""

import os
import re
import glob
import json

GLOSSARY_NAME = "glossary.json"
STATE_NAME = "_batch_state.json"
_RESERVED = {GLOSSARY_NAME, STATE_NAME}


# --------------------------------------------------------------------------
# JSON pointer (list of str keys / int indices) into a parsed JSON document
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
# IO
# --------------------------------------------------------------------------
def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    # Atomic-ish write (temp + replace) to avoid truncation on crash.
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def doc_path(store_dir, source_file):
    """tl/<SourceName>.json for a given data file name (e.g. CommonEvents.json)."""
    stem = os.path.splitext(os.path.basename(source_file))[0]
    return os.path.join(store_dir, stem + ".json")


def save_doc(store_dir, source_file, units, meta=None):
    obj = {"meta": dict(meta or {}, source_file=source_file), "units": units}
    _write_json(doc_path(store_dir, source_file), obj)
    return obj


def load_docs(store_dir):
    """Return [(path, doc), ...] for every unit file in the store (sorted)."""
    docs = []
    for p in sorted(glob.glob(os.path.join(store_dir, "*.json"))):
        if os.path.basename(p) in _RESERVED:
            continue
        docs.append((p, _read_json(p)))
    return docs


def save_docs(docs):
    for p, doc in docs:
        _write_json(p, doc)


# --------------------------------------------------------------------------
# Glossary
# --------------------------------------------------------------------------
def glossary_path(store_dir):
    return os.path.join(store_dir, GLOSSARY_NAME)


def load_glossary(store_dir):
    p = glossary_path(store_dir)
    if os.path.exists(p):
        g = _read_json(p)
    else:
        g = {}
    g.setdefault("names", {})
    g.setdefault("terms", {})
    g.setdefault("meta", {})
    return g


def save_glossary(store_dir, glossary):
    _write_json(glossary_path(store_dir), glossary)


# A glossary name value may be a plain string ("Kuroa") or a rich character
# entry: {"en": "Kuroa", "gender": "female", "role": "...", "register": "...",
#         "aliases": [...], "note": "..."}.  These helpers accept either form.
def name_en(value):
    if isinstance(value, dict):
        return (value.get("en") or "").strip()
    return (value or "").strip() if isinstance(value, str) else ""


def name_lookup(glossary, jp):
    """Translated name for a raw JP speaker/actor name, or the original if absent."""
    en = name_en(glossary.get("names", {}).get(jp))
    return en or jp


def name_needs_tl(value):
    return not name_en(value)


def set_name(glossary, jp, en, gender=None):
    """Write a translated name (and optional gender), preserving entry shape."""
    cur = glossary["names"].get(jp)
    if isinstance(cur, dict):
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
    _write_json(state_path(store_dir), state)


def load_state(store_dir):
    p = state_path(store_dir)
    if not os.path.exists(p):
        return None
    return _read_json(p)


# --------------------------------------------------------------------------
# misc
# --------------------------------------------------------------------------
def sanitize_id(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_:.\-]", "_", s)
