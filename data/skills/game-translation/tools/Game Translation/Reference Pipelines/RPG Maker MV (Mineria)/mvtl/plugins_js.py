#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
plugins_js.py - the `js/plugins.js` UI-text track.

This text is on a DIFFERENT track from `data/*.json`. Data flows
store -> export -> game; plugin parameters are edited IN PLACE in the game
folder. Mixing the two models means an export silently reverts an in-place
edit, or an in-place edit is lost on the next export. So this module keeps its
own ledger (`tl/plugins_js.json`) mapping a fully-qualified leaf path to its
Japanese source and English replacement, and writes only through
`json.JSONDecoder.raw_decode` on the `var $plugins = [...]` array so untouched
entries stay byte-identical.

One coupling in this game that nothing else would catch:

    LL_MenuScreenCustomMV.menuHelpTexts[i].symbol

is looked up as `menuHelpLists[this._commandWindow.currentName()]`
(LL_MenuScreenCustomMV.js:613) - keyed by the DISPLAYED command name, which
comes from `System.json terms.commands`. Translate the command and leave the
symbol, and every menu help line silently disappears. `MIRRORS` below declares
that dependency so `check` can prove the two agree.

And one string that must NOT be translated:

    MessageWindowHidden.triggerButton contains `右クリック`, which
    MessageWindowHidden.js:334 matches with `case '右クリック':`. Translating it
    disables right-click-to-hide with no error.
"""

import os
import re
import json
import shutil
import datetime

from . import codes, store

ARRAY_RE = re.compile(r"var\s+\$plugins\s*=\s*")

# Leaves worth translating, as {plugin: [parameter, ...]}. Every one was found
# by decoding each parameter recursively while its decoded value was still an
# object, an array or another serialized string - never by a blanket "find
# Japanese in the file" scan, which also hits note-tag keys and switch names
# that code reads back.
TRANSLATABLE = {
    "MasterVolumeOption": ["項目名称"],
    "gameEnd": ["endName"],
    "KMS_ShopInventory": ["Sold out text", "Caption for stock"],
    "TMMenuLabel": ["labelAName", "labelBName", "labelCName", "labelDName"],
    "TMMapHpGauge": ["gaugeA", "gaugeB"],           # JSON leaf: .name
    "LL_MenuScreenCustomMV": ["menuHelpTexts", "leftBlockLabel"],
    "NRP_GameWindowSize": ["optionName"],           # disabled plugin: latent
    "CTRS_TradeShop": ["tradeItemTanni"],           # disabled plugin: latent
}

# Leaves inside a parameter whose value is itself JSON.
JSON_LEAVES = {
    "TMMapHpGauge": {"gaugeA": ["name"], "gaugeB": ["name"]},
    "LL_MenuScreenCustomMV": {"menuHelpTexts": ["symbol", "helpText"]},
}

# `symbol` must equal the English used for the matching System.json
# terms.commands entry, because the plugin keys its help table by the DISPLAYED
# command name.
MIRRORS = {
    "LL_MenuScreenCustomMV.menuHelpTexts[].symbol": "System:terms:commands",
}

NEVER = {"右クリック"}

# Layout repairs, not translations. Where a widget's bound is itself a plugin
# PARAMETER, the right fix for English that no longer fits is to raise the
# bound - not to compress the words until the label stops meaning anything.
#
# The map HUD is the case that forces this. `Window_MapHpGauge.drawVnGauge`
# calls `drawVnCurrentAndMax`, which silently DROPS the `/max` half of the
# readout when the label plus the numbers no longer fit:
#
#     x3 = x + width - valueWidth - slashWidth - valueWidth
#     if (x3 >= x + labelWidth) { draw current, '/', max } else { draw current }
#
# At fontSize 25 a half-width cell is 12.5px. 淫乱度 is 3 full-width glyphs =
# 75px and clears the 82.5px budget at width 195. "Lewdness" is 8 half-width
# glyphs = 100px and does not - so the English build would quietly lose the
# maximum from the gauge, with no error and nothing for a text check to see.
# Widening gaugeA to 250 puts the budget at 137.5px, and gaugeB and the window
# move to match. The screen is 1020px wide; the widened window ends at 540.
LAYOUT_OVERRIDES = {
    "TMMapHpGauge": {
        "gaugeA.width": ("250", "'Lewdness' is 100px at fontSize 25 and needs "
                                "a 137.5px budget to keep the /max readout"),
        "gaugeB.x": ("290", "moved right of the widened gaugeA (20..270)"),
        "gaugeWindowWidth": ("540", "gaugeB now ends at 510"),
    },
}

LEDGER = "plugins_js.json"


# --------------------------------------------------------------------------
def parse_plugins(path):
    """(prefix, entries, raw_entries, suffix) with each entry's original bytes."""
    text = open(path, encoding="utf-8-sig").read()
    m = ARRAY_RE.search(text)
    if not m:
        raise ValueError("no `var $plugins =` in %s" % path)
    start = text.index("[", m.end() - 1)
    arr, end = json.JSONDecoder().raw_decode(text, start)
    trailer = text[end:].lstrip()
    if not trailer.startswith(";"):
        raise ValueError("plugins array is not followed by ';'")
    if not isinstance(arr, list) or not all(isinstance(e, dict) for e in arr):
        raise ValueError("plugins array is not a list of objects")
    return text[:start], arr, text[end:], start, end


def _leaves(entry, plugin, ledger, collect):
    """Walk this plugin's whitelisted parameters, yielding (path, value)."""
    params = entry.get("parameters") or {}
    for key in TRANSLATABLE.get(plugin, []):
        if key not in params:
            continue
        raw = params[key]
        if not isinstance(raw, str):
            continue
        sub = (JSON_LEAVES.get(plugin) or {}).get(key)
        if sub:
            for path, val in _json_leaves(raw, sub, "%s.%s" % (plugin, key)):
                collect(path, val)
        elif codes.has_jp(raw):
            collect("%s.%s" % (plugin, key), raw)


def _decode(s):
    try:
        v = json.loads(s)
    except Exception:
        return None
    return v


def _json_leaves(raw, keys, prefix):
    v = _decode(raw)
    out = []
    if isinstance(v, list):
        for i, item in enumerate(v):
            o = _decode(item) if isinstance(item, str) else item
            if isinstance(o, dict):
                for k in keys:
                    val = o.get(k)
                    if isinstance(val, str) and codes.has_jp(val):
                        out.append(("%s[%d].%s" % (prefix, i, k), val))
    elif isinstance(v, dict):
        for k in keys:
            val = v.get(k)
            if isinstance(val, str) and codes.has_jp(val):
                out.append(("%s.%s" % (prefix, k), val))
    return out


def scan(cfg):
    """{path: japanese} for every translatable plugin leaf."""
    _pre, arr, _suf, _s, _e = parse_plugins(cfg.plugins_js)
    found = {}

    def collect(path, val):
        if val in NEVER:
            return
        found[path] = val

    for entry in arr:
        name = entry.get("name")
        if name in TRANSLATABLE:
            _leaves(entry, name, None, collect)
    return found, arr


def ledger_path(store_dir):
    return os.path.join(store_dir, LEDGER)


def load_ledger(store_dir):
    p = ledger_path(store_dir)
    return store.read_json(p) if os.path.exists(p) else {}


def save_ledger(store_dir, led):
    store.write_json(ledger_path(store_dir), led)


def refresh(cfg, store_dir, verbose=True):
    """Re-scan and merge into the ledger without losing an existing English."""
    found, _arr = scan(cfg)
    led = load_ledger(store_dir)
    added = 0
    for path, jp in found.items():
        row = led.get(path)
        if row and row.get("jp") == jp:
            continue
        if row and row.get("en") and row.get("jp") != jp:
            row["stale"] = True
            row["new_jp"] = jp
            continue
        led[path] = {"jp": jp, "en": (row or {}).get("en", "")}
        added += 1
    for path in list(led):
        if path not in found:
            led[path]["gone"] = True
    save_ledger(store_dir, led)
    if verbose:
        print("plugins.js: %d leaves, %d new -> %s"
              % (len(found), added, ledger_path(store_dir)))
        todo = [p for p, r in led.items() if not r.get("en")]
        for p in todo:
            print("   TODO %-52s %s" % (p, led[p]["jp"][:60]))
    return led


# --------------------------------------------------------------------------
def _set_leaf(entry, path, value):
    """Write one leaf back at the escaping depth it already uses."""
    _plugin, rest = path.split(".", 1)
    params = entry.setdefault("parameters", {})
    if "[" in rest:
        key, tail = rest.split("[", 1)
        idx, leaf = tail.split("].", 1)
        idx = int(idx)
        raw = params.get(key)
        arr = _decode(raw)
        if not isinstance(arr, list) or idx >= len(arr):
            return False
        item = arr[idx]
        obj = _decode(item) if isinstance(item, str) else item
        if not isinstance(obj, dict):
            return False
        obj[leaf] = value
        arr[idx] = (json.dumps(obj, ensure_ascii=False)
                    if isinstance(item, str) else obj)
        params[key] = json.dumps(arr, ensure_ascii=False)
        return True
    if "." in rest:
        key, leaf = rest.split(".", 1)
        raw = params.get(key)
        obj = _decode(raw)
        if not isinstance(obj, dict):
            return False
        obj[leaf] = value
        params[key] = json.dumps(obj, ensure_ascii=False)
        return True
    params[rest] = value
    return True


def apply(cfg, store_dir, verbose=True):
    """Write the ledger's English into plugins.js, in place, with a backup."""
    led = load_ledger(store_dir)
    pending = {p: r for p, r in led.items()
               if r.get("en") and not r.get("gone")}
    if not pending and not LAYOUT_OVERRIDES:
        if verbose:
            print("plugins.js: nothing to apply (fill `en` in %s first)"
                  % ledger_path(store_dir))
        return 0
    if not pending and verbose:
        print("plugins.js: no translated leaves yet - applying layout "
              "overrides only")

    prefix, arr, suffix, _s, _e = parse_plugins(cfg.plugins_js)
    by_name = {}
    for e in arr:
        by_name.setdefault(e.get("name"), []).append(e)

    written = 0
    for path, row in sorted(pending.items()):
        plugin = path.split(".", 1)[0]
        entries = by_name.get(plugin) or []
        if len(entries) != 1:
            print("  ! %s: plugin appears %d times, skipped"
                  % (path, len(entries)))
            continue
        if _set_leaf(entries[0], path, row["en"]):
            written += 1
        else:
            print("  ! %s: leaf not reachable, skipped" % path)

    layout = 0
    for plugin, table in LAYOUT_OVERRIDES.items():
        entries = by_name.get(plugin) or []
        if len(entries) != 1:
            print("  ! layout override for %s: plugin appears %d times, skipped"
                  % (plugin, len(entries)))
            continue
        for leaf, (value, why) in sorted(table.items()):
            if _set_leaf(entries[0], "%s.%s" % (plugin, leaf), value):
                layout += 1
                if verbose:
                    print("  layout  %s.%s = %s  (%s)" % (plugin, leaf, value, why))
            else:
                print("  ! layout override %s.%s not reachable" % (plugin, leaf))

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = cfg.plugins_js + ".bak_" + stamp
    shutil.copy2(cfg.plugins_js, backup)

    body = json.dumps(arr, ensure_ascii=False, indent=2)
    out = prefix + body + suffix
    # Re-parse our own output before it can be seen by the game: an
    # interrupted or malformed plugins.js means the game will not boot.
    tmp = cfg.plugins_js + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(out)
        f.flush()
        os.fsync(f.fileno())
    check_prefix, check_arr, _cs, _a, _b = parse_plugins(tmp)
    if len(check_arr) != len(arr):
        os.unlink(tmp)
        raise RuntimeError("re-parse of the rewritten plugins.js changed the "
                           "entry count (%d -> %d); nothing was written"
                           % (len(arr), len(check_arr)))
    store._replace_retry(tmp, cfg.plugins_js)
    if verbose:
        print("plugins.js: wrote %d text leaf/leaves and %d layout override(s) "
              "(backup: %s)" % (written, layout, os.path.basename(backup)))
    return written


def check_mirrors(cfg, store_dir, verbose=True):
    """Prove menuHelpTexts[].symbol matches the translated terms.commands."""
    from . import fileio
    problems = []
    led = load_ledger(store_dir)
    docs = store.load_docs(store_dir)
    commands = {}
    for _p, doc in docs:
        if doc["meta"]["source_file"] != "System.json":
            continue
        for u in doc["units"]:
            if u["id"].startswith("System:terms:commands:"):
                commands[u["raw"]] = (u.get("tl") or "").strip()

    for path, row in led.items():
        if not path.endswith(".symbol"):
            continue
        jp = row["jp"]
        want = commands.get(jp)
        if want is None:
            problems.append("%s: %r is not a System terms.commands value; the "
                            "help table will key on nothing" % (path, jp))
        elif want and row.get("en") != want:
            problems.append("%s: symbol %r but terms.commands says %r - the "
                            "menu help line will not render"
                            % (path, row.get("en"), want))
    if verbose:
        if problems:
            print("plugins.js MIRROR CHECK: %d problem(s)" % len(problems))
            for p in problems:
                print("   ! " + p)
        else:
            print("plugins.js MIRROR CHECK: menu help symbols agree with "
                  "System.json terms.commands")
    return problems


def autofill_mirrors(cfg, store_dir, verbose=True):
    """Copy the translated terms.commands into the matching symbol leaves."""
    led = load_ledger(store_dir)
    docs = store.load_docs(store_dir)
    commands = {}
    for _p, doc in docs:
        if doc["meta"]["source_file"] != "System.json":
            continue
        for u in doc["units"]:
            if u["id"].startswith("System:terms:commands:"):
                commands[u["raw"]] = (u.get("tl") or "").strip()
    n = 0
    for path, row in led.items():
        if path.endswith(".symbol") and commands.get(row["jp"]):
            if row.get("en") != commands[row["jp"]]:
                row["en"] = commands[row["jp"]]
                n += 1
    if n:
        save_ledger(store_dir, led)
    if verbose:
        print("plugins.js: mirrored %d menu-help symbol(s) from "
              "System.json terms.commands" % n)
    return n
