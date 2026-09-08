"""Pre-fill the glossary entries we are certain about.

Only the ones a human would overrule the model on: the heroine, the named cast
whose reading is unambiguous, and the generic role labels that must not drift
between scenes. Everything else is left blank for the names pass.
"""
import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
P = r"C:\Users\sw\Desktop\Tools\Game Translation\Active Projects\Dress Quest (RPG Maker VX Ace)"
sys.path.insert(0, P)
from acetl import store

NAMES = {
    # jp: (en, gender, role, register)
    "エリス": ("Eris", "female", "heroine - knight-commander of Baron, titled the Knight of the White Lotus",
              "formal and commanding in public, first person 私; the formality cracks but never disappears when she is cornered"),
    "白蓮の騎士": ("Knight of the White Lotus", "female", "Eris's title / nickname", ""),
    "クリフ将軍": ("General Cliff", "male", "Eris's second in command", "deferential to Eris, curt with his men"),
    "クリフ": ("Cliff", "male", "General Cliff, in casual reference", ""),
    "バロン王": ("King Baron", "male", "the king of Baron", "regal, then vicious"),
    "バロン兵": ("Baron Soldier", "male", "rank-and-file soldier of Baron", "coarse to civilians, deferential to Eris"),
    "騎士団": ("Knights", "unknown", "Eris's knight order, speaking in chorus", ""),
    "町人": ("Townsperson", "unknown", "generic town NPC", "plain, unpolished"),
    "村人": ("Villager", "unknown", "generic village NPC", ""),
    "村の男": ("Village Man", "male", "generic village NPC", "crude"),
    "村の女性": ("Village Woman", "female", "generic village NPC", ""),
    "村の住人": ("Villager", "unknown", "generic village NPC", ""),
    "村長": ("Village Chief", "male", "village elder", ""),
    "老人": ("Old Man", "male", "generic elderly NPC", ""),
    "子供": ("Child", "unknown", "generic child NPC", ""),
    "モンスター": ("Monster", "unknown", "generic monster speaker", "guttural, leering, short sentences"),
    "オーク": ("Orc", "male", "monster", "guttural"),
    "ゴブリン": ("Goblin", "male", "monster", "guttural"),
    "サキュバス": ("Succubus", "female", "monster", "teasing, dominant"),
    "トロール": ("Troll", "male", "monster", "guttural"),
    "キメラ": ("Chimera", "unknown", "monster", ""),
    "黒竜": ("Black Dragon", "unknown", "monster", ""),
    "ならず者": ("Thug", "male", "bandit / rough", "crude street speech"),
    "ならず者警備": ("Thug Guard", "male", "bandit acting as a guard", "crude"),
    "貴族": ("Nobleman", "male", "aristocrat", "oily formality"),
    "貴族女性": ("Noblewoman", "female", "aristocrat", "oily formality"),
    "メイド": ("Maid", "female", "servant", "polite"),
    "召使い": ("Servant", "unknown", "servant", "polite"),
    "シスター": ("Sister", "female", "nun", "pious"),
    "神父": ("Priest", "male", "clergy", "pious"),
    "大司教": ("Archbishop", "male", "senior clergy", "grand, self-satisfied"),
    "学者": ("Scholar", "male", "researcher NPC", "wordy"),
    "商人": ("Merchant", "male", "shop NPC", ""),
    "旅の商人": ("Traveling Merchant", "male", "shop NPC", ""),
    "旅人": ("Traveler", "unknown", "wandering NPC", ""),
    "受付": ("Receptionist", "unknown", "counter NPC", "polite"),
    "賭博受付": ("Betting Clerk", "male", "arena betting counter", "brisk"),
    "案内人": ("Guide", "unknown", "arena / venue guide", "polite"),
    "参加者": ("Contestant", "male", "arena fighter", ""),
    "司会": ("Announcer", "male", "arena announcer", "loud, showy"),
    "格闘家": ("Brawler", "male", "arena fighter", ""),
    "情報屋": ("Informant", "male", "sells information", "sly"),
    "酔っ払い": ("Drunk", "male", "tavern NPC", "slurred"),
    "乞食": ("Beggar", "male", "street NPC", ""),
    "旅行客": ("Tourist", "unknown", "visitor NPC", ""),
    "姫様": ("Princess", "female", "form of address, not a name", ""),
    "足軽": ("Foot Soldier", "male", "Zipang-region soldier", "samurai-drama diction"),
    "性奴隷の少女": ("Slave Girl", "female", "captive", "broken, frightened"),
    "女盗賊": ("Bandit Woman", "female", "bandit", "rough"),
    "支配人": ("Manager", "male", "venue manager", "unctuous"),
    "調理場のおばちゃん": ("Kitchen Auntie", "female", "castle cook", "warm, familiar"),
    "城下町の飲んだくれ": ("Castle-Town Drunk", "male", "tavern NPC", "slurred"),
    "地獄の調教人": ("Hell's Trainer", "unknown", "monster / tormentor", "cold"),
    "詐欺に遭ったじいさん": ("Swindled Old Man", "male", "sidequest NPC", ""),
    "エリス（村娘）": ("Eris (Village Girl)", "female", "Eris disguised as a village girl", ""),
    "メイド（村娘）": ("Maid (Village Girl)", "female", "village girl in a maid's dress", ""),
}

TERMS = {
    "アンファンクアーマー": "Anfunk Armour",
    "アンファンクアーマーＰ": "Anfunk Armour P",
    "チャイナドレス": "China Dress",
    "メイドドレス": "Maid Dress",
    "巫女ドレス": "Shrine Maiden Dress",
    "マジックドレス": "Magic Dress",
    "シスタードレス": "Sister Dress",
    "フィーラードレス": "Feeler Dress",
    "ドレス": "dress",
    "バロン": "Baron",
    "王都バロン": "the Royal Capital of Baron",
    "バロン城": "Baron Castle",
    "コロン村": "Colon Village",
    "マッスルーム": "Mussroom",
    "レーゲンヘーレ": "Regenhere",
    "エミリオン": "Emilion",
    "デュッセルドルフ": "Dusseldorf",
    "ジパング": "Zipang",
    "鉄の騎士団": "the Iron Knights",
    "騎士団": "the knight order",
    "魔棺": "the Demon Coffin",
    "結界": "barrier",
    "聖水": "holy water",
    "魔法薬": "magic potion",
    "エクスカリバー（贋）": "Excalibur (Replica)",
    "聖剣エクスカリバー": "the Holy Sword Excalibur",
    "回想": "Recollection",
    "周回プレイ": "New Game+",
}


def main():
    sdir = os.path.join(P, "tl")
    g = store.load_glossary(sdir)
    filled = added = 0
    for jp, (en, gender, role, register) in NAMES.items():
        cur = g["names"].get(jp)
        if cur is None:
            g["names"][jp] = {"en": en, "gender": gender, "role": role,
                              "register": register, "aliases": [], "count": 0,
                              "note": "pre-filled by hand"}
            added += 1
            continue
        if not isinstance(cur, dict):
            cur = {"en": cur}
            g["names"][jp] = cur
        if not cur.get("en"):
            cur["en"] = en
            filled += 1
        for k, v in (("gender", gender), ("role", role), ("register", register)):
            if v and not cur.get(k):
                cur[k] = v
    g["terms"].update({k: v for k, v in TERMS.items() if k not in g["terms"]})
    store.save_glossary(sdir, g)
    print("glossary: %d names filled, %d added, %d names total, %d terms"
          % (filled, added, len(g["names"]), len(g["terms"])))
    missing = [(jp, v.get("count", 0)) for jp, v in g["names"].items()
               if isinstance(v, dict) and not v.get("en")]
    missing.sort(key=lambda x: -x[1])
    print("still to translate: %d (top: %s)"
          % (len(missing), ", ".join("%s(%d)" % m for m in missing[:12])))


main()
