r"""Where did the English INVENT a gender the Japanese did not state?

    gender_scan.py [--show 30]

Japanese leans on gender-neutral words for people - やつ 奴 こいつ 者 方 - far more than
English does, and a translator reaching for a natural-sounding equivalent
reaches for "guy". That is fine about a man and wrong about the protagonist,
who is female.

WHY THE EXISTING CHECK MISSES IT. `validate`'s misgender warning compares
PRONOUNS against the SPEAKER's gender in the glossary. This defect is neither:
it is a gendered NOUN, applied to the ADDRESSEE. The line is fluent English with
no placeholders, no residual Japanese and no overflow, so nothing else can see
it either.

THREE PASSES, because the wide one is mostly noise:

  invented   the English uses a male term where the Japanese word was NEUTRAL.
             480 hits on this game, and most are correct - the neutral word
             referred to a man who really is one. Useful to skim, not to act on.
  addressed  a male noun predicated of "YOU", in a line whose Japanese carries a
             second-person word, spoken by someone other than the protagonist.
             11 hits, of which 2 were real. That is a list a human can read.
  unsourced  a gendered PRONOUN in the English where the Japanese names no
             referent at all. `逃がさないわよ……！` is a verb and two particles
             with no object, and it shipped as "I won't let HER get away" about
             a man. 1,944 lines match that shape across the corpus, which is
             unreadable, so it is ranked by SOURCE LENGTH: the shorter the
             Japanese, the less room it had to imply anyone, and the more
             certainly the gender was invented. 113 lines at 12 characters.

The unsourced pass cannot be a gate and is not one. It has no way to know who a
line is about, so it returns a REVIEW list for someone who has played the scene.
What it does guarantee is that the question gets asked, which nothing else here
does: the reported line was fluent, placeholder-clean, residual-Japanese-clean,
inside its box, and duplicated across two maps with the SAME wrong pronoun, so
even a same-source consistency check called it consistent.

The narrow pass is the one worth running. The wide one is here so the ratio
stays visible: a check that flags 480 things nobody reads is not a check.
"""

import collections
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from artl import config, store                                       # noqa: E402

# Japanese words for a person that carry NO gender.
NEUTRAL = ["やつ", "奴", "こいつ", "そいつ",
           "あいつ", "人", "者", "方"]
# ...and ones that do, so an English male term is simply correct.
MALE = ["男", "彼は", "彼が", "彼も", "息子",
        "兄", "弟", "父", "おじさん", "少年",
        "王子", "神父", "郎", "紳士", "旦那"]
# Second person: the line is aimed at someone, and in this game that is usually
# the protagonist.
SECOND = ["君", "あんた", "お前", "貴様",
          "あなた", "おぬし", "そなた",
          "おめえ"]

NOUN = (r"(guy|guys|man|men|dude|dudes|boy|boys|fellow|lad|gentleman|sir|bro)")
WIDE = re.compile(r"\b(" + NOUN + r"|he|him|his|himself)\b", re.I)
# A male noun predicated of the person being spoken to.
ADDRESSED = [
    re.compile(r"\byou(?:'re|\s+are|\s+were|\sain't)\b[^.!?\n]{0,44}\b" + NOUN + r"\b", re.I),
    re.compile(r"\b" + NOUN + r"\s+like\s+you\b", re.I),
    re.compile(r"\byou\b[^.!?\n]{0,10}\b" + NOUN + r"\b[^.!?\n]{0,6}[!?.]", re.I),
]

# THIRD PASS: a gendered PRONOUN the source never asked for.
#
# Japanese drops the object constantly. `逃がさないわよ……！` is verb plus
# particles with no object at all, and it came back as "I won't let HER get
# away" about a man. Nothing else can see that: the line is fluent, has no
# placeholders, no residual Japanese, and the same source appears twice
# translated the same wrong way, so even a same-source conflict check calls it
# consistent.
PRONOUN = re.compile(r"\b(she|her|hers|herself|he|him|his|himself)\b", re.I)
# Anything in the Japanese that could licence a third-person pronoun.
REFERENT = ["彼女", "彼", "あいつ", "こいつ", "そいつ", "あの人", "その人",
            "あの子", "この子", "男", "女", "兄", "姉", "弟", "妹", "父", "母",
            "娘", "息子", "少年", "少女", "おじさん", "おばさん", "王子", "王女",
            "おっさん", "嬢", "さん", "ちゃん", "様", "殿", "君", "ママ", "パパ"]
# The shorter the Japanese, the less room it had to imply a referent, so the
# more certainly the gender was invented. 12 characters is the readable tier.
UNSOURCED_MAX_CHARS = 12


def main(*argv):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    show = int(argv[argv.index("--show") + 1]) if "--show" in argv else 30
    cfg = config.load()
    docs = store.load_docs(cfg["store_dir"])
    hero = cfg.get("protagonist_jp", "アルテシア")

    wide, narrow, unsourced, tiers = [], [], [], collections.Counter()
    by_scene = collections.defaultdict(list)
    for _p, u in store.all_units(docs):
        if u["kind"] != "text":
            continue
        en = (u.get("tl") or "")
        jp = u.get("src") or ""
        if not en.strip():
            continue
        if WIDE.search(en) and not any(w in jp for w in MALE) \
                and any(w in jp for w in NEUTRAL):
            wide.append(u)
        if (u.get("speaker") or "") == hero:
            continue
        if not any(w in jp for w in SECOND):
            continue
        for p in ADDRESSED:
            m = p.search(en)
            if m:
                narrow.append((u, m.group(0)))
                break

    for _p, u in store.all_units(docs):
        if u["kind"] != "text":
            continue
        en, jp = (u.get("tl") or ""), (u.get("src") or "")
        if not en.strip() or not jp.strip():
            continue
        if not PRONOUN.search(en) or any(w in jp for w in REFERENT):
            continue
        longest = max((len(l) for l in jp.split("\n") if l.strip()), default=0)
        for tier in (12, 16, 20, 24):
            if longest <= tier:
                tiers[tier] += 1
        if longest <= UNSOURCED_MAX_CHARS:
            unsourced.append(u)
        # Ranking by source length alone buried three of the four lines in one
        # reported scene at 13, 15 and 16 characters. The model does not invent
        # a gender per line, it commits to one for a whole SCENE and runs with
        # it, so count per script and review the scene rather than the line.
        if longest <= 24:
            by_scene[u["id"].rsplit(":", 2)[0]].append(u)

    print("GENDER SCAN")
    print("  wide   - male term where the Japanese word is neutral : %d" % len(wide))
    print("  narrow - male noun applied to the ADDRESSEE           : %d" % len(narrow))
    print("  unsourced - gendered PRONOUN the Japanese never asked for:")
    for tier in (24, 20, 16, 12):
        print("      Japanese line <= %2d chars : %4d%s"
              % (tier, tiers[tier], "   <-- the readable tier"
                 if tier == UNSOURCED_MAX_CHARS else ""))
    worst = [(k, v) for k, v in
             sorted(by_scene.items(), key=lambda kv: -len(kv[1])) if len(v) > 1]
    print("\n  BY SCENE, most unsourced pronouns first. Fix the scene, not the")
    print("  line: several in one scene is ONE guess repeated, not several.\n")
    for scene, us in worst[:show]:
        mixed = len(set("F" if re.search(r"\b(she|her|hers|herself)\b",
                                         u["tl"], re.I) else "M"
                        for u in us)) > 1
        print("   %-44s %2d lines%s"
              % (scene[:44], len(us), "   MIXED GENDER" if mixed else ""))
        for u in us[:3]:
            print("        jp: %s" % (u.get("src") or "").replace("\n", " ")[:38])
            print("        en: %s" % (u.get("tl") or "").replace("\n", " ")[:68])

    print("\n  the unsourced list, shortest source first - the gender in these")
    print("  came from the model, so each one needs a human who knows the scene:\n")
    for u in sorted(unsourced, key=lambda x: len(x.get("src") or ""))[:show]:
        print("   [%s] jp: %s" % ((u.get("speaker_en") or u.get("speaker") or "-")[:16],
                                  (u.get("src") or "").replace("\n", " / ")[:44]))
        print("        en: %s" % (u.get("tl") or "").replace("\n", " / ")[:76])
        print("        %s" % u["id"][:54])
    if not unsourced:
        print("   nothing")
    print("\n  the narrow list is the one to read next:\n")
    for u, frag in narrow[:show]:
        print("   [%s]  ...%s..." % (
            (u.get("speaker_en") or u.get("speaker") or "-")[:20], frag[:56]))
        print("       jp: %s" % (u.get("src") or "").replace("\n", " / ")[:74])
        print("       en: %s" % (u.get("tl") or "").replace("\n", " / ")[:82])
        print("       %s" % u["id"][:54])
    if not narrow:
        print("   nothing")
    by = collections.Counter(
        (u.get("speaker_en") or u.get("speaker") or "-") for u, _f in narrow)
    if by:
        print("\n  by speaker: %s" % dict(by.most_common(8)))
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
