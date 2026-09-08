#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tag_evidence.py - pick release-thread tags from the CORPUS, not from impressions.

You have every line of the game in the store. That is a far better source than
memory of a few scenes, and the failure mode of picking from memory is specific:
a tag that is *mentioned* once gets applied as if it were depicted.

So each candidate tag gets a probe in **both** languages and the hits are
printed for a human to read. Censored spellings survive into a translation and
are often the only unambiguous evidence, which is why the Japanese `raw` is
searched as well as the English `tl`.

Nothing here decides a tag. It prints evidence, counts it, and separates the
tags that are settled by the BUILD (renderer, protagonist, voice) from the ones
that need reading.

    python tools/tag_evidence.py
    python tools/tag_evidence.py --show 6      # more example lines per tag
"""

import os
import re
import sys
import json
import argparse
import collections

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from mvtl import store, config  # noqa: E402

TAGS_JSON = r"C:\Users\sw\Desktop\Games\ForumPostGen\tags.json"

# (tag, english probe, japanese probe). Probes are tightened deliberately:
# a broad one is noisy in exactly the ways that produce a wrong tag.
PROBES = [
    # `お尻` alone is noisy (it is also just "butt"), so it only counts when it
    # is paired with penetration or with the other hole in the same line - which
    # is exactly how CE28 depicts it: お尻とオマンコ…両方同時にピストン.
    ("Anal Sex", r"\banal\b|\bass(?:hole)?\b.{0,24}(?:inside|thrust|filled)",
     r"アナル|尻穴|お尻の穴|お尻.{0,10}(?:と|も).{0,10}(?:オマンコ|前)|お尻.{0,14}(?:入っ|突|ピストン)"),
    ("Ahegao", r"ahegao|eyes? rolled|tongue lolling", r"アヘ顔|白目|舌を出し"),
    ("Bestiality", r"\bbeast\b|\bmutt\b.{0,30}(?:mount|thrust)", r"獣[●〇姦]|犬に.{0,8}(?:犯|突|され)"),
    ("Big Tits", r"\b(?:huge|enormous|massive)\s+(?:tits|breasts)", r"爆乳|巨乳|おっぱい"),
    ("Bukkake", r"bukkake|covered in (?:cum|semen)", r"ぶっかけ|顔射"),
    ("Corruption", r"\bcorrupt|\bdeprav|falling further", r"堕[ちとろ]|淫乱度|調教"),
    ("Creampie", r"creampie|came? inside|filled .{0,12}(?:womb|pussy)", r"中出し|膣内射精"),
    ("Fantasy", r"demon lord|magic|dungeon|monster", r"魔王|魔法|ダンジョン|魔物"),
    ("Female Protagonist", r"", r""),          # settled by the build - see below
    ("Group Sex", r"\bboth of them\b|all (?:three|four) of", r"複数|輪[姦か]|3P|囲まれ"),
    ("Humiliation", r"humiliat|degrad|so pathetic", r"屈辱|惨め|無様|恥ずかし"),
    ("Humor", r"", r""),                       # settled by reading, not grep
    ("Japanese Game", r"", r""),
    ("Male Domination", r"", r"犯[すされし]|押さえつけ|無理やり"),
    ("Masturbation", r"masturbat|touch(?:ing|ed) herself", r"オナニー|自慰|自分で慰め"),
    ("Monster", r"\b(?:slime|orc|goblin|ghost|mimic|tentacle|spider)\b",
     r"スライム|オーク|ゴブリン|幽霊|ミミック|触手|クモ"),
    ("Monster Girl", r"", r"サキュバス|淫魔|魔物娘"),
    ("Oral Sex", r"blowjob|fellatio|in her mouth|suck(?:ing|ed) (?:him|it)",
     r"フェラ|口内|咥え"),
    ("Rape", r"\brape|forced (?:her|onto)|against her will", r"[レﾚ][イｲ][プﾌ]|無理やり|犯され"),
    ("Sandbox", r"", r""),
    ("Tentacles", r"tentacle", r"触手"),
    ("Titfuck", r"titf|paizuri|between her (?:breasts|tits)", r"パイズリ|胸で挟"),
    ("Turn Based Combat", r"", r""),
    ("Vaginal Sex", r"\bpussy\b|\bvagina|thrust into her", r"膣|オマンコ|挿入"),
    ("Voiced", r"", r""),
]

# Settled by the BUILD, not the script. Each carries its evidence.
FROM_BUILD = {
    "2D Game": "RPG Maker MV renderer, hand-drawn 2D CGs (57 S_*.png stills).",
    "2DCG": "Same.",
    "Japanese Game": "RPG Maker MV, System.json locale ja_JP, circle さざめき通り.",
    "Female Protagonist": ("Actors.json holds exactly one actor, ミネリア, and "
                           "all 132 standing pictures are hers."),
    "Fantasy": "Demon lord, magic, dungeon, monsters.",
    "Censored": ("A DLsite JP release is mosaicked by law, so 'Yes (Mosaics)' "
                 "is the right default - but VERIFY it against the CGs before "
                 "posting. This is one of the few fields a reader notices."),
    "Voiced": ("NO. www/audio holds bgm/ bgs/ me/ se/ only - there is no "
               "voice/ folder and no voice cue anywhere in the script."),
    "Combat": ("NO. Troops.json, Enemies.json and Skills.json are all empty and "
               "the census found zero code-301 Battle Processing commands. "
               "Monster contact is a trap, not a fight."),
    "Turn Based Combat": "NO - see Combat.",
    "Animated": ("Check before claiming. ApngPicture / PixiApngAndGif are "
                 "registered, so some pictures may be APNG."),
}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=os.path.join(os.path.dirname(HERE), "tl"))
    ap.add_argument("--show", type=int, default=3)
    args = ap.parse_args(argv)

    docs = store.load_docs(args.store)
    units = [u for _d, u in store.all_units(docs)]
    jp = [(u["id"], u.get("raw") or "") for u in units]
    en = [(u["id"], u.get("tl") or "") for u in units if (u.get("tl") or "").strip()]
    print("corpus: %d units, %d translated\n" % (len(units), len(en)))
    if not en:
        print("(the English half is empty - re-run this after the translation "
              "pass so both languages are searched)\n")

    vocab = set(json.load(open(TAGS_JSON, encoding="utf-8")))
    suggested = []
    for tag, en_re, jp_re in PROBES:
        if tag not in vocab:
            print("!! %r is not in tags.json - the picker would have no chip "
                  "for it" % tag)
        hits = []
        if jp_re:
            rx = re.compile(jp_re)
            hits += [(uid, s, "JP") for uid, s in jp if rx.search(s)]
        if en_re:
            rx = re.compile(en_re, re.I)
            hits += [(uid, s, "EN") for uid, s in en if rx.search(s)]
        if not hits:
            continue
        suggested.append((tag, len(hits)))
        print("%-20s %4d hit(s)" % (tag, len(hits)))
        for uid, s, lang in hits[:args.show]:
            print("      [%s] %-30s %s" % (lang, uid, s.replace("\n", " / ")[:78]))
        print()

    print("=" * 72)
    print("SETTLED BY THE BUILD (evidence, not impression):")
    for tag, why in sorted(FROM_BUILD.items()):
        print("  %-20s %s" % (tag, why))

    print("\n" + "=" * 72)
    print("Read the hits above before committing any of these. Two rules that")
    print("catch most wrong tags:")
    print("  * DEPICTED vs MENTIONED. One line referring to a thing is not a tag.")
    print("  * WHO is doing it. A hit inside a monster's line is not the")
    print("    protagonist doing it, and vice versa.")
    print("\nSuggested starting set (order by hit count, then read):")
    for tag, n in sorted(suggested, key=lambda x: -x[1]):
        print("  %-20s %d" % (tag, n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
