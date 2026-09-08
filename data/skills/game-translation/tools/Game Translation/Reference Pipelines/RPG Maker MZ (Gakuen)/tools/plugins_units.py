#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
plugins_units.py - bridge the plugins.js ledger onto the normal unit pipeline.

The plugin track is edited IN PLACE in the game folder while data flows
store -> export -> game, and the two must never be mixed. But there is no
reason for the plugin text to be TRANSLATED by a second, weaker path: it wants
the same cached bible, the same glossary, the same placeholder validation and
the same QA passes as everything else.

So the ledger is projected into a store doc whose `source_file` is
`plugins.js`. `inject.run` only walks `data/*.json` and looks each file's units
up by name, so that doc is invisible to it and the in-place track stays
in place. `sync` copies the finished English back into the ledger, which
`mztl.plugins_js.apply` then writes into the game.

    python tools/plugins_units.py build     ledger -> tl/units/plugins.json
    python tools/plugins_units.py sync      tl/units/plugins.json -> ledger
"""

import os
import re
import sys
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from mztl import codes, config, store, plugins_js  # noqa: E402

# What each leaf actually IS on screen, so the model writes a button like a
# button and a notification like a notification. A generic "translate this"
# is why patches ship menu entries reading "The Strongest Equipment Set".
KIND_BY_SUFFIX = [
    (".title", "name", "an achievement's TITLE - a short trophy name, title "
                       "case, no final punctuation"),
    (".description", "desc", "an achievement's description, one or two short "
                             "sentences; a literal \\n in the source is a line "
                             "break and must survive"),
    (".hint", "desc", "the hint shown while an achievement is still locked - "
                      "it must NOT give the answer away, and it keeps the "
                      "source's trailing ellipsis"),
    (".symbol", "term", "a LOOKUP KEY that must equal the English of the "
                        "matching main-menu command"),
    (".helpText", "desc", "the one-line help shown under a main-menu command"),
    (".CategoryName", "term", "a bestiary category tab"),
    (".PageCategoryName", "term", "a bestiary page tab"),
    (".ContentName", "term", "a bestiary completion counter label"),
    (".ParamName", "term", "a label drawn beside a number on the save or "
                           "battle-result screen - keep it under about 12 "
                           "characters"),
    (".Name", "term", "an Options-screen row label"),
    (".StringItems[]", "term", "one selectable value of an Options row"),
    (".name", "term", "a menu entry label"),
    (".role", "name", "the name of a poker or blackjack hand"),
    (".targetText", "name", "a name the engine searches message text for so it "
                            "can colour it - give exactly the English spelling "
                            "the glossary uses for this character, nothing else"),
    (".Label", "term", "a gauge label"),
    (".commandMessage", "text", "the shopkeeper's greeting"),
    (".buyMessage", "text", "the shopkeeper's line when buying"),
    (".sellMessage", "text", "the shopkeeper's line when selling"),
    (".thanksMessage", "text", "the shopkeeper's thank-you"),
    (".AnalyzeMissMessage", "message", "a battle-log line; %2 is a runtime "
                                       "substitution"),
]

KIND_BY_LEAF = {
    "popupMessage": ("term", "the achievement-unlocked popup headline"),
    "titleMenuText": ("term", "the title-screen menu entry for achievements"),
    "achievementMenuHiddenTitle": ("term", "the placeholder shown in place of a "
                                           "still-secret achievement's name"),
    "leftBlockLabel": ("term", "menu label, drawn immediately before a value"),
    "rightBlockLabel": ("term", "menu label, drawn immediately before a value"),
    "leftBottomBlockLabel": ("term", "menu label, drawn beside a number"),
    "rightBottomBlockLabel": ("term", "menu label, drawn beside a number"),
    "betInfoStr": ("term", "the casino prompt asking how much to bet"),
    "winMessage1": ("message", "casino win line; %s / %d are substitutions"),
    "winMessage2": ("message", "casino win line; %d is a substitution"),
    "loseMessage1": ("message", "casino lose line"),
    "loseMessage2": ("message", "casino prompt asking whether to play again"),
    "notCoinMessage": ("message", "casino refusal - not enough coins"),
    "yesLanguage": ("choice", "the Yes button"),
    "noLanguage": ("choice", "the No button"),
    "ItemCostName": ("term", "the counter word drawn after an item quantity"),
    "ItemCurrency": ("term", "the counter word drawn after an item quantity"),
    "CommandName": ("term", "a menu command"),
    "EnemyInfoCommandName": ("term", "a menu command"),
    "MenuSkillTreeText": ("term", "a menu command"),
    "NeedSpText": ("message", "skill-tree cost label; %1 is a substitution"),
    "OpenedNodeText": ("term", "shown on an already-learned skill node"),
    "NodeOpenConfirmationText": ("message", "skill-tree confirmation; %1 %2 %3 "
                                            "are substitutions in that order"),
    "NodeOpenYesText": ("choice", "the confirm button"),
    "NodeOpenNoText": ("choice", "the cancel button"),
    "BattleEndGetSpText": ("message", "reward line; %1 %2 are substitutions"),
    "LevelUpGetSpText": ("message", "reward line; %1 %2 are substitutions"),
    "ResultName": ("term", "the battle-results window header"),
    "LevelUpResultHelpName": ("message", "level-up line; %1 %2 are "
                                         "substitutions"),
    "baseGainSingleMessage": ("message", r"item-pickup notification; \name is "
                                         "the item name inserted at run time"),
    "baseGainMultiMessage": ("message", r"item-pickup notification; \name and "
                                        r"\count are inserted at run time"),
    "baseGainMoneyMessage": ("message", r"money-pickup notification; \gold and "
                                        r"\G are inserted at run time"),
    "GetTextMessage": ("message", "item-pickup line; %1 %2 are substitutions"),
    "GetGoldMessage": ("message", "money-pickup line; %1 %3 are substitutions"),
    "ObtainItemMessage": ("message", "item-pickup line; %1 %2 %3 are "
                                     "substitutions"),
    "MainMessage": ("text", "the crash screen's message to the player"),
    "Battle Voice Name at Option": ("term", "an Options-screen row label"),
    "enabledAll-Text": ("term", "an Options-screen row label"),
    "NoneItemText": ("term", "shown in a shop list when there is nothing to "
                             "show"),
}

DOC = "plugins.js"


def classify(path):
    leaf = path.rsplit(".", 1)[-1]
    if leaf in KIND_BY_LEAF:
        return KIND_BY_LEAF[leaf]
    for suffix, kind, note in KIND_BY_SUFFIX:
        if path.endswith(suffix):
            return kind, note
    return "term", "a plugin UI label"


def build(store_dir, cfg):
    led = plugins_js.load_ledger(store_dir)
    path_doc = store.doc_path(store_dir, DOC)
    old = store.read_json(path_doc).get("units", []) if os.path.exists(path_doc) else []

    units = []
    for path in sorted(led):
        row = led[path]
        if row.get("gone"):
            continue
        jp = row["jp"]
        if not codes.has_jp(jp):
            continue
        kind, note = classify(path)
        masked, cmap = codes.mask_codes(codes.clean_source(jp))
        u = {
            "id": "plugins:" + store.sanitize_id(path),
            "kind": kind,
            "sites": [{"ptr": ["__ledger__", path]}],
            "src": masked,
            "raw": jp,
            "tl": row.get("en", ""),
            "ctx": "js/plugins.js  %s" % path,
            "note": note,
            "codes": cmap,
        }
        # A mirror is not a translation decision at all - it is a copy of a
        # value chosen in another file, so it is locked out of the model's
        # reach entirely and filled by plugins_js.autofill_mirrors.
        if path.endswith(".symbol"):
            u["locked"] = True
        units.append(u)

    kept = store.merge_translations(old, units)
    store.save_doc(store_dir, DOC, units)
    print("plugins.js -> %d unit(s) (%d translations carried over)"
          % (len(units), kept))
    todo = sum(1 for u in units if not u["tl"].strip() and not u.get("locked"))
    print("   %d still need the model" % todo)
    return units


def sync(store_dir, cfg):
    led = plugins_js.load_ledger(store_dir)
    path_doc = store.doc_path(store_dir, DOC)
    if not os.path.exists(path_doc):
        sys.exit("no plugins.js unit doc - run `build` first")
    doc = store.read_json(path_doc)
    n = bad = 0
    for u in doc["units"]:
        tl = (u.get("tl") or "").strip()
        if not tl:
            continue
        tl = codes.clean_translation(tl)
        if codes.has_untranslated_jp(tl):
            print("  ! %s still holds Japanese - not synced" % u["id"])
            bad += 1
            continue
        restored = codes.unmask_codes(tl, u.get("codes") or {}, pad_inserts=True)
        restored = codes.space_bare_escapes(restored)
        # Every one of these lives inside a JSON string that RPG Maker parses
        # at boot. A raw double quote breaks the escape level and the whole
        # plugin's parameters fail to parse.
        restored = restored.replace('"', "'")
        path = u["sites"][0]["ptr"][1]
        row = led.get(path)
        if row is None:
            print("  ! %s: ledger row is gone" % path)
            bad += 1
            continue
        if row.get("en") != restored:
            row["en"] = restored
            n += 1
    plugins_js.save_ledger(store_dir, led)
    print("plugins.js ledger: %d row(s) updated, %d skipped" % (n, bad))
    return n


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["build", "sync"])
    ap.add_argument("--store", default=os.path.join(os.path.dirname(HERE), "tl"))
    args = ap.parse_args(argv)
    cfg = config.Config()
    if args.action == "build":
        build(args.store, cfg)
    else:
        sync(args.store, cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
