"""Translate the Cock Memories gallery reviews (DataBase T96 メモ fields).

WolfDawn classifies メモ fields as internal dev notes and never extracts them,
but in this game T96's memos are player-facing: Asuka's written review of each
remembered partner, shown in the recollection gallery. Hand-translated in her
blunt diary voice; rows kept under ~72 cells (the JP originals' width).

Edits relayout/db_cur.json in place; apply with:
  wolf db-apply relayout/db_cur.json --base <deployed DataBase.project> -o <out>
"""
import json
import sys
from pathlib import Path

WS = Path(__file__).resolve().parents[1]

MEMOS = {
    1: "President of the AV agency. My boss. Rough sex, pounding hard and deep.\r\n"
       "He's good at foreplay too. Overall pretty good... but I hate the forced cleanup blowjobs.",
    2: "Head of the shopping street association; he looks after me. His full-body\r\n"
       "kissing is gross. Apparently he knocked up his wife with unsanctioned creampie\r\n"
       "play and married her... I really wish he'd wear a condom...",
    3: "Known as \"Nikubo\". Runs Ito Meat in the shopping street. I couldn't even\r\n"
       "tell if it was in... He came in about three strokes and it was over just like that.",
    4: "Moans really loud during sex. The moment he cums, he just wraps things up.\r\n"
       "Normally you'd say something to the girl afterward, right...? Ruins the mood.",
    5: "The pressure inside was incredible. And it's pitch black. The way he licks\r\n"
       "all over my face when we kiss was kind of gross.",
    6: "First-class fingerwork. He works all kinds of pressure points even during sex,\r\n"
       "so I feel refreshed afterward. I think he's pressing the ones inside me too...",
    7: "Quiet at the association meetings, but talkative one-on-one.\r\n"
       "Really hard, with a deep ridge. When he grinds it inside me, it feels great.",
    8: "Treats me like a hooker and goes in with zero foreplay. Not gentle.\r\n"
       "Doesn't even pay me. No wonder his wife stopped sleeping with him...",
    9: "Apparently he loves getting touchy in the bath. He washes me thoroughly,\r\n"
       "but his hands feel lewd and kind of creepy... The money's good, so I endure it...",
    10: "Fully hooded and it won't pull back. So much smegma I worry about\r\n"
        "hygiene. Maybe it's the skin, but it feels baggy inside and not good at all.",
    11: "A thick cock that scoops upward. He's greasy and smelly, but good at\r\n"
        "sex... Judging by how obedient Chiyo-san is, I'd say she's been trained.",
    12: "A relaxed, slow-sex style. Not much stimulation, but it feels gentle.\r\n"
        "This kind isn't bad either... He has trouble getting hard, so I have to\r\n"
        "service him with my mouth.",
    13: "Honestly, I don't know what to think about Dad. He's really rough. I wonder\r\n"
        "if he did Mom like this too... The foreplay was gentle, but knowing this is\r\n"
        "how I was made leaves me with complicated feelings.",
    14: "Bought it on zonama, going by the reviews. Imagining I'm being violated by\r\n"
        "an emotionless machine gets me excited. It's loud, though - I worry the\r\n"
        "next room can hear it.",
    15: "Momoka's nipples are so sensitive (lol). Her kisses are clumsy and she's\r\n"
        "adorable all around. Being like this with Momoka puts my heart at ease.",
    16: "Gloria-sama, my idol: first-rate at singing, dancing, talking - and sex!\r\n"
        "Her fingerwork is incredible... she turns me into a melted mess...\r\n"
        "I want her to ravish me even more.",
}


def main():
    p = WS / "relayout" / "db_cur.json"
    db = json.loads(p.read_text(encoding="utf-8"))
    t = db["types"][96]
    assert "チンポ" in t["name"], t["name"]
    n = 0
    for r in t["rows"]:
        if r.get("id") in MEMOS:
            r["values"]["メモ"] = MEMOS[r["id"]]
            n += 1
    p.write_text(json.dumps(db, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"translated {n} gallery memos into {p.name}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
