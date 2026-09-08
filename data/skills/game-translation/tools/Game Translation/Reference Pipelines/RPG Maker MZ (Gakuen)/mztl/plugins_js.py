#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
plugins_js.py - the `js/plugins.js` UI-text track.

This text is on a DIFFERENT track from `data/*.json`. Data flows
store -> export -> game; plugin parameters are edited IN PLACE in the game
folder. Mixing the two models means an export silently reverts an in-place
edit, or an in-place edit is lost on the next export. So this module keeps its
own ledger (`tl/plugins_js.json`) mapping a fully-qualified leaf path to its
Japanese source and English replacement, and writes only through
`json.JSONDecoder.raw_decode` on the `var $plugins = [...]` array so untouched
entries stay byte-identical.

Leaves are addressed by a PATH, not by a fixed nesting depth, because this
game's parameters are JSON inside JSON inside JSON:

    baseAchievementData[].title          array of JSON strings -> object
    GaugeList[].Detail.Label             ...whose member is another JSON string
    actionLanguageList[]                 a bare array of strings
    betInfoStr                           a plain scalar

`_walk` decodes a value whenever the next path step needs it to be a container,
and `_set` re-encodes at exactly the depth it decoded, so a leaf that lived at
three levels of escaping goes back at three levels. Normalising the file to one
depth produces either a visible literal `\\n` in the window or a real newline
that breaks the enclosing JSON string, and RPG Maker then fails the whole
plugin-parameter parse at boot.

Two couplings nothing else would catch
--------------------------------------

**LL_MenuScreenCustom.menuHelpTexts[].symbol** is looked up as
`menuHelpLists[this._commandWindow.currentName()]` - keyed by the DISPLAYED
command name, which comes from `System.json terms.commands`. Translate the
command and leave the symbol, and every menu help line silently disappears:
no error, just an empty row. `MIRRORS` declares that dependency and
`check_mirrors` proves the two agree.

**MessageAutoReplace.replaceList** is a search-and-replace over message text -
`new RegExp(item.targetText, 'g')` (MessageAutoReplace.js:91). Its live job in
this game is to colour the two heroines' names wherever they appear. Leave
`targetText` in Japanese and it stops matching the moment the dialogue is
English, and both names lose their colour everywhere. So `targetText` is
translated too, and `text` is REBUILT from it rather than translated
separately, preserving the exact control-code wrapper - see `fix_autoreplace`.
"""

import os
import re
import json
import shutil
import datetime

from . import codes, store

ARRAY_RE = re.compile(r"var\s+\$plugins\s*=\s*")

# --------------------------------------------------------------------------
# What is text. Everything here was read out of `audit/PLUGINS.txt`, which
# decodes every parameter recursively - never from a blanket "find Japanese in
# the file" scan, which also sweeps up note-tag keys, font call-names, image
# paths and switch names that code reads back.
TRANSLATABLE = {
    "TorigoyaMZ_Achievement2": [
        "baseAchievementData[].title",
        "baseAchievementData[].description",
        "baseAchievementData[].hint",
        "popupMessage",
        "titleMenuText",
        "achievementMenuHiddenTitle",
    ],
    # `prefix` is deliberately absent: it is matched against an achievement
    # KEY, not displayed.
    "TorigoyaMZ_Achievement2_AddonCategory": ["categories[].name"],
    "LL_MenuScreenCustom": [
        "menuHelpTexts[].symbol",          # a MIRROR - see below
        "menuHelpTexts[].helpText",
        "leftBlockLabel", "rightBlockLabel",
        "leftBottomBlockLabel", "rightBottomBlockLabel",
    ],
    "LL_MenuScreenShop": [
        "shopLists[].commandMessage", "shopLists[].buyMessage",
        "shopLists[].sellMessage", "shopLists[].thanksMessage",
    ],
    "Tatsu_PokerGames": [
        "roleStruct[].role", "betInfoStr", "winMessage1", "winMessage2",
        "notCoinMessage", "loseMessage1", "loseMessage2",
        "yesLanguage", "noLanguage",
    ],
    "Tatsu_BlackJack": [
        "roleInfoStruct[].role", "actionLanguageList[]", "betInfoStr",
        "winMessage1", "winMessage2", "notCoinMessage", "loseMessage1",
        "loseMessage2", "yesLanguage", "noLanguage",
    ],
    # ONLY ItemCostName. Every `*MetaName` parameter is a NOTETAG NAME - the
    # plugin reads `<HP消費:...>` out of a skill's note field with it, so
    # translating one silently disables that whole cost type.
    "SkillCost": ["ItemCostName"],
    "MessageAutoReplace": ["replaceList[].targetText"],
    "NUUN_EnemyBook": [
        "CommandName", "EnemyInfoCommandName",
        "EnemyBookCategory[].CategoryName",
        "PercentContent[].ContentName",
        "PageSetting[].PageCategoryName",
        "InfoPageSetting[].PageCategoryName",
        "AnalyzeSkillMode[].AnalyzeMissMessage",
    ],
    "SkillTree": [
        "MenuSkillTreeText", "NeedSpText", "OpenedNodeText",
        "NodeOpenConfirmationText", "NodeOpenYesText", "NodeOpenNoText",
        "BattleEndGetSpText", "LevelUpGetSpText",
    ],
    "NUUN_Result": [
        "ResultName", "LevelUpResultHelpName",
        "ActorExpDataList[].ParamName", "GainParam[].ParamName",
        "GetItemParam[].ParamName", "LearnSkillParam[].ParamName",
    ],
    "CustomizeConfigItem": [
        "NumberOptions[].Name", "StringOptions[].Name",
        "StringOptions[].StringItems[]", "SwitchOptions[].Name",
    ],
    "NUUN_SaveScreen": ["ContentsList[].ParamName"],
    "TorigoyaMZ_NotifyMessage_AddonGetItem": [
        "baseGainSingleMessage", "baseGainMultiMessage", "baseGainMoneyMessage",
    ],
    "TorigoyaMZ_EasyStaffRoll": ["baseStaffRollContent[].title"],
    "TorigoyaMZ_CommonMenu": ["baseItems[].name"],
    "ExtraGauge": ["GaugeList[].Detail.Label"],
    "NUUN_RandomItems": ["GetTextMessage", "GetGoldMessage"],
    "CustomizeErrorScreen": ["MainMessage"],
    "BattleVoiceMZ": ["Battle Voice Name at Option"],
    "FilterControllerMZ": ["enabledAll-Text"],
    "DropItemCount": ["ObtainItemMessage"],
    "YKP_ShopManager": ["ItemCurrency"],
    "ShopScene_Extension": ["NoneItemText"],
}

# `symbol` must equal the English chosen for the matching System.json
# terms.commands entry, because the plugin keys its help table by the DISPLAYED
# command name.
MIRRORS = {
    "LL_MenuScreenCustom.menuHelpTexts[].symbol": "System:terms:commands",
}

# Strings something reads back as a key. Belt and braces on top of the
# whitelist, so a widened whitelist cannot reach one by accident.
NEVER = {
    "右クリック",                       # MessageWindowHidden: case '右クリック'
    "選択肢ヘルプ", "<選択肢ヘルプ>",     # MPP_ChoiceEX comment marker
    "ChoiceHelp", "<ChoiceHelp>",
    "普通", "ドット",                   # Keke_AnyTimeFontChange call names
    "テキスト", "画像", "左右", "上下",   # CBR_EroStatus command keywords
}

# Layout repairs, not translations. Where a widget's bound is itself a plugin
# PARAMETER, the fix for English that no longer fits is to raise the bound -
# not to compress the words until the label stops meaning anything.
LAYOUT_OVERRIDES = {
    "EventLabel": {
        # `Sprite.anchor.x = 0.5` (EventLabel.js:383) centres the caption on its
        # event, so a long one spreads BOTH ways: into the neighbouring event's
        # caption, and off the edge of the viewport. The recollection room is a
        # grid of scene titles 7 tiles (336 px) apart, and English scene names
        # are long - "Frigid Girl and the Janitor" is 378 px at the shipped
        # fontSize 28 and lands 21 px inside "Suspicious Part-Time Job".
        #
        # Measured over every `<LB:>` label in the game, pairing each with its
        # neighbour ON THE SAME ROW (labels on different rows are separated
        # vertically, so game-wide column spacing is the wrong budget):
        #
        #     fontSize 28 -> 2 same-row collisions
        #     fontSize 24 -> 1, and that one is Map001 = ＴＥＳＴＭＡＰ, a dev
        #                     map with no way in, overlapping by 6 px
        #     fontSize 22 -> 0
        #
        # **THE SIZE IS NOT FREE TO CHOOSE, AND THE PIXEL GRID IS NOT WHY.**
        # The first attempt at this reasoned purely from the glyph outlines:
        # `x12y12pxMaruMinyaM.ttf` has unitsPerEm 1200 with every outline
        # coordinate on a 50-unit grid, so its design resolution is
        # 1200/50 = 24 px/em and it rasterises with ZERO antialiased pixels
        # only at 12, 24, 36, 48. That measurement is correct - and it is not
        # what decides whether the caption looks sharp. Two sizes were shipped
        # on it and a player called both blurry.
        #
        # What actually dominates is STROKE WEIGHT AGAINST A FIXED OUTLINE.
        # `Bitmap.outlineWidth` is 3 px and EventLabel never changes it, so the
        # dark halo is 3 px at EVERY font size while the white glyph strokes
        # scale with the size:
        #
        #     28 (shipped)  strokes ~2.33 px  outline is 3 px -> letters hold
        #     24            strokes  2 px     the halo eats into them and
        #                                     fills the counters of a/e/o ->
        #                                     low contrast, reads as mush
        #     22            strokes ~1.83 px  worse still
        #
        # Rendering all three through the real pipeline - pixel font, 3 px
        # round-join stroke at rgba(0,0,0,0.5), white fill - and looking at the
        # result at 3x makes the ordering obvious, and it matches the player's
        # reports exactly. A pixel-exact raster is worth nothing if the outline
        # is thicker than the strokes it surrounds.
        #
        # So the author's 28 stands. Do not lower a pixel font's size to buy
        # layout room while an unscaled outline is drawn over it: measure the
        # grid, then check the stroke-to-outline ratio, and let the ratio win.
        # Clipping at the map edges is handled by `<LB_X:>` offsets instead
        # (`inject._apply_label_offsets`), which cost no legibility at all.
        #
        # This entry is therefore a no-op against the shipped value, and is
        # kept ONLY because it is the single source of truth the offset pass
        # reads its width-per-character from. Changing it re-derives every
        # offset; deleting it disables that pass.
        "fontSize": ("28", "the author's size, restored: a 3 px outline over a "
                           "pixel font needs the strokes it surrounds, and "
                           "anything smaller reads blurry"),
    },
}

LEDGER = "plugins_js.json"


# --------------------------------------------------------------------------
# plugins.js structure
# --------------------------------------------------------------------------
def parse_plugins(path):
    """(prefix, entries, suffix, start, end) with the array decoded in place."""
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


# --------------------------------------------------------------------------
# generic path walk over JSON-inside-JSON
# --------------------------------------------------------------------------
_STEP_RE = re.compile(r"\[\]|[^.\[\]]+")


def _steps(path):
    """'GaugeList[].Detail.Label' -> ['GaugeList', '[]', 'Detail', 'Label']"""
    return _STEP_RE.findall(path)


def _decode(v):
    """Decode a JSON-in-string one level, or return None if it is not one."""
    if not isinstance(v, str):
        return None
    s = v.strip()
    if not s or s[0] not in "[{":
        return None
    try:
        return json.loads(s)
    except Exception:
        return None


def _walk(node, steps, prefix, out):
    """Collect (concrete_path, string) for every leaf the path reaches."""
    if not steps:
        if isinstance(node, str) and node.strip() and codes.has_jp(node):
            out.append((prefix, node))
        return
    step, rest = steps[0], steps[1:]
    if step == "[]":
        seq = node if isinstance(node, list) else _decode(node)
        if not isinstance(seq, list):
            return
        for i, item in enumerate(seq):
            _walk(item, rest, "%s[%d]" % (prefix, i), out)
        return
    obj = node if isinstance(node, dict) else _decode(node)
    if not isinstance(obj, dict) or step not in obj:
        return
    _walk(obj[step], rest, "%s.%s" % (prefix, step) if prefix else step, out)


def _set(node, steps, value):
    """Write `value` at `steps`, re-encoding at exactly the depth decoded.

    Returns the (possibly re-encoded) node, or None when the path is not
    reachable - never a partially written structure."""
    if not steps:
        return value
    step, rest = steps[0], steps[1:]

    if step == "[]":
        raise ValueError("a bare [] must be preceded by an index")

    if step.startswith("#"):                      # concrete list index
        idx = int(step[1:])
        was_str = isinstance(node, str)
        seq = _decode(node) if was_str else node
        if not isinstance(seq, list) or idx >= len(seq):
            return None
        sub = _set(seq[idx], rest, value)
        if sub is None:
            return None
        seq[idx] = sub
        return json.dumps(seq, ensure_ascii=False) if was_str else seq

    was_str = isinstance(node, str)
    obj = _decode(node) if was_str else node
    if not isinstance(obj, dict) or step not in obj:
        return None
    sub = _set(obj[step], rest, value)
    if sub is None:
        return None
    obj[step] = sub
    return json.dumps(obj, ensure_ascii=False) if was_str else obj


_CONCRETE_RE = re.compile(r"\[(\d+)\]")


def _concrete_steps(path):
    """A collected path ('a[2].b') -> steps with '#2' for the index."""
    return _STEP_RE.findall(_CONCRETE_RE.sub(r".#\1", path))


# --------------------------------------------------------------------------
def scan(cfg):
    """{path: japanese} for every whitelisted plugin leaf that holds text."""
    _pre, arr, _suf, _s, _e = parse_plugins(cfg.plugins_js)
    found = {}
    for entry in arr:
        name = entry.get("name")
        spec = TRANSLATABLE.get(name)
        if not spec:
            continue
        if not entry.get("status"):
            # Only ENABLED plugins. A disabled plugin's parameters are never
            # read, so translating them is pure cost and pure risk.
            continue
        params = entry.get("parameters") or {}
        for path in spec:
            out = []
            _walk(params, _steps(path), "", out)
            for concrete, value in out:
                if value.strip() in NEVER:
                    continue
                found["%s.%s" % (name, concrete)] = value
    return found, arr


def ledger_path(store_dir):
    return os.path.join(store_dir, LEDGER)


def load_ledger(store_dir):
    p = ledger_path(store_dir)
    return store.read_json(p) if os.path.exists(p) else {}


def save_ledger(store_dir, led):
    store.write_json(ledger_path(store_dir), led)


def leaf_value(arr, path):
    """The value plugins.js currently holds at a collected leaf path, or None."""
    plugin, rest = path.split(".", 1)
    for e in arr:
        if e.get("name") != plugin:
            continue
        out = []
        _walk(e.get("parameters") or {}, _steps(_CONCRETE_RE.sub("[]", rest)),
              "", out)
        for concrete, value in out:
            if concrete == rest:
                return value
        # `_walk` only yields leaves that still contain Japanese, so fall back
        # to reading the exact path directly for an already-translated one.
        return _read_exact(e.get("parameters") or {}, _concrete_steps(rest))
    return None


def _read_exact(node, steps):
    for step in steps:
        if step.startswith("#"):
            seq = node if isinstance(node, list) else _decode(node)
            i = int(step[1:])
            if not isinstance(seq, list) or i >= len(seq):
                return None
            node = seq[i]
            continue
        obj = node if isinstance(node, dict) else _decode(node)
        if not isinstance(obj, dict) or step not in obj:
            return None
        node = obj[step]
    return node if isinstance(node, str) else None


def refresh(cfg, store_dir, verbose=True):
    """Re-scan and merge into the ledger without losing an existing English.

    A leaf we have ALREADY translated no longer contains Japanese, so `scan`
    stops finding it. Marking those `gone` would be wrong twice over: it hides
    them from the ledger's own todo list, and it makes a later `apply` write
    nothing at all, so an accidental restore of plugins.js could never be
    repaired. A row whose leaf now holds exactly this row's English is
    `applied`, not gone."""
    found, arr = scan(cfg)
    led = load_ledger(store_dir)
    added = 0
    for path, jp in found.items():
        row = led.get(path)
        if row and row.get("jp") == jp:
            row.pop("gone", None)
            row.pop("applied", None)
            continue
        if row and row.get("en") and row.get("jp") != jp:
            row["stale"] = True
            row["new_jp"] = jp
            continue
        led[path] = {"jp": jp, "en": (row or {}).get("en", "")}
        added += 1
    applied = 0
    for path in list(led):
        if path in found:
            continue
        row = led[path]
        cur = leaf_value(arr, path)
        if row.get("en") and cur == row["en"]:
            row.pop("gone", None)
            row["applied"] = True
            applied += 1
        else:
            row["gone"] = True
    save_ledger(store_dir, led)
    if verbose:
        todo = [p for p, r in led.items()
                if not r.get("en") and not r.get("gone")]
        gone = [p for p, r in led.items() if r.get("gone")]
        print("plugins.js: %d untranslated leaf/leaves in the file, %d already "
              "applied, %d new, %d still to do, %d gone -> %s"
              % (len(found), applied, added, len(todo), len(gone),
                 ledger_path(store_dir)))
    return led


# --------------------------------------------------------------------------
def fix_autoreplace(cfg, store_dir, verbose=True):
    r"""Rebuild MessageAutoReplace `text` from the translated `targetText`.

    The pair is a search and a replacement over live message text. Its job here
    is to wrap the two heroines' names in a colour scope
    (`アズサ` -> `\c[2]アズサ\c[0]`), so the replacement must be the SAME name
    the search looks for, in the same wrapper. Deriving it is deterministic;
    asking the model for it twice is how the two drift apart and the colour
    lands on nothing.

    Where the source pair is a JP-to-JP rename rather than a decoration
    (`ドラゴンクラス` -> `クラスドラゴン`) the replacement is the glossary's
    English for the DISPLAYED form, which the bible already pins."""
    led = load_ledger(store_dir)
    _pre, arr, _suf, _s, _e = parse_plugins(cfg.plugins_js)
    entry = next((e for e in arr if e.get("name") == "MessageAutoReplace"), None)
    if entry is None:
        return 0
    raw = (entry.get("parameters") or {}).get("replaceList")
    seq = _decode(raw) or []
    n = 0
    for i, item in enumerate(seq):
        obj = _decode(item) if isinstance(item, str) else item
        if not isinstance(obj, dict):
            continue
        jp_target = obj.get("targetText", "")
        jp_text = obj.get("text", "")
        key = "MessageAutoReplace.replaceList[%d].targetText" % i
        row = led.get(key)
        en_target = (row or {}).get("en", "").strip()
        if not en_target:
            continue
        # Keep whatever wrapped the name, put the English inside it.
        if jp_target and jp_target in jp_text:
            en_text = jp_text.replace(jp_target, en_target)
        else:
            # A rename rather than a decoration: both sides become the one
            # English spelling, which makes the rule a harmless no-op instead
            # of a rule that can never fire.
            en_text = en_target
        tkey = "MessageAutoReplace.replaceList[%d].text" % i
        if led.get(tkey, {}).get("en") != en_text:
            led[tkey] = {"jp": jp_text, "en": en_text,
                         "derived": "rebuilt from targetText"}
            n += 1
    if n:
        save_ledger(store_dir, led)
    if verbose:
        print("plugins.js: rebuilt %d MessageAutoReplace replacement(s) from "
              "their translated search term" % n)
    return n


# --------------------------------------------------------------------------
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

    prefix, arr, suffix, _s, _e = parse_plugins(cfg.plugins_js)
    by_name = {}
    for e in arr:
        by_name.setdefault(e.get("name"), []).append(e)

    written = skipped = 0
    for path, row in sorted(pending.items()):
        plugin, rest = path.split(".", 1)
        entries = by_name.get(plugin) or []
        if len(entries) != 1:
            print("  ! %s: plugin appears %d times, skipped"
                  % (path, len(entries)))
            skipped += 1
            continue
        params = entries[0].setdefault("parameters", {})
        got = _set(params, _concrete_steps(rest), row["en"])
        if got is None:
            print("  ! %s: leaf not reachable, skipped" % path)
            skipped += 1
        else:
            entries[0]["parameters"] = got
            written += 1

    layout = 0
    for plugin, table in LAYOUT_OVERRIDES.items():
        entries = by_name.get(plugin) or []
        if len(entries) != 1:
            print("  ! layout override for %s: plugin appears %d times, skipped"
                  % (plugin, len(entries)))
            continue
        for leaf, (value, why) in sorted(table.items()):
            got = _set(entries[0].setdefault("parameters", {}),
                       _concrete_steps(leaf), value)
            if got is None:
                print("  ! layout override %s.%s not reachable" % (plugin, leaf))
            else:
                entries[0]["parameters"] = got
                layout += 1
                if verbose:
                    print("  layout  %s.%s = %s  (%s)" % (plugin, leaf, value, why))

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = cfg.plugins_js + ".bak_" + stamp
    if not os.path.exists(backup):
        shutil.copy2(cfg.plugins_js, backup)

    body = json.dumps(arr, ensure_ascii=False, indent=2)
    out = prefix + body + suffix
    # Re-parse our own output before it can be seen by the game: an interrupted
    # or malformed plugins.js means the game does not boot at all.
    tmp = cfg.plugins_js + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(out)
        f.flush()
        os.fsync(f.fileno())
    _cp, check_arr, _cs, _a, _b = parse_plugins(tmp)
    if len(check_arr) != len(arr):
        os.unlink(tmp)
        raise RuntimeError("re-parse of the rewritten plugins.js changed the "
                           "entry count (%d -> %d); nothing was written"
                           % (len(arr), len(check_arr)))
    names_before = [e.get("name") for e in arr]
    if [e.get("name") for e in check_arr] != names_before:
        os.unlink(tmp)
        raise RuntimeError("re-parse changed the plugin ORDER; nothing written")
    store._replace_retry(tmp, cfg.plugins_js)
    if verbose:
        print("plugins.js: wrote %d text leaf/leaves (%d skipped) and %d layout "
              "override(s) (backup: %s)"
              % (written, skipped, layout, os.path.basename(backup)))
    return written


# --------------------------------------------------------------------------
def _commands_map(store_dir):
    docs = store.load_docs(store_dir)
    out = {}
    for _p, doc in docs:
        if doc["meta"]["source_file"] != "System.json":
            continue
        for u in doc["units"]:
            if u["id"].startswith("System:terms:commands:"):
                out[u["raw"]] = (u.get("tl") or "").strip()
    return out


def check_mirrors(cfg, store_dir, verbose=True):
    """Prove menuHelpTexts[].symbol matches the translated terms.commands."""
    problems = []
    led = load_ledger(store_dir)
    commands = _commands_map(store_dir)
    n = 0
    for path, row in led.items():
        if not path.endswith(".symbol") or row.get("gone"):
            continue
        n += 1
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
            print("plugins.js MIRROR CHECK: %d problem(s) over %d symbol(s)"
                  % (len(problems), n))
            for p in problems:
                print("   ! " + p)
        else:
            print("plugins.js MIRROR CHECK: %d menu help symbol(s) agree with "
                  "System.json terms.commands" % n)
    return problems


def autofill_mirrors(cfg, store_dir, verbose=True):
    """Copy the translated terms.commands into the matching symbol leaves."""
    led = load_ledger(store_dir)
    commands = _commands_map(store_dir)
    n = 0
    for path, row in led.items():
        if path.endswith(".symbol") and commands.get(row.get("jp")):
            if row.get("en") != commands[row["jp"]]:
                row["en"] = commands[row["jp"]]
                row["derived"] = "mirror of System.json terms.commands"
                n += 1
    if n:
        save_ledger(store_dir, led)
    if verbose:
        print("plugins.js: mirrored %d menu-help symbol(s) from "
              "System.json terms.commands" % n)
    return n
