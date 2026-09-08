#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
seed_stock_ui.py - fill RPG Maker VX Ace's OWN strings with Enterbrain's own
published English, and lock them. No API call, no cost, no drift.

Two places hold them on Ace:

  System.rvdata2   `terms.basic` / `params` / `etypes` / `commands`, plus the
                   currency unit and the stock elements and skill types. These
                   are STORE UNITS.
  Vocab (script)   ~50 constants in Ruby source - the shop, save and load
                   prompts and the whole battle log. These are LEDGER ENTRIES
                   on the in-place scripts track.

Matching the engine's published English exactly is what keeps the UI from
reading half-localised. It is also what stops a model producing "The Strongest
Equipment Set" for `最強装備` - correct, and wrong.

Every seeded entry is marked `locked`, so `dryrun`, `run` and `retry` skip it
and a later pass can never overwrite it.

A seed is applied ONLY where the Japanese in the game matches the stock
Japanese this table was written against. This game replaced some slots with its
own values (`衣装タイプ` armour types, an extra `打撃` element), and silently
seeding the stock English over a customised slot is how a patch renames the
wrong thing.

    python tools/seed_stock_ui.py            # report
    python tools/seed_stock_ui.py --apply
"""

import os
import sys
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from acetl import store, config, codes                     # noqa: E402

# --- System.rvdata2 -------------------------------------------------------
# (unit id, expected Japanese, official English)
SYSTEM = [
    ("System:terms:basic:0", "レベル", "Level"),
    ("System:terms:basic:1", "Lv", "Lv"),
    ("System:terms:basic:2", "ＨＰ", "HP"),
    ("System:terms:basic:3", "ＨＰ", "HP"),
    ("System:terms:basic:4", "ＭＰ", "MP"),
    ("System:terms:basic:5", "ＭＰ", "MP"),
    ("System:terms:basic:6", "ＴＰ", "TP"),
    ("System:terms:basic:7", "ＴＰ", "TP"),

    ("System:terms:params:0", "最大ＨＰ", "Max HP"),
    ("System:terms:params:1", "最大ＭＰ", "Max MP"),
    ("System:terms:params:2", "攻撃力", "Attack"),
    ("System:terms:params:3", "防御力", "Defense"),
    ("System:terms:params:4", "魔法力", "M.Attack"),
    ("System:terms:params:5", "魔法防御", "M.Defense"),
    ("System:terms:params:6", "敏捷性", "Agility"),
    ("System:terms:params:7", "運", "Luck"),

    ("System:terms:etypes:0", "武器", "Weapon"),
    ("System:terms:etypes:1", "腕", "Shield"),
    ("System:terms:etypes:2", "頭", "Head"),
    ("System:terms:etypes:3", "身体", "Body"),
    ("System:terms:etypes:4", "装飾品", "Accessory"),

    ("System:terms:commands:0", "戦う", "Fight"),
    ("System:terms:commands:1", "逃げる", "Escape"),
    ("System:terms:commands:2", "攻撃", "Attack"),
    ("System:terms:commands:3", "防御", "Guard"),
    ("System:terms:commands:4", "道具", "Item"),
    ("System:terms:commands:5", "スキル", "Skill"),
    ("System:terms:commands:6", "装備", "Equip"),
    ("System:terms:commands:7", "ステータス", "Status"),
    ("System:terms:commands:8", "並び替え", "Formation"),
    ("System:terms:commands:9", "セーブ", "Save"),
    ("System:terms:commands:10", "ゲーム終了", "Game End"),
    ("System:terms:commands:12", "武器", "Weapon"),
    ("System:terms:commands:13", "防具", "Armor"),
    ("System:terms:commands:14", "大事なもの", "Key Item"),
    ("System:terms:commands:15", "装備変更", "Equip"),
    ("System:terms:commands:16", "最強装備", "Optimize"),
    ("System:terms:commands:17", "全て外す", "Clear"),
    ("System:terms:commands:18", "ニューゲーム", "New Game"),
    ("System:terms:commands:19", "コンテニュー", "Continue"),
    ("System:terms:commands:20", "シャットダウン", "Shutdown"),
    ("System:terms:commands:21", "タイトルへ", "To Title"),
    ("System:terms:commands:22", "やめる", "Cancel"),

    ("System:currencyUnit", "Ｇ", "G"),

    ("System:elements:1", "物理", "Physical"),
    ("System:elements:2", "吸収", "Absorb"),
    ("System:elements:3", "炎", "Fire"),
    ("System:elements:4", "氷", "Ice"),
    ("System:elements:5", "雷", "Thunder"),
    ("System:elements:6", "水", "Water"),
    ("System:elements:7", "大地", "Earth"),
    ("System:elements:8", "風", "Wind"),
    ("System:elements:9", "神聖", "Holy"),
    ("System:elements:10", "暗黒", "Darkness"),
    # elements[11] `打撃` is this game's own addition, not stock - left to the
    # translator.
    ("System:skill_types:1", "特技", "Special"),
    ("System:skill_types:2", "魔法", "Magic"),
]

# --- Vocab (RGSS3 script) --------------------------------------------------
# Source-level text: exactly the characters between the quotes, so `\\G` stays
# two characters of Ruby source.
VOCAB = {
    "購入する": "Buy",
    "売却する": "Sell",
    "やめる": "Cancel",
    "持っている数": "Possession",
    "現在の経験値": "Current EXP",
    "次の%sまで": "To Next %s",
    "どのファイルにセーブしますか？": "Save to which file?",
    "どのファイルをロードしますか？": "Load which file?",
    "ファイル": "File",
    "%sたち": "%s's Party",
    "%sが出現！": "%s emerged!",
    "%sは先手を取った！": "%s got the upper hand!",
    "%sは不意をつかれた！": "%s was surprised!",
    "%sは逃げ出した！": "%s has started to escape!",
    "しかし逃げることはできなかった！": "However, it was unable to escape!",
    "%sの勝利！": "%s was victorious!",
    "%sは戦いに敗れた。": "%s was defeated.",
    "%s の経験値を獲得！": "%s experience points received!",
    # Raw strings on both sides: the ledger holds SOURCE-level text, and this
    # literal really does carry two backslash characters in the .rb file
    # (Ruby's `"\\G"` renders as `\G`, the currency escape). Writing it as a
    # normal Python literal halves it and the row silently matches nothing.
    r"お金を %s\\G 手に入れた！": r"Found %s\\G!",
    "%sを手に入れた！": "%s found!",
    "%sは%s %s に上がった！": "%s is now %s %s!",
    "%sを覚えた！": "%s learned!",
    "%sは%sを使った！": "%s uses %s!",
    "会心の一撃！！": "An excellent hit!!",
    "痛恨の一撃！！": "A painful blow!!",
    "%sは %s のダメージを受けた！": "%s took %s damage!",
    "%sの%sが %s 回復した！": "%s recovered %s %s!",
    "%sの%sが %s 増えた！": "%s gained %s %s!",
    "%sの%sが %s 減った！": "%s lost %s %s!",
    "%sは%sを %s 奪われた！": "%s was drained of %s %s!",
    "%sはダメージを受けていない！": "%s took no damage!",
    "ミス！　%sはダメージを受けていない！": "Miss! %s took no damage!",
    "%sに %s のダメージを与えた！": "%s took %s damage!",
    "%sの%sを %s 奪った！": "%s was drained of %s %s!",
    "%sにダメージを与えられない！": "%s took no damage!",
    "ミス！　%sにダメージを与えられない！": "Miss! %s took no damage!",
    "%sは攻撃をかわした！": "%s evaded the attack!",
    "%sは魔法を打ち消した！": "%s nullified the magic!",
    "%sは魔法を跳ね返した！": "%s reflected the magic!",
    "%sの反撃！": "%s counterattacked!",
    "%sが%sをかばった！": "%s protected %s!",
    "%sの%sが上がった！": "%s's %s went up!",
    "%sの%sが下がった！": "%s's %s went down!",
    "%sの%sが元に戻った！": "%s's %s returned to normal!",
    "%sには効かなかった！": "There was no effect on %s!",
    "プレイヤーの初期位置が設定されていません。":
        "The player's starting position is not set.",
    "コモンイベントの呼び出しが上限を超えました。":
        "Common event calls exceeded the limit.",
}


def seed_units(store_dir, apply):
    docs = store.load_docs(store_dir)
    want = {uid: (jp, en) for uid, jp, en in SYSTEM}
    hit = mismatch = 0
    for _p, doc in docs:
        if doc["meta"]["source_file"] != "System.rvdata2":
            continue
        for u in doc["units"]:
            entry = want.pop(u["id"], None)
            if entry is None:
                continue
            jp, en = entry
            if u.get("raw", "").strip() != jp:
                print("   ~ %-28s this game has %r, the stock table expects "
                      "%r - NOT seeded" % (u["id"], u.get("raw"), jp))
                mismatch += 1
                continue
            if codes.placeholder_ids(u["src"]) != codes.placeholder_ids(en):
                print("   !! %s: placeholder mismatch - skipped" % u["id"])
                continue
            if apply:
                u["tl"] = en
                u["locked"] = True
            hit += 1
    if apply:
        store.save_docs(docs)
    return hit, mismatch, want


def seed_vocab(store_dir, apply):
    path = os.path.join(store_dir, "scripts_rb.json")
    if not os.path.exists(path):
        print("   (no scripts_rb.json - run `tl.py scripts refresh` first)")
        return 0, 0
    led = store.read_json(path)
    hit = 0
    unmatched = dict(VOCAB)
    for e in led.get("entries", []):
        en = VOCAB.get(e["jp"])
        if not en:
            continue
        unmatched.pop(e["jp"], None)
        if apply:
            e["en"] = en
            e["translate"] = True
            e["locked"] = True
        hit += 1
    if apply:
        store.write_json(path, led)
    return hit, unmatched


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=os.path.join(os.path.dirname(HERE), "tl"))
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)

    print("STOCK UI SEED")
    hit, mismatch, missing = seed_units(a.store, a.apply)
    print("  System units seeded : %d  (%d slot(s) this game customised, left "
          "to the translator)" % (hit, mismatch))
    if missing:
        print("  table rows that matched no unit (harmless - the slot may be "
              "empty in this game):")
        for uid in sorted(missing):
            print("     %s" % uid)
    vhit, vmissing = seed_vocab(a.store, a.apply)
    print("  Vocab literals seeded: %d" % vhit)
    if vmissing:
        print("  Vocab rows that matched no script literal: %d" % len(vmissing))
        for jp in list(vmissing)[:10]:
            print("     %r" % jp)
    if not a.apply:
        print("\ndry run - pass --apply to write them into the store and the "
              "script ledger")
    return 0


if __name__ == "__main__":
    sys.exit(main())
