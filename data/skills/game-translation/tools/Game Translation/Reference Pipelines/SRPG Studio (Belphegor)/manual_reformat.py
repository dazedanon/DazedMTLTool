#!/usr/bin/env python3
"""Condense overflowing manual pages (Project/Extra/characters.json) so the English
fits the fixed page height (the manual paginates one entry per page; the left text
column is ~43 half-width chars and holds about as many lines as the Japanese used).
Raw-text replacement of the exact en value keeps the file's formatting intact.
"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHARS = os.path.join(ROOT, "Project", "Extra", "characters.json")

# index -> new English body: a compact table/paragraph matching the JP, each line
# <= ~43 half-width chars and total lines <= the JP's (so it never overflows a page).
NEW = {
    0: (
        "Story\n"
        "A succubus descends on the Peor Kingdom\n"
        "in the west of the continent. Her name is\n"
        "Belphegor, Demon King of Lust and Sloth.\n"
        "Her goal: to cast every soul in the kingdom\n"
        "into the depths of corruption.\n"
        "\n"
        "She latches onto Root Elron (the player),\n"
        "sworn servant to Princess Eschalot, and\n"
        "schemes to corrupt him. Tempted again and\n"
        "again, Root slowly begins to fall. Will he\n"
        "yield and sink into darkness? Or honor his\n"
        "ancient oath and live in the light? That\n"
        "choice will decide the kingdom's fate..."
    ),
    1: (
        "Battle Phase\n"
        "Achieve the victory condition. Enemy forces\n"
        "attack, set traps, and more to stop you. As\n"
        "Root Elron, lead your unit to victory. Meet\n"
        "the defeat condition and it's Game Over.\n"
        "\n"
        "Base Phase\n"
        "Ready your forces for battle: buy and issue\n"
        "weapons, class change, and prepare to gain\n"
        "the edge in combat. The Costume Room swaps\n"
        "Battle Skins; the Light arc adds night\n"
        "service, and the Dark arc adds training,\n"
        "breeding, and birthing."
    ),
    5: (
        "Combat Forecast (Left Shift)\n"
        "Select a unit on the map and press Left\n"
        "Shift to show forecasts vs all opposing\n"
        "units; press again to show levels.\n"
        "\n"
        "The forecast shows: top = damage the chosen\n"
        "unit (attacker) deals; mid = damage taken\n"
        "from the foe (counter); bottom = the foe's\n"
        "current HP. Damage = per-hit × attacks,\n"
        "and turns red if it exceeds HP. The bar\n"
        "below is hit rate. If Critical is 1+,\n"
        "'ATK'/'CTR' turn yellow. A '+' shows for\n"
        "multiple attacks. If a weapon will break,\n"
        "its background darkens."
    ),
    6: (
        "Parameters\n"
        " Strength — Phys. attacks; raises Agility\n"
        " Magic — Magic attacks; raises Agility\n"
        " Skill — Hit, Critical, and Critical Avoid\n"
        " Speed — Avoid, Critical Avoid, Agility\n"
        " Arousal — Greatly raises Critical rate\n"
        " Defense — Cuts physical damage taken\n"
        " Res — Cuts magical damage taken\n"
        " Movement — Movement range on the map\n"
        "Combat Stats\n"
        " Attack — Attack power with your weapon\n"
        " Hit — Accuracy with your weapon\n"
        " Critical — Critical rate when attacking\n"
        " Avoid — Your current avoid rate\n"
        " Range — Range of your equipped weapon\n"
        " Agility — Combat speed; beat a foe's by\n"
        "  5 or more to strike twice"
    ),
    8: (
        "Weapon Types\n"
        " Axe — Low hit but high power\n"
        " Sword — Low power but high hit\n"
        " Lance — Balanced power and hit\n"
        " Spear-Axe — Unwieldy but high power\n"
        " Bow — Ranged; strong vs fliers\n"
        " Siege Bow — Arch Armor only; vs fliers\n"
        " Great Bow — Shooter only; vs fliers\n"
        "Weapon Triangle\n"
        " Sword > Axe > Lance > Sword: +15% hit\n"
        " and avoid. Spear-Axe: +10% hit and avoid\n"
        " vs Axe, Sword, and Lance."
    ),
    9: (
        "Magic Types\n"
        " Fire — Fierce flames; average; vs Undead\n"
        " Wind — Power 0 but hits in a row; no\n"
        "  counter; vs fliers\n"
        " Ice — Ice attack; high hit; vs cavalry\n"
        "  and soft-body types\n"
        " Thunder — Lightning; range 3; vs machine\n"
        "  and giant-beast types\n"
        " Light — Holy light; vs Undead and demons\n"
        " Necromancy — Commands the dead; range 2–4\n"
        " Healing Staff — Restores an ally's HP;\n"
        "  some can heal at range\n"
        "※Sages use low-tier light and healing\n"
        " magic; Bishops use low-tier attack magic."
    ),
    13: (
        "Assault Knight\n"
        "Adapts weapons to keep a good matchup.\n"
        "Weapons: Axe, Sword, Lance, Spear-Axe\n"
        "Skills: Berserker II, Counter II, Heavy\n"
        " Strike II, Meat Armor II\n"
        "\n"
        "Social Knight\n"
        "Mounted; Cavalry Charge hits foot units.\n"
        "Weapons: Sword, Lance\n"
        "Skills: Flash Strike II, Pierce II, Heavy\n"
        " Strike II, Meat Armor II\n"
        "\n"
        "Combat Knight\n"
        "Steals items, forces debuffs, wrecks walls.\n"
        "Weapons: Axe, Sword\n"
        "Skills: Flash Strike II, Pierce II, Martial\n"
        " Arts II, Arrow Block II"
    ),
    15: (
        "Arch Knight\n"
        "Bow range 2 but gains Canter; hit-and-run.\n"
        "Weapons: Bow\n"
        "Skills: Flash Strike II, Counter II, Pierce\n"
        " II, Arrow Block II\n"
        "\n"
        "Mage\n"
        "Elemental magic; hits weaknesses hard.\n"
        "Weapons: Tome\n"
        "Skills: Counter II, Martial Arts II, Arrow\n"
        " Block II, Field Camp\n"
        "\n"
        "Priest\n"
        "Holy staff support; scripture vs Undead.\n"
        "Weapons: Scripture, Staff\n"
        "Skills: Counter II, Martial Arts II, Arrow\n"
        " Block II, Field Camp"
    ),
    16: (
        "Selectable Skills\n"
        " Berserker II — Str% to attack 3 times\n"
        " Counter II — Skill×2% crit on counter\n"
        " Heavy Strike II — Str×2% ignore Defense\n"
        " Arrow Block II — Skill×2% negate bows\n"
        " Martial Arts II — Skill×2% dodge melee\n"
        " Flash Strike II — Speed×2% attack again\n"
        " Pierce II — Skill×2% effective damage\n"
        " Meat Armor II — boost: HP +8\n"
        " Field Camp — boost: Movement +1\n"
        "※Skills vary by class.\n"
        "Growth Specialty\n"
        " Raise growth of one stat: Str, Magic,\n"
        " Skill, Speed, Defense, or Res."
    ),
    18: (
        "Aphrodisiac Magic\n"
        "A unit with the Enhanced Slave skill hit by\n"
        "enemy Aphrodisiac Magic starts masturbating\n"
        "on the spot. While doing so, all stats\n"
        "(including Movement) drop and Arousal rises\n"
        "sharply, for 4 turns. A stronger Greater\n"
        "Aphrodisiac Magic also exists.\n"
        "\n"
        "Reverse Night Service\n"
        "As the Princess of Light arc advances, you\n"
        "can perform reverse night service with the\n"
        "heroines, teaching them the powerful Combo\n"
        "Skills. Pick it from 'Communication' in the\n"
        "Base phase."
    ),
    19: (
        "Combo Skills\n"
        "As the Princess of Light arc advances,\n"
        "heroines learn Combo Skills that inflict\n"
        "bad statuses:\n"
        " Disarm \"W\" (Attack −10)\n"
        " Terror \"T\" (Hit, Avoid, Critical −30)\n"
        " Stagger \"B\" (Defense −5)\n"
        "These are strong but clear after 1 battle.\n"
        "\n"
        "Combo Critical Skill\n"
        "Later, heroines learn the Combo Critical\n"
        "Skill: it lands Sure-Hit + Critical on any\n"
        "foe afflicted by a Combo Skill. When held,\n"
        "its icon shows by the portrait. Attack with\n"
        "the unit whose icon matches the inflicted\n"
        "status to trigger it."
    ),
    20: (
        "About Karma\n"
        "In the Dark Chancellor arc, earn Karma by\n"
        "defeating enemies and clearing side quests.\n"
        "Karma is spent on many things in that arc.\n"
        "\n"
        "Demon King Weapon Development\n"
        "Spend Karma to develop the powerful Demon\n"
        "King weapon series. Their uses are restored\n"
        "by clearing a map.\n"
        "\n"
        "Quick Training Room\n"
        "Spend Karma to recruit Enhanced Slaves with\n"
        "no training event — a flat 200 K each."
    ),
    21: (
        "Training & Retraining\n"
        "Defeated heroines can be Trained (via\n"
        "Communication at the Base, for Karma) to\n"
        "join you. Retraining upgrades their skills.\n"
        "\n"
        "Breeding\n"
        "As the story advances, you can breed the\n"
        "heroines. Pick a monster type when breeding\n"
        "to boost that monster's base stats. Once\n"
        "the pregnant heroine beats 3 foes, Prenatal\n"
        "Training begins.\n"
        "\n"
        "Prenatal Training\n"
        "Raping the pregnant heroines raises the\n"
        "monster's growth rates. Then a birth\n"
        "H-scene plays; the monster joins as a unit."
    ),
    23: (
        "Class Change to Tier 1\n"
        "Classes like Recruit Soldier and Vigilante\n"
        "can promote to a Tier 1 class with a Knight\n"
        "Commission at level 5+.\n"
        "\n"
        "Class Change to Tier 2\n"
        "Tier 1 classes promote to Tier 2 with an\n"
        "Advanced Knight Commission at level 15+.\n"
        "Tier 2 also boosts growth, so promote\n"
        "as soon as you meet the conditions.\n"
        "\n"
        "※Root, Eschalot, and Ben-Ami can't use the\n"
        "Advanced Knight Commission; they promote by\n"
        "advancing the story."
    ),
    28: (
        "Titles\n"
        "Meet specific conditions to earn titles.\n"
        "Earning a title increases the Clear Points\n"
        "you get after clearing the game.\n"
        "\n"
        "Clear Points\n"
        "Once earned, Clear Points add to your total\n"
        "even if not re-earned next playthrough. All\n"
        "titles ever earned show on the title menu;\n"
        "titles from the current save show on the\n"
        "battle prep screen. Each run adds to your\n"
        "playthrough count, and Clear Points rise by\n"
        "(difficulty CP × playthrough count)."
    ),
    29: (
        "Titles split into two kinds: 'Title/Base\n"
        "titles' and 'Battle Map titles.' Title/Base\n"
        "titles are earned across all playthroughs —\n"
        "once met in any save, they register. Battle\n"
        "Map titles are tied to the current save.\n"
        "\n"
        "For example, if Root and Ritz fight in\n"
        "Chapter 1 you earn a title; but if you load\n"
        "and finish the chapter without that fight,\n"
        "it lands under Title/Base, not Battle Map.\n"
        "\n"
        "So a boss-fight title often won't appear\n"
        "under Battle Map after a reload — beware.\n"
        "Note: Clear Points use Title/Base titles,\n"
        "so Battle Map titles don't affect them."
    ),
    30: (
        "Single Playthrough Bonus\n"
        "After the Light or Dark ending, start a new\n"
        "game with all skins unlocked. The Costume\n"
        "Room opens from the Base after Chapter 1.\n"
        "\n"
        "Both Stories Bonus\n"
        "After both endings, buy bonus items with\n"
        "Clear Points on a new game. Points refill\n"
        "at each new game's start. Calculation:\n"
        "\n"
        "Sum of cleared difficulty P × playthroughs\n"
        "+ total other title P"
    ),
    31: (
        "Effective Attacks\n"
        "Some weapons and magic deal effective hits\n"
        "to certain enemies. On higher difficulties,\n"
        "using them well is key to clearing maps.\n"
        "Hitting Armor Knight types with an\n"
        "Armorkiller or armor-piercing weapon deals\n"
        "effective damage and negate 'Great Shield.'\n"
        "Don't hold back against tough foes.\n"
        "\n"
        "Fighting Monsters\n"
        "Powerful monsters appear as the story\n"
        "advances. They have weaknesses; attack with\n"
        "weapons or magic effective against them for\n"
        "effective damage. Exploit their weaknesses."
    ),
    32: (
        "Using the Guard Skill\n"
        "Armor Knight types' Guard skill lets them\n"
        "fight for a chosen adjacent ally 1 turn.\n"
        "With it, even Mages hold the front line.\n"
        "Enemies tend to target low-Defense or\n"
        "near-death units; use such a unit as bait\n"
        "and Guard to redirect enemy attacks.\n"
        "\n"
        "Enemy 'Cover' Skill\n"
        "Enemy Armor Knights and Enhanced Slaves\n"
        "have 'Cover,' fighting for adjacent allies.\n"
        "When you spot them, watch enemy positioning\n"
        "and formation."
    ),
    33: (
        "Enemies with Rank Insignia\n"
        "Some enemies carry a Rank Insignia, giving\n"
        "big Defense and Res bonuses — very tough.\n"
        "Weaken them via a Combat Knight or Thief's\n"
        "Steal to take the Insignia. Steal can also\n"
        "force a Binding tool (e.g. Hand Shackles)\n"
        "onto them to weaken them further.\n"
        "\n"
        "Earth Mother & Demon King Weapons\n"
        "Some strong foes can't have their Insignia\n"
        "stolen, or are tough without one. Then send\n"
        "units with strong weapons — Earth Mother or\n"
        "Demon King weapons, from mid-story on.\n"
        "Their uses refill on clearing a map, so use\n"
        "them freely."
    ),
    34: (
        "To carry data from the trial to the full\n"
        "version, or an old version to the latest,\n"
        "move 'environment.evs' and 'Save' folder\n"
        "into the full/latest version's folder and\n"
        "overwrite. As a precaution, copy your old\n"
        "data first. ※Trial v0.9.x saves cannot\n"
        "be transferred. (See the Readme for your\n"
        "version number.)"
    ),
}


def wlen(s):
    return sum(2 if ord(c) > 0x2500 else 1 for c in s)


def manual_body(entry):
    """The wrapped {jp,en} that holds the page's long body text."""
    best = None
    def walk(o):
        nonlocal best
        if isinstance(o, dict):
            if "jp" in o and all(isinstance(v, str) for v in o.values()):
                if best is None or o["jp"].count("\n") > best["jp"].count("\n"):
                    best = o
                return
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(entry)
    return best


def main():
    d = json.load(open(CHARS, encoding="utf-8"))
    raw = open(CHARS, encoding="utf-8").read()
    problems = []
    for idx in sorted(NEW):
        new_en = NEW[idx]
        body = manual_body(d[idx])
        old_en = body["en"]
        lines = new_en.split("\n")
        jp_lines = body["jp"].count("\n") + 1
        wide = [(l, wlen(l)) for l in lines if wlen(l) > 43]
        if len(lines) > jp_lines:
            problems.append(f"[{idx}] {len(lines)} lines > JP {jp_lines}")
        if wide:
            problems.append(f"[{idx}] too wide: {wide}")
        old_esc = json.dumps(old_en, ensure_ascii=False)
        if old_en == new_en:
            continue  # already applied
        if raw.count(old_esc) != 1:
            problems.append(f"[{idx}] old en not uniquely found ({raw.count(old_esc)})")
            continue
        raw = raw.replace(old_esc, json.dumps(new_en, ensure_ascii=False))
    if problems:
        print("PROBLEMS:")
        for p in problems:
            print("  " + p)
        sys.exit(1)
    open(CHARS, "w", encoding="utf-8", newline="").write(raw)
    json.load(open(CHARS, encoding="utf-8"))  # validate
    print(f"reformatted {len(NEW)} pages, all fit; file valid")


if __name__ == "__main__":
    main()
