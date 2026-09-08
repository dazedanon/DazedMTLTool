#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
store.py — the translation store and glossary.

Layout (default `tools/tl/`):

    glossary.json                 {"names": {...}, "terms": {...}, "meta": {...}}
    game_prompt.md                per-game bible, cached into every request
    playmaker_param_types.json    derived paramDataType -> column mapping
    <Bucket>.json                 {"meta": {...}, "units": [unit, ...]}
    _batch_state.json             transient Anthropic batch bookkeeping

A *unit* is one UNIQUE Japanese string:

    {
      "id":     "Menu:1a2b3c4d",        # bucket + sha1(raw)[:8], stable across re-extracts
      "kind":   "subtitle",             # subtitle|message|ui|screen|stagename|stagehint|controlhint
      "raw":    "…",                    # EXACT game string — the runtime dictionary key
      "src":    "…",                    # `raw` with markup masked to ⟦n⟧, shown to the model
      "codes":  {"⟦0⟧": "<color=#f00>"},
      "ctx":    "Balloon_Announce / FSM Talk / state 00A",
      "n":      12,                     # total occurrences in the export
      "sites":  [{"file":…, "line":…, "site":…, "obj":…}, …],   # capped, for context only
      "tl":     ""
    }

Units are deduped by `raw` GLOBALLY: delivery is a runtime JP->EN dictionary, so
one Japanese string can only ever map to one English string. Every occurrence is
still recorded in `sites` so the translator sees each place it is used.
"""

import glob
import hashlib
import json
import os
import re

GLOSSARY_NAME = "glossary.json"
STATE_NAME = "_batch_state.json"
PROMPT_NAMES = ("game_prompt.md", "game_prompt.txt")
_RESERVED = {GLOSSARY_NAME, STATE_NAME, "playmaker_param_types.json",
             "manual_denylist.json"}

MAX_SITES = 6      # per unit; context only, so a cap keeps the store readable


def unit_id(bucket: str, raw: str, salt: str = "") -> str:
    """Stable id from the source string, so re-extracting keeps existing work.

    `salt` separates units that share a source string but not a role — a CSV line
    can appear both as a subtitle and as the narrator's commentary, and those get
    independent translations.
    """
    h = hashlib.sha1((salt + "\x00" + raw).encode("utf-8")).hexdigest()[:8]
    return f"{bucket}:{h}"


def sanitize_id(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_:.\-]", "_", s)


# --------------------------------------------------------------------------
# IO
# --------------------------------------------------------------------------
def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def doc_path(store_dir, bucket):
    return os.path.join(store_dir, bucket + ".json")


def save_doc(store_dir, bucket, units, meta=None):
    obj = {"meta": dict(meta or {}, bucket=bucket), "units": units}
    _write_json(doc_path(store_dir, bucket), obj)
    return obj


def load_docs(store_dir):
    docs = []
    for p in sorted(glob.glob(os.path.join(store_dir, "*.json"))):
        if os.path.basename(p) in _RESERVED:
            continue
        docs.append((p, _read_json(p)))
    return docs


def save_docs(docs):
    for p, doc in docs:
        _write_json(p, doc)


def existing_translations(store_dir, bucket=None):
    """{raw: tl} from whatever is already in the store — survives re-extraction.

    With `bucket`, only that bucket's translations are returned, which keeps a CSV's
    per-file translations from leaking into a different file's context.
    """
    out = {}
    if not os.path.isdir(store_dir):
        return out
    for _p, doc in load_docs(store_dir):
        if bucket and doc.get("meta", {}).get("bucket") != bucket:
            continue
        for u in doc.get("units", []):
            tl = (u.get("tl") or "").strip()
            if tl:
                out[u.get("raw", "")] = u["tl"]
    return out


# --------------------------------------------------------------------------
# glossary
# --------------------------------------------------------------------------
def glossary_path(store_dir):
    return os.path.join(store_dir, GLOSSARY_NAME)


def load_glossary(store_dir):
    p = glossary_path(store_dir)
    g = _read_json(p) if os.path.exists(p) else {}
    g.setdefault("names", {})
    g.setdefault("terms", {})
    g.setdefault("meta", {})
    return g


def save_glossary(store_dir, glossary):
    _write_json(glossary_path(store_dir), glossary)


def name_en(value):
    if isinstance(value, dict):
        return (value.get("en") or "").strip()
    return value.strip() if isinstance(value, str) else ""


def name_needs_tl(value):
    return not name_en(value)


def set_name(glossary, jp, en, gender=None):
    cur = glossary["names"].get(jp)
    if isinstance(cur, dict):
        cur["en"] = en
        if gender and not cur.get("gender"):
            cur["gender"] = gender
    elif gender:
        glossary["names"][jp] = {"en": en, "gender": gender}
    else:
        glossary["names"][jp] = en


def load_game_prompt(store_dir):
    for name in PROMPT_NAMES:
        p = os.path.join(store_dir, name)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return f.read().strip()
    return ""


# --------------------------------------------------------------------------
# batch state
# --------------------------------------------------------------------------
def state_path(store_dir):
    return os.path.join(store_dir, STATE_NAME)


def save_state(store_dir, state):
    _write_json(state_path(store_dir), state)


def load_state(store_dir):
    p = state_path(store_dir)
    return _read_json(p) if os.path.exists(p) else None
