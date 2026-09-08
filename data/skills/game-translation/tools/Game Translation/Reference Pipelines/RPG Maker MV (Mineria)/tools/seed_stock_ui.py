#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
seed_stock_ui.py - fill System.json's stock strings with RPG Maker's OWN
official English, and lock them.

Every string below is unchanged RPG Maker MV boilerplate that ships with the
engine in both languages. Matching the engine's published English exactly is
what keeps the UI from reading half-localised - a model asked to translate
`最強装備` in isolation produces "The Strongest Equipment Set", which is
correct and wrong. It is also free: these need no API call at all.

The entries are marked `locked`, so `dryrun`, `run` and `retry` skip them and
an edit here is never overwritten by a later pass.

Nothing here is guessed. Where this game has no battles at all (Troops,
Enemies and Skills are empty and the census found zero code-301 commands) the
battle-log lines still get their canonical English, because they cost nothing
and a later build might use them.

    python tools/seed_stock_ui.py            # report
    python tools/seed_stock_ui.py --apply
"""

import os
import sys
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from mvtl import store, config  # noqa: E402

BASIC = {0: "Level", 2: "HP", 4: "MP", 6: "TP", 8: "EXP"}

COMMANDS = {
    0: "Fight", 1: "Escape", 2: "Attack", 3: "Guard",
    4: "Item", 5: "Skill", 6: "Equip", 7: "Status", 8: "Formation",
    9: "Save", 10: "Game End", 11: "Options",
    12: "Weapon", 13: "Armor", 14: "Key Items", 15: "Equip",
    16: "Optimize", 17: "Clear",
    18: "New Game", 19: "Continue", 21: "Go to Title", 22: "Cancel",
    24: "Buy", 25: "Sell",
}

PARAMS = {
    0: "Max HP", 1: "Max MP", 2: "Attack", 3: "Defense",
    4: "M.Attack", 5: "M.Defense", 6: "Agility", 7: "Luck",
    8: "Hit", 9: "Evasion",
}

# %1 %2 %3 are (name, parameter, value) in that order - Window_BattleLog
# formats them as fmt.format(target.name(), TextManager.hp, value). Keeping the
# canonical order is what stops a battle line reading "Mineria recovered 100 HP"
# where the engine substitutes "HP" into %2.
MESSAGES = {
    "actionFailure": "There was no effect on %1!",
    "actorDamage": "%1 took %2 damage!",
    "actorDrain": "%1 was drained of %2 %3!",
    "actorGain": "%1 gained %2 %3!",
    "actorLoss": "%1 lost %2 %3!",
    "actorNoDamage": "%1 took no damage!",
    "actorNoHit": "Miss! %1 took no damage!",
    "actorRecovery": "%1 recovered %2 %3!",
    "alwaysDash": "Always Dash",
    "bgmVolume": "BGM Volume",
    "bgsVolume": "BGS Volume",
    "buffAdd": "%1's %2 went up!",
    "buffRemove": "%1's %2 returned to normal!",
    "commandRemember": "Command Remember",
    "counterAttack": "%1 counterattacked!",
    "criticalToActor": "A painful blow!!",
    "criticalToEnemy": "An excellent hit!!",
    "debuffAdd": "%1's %2 went down!",
    "defeat": "%1 was defeated.",
    "emerge": "%1 emerged!",
    "enemyDamage": "%1 took %2 damage!",
    "enemyDrain": "%1 was drained of %2 %3!",
    "enemyGain": "%1 gained %2 %3!",
    "enemyLoss": "%1 lost %2 %3!",
    "enemyNoDamage": "%1 took no damage!",
    "enemyNoHit": "Miss! %1 took no damage!",
    "enemyRecovery": "%1 recovered %2 %3!",
    "escapeFailure": "However, it was unable to escape!",
    "escapeStart": "%1 has started to escape!",
    "evasion": "%1 evaded the attack!",
    "expNext": "To Next %1",
    "expTotal": "Current %1",
    "file": "File",
    "levelUp": "%1 is now %2 %3!",
    "loadMessage": "Load which file?",
    "magicEvasion": "%1 nullified the magic!",
    "magicReflection": "%1 reflected the magic!",
    "meVolume": "ME Volume",
    "obtainExp": "%1 %2 received!",
    "obtainGold": "Found %1\\G!",
    "obtainItem": "%1 found!",
    "obtainSkill": "%1 learned!",
    "partyName": "%1's Party",
    "possession": "Possession",
    "preemptive": "%1 got the upper hand!",
    "saveMessage": "Save to which file?",
    "seVolume": "SE Volume",
    "substitute": "%1 protected %2!",
    "surprise": "%1 was surprised!",
    "useItem": "%1 uses %2!",
    "victory": "%1 was victorious!",
}

# Game-specific, but deterministic and short enough to be worth locking.
OTHER = {
    "System:currencyUnit": "G",
    "System:gameTitle": ("Demon Lord Mineria and the Nameless Village's "
                         "Ero Trap Dungeon"),
    "System:armorTypes:1": "General",
    "System:weaponTypes:1": "General",
    "System:equipTypes:1": "Clothing",
    "System:equipTypes:2": "Accessory",
}


def table():
    t = dict(OTHER)
    for i, v in BASIC.items():
        t["System:terms:basic:%d" % i] = v
    for i, v in COMMANDS.items():
        t["System:terms:commands:%d" % i] = v
    for i, v in PARAMS.items():
        t["System:terms:params:%d" % i] = v
    for k, v in MESSAGES.items():
        t["System:terms:messages:%s" % k] = v
    return t


def to_sentinels(seed, code_map):
    """Rewrite the table's readable `%1` / `\\G` into the unit's own sentinels.

    The store masks `%1` and `\\G` to `⟦n⟧` before the model ever sees them, so
    a seed written in raw codes would fail the placeholder check. Substitution
    is longest-code-first and consumes each sentinel once, so a code the source
    uses twice maps to two distinct sentinels rather than collapsing."""
    pending = {}
    for ph, code in code_map.items():
        pending.setdefault(code, []).append(ph)
    for code in pending:
        pending[code].sort(key=lambda p: int(p[1:-1]))
    out = seed
    for code in sorted(pending, key=len, reverse=True):
        queue = list(pending[code])
        parts = out.split(code)
        rebuilt = parts[0]
        for p in parts[1:]:
            rebuilt += (queue.pop(0) if queue else code) + p
        out = rebuilt
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=os.path.join(os.path.dirname(HERE), "tl"))
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)

    from mvtl import codes

    t = table()
    docs = store.load_docs(args.store)
    hit = miss = skipped = 0
    unmatched = set(t)
    for _p, doc in docs:
        if doc["meta"]["source_file"] != "System.json":
            continue
        for u in doc["units"]:
            want = t.get(u["id"])
            if want is None:
                miss += 1
                print("   no stock English for %-34s %r" % (u["id"], u["raw"]))
                continue
            unmatched.discard(u["id"])
            want = to_sentinels(want, u.get("codes") or {})
            if codes.placeholder_ids(u["src"]) != codes.placeholder_ids(want):
                print("   !! %s: placeholder mismatch src%s vs seed%s - skipped"
                      % (u["id"], sorted(codes.placeholder_ids(u["src"])),
                         sorted(codes.placeholder_ids(want))))
                skipped += 1
                continue
            if args.apply:
                u["tl"] = want
                u["locked"] = True
            hit += 1
    if args.apply:
        store.save_docs(docs)
    print("\nstock UI: %d seeded, %d units with no table entry, %d skipped"
          % (hit, miss, skipped))
    if unmatched:
        print("table rows that matched no unit (harmless, but check the ids):")
        for k in sorted(unmatched):
            print("   %s" % k)
    if not args.apply:
        print("\ndry run - pass --apply to write them into the store")
    return 0


if __name__ == "__main__":
    sys.exit(main())
