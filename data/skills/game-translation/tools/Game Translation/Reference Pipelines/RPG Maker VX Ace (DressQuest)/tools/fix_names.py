"""Corrections to the names pass, each from evidence in the corpus.

The text batch was already submitted against the roster as it stood, so these
change the name PLATE (rebuilt from the glossary on inject), the misgender
check, and any later retry - not the dialogue already in flight.
"""
import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
P = r"C:\Users\sw\Desktop\Tools\Game Translation\Active Projects\Dress Quest (RPG Maker VX Ace)"
sys.path.insert(0, P)
from acetl import store

FIX = {
    # jp: (en or None to keep, gender, role, aliases)
    "シル": ("Syl", "female",
            "the Black Dragon sage, real name シルフェイド (Sylpheid); humans "
            "call her a Great Sage. Gives Eris the dresses.",
            ["シルフェイド", "黒竜"]),
    "黒竜": ("Black Dragon", "female",
            "Syl in dragon form - the same character as シル", ["シル"]),
    "レイン": ("Rain", "male",
             "slaver boss who imprisons Eris in Hoodlum; 俺様, sneering",
             []),
    "ウィーク": ("Weak", "male",
              "arena fighter, announced as ウィーク選手; the ring name is "
              "ironic and stays ironic in English", []),
    "ポンチョ": ("Poncho", "male", "rogue who breaks Eris out", []),
    "魔剤士": ("Apothecary", "male",
             "the old potion-brewer of Emilion; elderly speech (じゃ / ぞい)",
             []),
    "マックス": (None, "male", "arena/street fighter Eris repeatedly loses to", []),
    "ガロン": (None, "male", "monster lord", []),
    "お菊": (None, "female", "Zipang-region character, a Japanese given name", []),
    "アリス": (None, "female",
             "worshipped as 有神アリス様, a goddess figure and the antagonist "
             "behind the monster plague", []),
    "マッコリ": (None, "male",
              "fixer who procures 'guests' for the nobles; addressed as "
              "マッコリさん / マッコリ様", []),
    "シーラ": (None, "female", "castle attendant close to the royal family", []),
}

TERMS = {
    "シルフェイド": "Sylpheid",
    "有神": "Goddess",
    "魔剤士": "Apothecary",
    "魔気": "demonic aura",
    "アンファンクアーマー": "Anfunk Armour",
}


def main():
    sdir = os.path.join(P, "tl")
    g = store.load_glossary(sdir)
    changed = []
    for jp, (en, gender, role, aliases) in FIX.items():
        v = g["names"].get(jp)
        if not isinstance(v, dict):
            v = {"en": v or "", "aliases": []}
            g["names"][jp] = v
        before = (v.get("en"), v.get("gender"))
        if en:
            v["en"] = en
        v["gender"] = gender
        if role:
            v["role"] = role
        if aliases:
            v["aliases"] = sorted(set((v.get("aliases") or []) + aliases))
        if before != (v.get("en"), v.get("gender")):
            changed.append("%s: %r/%s -> %r/%s" % (jp, before[0], before[1] or "-",
                                                   v["en"], v["gender"]))
    for k, val in TERMS.items():
        g["terms"].setdefault(k, val)
    store.save_glossary(sdir, g)
    print("glossary corrections:")
    for c in changed:
        print("  " + c)
    blank = [jp for jp, v in g["names"].items()
             if isinstance(v, dict) and not v.get("gender")]
    print("%d name(s) still have no gender (soft misgender check skips them)"
          % len(blank))


main()
