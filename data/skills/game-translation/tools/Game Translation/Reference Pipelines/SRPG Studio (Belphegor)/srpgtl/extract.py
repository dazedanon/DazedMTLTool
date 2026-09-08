#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract.py — pull translatable text out of the SRPG Studio (Belphegor) game into
the rpgmvtl-style store + glossary, so the shared batch engine can translate it.

Two sources, one store:
  1. The SRPG_Unpacker translation patch  (patch/*.json)  — dialogue, names,
     descriptions, win/lose conditions, info windows, UI command labels, story
     pages, customParameters (escort/glossary strings).
  2. js_strings.json  — hardcoded player-facing JP in the plugin/engine .js files
     (from js_text_tool.py).

Design:
  * Dialogue (message `data`, info windows) is stored PER MAP, scene-grouped (so
    the model sees a coherent run of lines with their speakers).
  * Names / descriptions / UI / story-pages / conditions are DEDUPED globally
    (one unit per unique JP string; injected to every occurrence).
  * customParameters values are JS object literals (`{escort_word:'護衛：ルート',
    range:1}`); only the single-quoted JP substrings are extracted as units.
  * Plugin strings come straight from js_strings.json.
  * Control codes (\\C[n] colour, \\v[n] var, \\B \\f …) are masked to ⟦k⟧ exactly
    like the RPG Maker engine. Real newlines are kept as line breaks.
  * Character names (everything that ever appears as a message `speaker`) are
    seeded into glossary["names"] and NOT emitted as name units — the glossary is
    the single source of truth for those, for voice/pronoun/name-box consistency.
"""

import os
import re
import json
import glob

from . import codes, store

# ---- which keys carry translatable text, and the unit kind they map to -------
KEY_KIND = {
    "data": "text",            # message dialogue (has a speaker)
    "msg": "text",
    "infoText": "info",        # action-log / info window
    "name": "name",
    "desc": "desc",
    "description": "desc",
    "victoryConds": "cond",
    "defeatConds": "cond",
    "pages": "pages",          # story / dictionary pages (multi-line narration)
    "commandName": "ui",
    "command": "ui",
    "mapName": "ui",
    "windowTitle": "title",
    "gameTitle": "title",
    "saveFileTitle": "title",
    "rewardData": "ui",
}
# Keys explicitly NOT translated: speaker (context only), comment (dev notes),
# fontName (font face names), plus anything not in KEY_KIND.
SKIP_KEYS = {"speaker", "comment", "fontName"}

JP = codes.JP_RE
# single-quoted substring inside a customParameters JS literal
_SQ_RE = re.compile(r"'([^'\\]*(?:\\.[^'\\]*)*)'")

# --- plugin-string denylist: skip NON-player-facing JS strings so they're never
# translated (translating an asset filename or an internal trigger-id breaks the
# game). Default is KEEP (UI/StringTable/EC_DefineString text is player-facing).
_ASSET_EXT = re.compile(r"\.(png|jpg|jpeg|bmp|gif|ogg|wav|mp3|mp4|webm|m4a|avi|ttf|otf|json|js|txt|csv|dat|res|mid|webp)$", re.I)
_LOG_CTX = re.compile(r"\b(?:EC_Putlog|console\.(?:log|warn|error|info)|root\.log)\s*\(")
_ASSETLOAD_CTX = re.compile(r"getMaterialManager|createImage|createObject|loadImage|getImageCache|getGraphicsManager|getMaterial\b|\.png|\.ogg")
_COMPARE_CTX = re.compile(r"[=!]==|===|!==")  # `strw === 'x'` etc. -> the string is an internal id


def _internal_ctx(o, ctx):
    """This specific occurrence is a non-display use (asset/path/log/compare/load)."""
    if _ASSET_EXT.search(o) or "/" in o or "\\" in o:
        return True
    return bool(_LOG_CTX.search(ctx) or _COMPARE_CTX.search(ctx) or _ASSETLOAD_CTX.search(ctx))


def plugin_blacklist(js_data):
    """Originals that are EVER used as an internal key/asset/comparison/log arg.
    Such a string is an ID, so it must NOT be translated *anywhere* (e.g. a voice
    key used both as `=== '戦闘開始'` and as `VoiceBattle('戦闘開始')`)."""
    bl = set()
    for _f, entries in js_data.items():
        for e in entries:
            o = (e.get("original") or "").strip()
            if o and _internal_ctx(o, e.get("context") or ""):
                bl.add(o)
    return bl


def plugin_translatable(original, context, blacklist=frozenset()):
    """True if a js_strings.json entry is genuinely player-facing UI text."""
    o = (original or "").strip()
    if not (o and JP.search(o)):
        return False
    if o in blacklist:                                   # used as an ID somewhere
        return False
    if _internal_ctx(o, context or ""):                  # this occurrence is internal
        return False
    return True


def _clean_mask(raw):
    """clean + code-mask one JP string -> (src_for_model, code_map)."""
    cleaned = codes.clean_source(raw)
    masked, cm = codes.mask_codes(cleaned)
    return masked, cm


# --------------------------------------------------------------------------
# walk the patch
# --------------------------------------------------------------------------
def _collect_speakers(patch_dir):
    """Every distinct non-empty message `speaker` -> a character for the glossary."""
    speakers = {}
    for f in glob.glob(os.path.join(patch_dir, "**", "*.json"), recursive=True):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue

        def w(o):
            if isinstance(o, dict):
                if o.get("type") == "message":
                    sp = (o.get("speaker") or "").strip()
                    if sp and JP.search(sp):
                        speakers[sp] = speakers.get(sp, 0) + 1
                for v in o.values():
                    w(v)
            elif isinstance(o, list):
                for v in o:
                    w(v)
        w(d)
    return speakers


def _walk_strings(node, parent_key=None, parent=None, path=()):
    """Yield (raw_string, key, container_dict, path) for every string value. The
    container lets message text read its sibling `speaker`; the path lets us group
    a whole command-list (event page) into one translation "scene"."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk_strings(v, k, node, path + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk_strings(v, parent_key, parent, path + (i,))
    elif isinstance(node, str):
        yield node, parent_key, parent, path


def _scene_id(path):
    """Stable short id for the command-list (event page) containing a message, so
    consecutive dialogue lines share a scene. Path looks like
    (..., 'commands', <cmd>, 'data', 0); drop everything from the last 'commands'."""
    p = list(path)
    for marker in ("commands", "pages"):
        if marker in p:
            i = len(p) - 1 - p[::-1].index(marker)
            p = p[:i + 1]
            break
    else:
        p = p[:-2]
    return "_".join(str(x) for x in p)


def extract_store(patch_dir, js_strings_path, store_dir, wrap_note=""):
    """Build the store + seed the glossary. Returns (summary, glossary)."""
    os.makedirs(store_dir, exist_ok=True)
    glossary = store.load_glossary(store_dir)

    # Preserve any existing translations across a re-extract (game update / re-run):
    # carry tl forward by (kind, original-JP). The glossary is preserved by
    # store.load_glossary above.
    old_tl = {}
    for p in glob.glob(os.path.join(store_dir, "*.json")):
        b = os.path.basename(p)
        if b.startswith("_") or b in (store.GLOSSARY_NAME, store.STATE_NAME):
            continue
        try:
            for u in (json.load(open(p, encoding="utf-8")).get("units") or []):
                if u.get("tl", "").strip():
                    old_tl[(u.get("kind"), u.get("raw"))] = u["tl"]
        except Exception:
            pass

    # 1) seed character glossary from speakers (don't clobber existing entries)
    speakers = _collect_speakers(patch_dir)
    char_set = set(speakers)
    for sp, n in sorted(speakers.items(), key=lambda x: -x[1]):
        if sp not in glossary["names"]:
            glossary["names"][sp] = {"en": "", "gender": "", "role": "", "register": "", "note": f"speaker x{n}"}

    # global dedup buckets: (kind) -> {raw: unit}
    global_units = {}   # key (kind, raw) -> unit dict
    per_map = {}        # mapfile -> [units]  (dialogue/info, scene-grouped, not deduped)
    summary = []

    def global_unit(kind, raw):
        gk = (kind, raw)
        u = global_units.get(gk)
        if u is None:
            src, cm = _clean_mask(raw)
            u = {"id": "", "kind": kind, "src": src, "raw": raw, "codes": cm, "tl": old_tl.get(gk, "")}
            global_units[gk] = u
        return u

    # 2) walk every patch file
    for path in sorted(glob.glob(os.path.join(patch_dir, "**", "*.json"), recursive=True)):
        rel = os.path.relpath(path, patch_dir).replace("\\", "/")
        try:
            data = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        is_map = rel.startswith("Maps/")
        map_units = []

        for raw, key, container, path in _walk_strings(data):
            if key in SKIP_KEYS:
                continue
            # customParameters: JS object literal — pull only its quoted JP substrings
            if key == "customParameters" and raw and JP.search(raw):
                for m in _SQ_RE.finditer(raw):
                    val = m.group(1)
                    if JP.search(val):
                        global_unit("customparam", val)
                continue
            if key not in KEY_KIND:
                continue
            if not (raw and JP.search(raw)):
                continue
            kind = KEY_KIND[key]

            if kind in ("text", "info") and is_map:
                # per-map, grouped by event-page scene, with speaker
                sp = (container.get("speaker") or "").strip() if isinstance(container, dict) else ""
                src, cm = _clean_mask(raw)
                cidx = len(map_units)
                sk = store.sanitize_id(_scene_id(path))
                u = {"id": f"{_stem(rel)}:{sk}:c{cidx}", "kind": kind,
                     "src": src, "raw": raw, "codes": cm, "tl": old_tl.get((kind, raw), ""),
                     "speaker": sp, "ctx": sk}
                map_units.append(u)
            else:
                # global deduped (names, descs, ui, conds, pages, msg outside maps)
                global_unit(kind, raw)

        if map_units:
            per_map[rel] = map_units
            summary.append((rel, len(map_units)))

    # 3) plugin/engine JS strings (js_strings.json) -> plugin units (deduped by text)
    js_units = []
    skipped = 0
    if os.path.exists(js_strings_path):
        js = json.load(open(js_strings_path, encoding="utf-8"))
        bl = plugin_blacklist(js)
        seen = {}
        skipped = 0
        for jsfile, entries in js.items():
            for e in entries:
                raw = e.get("original", "")
                if not plugin_translatable(raw, e.get("context", ""), bl):
                    skipped += 1
                    continue
                if raw in seen:
                    continue
                src, cm = _clean_mask(raw)
                u = {"id": f"plugin:{len(js_units)}", "kind": "plugin",
                     "src": src, "raw": raw, "codes": cm, "tl": old_tl.get(("plugin", raw), "")}
                seen[raw] = u
                js_units.append(u)

    # 4) drop character names out of the global name bucket (glossary owns them)
    name_units = [u for (k, raw), u in global_units.items()
                  if k == "name" and raw not in char_set]
    other_global = [u for (k, raw), u in global_units.items() if k != "name"]

    # 5) assign stable ids to global docs, write everything
    def write_doc(name, units):
        for i, u in enumerate(units):
            if not u["id"]:
                u["id"] = f"{name}:{i}"
        store.save_doc(store_dir, name + ".json", units, meta={"kind_doc": name})
        return len(units)

    # dialogue: one store doc per map
    for rel, units in per_map.items():
        store.save_doc(store_dir, "dlg_" + _stem(rel) + ".json", units,
                       meta={"kind_doc": "dialogue", "map": rel})

    counts = {}
    counts["names"] = write_doc("names", name_units)
    counts["desc"] = write_doc("desc", [u for u in other_global if u["kind"] == "desc"])
    counts["ui"] = write_doc("ui", [u for u in other_global if u["kind"] in ("ui", "title", "cond", "pages")])
    counts["info_global"] = write_doc("info_misc", [u for u in other_global if u["kind"] in ("text", "info")])
    counts["customparams"] = write_doc("customparams", [u for u in other_global if u["kind"] == "customparam"])
    counts["plugins"] = write_doc("plugins", js_units)
    counts["plugins_skipped_nonfacing"] = skipped
    counts["dialogue"] = sum(len(v) for v in per_map.values())
    counts["maps_with_dialogue"] = len(per_map)
    counts["characters_seeded"] = len(char_set)

    store.save_glossary(store_dir, glossary)
    return summary, glossary, counts


def _stem(rel):
    return store.sanitize_id(os.path.splitext(os.path.basename(rel))[0])
