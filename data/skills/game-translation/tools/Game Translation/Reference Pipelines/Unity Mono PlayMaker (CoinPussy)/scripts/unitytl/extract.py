#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract.py — pull every player-facing Japanese string out of an AssetRipper export.

The game (コイン☆プッシー / Kujira1Percent, Unity Mono) has NO localization system
and NO hardcoded strings in Assembly-CSharp: all logic is PlayMaker FSMs, and all
text lives in exactly three places, established by a full census of the export
(`tools/logs/census.txt` — 24 JP-bearing YAML paths across 8,136 files):

  1. `m_Text`  on UnityEngine.UI.Text components
  2. `m_text`  on TextMeshPro components
  3. PlayMaker FSMs — action string params, and FSM string-variable defaults

Everything else that contains Japanese is an identifier: FSM state names,
GameObject/Material/Mesh/Sprite/AnimationClip names, animator triggers and
condition events, animation binding paths, blendshape names, the font atlas
character set, and PlayMaker action `description` designer notes.

Precision comes from decoding PlayMaker's packed parameter table (see pmparams)
so each string is attributed to an exact (action, parameter) site. Display sites
are allow-listed; key sites are deny-listed; anything unrecognised is EXCLUDED
but written to `excluded.jsonl` with a reason, so a re-run after a game update
surfaces new sites instead of silently dropping or mistranslating them.

Strings used at a key site (StringSwitch comparison, animator trigger, FSM name,
ES3 save key) are not translatable on their own. A few are used BOTH ways — a
speaker-name label that also drives a StringSwitch. Those stay in the store and
are flagged `collides_with_key`: delivery hooks the `Text`/`TMP_Text` setter,
which runs after every FSM comparison, so the switch still sees Japanese. The
flag exists so the plugin restricts them to exact-match replacement and never
substring/compose replacement.
"""

import json
import os
import re
import time
from collections import Counter, OrderedDict

from . import codes, csvtext, pmparams, store, uyaml

# --------------------------------------------------------------------------
# site classification
# --------------------------------------------------------------------------
# (PlayMaker action short name, parameter name) -> unit kind. These are the sites
# that actually push a string into a UI component or into a variable that a UI
# component later reads.
DISPLAY_SITES = {
    ("setTextmeshProUGUIText", "textString"): "subtitle",
    ("UiTextSetText", "text"): "ui",
    ("SetStringValue", "stringValue"): "message",
    ("BuildString", "stringParts"): "message",
    ("StringAddNewLine", "stringParts"): "message",
    ("SetFsmString", "setValue"): "message",
}

# Sites whose strings are engine keys — not translatable in their own right
# (see the module docstring for the both-ways case).
KEY_SITES = {
    ("StringSwitch", "compareTo"),
    ("SetAnimatorTrigger", "trigger"),
    ("SetAnimatorBool", "parameter"),
    ("SetAnimatorFloat", "parameter"),
    ("SetAnimatorInt", "parameter"),
    ("PlayAnimation", "animName"),
    ("CrossFadeAnimation", "animName"),
}

# Parameter names that are always keys/identifiers regardless of action.
KEY_PARAM_NAMES = frozenset({
    "fsmName", "eventTarget", "sendEvent", "finishEvent", "errorEvent",
    "trigger", "parameter", "stateName", "layerName", "animName", "variableName",
    "key", "keys", "path", "directory", "tag", "objectName", "gameObjectName",
    "property", "propertyName", "methodName", "behaviour", "component",
    "compareTo", "sceneName", "prefabName", "resourceName", "poolName",
})

# FSM string-variable names that hold display text. The rest of this game's string
# variables are animation-state keys (`SetStage NN / Animation`) or runtime slots.
VAR_NAME_KINDS = (
    (re.compile(r"^Text\s*Name\b", re.I), "stagename"),
    (re.compile(r"^Text\s*explain\b", re.I), "stagehint"),
    (re.compile(r"^Text\s*[/]?\s*(Pad|Key|Mouse)\b", re.I), "controlhint"),
    (re.compile(r"^Text\b", re.I), "ui"),
)

ASSET_EXTS = (".unity", ".prefab", ".asset")

# Which store bucket a source file belongs to. Scenes get their own bucket so a
# translation request stays inside one scene's context.
def bucket_for(rel: str) -> str:
    parts = rel.replace("\\", "/").split("/")
    if parts[0] == "Scenes" and parts[-1].endswith(".unity"):
        return os.path.splitext(parts[-1])[0]
    if parts[0] == "GameObject":
        return "Prefabs"
    return parts[0] or "Misc"


_DOC_RE = re.compile(r"^--- !u!(\d+) &(-?\d+)")
_FILEID_RE = re.compile(r"\{fileID: (-?\d+)")
_KV_RE = re.compile(r"^(?:- )?([A-Za-z_][A-Za-z0-9_]*):(?:\s(.*))?$")


def _gameobject_names(path):
    """{fileID: m_Name} for every GameObject document in the file.

    A separate pass because a MonoBehaviour can reference its GameObject before
    that GameObject's own document appears.
    """
    names = {}
    cur = None
    for _ln, indent, text in uyaml.iter_lines(path):
        m = _DOC_RE.match(text)
        if m:
            cur = m.group(2) if m.group(1) == "1" else None
            continue
        if cur and indent == 2 and text.startswith("m_Name:"):
            names[cur] = uyaml.decode_scalar(text[len("m_Name:"):])
            cur = None
    return names


class Hit:
    """One occurrence of one Japanese string at one site."""

    __slots__ = ("raw", "kind", "site", "obj", "ctx", "rel", "line", "reason")

    def __init__(self, raw, kind, site, obj, ctx, rel, line, reason=""):
        self.raw, self.kind, self.site = raw, kind, site
        self.obj, self.ctx, self.rel, self.line = obj, ctx, rel, line
        self.reason = reason


def scan_file(path, rel, mapping):
    """Yield Hit for every Japanese string in one asset file.

    `kind` is "" for a rejected hit; `reason` then says why. Nothing is dropped
    silently — the caller logs every rejection.
    """
    go_names = _gameobject_names(path)

    doc_class = None
    go_id = None
    fsm_indent = None
    fsm_name = ""
    cur_state = ""
    var_list = None          # which typed variable list we are inside
    var_name = ""
    ad_buf = None
    ad_base = 0
    ad_line = 0

    def obj_name():
        return go_names.get(go_id, "") if go_id else ""

    def flush_actiondata():
        """Decode the buffered actionData block into hits."""
        blk, _ = uyaml.parse_block(ad_buf, 0, ad_base + 2, ad_line)
        ad = pmparams.ActionData(blk)
        ctx = " / ".join(x for x in (obj_name(), f"FSM {fsm_name}" if fsm_name else "",
                                    f"state {cur_state}" if cur_state else "") if x)
        for action, pname, _col, _pos, rawv in ad.string_params(mapping):
            val = uyaml.decode_scalar(rawv)
            if not codes.has_jp(val):
                continue
            short = action.rsplit(".", 1)[-1]
            site = f"{short}.{pname}"
            if (short, pname) in KEY_SITES or pname in KEY_PARAM_NAMES:
                yield Hit(val, "", site, obj_name(), ctx, rel, ad_line, "key-site")
                continue
            kind = DISPLAY_SITES.get((short, pname))
            if kind:
                yield Hit(val, kind, site, obj_name(), ctx, rel, ad_line)
            else:
                yield Hit(val, "", site, obj_name(), ctx, rel, ad_line, "unknown-site")

    for lineno, indent, text in uyaml.iter_lines(path):
        if ad_buf is not None:
            if indent > ad_base:
                ad_buf.append((lineno, indent, text))
                continue
            yield from flush_actiondata()
            ad_buf = None

        m = _DOC_RE.match(text)
        if m:
            doc_class = m.group(1)
            go_id = None
            fsm_indent = None
            fsm_name = ""
            cur_state = ""
            var_list = None
            continue

        if fsm_indent is not None and indent <= fsm_indent and text != "fsm:":
            fsm_indent = None
            var_list = None

        if doc_class != "114":       # MonoBehaviour
            continue

        if indent == 2:
            if text.startswith("m_GameObject:"):
                g = _FILEID_RE.search(text)
                if g:
                    go_id = g.group(1)
                continue
            if text == "fsm:":
                fsm_indent = indent
                continue
            for field, kindname in (("m_Text:", "uitext"), ("m_text:", "tmp")):
                if text.startswith(field):
                    val = uyaml.decode_scalar(text[len(field):])
                    if codes.has_jp(val):
                        kind = "screen" if (codes.line_count(val) > 1 or len(val) > 24) else "ui"
                        yield Hit(val, kind, field.rstrip(":"), obj_name(),
                                  obj_name(), rel, lineno)
                    break
            continue

        if fsm_indent is None:
            continue

        if indent == fsm_indent + 2:
            if text.startswith("- name:"):
                cur_state = uyaml.decode_scalar(text[len("- name:"):])
            elif text.startswith("name:"):
                fsm_name = uyaml.decode_scalar(text[len("name:"):])
            elif text == "variables:":
                var_list = ""
            elif _KV_RE.match(text):
                var_list = None
            continue

        if var_list is not None and indent == fsm_indent + 4:
            if text.endswith("Variables:") or text.endswith("Variables: []"):
                var_list = text.split(":", 1)[0]
            elif text.startswith("- "):
                var_name = ""
            continue

        if var_list == "stringVariables" and indent == fsm_indent + 6:
            if text.startswith("name:"):
                var_name = uyaml.decode_scalar(text[len("name:"):])
            elif text.startswith("value:"):
                val = uyaml.decode_scalar(text[len("value:"):])
                if codes.has_jp(val):
                    kind = ""
                    for rx, k in VAR_NAME_KINDS:
                        if rx.match(var_name or ""):
                            kind = k
                            break
                    site = f"fsmvar:{var_name}"
                    ctx = " / ".join(x for x in (obj_name(), f"FSM {fsm_name}" if fsm_name else "") if x)
                    yield Hit(val, kind, site, obj_name(), ctx, rel, lineno,
                              "" if kind else "non-text-variable")
            continue

        if indent == fsm_indent + 4 and text == "actionData:":
            ad_buf, ad_base, ad_line = [], indent, lineno

    if ad_buf is not None:
        yield from flush_actiondata()


# --------------------------------------------------------------------------
# store construction
# --------------------------------------------------------------------------
def _list_assets(assets_dir):
    files = []
    for dp, _dn, fns in os.walk(assets_dir):
        for fn in fns:
            if fn.lower().endswith(ASSET_EXTS):
                files.append(os.path.join(dp, fn))
    files.sort()
    return files


def extract_csvs(textasset_dir, store_dir, verbose=True):
    """Build the CSV buckets from the dumped TextAssets. Returns (buckets, stats)."""
    if not os.path.isdir(textasset_dir):
        return {}, {}
    buckets, stats = {}, {}
    for name in sorted(csvtext.POLICY):
        path = os.path.join(textasset_dir, name)
        if not os.path.exists(path):
            if verbose:
                print(f"  ! missing {name} — run tools/scripts/dump_textassets.py")
            continue
        pol = csvtext.POLICY[name]
        carried = store.existing_translations(store_dir, pol["bucket"])
        bucket, units, st = csvtext.extract_file(path, carried)
        for u in units:
            u["id"] = store.unit_id(bucket, u["raw"], u["kind"])
        buckets[bucket] = units
        stats[name] = st
        store.save_doc(store_dir, bucket, units,
                       {"source_csv": name, "n_units": len(units), **st})
        if verbose:
            print(f"  {name:32s} rows={st['rows']:5d} units={st['units']:5d} "
                  f"cells={st['cells']:5d}")
    return buckets, stats


def extract_store(assets_dir, store_dir, out_dir, textasset_dir=None, verbose=True):
    """Scan the export, (re)build the store, and write the reports.

    Returns a summary dict. Existing translations are carried over by exact source
    string, so re-extracting after a game update never loses finished work.
    """
    os.makedirs(out_dir, exist_ok=True)
    mapping = pmparams.load_mapping(store_dir)
    if not mapping:
        raise SystemExit("No PlayMaker param mapping — run `tl.py derive` first.")

    carried = store.existing_translations(store_dir)
    files = _list_assets(assets_dir)

    units = OrderedDict()        # raw -> unit dict
    excluded = OrderedDict()     # raw -> {reason, sites, n}
    key_strings = set()          # raw seen at a key site
    site_counts = Counter()
    t0 = time.time()

    for i, path in enumerate(files):
        rel = os.path.relpath(path, assets_dir)
        bucket = bucket_for(rel)
        for h in scan_file(path, rel, mapping):
            site_counts[(h.site, h.kind or "-" + (h.reason or "?"))] += 1
            if not h.kind:
                if h.reason == "key-site":
                    key_strings.add(h.raw)
                e = excluded.setdefault(h.raw, {"reason": h.reason, "n": 0, "sites": []})
                e["n"] += 1
                if len(e["sites"]) < store.MAX_SITES:
                    e["sites"].append({"file": rel, "line": h.line, "site": h.site,
                                       "obj": h.obj})
                continue
            u = units.get(h.raw)
            if u is None:
                src, cmap = codes.mask(h.raw)
                u = {
                    "id": store.unit_id(bucket, h.raw),
                    "kind": h.kind,
                    "raw": h.raw,
                    "src": src,
                    "codes": cmap,
                    "ctx": h.ctx,
                    "n": 0,
                    "sites": [],
                    "tl": carried.get(h.raw, ""),
                    "_bucket": bucket,
                }
                units[h.raw] = u
            u["n"] += 1
            # A subtitle/screen classification always wins over a bare `ui` one:
            # the same string can be set both by a generic label and by a dialogue
            # action, and the richer kind gives the model better instructions.
            if u["kind"] == "ui" and h.kind in ("subtitle", "screen", "message"):
                u["kind"] = h.kind
            if len(u["sites"]) < store.MAX_SITES:
                u["sites"].append({"file": rel, "line": h.line, "site": h.site,
                                   "obj": h.obj})
        if verbose and i % 1000 == 0:
            print(f"  scanned {i}/{len(files)} ({time.time() - t0:.0f}s)", flush=True)

    # Strings that are BOTH displayed and used as an engine key (speaker-name
    # labels that also drive a StringSwitch, the 終了 menu label). They stay
    # translatable: delivery hooks the `Text`/`TMP_Text` setter, which runs after
    # every FSM comparison, so the switch still sees Japanese. They are flagged so
    # the plugin never applies substring/compose replacement to them — only exact.
    collisions = []
    for raw in units:
        if raw in key_strings:
            units[raw]["collides_with_key"] = True
            u = units[raw]
            collisions.append({"raw": raw, "kind": u["kind"], "n": u["n"],
                               "sites": u["sites"]})

    # Write per-bucket docs, preserving discovery order inside each bucket.
    by_bucket = OrderedDict()
    for u in units.values():
        by_bucket.setdefault(u.pop("_bucket"), []).append(u)
    for b, us in by_bucket.items():
        store.save_doc(store_dir, b, us, {"assets_dir": assets_dir, "n_units": len(us)})

    csv_dir = textasset_dir or os.path.join(os.path.dirname(out_dir), "extracted", "textassets")
    if not os.path.isdir(csv_dir):
        csv_dir = os.path.join(out_dir, "textassets")
    if verbose:
        print("Scripted-dialogue CSVs:")
    csv_buckets, csv_stats = extract_csvs(csv_dir, store_dir, verbose)

    _write_reports(out_dir, units, excluded, collisions, site_counts, by_bucket,
                   len(files), csv_buckets, csv_stats)
    return {
        "files": len(files),
        "csv_units": sum(len(v) for v in csv_buckets.values()),
        "csv_cells": sum(st["cells"] for st in csv_stats.values()),
        "csv_buckets": {b: len(v) for b, v in csv_buckets.items()},
        "csv_kinds": Counter(u["kind"] for v in csv_buckets.values() for u in v),
        "units": len(units),
        "buckets": {b: len(us) for b, us in by_bucket.items()},
        "excluded": len(excluded),
        "collisions": len(collisions),
        "carried": sum(1 for u in units.values() if u["tl"]),
        "kinds": Counter(u["kind"] for u in units.values()),
    }


def _write_reports(out_dir, units, excluded, collisions, site_counts, by_bucket,
                   nfiles, csv_buckets=None, csv_stats=None):
    def w(name, text):
        p = os.path.join(out_dir, name)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    ordered = list(units.values())
    w("jp_all_strings.txt",
      "".join(u["raw"].replace("\r\n", "\\r\\n").replace("\n", "\\n").replace("\r", "\\r") + "\n"
              for u in ordered))

    with open(os.path.join(out_dir, "strings.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump([{k: u[k] for k in ("id", "kind", "raw", "src", "codes", "ctx", "n", "sites")
                    if k in u} for u in ordered], f, ensure_ascii=False, indent=2)

    with open(os.path.join(out_dir, "excluded.jsonl"), "w", encoding="utf-8", newline="\n") as f:
        for raw, e in excluded.items():
            f.write(json.dumps({"raw": raw, **e}, ensure_ascii=False) + "\n")

    with open(os.path.join(out_dir, "key_strings.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"note": "Never translate these — used as StringSwitch/animator/"
                           "FSM keys. Kept for the runtime hook's denylist.",
                   "strings": sorted({e_raw for e_raw, e in excluded.items()
                                      if e["reason"].endswith("key-site")}),
                   "display_and_key_collisions": collisions},
                  f, ensure_ascii=False, indent=2)

    csv_buckets = csv_buckets or {}
    csv_stats = csv_stats or {}
    csv_units = [u for v in csv_buckets.values() for u in v]

    if csv_units:
        with open(os.path.join(out_dir, "csv_strings.json"), "w", encoding="utf-8",
                  newline="\n") as f:
            json.dump([{k: u[k] for k in ("id", "kind", "raw", "src", "codes", "speaker",
                                          "scene", "event", "col", "cells") if k in u}
                       for u in csv_units], f, ensure_ascii=False, indent=2)
        w("jp_csv_strings.txt",
          "".join(u["raw"].replace("\r\n", "\\r\\n").replace("\n", "\\n")
                  .replace("\r", "\\r") + "\n" for u in csv_units))

    kinds = Counter(u["kind"] for u in ordered)
    markup = Counter()
    for u in ordered + csv_units:
        for tok in codes.markup_tokens(u["raw"]):
            markup[tok] += 1
    multiline = sum(1 for u in ordered if codes.line_count(u["raw"]) > 1)
    chars = sum(len(u["raw"]) for u in ordered)

    csv_chars = sum(len(u["raw"]) for u in csv_units)
    lines = [
        "CoinPussy — text extraction report",
        "",
        "A. asset-embedded text (UI.Text / TextMeshPro / PlayMaker FSMs)",
        f"   asset files scanned    : {nfiles}",
        f"   unique translatable JP : {len(ordered)}",
        f"   JP characters          : {chars:,}",
        f"   multiline strings      : {multiline}",
        f"   excluded (logged)      : {len(excluded)}",
        f"   display/key collisions : {len(collisions)}  (kept; exact-match replacement only)",
        "",
        "B. scripted dialogue (TextAsset CSVs in resources.assets)",
    ]
    for name, st in sorted(csv_stats.items()):
        lines.append(f"   {name:32s} rows={st['rows']:5d} units={st['units']:5d} "
                     f"cells={st['cells']:5d}")
    lines += [
        f"   CSV units total        : {len(csv_units)}",
        f"   CSV JP characters      : {csv_chars:,}",
        "",
        f"TOTAL translatable units : {len(ordered) + len(csv_units)}",
        f"TOTAL JP characters      : {chars + csv_chars:,}",
        "",
        "asset buckets:",
    ]
    for b, us in sorted(by_bucket.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"  {len(us):6d}  {b}")
    if csv_buckets:
        lines += ["", "CSV buckets:"]
        for b, v in sorted(csv_buckets.items(), key=lambda kv: -len(kv[1])):
            lines.append(f"  {len(v):6d}  {b}")
    lines += ["", "by kind:"]
    for k, n in (kinds + Counter(u["kind"] for u in csv_units)).most_common():
        lines.append(f"  {n:6d}  {k}")
    lines += ["", "markup tokens found in translatable text (masked to \u27e6n\u27e7):"]
    if markup:
        for tok, n in markup.most_common(40):
            lines.append(f"  {n:6d}  {tok}")
    else:
        lines.append("  (none)")
    lines += ["", "sites (site -> kind, occurrence count):"]
    for (site, kind), n in site_counts.most_common(60):
        lines.append(f"  {n:7d}  {site:44s} {kind}")
    w("extract_report.txt", "\n".join(lines) + "\n")
