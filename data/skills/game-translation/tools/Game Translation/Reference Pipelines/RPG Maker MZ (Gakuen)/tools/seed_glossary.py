#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
seed_glossary.py - lock the names and terms that are evidence, not guesses.

Everything here is either an actor record, a name the story states outright, or
a term whose English is fixed by something OTHER than a translator's taste - a
plugin that rewrites it before it reaches the screen, a widget it has to fit,
or a stat the status screen draws next to a number.

The names pass then fills only the ~170 walk-on speakers, with these already in
the cached roster so it has anchors to be consistent with.

    python tools/seed_glossary.py            # report
    python tools/seed_glossary.py --apply
"""

import os
import sys
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from mztl import store  # noqa: E402

# --------------------------------------------------------------------------
# Characters. Actors.json ids 1-8 are the party; the rest are speakers the
# story names.
NAMES = {
    "アズサ": dict(en="Azusa", gender="female",
                 role="protagonist, third-year magic-academy student",
                 register="soft, hesitant, self-deprecating; calls herself "
                          "ワタシ in katakana when she is dissociating",
                 note="Actors.json #1. Trapped in a time loop; must become Top "
                      "Maginoir to escape. MessageAutoReplace draws her name "
                      "in colour 2 wherever it appears in a message."),
    "ミリィ": dict(en="Milly", gender="female",
                 role="Azusa's senior and mentor at the academy",
                 register="warm, confident, teasing",
                 note="Actors.json #2. MessageAutoReplace draws her name in "
                      "colour 18."),
    "ゲイル": dict(en="Gale", gender="male", role="party member",
                 note="Actors.json #3"),
    "ミシェル": dict(en="Michelle", gender="female", role="party member",
                  note="Actors.json #4"),
    "アルベール": dict(en="Albert", gender="male", role="party member",
                   note="Actors.json #5"),
    "ケイシー": dict(en="Casey", gender="female", role="party member",
                  note="Actors.json #6"),
    "エリオット": dict(en="Elliot", gender="male", role="party member",
                   note="Actors.json #7"),
    "ローザ": dict(en="Rosa", gender="female", role="party member",
                 note="Actors.json #8"),
    "ドロシー": dict(en="Dorothy", gender="female",
                  note="named speaker in code-101 parameters[4]"),
    "学園長": dict(en="Principal", gender="male",
                role="head of the magic academy",
                note="named speaker in code-101 parameters[4]"),
    "カネアル": dict(en="Kaneal", gender="male",
                 role="wealthy man with a mansion (Map082)"),
    "カネアルジュニア": dict(en="Kaneal Jr.", gender="male",
                      role="Kaneal's son"),
    "ミカ": dict(en="Mika", gender="female"),
    "サキュバス": dict(en="Succubus", gender="female"),
    "？？？": dict(en="???", gender="",
                note="the engine's own unknown-speaker placeholder - keep the "
                     "three marks, do not name the character"),
    # Displayed differently from what the source writes: MessageAutoReplace
    # rewrites 狂った新郎 to 花嫁泥棒 before the message is drawn, so the player
    # has never seen the words "crazed groom".
    "狂った新郎": dict(en="Bride Thief", gender="male",
                  note="MessageAutoReplace rewrites this to 花嫁泥棒 at draw "
                       "time, so the English must be the English of THAT."),
    "魔人'花嫁泥棒'": dict(en="Demon 'Bride Thief'", gender="male"),
}

# --------------------------------------------------------------------------
# Terms. Not style preferences - each one is pinned by something in the game.
TERMS = {
    # The four houses. The source writes them backwards and a plugin flips
    # them before they are drawn, so the English must match the FLIPPED form.
    "フェニックスクラス, クラスフェニックス": "Class Phoenix",
    "ドラゴンクラス, クラスドラゴン": "Class Dragon",
    "ユニコーンクラス, クラスユニコーン": "Class Unicorn",
    "ドギークラス, クラスドギー": "Class Doggy",
    # Same mechanism.
    "ヴァメリ, ヴァーミリオン": "Vermilion",
    "花嫁泥棒": "Bride Thief",
    # The rank system the whole plot hangs on.
    "マギノワール": "Maginoir",
    "トップマギノワール": "Top Maginoir",
    "魔法学園": "magic academy",
    # Status-screen stats. These are drawn at a fixed x with a number after
    # them, so the English is bounded by the widget, not by taste.
    "淫乱度": "Lewdness",
    "貞操観念": "Chastity",
    "羞恥心": "Shame",
    "プライド": "Pride",
    "ループ": "loop",
    "ループ回数": "Loop Count",
    "肉体の状態": "Physical Condition",
    "精神状態": "Mental State",
    "エッチ経験数": "Sex Count",
    "オナニー回数": "Masturbation Count",
    "フェラ経験数": "Blowjob Count",
    "妊娠回数": "Pregnancy Count",
    "処女を奪った相手": "Took Her Virginity",
    "実績": "Achievements",
    "エロ実績": "Ero Achievements",
    "エンディング": "Endings",
    "エロステータス": "Ero Status",
    "モンスター図鑑": "Bestiary",
    # Recurring nouns whose first rendering would otherwise drift scene to
    # scene across 8,000 lines.
    "オナホ": "onahole",
    "ヤリチン": "fuckboy",
    "陰キャ": "gloomy loner",
    "陽キャ": "popular kid",
    "落ちこぼれ": "washout",
    "エロシーン": "ero scene",
    "既読": "already read",
    "回想部屋": "Recollection Room",
    "生徒会": "Student Council",
    "購買": "school store",
    "保健室": "nurse's office",
    "用務員室": "janitor's room",
    "女子寮": "girls' dormitory",
    "男子寮": "boys' dormitory",
    "大浴場": "public bath",
    "錬金室": "alchemy lab",
    "図書委員": "library committee member",
    "学年主任": "year head",
    "スラム": "slums",
    "闇オークション": "black-market auction",
}

# Strings something reads back as a key. Repeated from config.DO_NOT_TRANSLATE
# so the MODEL is told as well as the injector.
DNT = [
    "右クリック", "選択肢ヘルプ", "テキスト", "画像", "ページ", "初期化",
    "左右", "上下", "透明度", "普通", "ドット", "エロシーン終了",
]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=os.path.join(os.path.dirname(HERE), "tl"))
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)

    g = store.load_glossary(args.store)
    added = updated = absent = 0
    for jp, meta in NAMES.items():
        cur = g["names"].get(jp)
        if cur is None:
            absent += 1
            print("   (not a speaker in the corpus, added anyway) %s" % jp)
        entry = dict(cur) if isinstance(cur, dict) else {}
        entry.update({k: v for k, v in meta.items() if v})
        entry.setdefault("aliases", [])
        if args.apply:
            g["names"][jp] = entry
        if cur is None or not store.name_en(cur):
            added += 1
        else:
            updated += 1

    for jp, en in TERMS.items():
        if args.apply:
            g["terms"][jp] = en
    if args.apply:
        seen = list(g.get("do_not_translate") or [])
        for d in DNT:
            if d not in seen:
                seen.append(d)
        g["do_not_translate"] = seen
        store.save_glossary(args.store, g)

    print("\nnames: %d locked (%d of them new), %d not seen as a speaker" %
          (added + updated, added, absent))
    print("terms: %d" % len(TERMS))
    print("do-not-translate: %d" % len(DNT))
    still = [k for k, v in g["names"].items() if not store.name_en(v)]
    print("names still needing the model: %d" % len(still))
    if not args.apply:
        print("\ndry run - pass --apply to write")
    return 0


if __name__ == "__main__":
    sys.exit(main())
