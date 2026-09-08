#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
validate.py - what blocks injection, what only asks for a look.

HARD failures (block, and drive the retry queue):

    empty                 no translation
    identical             byte-identical to the source
    residual-jp           hiragana or kanji left in the output
    placeholder           the ⟦n⟧ sentinel set changed
    control-code          the RESTORED codes changed as a multiset
    overflow              wider than its widget's box AND wider than the JP
    degenerate            collapsed to one character, or a 45-long run
    leaked-scaffolding    `}Line1:` style output bleeding into player text
    number-drift          the visible numbers changed, in order
    invented-backslash    a backslash the model wrote that the source lacked
    invented-sentinel     a `[n]` sentinel the model added - it restores to
                          NOTHING on a unit with no codes, so the literal
                          sentinel ships on screen

and six engine-level traps recovered by decompiling MessageReader, every one of
which English can create and Japanese cannot (`ENGINE-CODES.md`):

    comma-in-code-arg     `\NPL[Smith, Jr.]` renders as `Smith` - the engine
                          splits every bracket argument on ASCII comma and
                          reads element 0
    unsafe-code-arg       a `]` `,` TAB or newline in text that is written
                          INSIDE a code bracket - checked on the value, never
                          by a whole-line regex, which cannot tell two codes on
                          one line apart
    blink-collision       `\blinked` matches the `blink` command by StartsWith
                          and then indexes an empty array
    tab-becomes-backslash a real TAB is drawn as a visible `\`
    trailing-backslash    a `\` at end of line eats the next line's first char
    bracket-after-bare-escape  `\b[x]` toggles bold and DELETES `[x]`

SOFT warnings (review, never block):

    misgender, over-expansion, leftover cosmetic kana, suspicious length ratio,
    same-source-different-translation, romanization near-miss.

Length ratio is deliberately NOT in the blocking set: JP to EN routinely
triples, and forcing review on expansion drowns the queue in good lines and
spends the whole review budget on noise.
"""

import re
import unicodedata
import collections

from . import budgets, codes, measure, store

_HE_RE = re.compile(r"\b(?:he|him|his|himself)\b", re.I)
_SHE_RE = re.compile(r"\b(?:she|her|hers|herself)\b", re.I)
_SCAFFOLD_RE = re.compile(r"(?:^|[}\]])\s*Line\d+\s*:", re.I)
_DEGEN_RE = re.compile(r"(.)\1{44,}")
_NUM_RE = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d+(?:[.,]\d+)?(?![A-Za-z0-9_])")
_PLACEHOLDER_WORD_RE = re.compile(r"^\s*(placeholder|todo|n/?a|tbd)\s*$", re.I)
# A capitalised word in the output, for the romanization-drift scan below.
# This is the SECOND constant the adaptation deleted while keeping its call
# site - the first, `_BARE_ESCAPE_RE`, took `validate` down on the first
# translated unit. This one hid a step further in: `romanization_near_misses`
# returns early when no glossary name is 6+ characters, so it was unreachable
# until the names pass filled the roster, and the review that caught the first
# could not reach it either. Both are the same failure - carrying a call across
# without its definition - and the fix for the class is the suite calling the
# function, not a sharper eye.
_TOKEN_RE = re.compile(r"(?<![\w])[A-Z][A-Za-z'’]+(?![\w])")


# --------------------------------------------------------------------------
# Number comparison
# --------------------------------------------------------------------------
# Quantity drift is the most damaging class of fluent-but-wrong output - 三日後
# as "in a few days", a quest needing 3 items described as needing 5 - and every
# one of those is grammatical English that spelling, grammar and placeholder
# checks wave straight through.
#
# The canonicalisation below is CODE carried over from two finished games
# (RPG Maker MV / Mineria, 61 flags to 5; VX Ace / DressQuest, 246 to 47). The
# rules are reusable. The MEASUREMENTS quoted in these comments belong to THOSE
# corpora and have NOT been re-derived here - re-run `audit/numablate.py` after
# this game's first full pass and rewrite the numbers from its evidence, rather
# than trusting a comment that already sounds settled.
#
# On those corpora a naive digit-for-digit comparison produced SEVEN false
# positives on the first run and zero true ones, and a check that cries wolf is
# a check that gets switched off. Every failure was the comparison's, not the
# translation's:
#
#   5000万G   -> "50,000,000 G"   CJK myriad grouping: 5000万 IS 50 million
#   10000G    -> "10,000G"        a thousands separator, and the trailing
#                                 currency unit made the two sides parse
#                                 asymmetrically
#   100年     -> "a hundred years"  English legitimately spells numbers out
#   2倍       -> "Doubles"          and legitimately lexicalises them
#
# So both sides are normalised to a canonical digit form first. The `3rd` /
# `HP100` / `Lv5` exemptions the lookarounds exist for still hold.

# `憶` (remember) is THIS AUTHOR's consistent typo for `億` (10^8). He writes
# `100憶G` and the correct English is "10 billion G" - so without this the
# check reports its own three loudest CONFLICT flags on three correct
# translations. Measured on this corpus, not inherited: `grep -c 憶G` finds it
# only ever adjacent to a digit and a currency mark.
_MYRIAD = [("兆", 10 ** 12), ("億", 10 ** 8), ("憶", 10 ** 8),
           ("万", 10 ** 4), ("千", 10 ** 3)]

_WORD_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}
_WORD_SCALES = {"hundred": 100, "thousand": 1000, "million": 10 ** 6,
                "billion": 10 ** 9}
# English ordinal WORDS, and a rule that is OFF after being measured.
#
# The skill's rule is CONVERT an ordinal on both sides, never delete it, and in
# isolation this works exactly as advertised: with the table on,
# `6番目の妻の2人目の子供` and "my sixth wife's second child" both canonicalise
# to ['6','2'], and `二度目` matches "the second time".
#
# MEASURED over this corpus anyway (`audit/ordinal_ablate.py`), because a rule
# that fixes the case in front of you can still lose on aggregate:
#
#     OFF   total 276   CONFLICT 29   invented 172   dropped 75
#     ON    total 290   CONFLICT 34   invented 195   dropped 61
#
# Worse on the total by 14 and worse on CONFLICT by 5 - and CONFLICT is the one
# bucket a real quantity error has to land in, so growing it to fix presentation
# in the others is a bad trade. The cause is that English uses ordinal words in
# prose where the Japanese has no numeral at all ("the second time you've tried
# that line", "second to none"), and every one of those becomes an invented
# number.
#
# So the table is left populated and the RULE IS OFF, which is the same shape
# as `_KANA_NUM` above: the next game may write its ordinals differently, and
# the measurement is the thing worth keeping.
_ORDINAL_WORDS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
    "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14,
    "fifteenth": 15, "twentieth": 20, "thirtieth": 30,
}
# `second` is also a unit of TIME, and "a second", "one more second", "for a
# second" are not the number 2. Guarded the way the skill records.
_ORDINAL_WORD_RE = re.compile(
    r"(?<!\ba )(?<!more )(?<!single )(?<!\bany )\b("
    + "|".join(sorted(_ORDINAL_WORDS, key=len, reverse=True)) + r")\b",
    re.I)
ORDINAL_WORDS_ENABLED = False

# Lexicalised multipliers. `2倍 -> "Doubles"` is a correct rendering, not a
# dropped number.
_WORD_MULT = {"double": 2, "doubles": 2, "doubled": 2, "twice": 2,
              "triple": 3, "triples": 3, "tripled": 3, "thrice": 3,
              "quadruple": 4, "quadruples": 4}
# `once` is deliberately absent. It is an adverb far more often than a count -
# "once my power's back", "at once", "once more", "once attached to the
# dungeon" - and mapping it to 1 flagged sixteen correct lines on the corpus
# this was tuned against.

# Kanji numerals, converted only when a COUNTER follows. `三日後` is a quantity
# and is the canonical damaging case ("in a few days"). `一番`, `一体`, `一緒`,
# `一人前` are lexical, and converting those would invent a number on the source
# side that no correct translation contains - turning the check into a false
# positive generator, which is how a check gets switched off.
_KANJI_DIGIT = {"〇": 0, "零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
                "六": 6, "七": 7, "八": 8, "九": 9}
_KANJI_SCALE = [("兆", 10 ** 12), ("億", 10 ** 8), ("憶", 10 ** 8),
                ("万", 10 ** 4), ("千", 10 ** 3), ("百", 10 ** 2), ("十", 10)]
# Two characters are deliberately NOT counters, because in the corpora this
# table was tuned on they are overwhelmingly part of an ordinary word:
#   体  `一体` is "what on earth", not "one body"
#   分  `十分` is じゅうぶん "enough" / "thoroughly", not じゅっぷん "ten minutes"
#       (`もう十分お持ちのようですね`, `魔力切れには十分注意`)
# Admitting either invents a number on the source side of perfectly ordinary
# prose, and a check that cries wolf is a check that gets switched off.
# `番` was added on the VX Ace game's evidence: `五番の耳を噛む` ("bites number five's
# ear") is a real quantity the English spells out, and the one lexical use,
# `一番` meaning "the most", canonicalises to 1 - which is dropped symmetrically
# from both sides anyway, so admitting it costs nothing.
#   位  `7位` is a rank the English writes as "7th place"
#   点  `三点攻め` is "three points" / "a triple assault"
_COUNTERS = "日人個回年月時秒匹枚本階度倍円歳割層つ番位点"

# An English ORDINAL suffix. `_NUM_RE` refuses a digit followed by a letter, so
# that `Lv5` and `HP100` are not read as quantities - but that same rule makes
# `7th` invisible on the English side while the Japanese `7位` is perfectly
# visible, so every rank in the game read as a dropped number. Strip the suffix
# before the scan; the guard against `Lv5` is unaffected because the digit
# comes FIRST here.
_ORDINAL_RE = re.compile(r"(?<=\d)(?:st|nd|rd|th)\b", re.I)
# Japanese ordinal markers. `第N章` / `N番目` / `N度目` / `N人目` are ordinals:
# strip the MARKER so the counter rules can convert the numeral underneath, and
# let the English ordinal word convert to the same digit. The skill's rule is
# CONVERT on both sides, never delete - deleting is one-sided, because English
# renders a Japanese ordinal as a cardinal and the reverse.
_JP_ORDINAL_PRE_RE = re.compile(r"第(?=[0-9〇零一二三四五六七八九十百千]) ?")
_JP_ORDINAL_POST_RE = re.compile(
    r"(?<=[0-9])\s*(?:番目|度目|人目|回目|作目|冊目|本目)")
# NOTATION, not quantity: a chapter, a floor, a rank, a serial. The two
# languages spell these with different tokens (`地下2階` against "B2"), so no
# conversion aligns them and they are deleted on BOTH sides.
_NOTATION_RE = re.compile(
    r"[0-9]+\s*(?:章|階|階層|等|位|丁目|周年)"
    r"|(?:Chapter|Ch\.|Floor|Level|Lv\.?|Stage|Act|Part|Volume|Vol\.|No\.)"
    r"\s*[0-9]+", re.I)
# `何` before a numeral makes it INDEFINITE - 何百年 is "hundreds of years",
# not 100 years - so the quantity is not comparable.
# Native kana numerals. `ふたつ：` heads a numbered list in this corpus and the
# English renders it "Two:", which no kanji rule can see.
#
# MEASURED, by ablation over the finished corpus (`audit/numablate.py`):
# the full table including ひとり and ふたり fixed 3 units and CREATED 23, a
# net +20 - because "ふたりきり" is "alone together" and "ひとりで" is "by
# herself", and English writes neither as a digit. Only the つ-series survives,
# and only from ふたつ up, since ひとつ is "a"/"one thing" far more often than
# it is the number 1 (and 1 is dropped symmetrically anyway).
# Narrowing it to the つ-series alone still nets +3 (fixes 3, causes 6), so the
# rule is OFF. It is left here, empty and documented, because the next game may
# write its counts this way and the measurement is the thing worth keeping.
#
# RE-MEASURED ON THIS GAME (`audit/kana_ablate.py`), because a per-game ruling
# does not travel and this author writes `ふたりの動きが止まった` where the English
# says "the two of them". Over 261 flagged distinct sources:
#
#     OFF (current)          total 261   CONFLICT 27   invented 172   dropped  62
#     tsu-series only        total 315   CONFLICT 30   invented 153   dropped 132   +54
#     people only            total 240   CONFLICT 30   invented 144   dropped  66   -21
#     hitori/hitotsu only    total 261   CONFLICT 27   invented 172   dropped  62    +0
#     all together           total 292   CONFLICT 29   invented 127   dropped 136   +31
#
# The つ-series is worse here too, and by more. The `people` group is the only
# one that lowers the TOTAL - and it raises CONFLICT from 27 to 30, which is
# the one bucket a real quantity error has to land in. Trading three new
# conflicts for twenty-one fewer invented flags is exactly the sideways churn
# the skill warns about, so the rule stays OFF on a second corpus.
_KANA_NUM = {}
_KANA_NUM_RE = re.compile("|".join(sorted(_KANA_NUM, key=len, reverse=True))
                          or r"(?!x)x")

_KANJI_NUM_RE = re.compile(
    r"(?<![0-9何])([〇零一二三四五六七八九十百千万億兆]{1,8})(?=["
    + _COUNTERS + r"])")


def _kanji_to_int(s):
    """`三` -> 3, `十五` -> 15, `五千万` -> 50000000. None if it does not parse."""
    total = section = cur = 0
    seen = False
    for ch in s:
        if ch in _KANJI_DIGIT:
            cur = _KANJI_DIGIT[ch]
            seen = True
            continue
        scale = dict(_KANJI_SCALE).get(ch)
        if scale is None:
            return None
        seen = True
        if scale >= 10 ** 4:
            section = (section + (cur or 0)) or 1
            total += section * scale
            section = cur = 0
        else:
            section += (cur or 1) * scale
            cur = 0
    return (total + section + cur) if seen else None

# `a`, `an` and `one` are only numerals when a SCALE follows ("a hundred") or
# when they close a longer numeral ("twenty one"). Standing alone they are an
# article or a pronoun, and "the one I took" was being read as the number 1 -
# inventing a quantity on the English side of ordinary prose.
_UNITS_ALT = "|".join(sorted(_WORD_UNITS, key=len, reverse=True))
# `one` may CONTINUE a numeral ("twenty one") but may not LEAD one, because a
# leading "one" is usually the pronoun. The cost of this is that a bare "one
# item" against a source `1個` no longer matches; that is the cheaper error, and
# this corpus writes its counts as digits anyway (`（上限3個）`).
_UNITS_LEAD = "|".join(sorted((k for k in _WORD_UNITS if k != "one"),
                              key=len, reverse=True))
_SCALES_ALT = "|".join(_WORD_SCALES)
_WORD_RE = re.compile(
    r"\b(?:"
    r"(?:a|an|one)[\s-]+(?:%s)"                  # a hundred / one thousand
    r"|(?:%s)(?:[\s-]+(?:%s|%s))*"               # ten, twenty one, three hundred
    r")\b" % (_SCALES_ALT, _UNITS_LEAD, _UNITS_ALT, _SCALES_ALT), re.I)
_MULT_RE = re.compile(r"\b(%s)\b" % "|".join(sorted(_WORD_MULT, key=len,
                                                    reverse=True)), re.I)
# `15 million` - a DIGIT followed by a scale word. English writes a large round
# number that way and Japanese writes it with a myriad mark (`１５００万`), so
# without this rule every auction bid in the game reads as drift: the source
# canonicalises to 15000000 and the target stays 15.
_DIGIT_SCALE_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)[\s-]+(%s)\b" % "|".join(_WORD_SCALES), re.I)
# A scale word standing alone with no numeral in front of it. `上位１００名`
# rendered "the top hundred" is a correct translation, and the bare "hundred"
# was reading as no number at all.
_BARE_SCALE_RE = re.compile(
    r"(?<![\w-])(%s)\b" % "|".join(_WORD_SCALES), re.I)


def _words_to_int(phrase):
    """`a hundred` -> 100, `twenty three` -> 23. None when the phrase is not
    actually a number ("a", "an" alone, or a bare article before a noun)."""
    toks = re.split(r"[\s-]+", phrase.strip().lower())
    total = cur = 0
    seen = False
    for t in toks:
        if t in ("a", "an"):
            cur = cur or 1
            continue
        if t in _WORD_UNITS:
            cur += _WORD_UNITS[t]
            seen = True
        elif t in _WORD_SCALES:
            cur = (cur or 1) * _WORD_SCALES[t]
            if _WORD_SCALES[t] >= 1000:
                total += cur
                cur = 0
            seen = True
        else:
            return None
    return (total + cur) if seen else None


def _canonical_numbers(text, currency="G"):
    """Both sides reduced to the same digit form before comparison."""
    t = codes.PH_RE.sub("", text)
    t = re.sub(r"\\+[A-Za-z]+\[[^\]]*\]", "", t)
    t = unicodedata.normalize("NFKC", t)

    # Order matters. Every step below assumes the digits are already settled by
    # the ones above it.

    # 0. NOTATION is deleted on both sides before anything reads a digit: a
    #    chapter, a floor, a rank and a serial number are labels, and the two
    #    languages spell them with different tokens, so no conversion aligns
    #    them.
    t = _NOTATION_RE.sub(" ", t)

    # 0b. ordinal MARKERS, stripped so the numeral underneath can convert. The
    #     marker goes, the number stays - deleting the number instead is
    #     one-sided, because English renders the same ordinal as a cardinal.
    t = _JP_ORDINAL_PRE_RE.sub("", t)
    if ORDINAL_WORDS_ENABLED:
        t = _ORDINAL_WORD_RE.sub(
            lambda m: str(_ORDINAL_WORDS[m.group(1).lower()]), t)

    # 0c. native kana numerals, before anything reads the digits
    t = _KANA_NUM_RE.sub(lambda m: str(_KANA_NUM[m.group(0)]), t)

    # 1. kanji numerals, counter-gated
    def _k(m):
        v = _kanji_to_int(m.group(1))
        return str(v) if v is not None else m.group(1)
    t = _KANJI_NUM_RE.sub(_k, t)

    # 1b. the ordinal SUFFIX, after the numeral is a digit.
    #
    #     This has to run AFTER step 1, not with the other ordinal rules at 0b.
    #     `二度目` carries its numeral in kanji, so at 0b there is no digit for
    #     `(?<=[0-9])` to anchor on; step 1 then converts `二度` to `2` because
    #     `度` is a counter, leaving a dangling `目`. Stripping the suffix here
    #     - after the counter has been consumed - handles the kanji and the
    #     arabic forms with one rule.
    t = re.sub(r"(?<=[0-9])\s*(?:番目|度目|人目|回目|作目|冊目|本目|目)", "", t)

    # 2. 1,234,567 -> 1234567, only where the grouping is well formed so a real
    #    decimal comma survives
    t = re.sub(r"(?<![\d,])\d{1,3}(?:,\d{3})+(?![\d,])",
               lambda m: m.group(0).replace(",", ""), t)

    # 2b. `N割` is TENTHS: 9割 is 90%, and the English writes "90%". Without
    #     this the two sides read 9 against 90 on every percentage the author
    #     writes the Japanese way. `割` stays in `_COUNTERS` as well, which is
    #     harmless - this rule consumes the pair before the counter rule sees
    #     it.
    t = re.sub(r"(\d+)\s*割", lambda m: str(int(m.group(1)) * 10), t)

    # 3. 5000万 -> 50000000. Largest scale first so a chain reduces correctly.
    #    Must run AFTER step 1 or `5000万` would have its 万 read as a bare
    #    kanji numeral and become `500010000`.
    for mark, scale in _MYRIAD:
        t = re.sub(r"(\d+)\s*" + mark,
                   lambda m, s=scale: str(int(m.group(1)) * s), t)

    # 4. detach the currency unit, which is a UNIT and not the `3rd` ordinal the
    #    trailing-letter exemption exists for. `\b` is wrong here: `G受` has no
    #    ASCII word boundary, so the Japanese side would keep its G and parse
    #    asymmetrically against the English. Must run AFTER step 3 so `5000万G`
    #    has become `50000000G` and the digit is adjacent.
    if currency:
        t = re.sub(r"(?<=\d)\s*%s(?![A-Za-z])" % re.escape(currency), " ", t)

    # 5. English lexicalisations and spelled-out numerals.
    #    Digit-plus-scale FIRST, so `15 million` is consumed as one value
    #    before the bare-scale rule can turn its `million` into a lone
    #    1000000 sitting next to a 15.
    t = _DIGIT_SCALE_RE.sub(
        lambda m: str(int(float(m.group(1)) * _WORD_SCALES[m.group(2).lower()])), t)
    t = _MULT_RE.sub(lambda m: str(_WORD_MULT[m.group(1).lower()]), t)

    def _w(m):
        v = _words_to_int(m.group(0))
        return str(v) if v is not None else m.group(0)
    t = _WORD_RE.sub(_w, t)
    t = _BARE_SCALE_RE.sub(lambda m: str(_WORD_SCALES[m.group(1).lower()]), t)
    t = _ORDINAL_RE.sub("", t)

    # A `+` before a digit is a SIGN, and a sign never changes the magnitude.
    # Drop it on both sides. Without this, `回数＋１` reads as "+1" while
    # `Count+1` reads as "1" (`_NUM_RE` will not take a sign that is glued to a
    # letter), and `MAXHP*5%アップ` reads as "5" while "MaxHP +5%" reads as
    # "+5" - twenty-two skill names flagged for a plus sign. `-` is left alone
    # because it does change the value.
    t = re.sub(r"\+(?=\d)", " ", t)

    # THE VALUE 1 IS NOT COMPARABLE ACROSS THESE TWO LANGUAGES and is dropped
    # from both sides. Japanese writes it as a counter (`一匹`, `一人`, `一回`,
    # `一つ`) where English uses an article, a pronoun or nothing at all -
    # `ゴブリン一匹に` is "even one goblin", `一人歩き` is "took on a life of its
    # own", `一気に` is "all at once". Every one of those is a correct
    # translation and every one was being flagged.
    #
    # This costs almost nothing, because the exemption is SYMMETRIC and a real
    # drift still shows: `1個` rendered "3 items" is [] vs ['3'], and `3個`
    # rendered "one item" is ['3'] vs []. Only 1-rendered-as-1 and
    # 1-rendered-as-nothing stop being distinguishable, and the second is a
    # dropped article rather than a quantity error.
    return [n for n in _NUM_RE.findall(t) if n not in ("1", "1.0")]


def _visible_numbers(text):
    """Numbers a player actually sees, canonicalised. Compared ORDERED, so
    "3 of the 5" becoming "5 of the 3" is still caught."""
    return _canonical_numbers(text)


def waivers(u):
    """`{check: reason}` for checks deliberately accepted on this unit.

    A validator with no escape hatch gets switched off wholesale the first time
    it is right about the shape and wrong about the case. A waiver is per-unit
    and per-check, must carry a reason, and is REPORTED by `validate` rather
    than silently applied - a suppression nobody can see is worse than the
    false positive it hides."""
    w = u.get("waive") or {}
    return {k: v for k, v in w.items() if isinstance(v, str) and v.strip()}


def hard_issues(u, cfg=None, m=None):
    """Ordered cheapest-first, short-circuiting on the cheap ones."""
    tl = u.get("tl") or ""
    if u.get("locked"):
        # A locked unit was filled deliberately - from RPG Maker's own English,
        # from a mirror of another file's value, or pre-filled with itself
        # because its body is a row of ellipses and only its NAMEPLATE needed
        # translating. 82 of those were being reported as `identical`, which is
        # exactly what they are and exactly what was intended; counting them
        # buries the 33 units where the model really did echo the source.
        return []
    if not tl.strip():
        return ["empty"]
    out = []
    src = u.get("src") or ""
    waived = waivers(u)

    # Compare what will actually SHIP, not the raw model output. The offline
    # cleanup in `codes.clean_translation` runs at inject time and converts a
    # stranded sokuon or vu, so a reply of `…………ッ` against a source of
    # `…………ッ` is reported identical here while the injected value would be
    # `…………` - a flag on a unit that is already fixed downstream.
    if codes.clean_translation(tl).strip() == src.strip():
        out.append("identical")
    if _PLACEHOLDER_WORD_RE.match(tl):
        out.append("placeholder-word")
    # Also on the SHIPPED value. `strip_residual_kana` is deterministic and
    # bails out unchanged the moment any full-size kana or kanji survives, so
    # it can only clear genuinely stranded decoration - a `ゔ` growled onto the
    # end of an English word, a sokuon after an ellipsis. Checking the raw
    # reply instead reports 116 units that inject would already have fixed, and
    # a retry on those can only produce the same decoration again.
    if codes.has_untranslated_jp(codes.clean_translation(tl)):
        out.append("residual-jp")
    if codes.placeholder_ids(src) != codes.placeholder_ids(tl):
        # A missing SENTINEL is not automatically a missing CODE. The model
        # frequently restores a code itself - it writes `%1's attack!` where
        # the payload said `⟦0⟧の攻撃！` - and the result is byte-identical to
        # what the injector would have produced. 145 of this game's first 150
        # sentinel flags were exactly that, and retrying them could only make
        # them worse.
        #
        # So the sentinel comparison is a CHEAP PRE-FILTER, and what decides is
        # the restored text as a multiset - the same test the control-code
        # check already applies. A genuinely dropped `\C[18]` or `\cm[...]`
        # still fails here, because restoring cannot invent it back.
        #
        # BUT the restored-multiset fallback only covers sentinels whose value
        # is a control code `_CODE_RE` can see. A choice-visibility clause
        # (`en(v[3]<=50)`) is masked into a sentinel too, and it is NOT a
        # control code - so a dropped one is invisible to the multiset and this
        # relaxation waved four of them straight through. The injected choice
        # came out as "Yes (Chastity 50 or Below)" with its gate deleted, which
        # makes a stat-gated option permanently visible. Any missing sentinel
        # that does not restore to a recognised code is a HARD failure.
        cmap = u.get("codes") or {}
        missing = codes.placeholder_ids(src) - codes.placeholder_ids(tl)
        opaque = [pid for pid in missing
                  if not codes.code_multiset(
                      cmap.get("%s%d%s" % (codes.PH_OPEN, pid, codes.PH_CLOSE), ""))]
        if opaque:
            out.append("placeholder")
        else:
            a = codes.code_multiset(codes.unmask_codes(src, cmap, pad_inserts=False))
            b = codes.code_multiset(codes.unmask_codes(tl, cmap, pad_inserts=False))
            if a != b:
                out.append("placeholder")
    if _SCAFFOLD_RE.search(tl):
        out.append("leaked-scaffolding")
    if _DEGEN_RE.search(tl):
        out.append("degenerate")

    stripped = codes.PH_RE.sub("", tl).strip()
    if len(stripped) <= 1 and len(codes.PH_RE.sub("", src).strip()) > 3:
        out.append("degenerate")

    if _visible_numbers(src) != _visible_numbers(tl):
        out.append("number-drift")

    # A sentinel the model INVENTED. `placeholder` below only catches a changed
    # set when something is also missing; an ADDED `⟦0⟧` on a unit whose
    # `codes` map is empty restores to nothing (`unmask_codes` returns early on
    # an empty map), so the literal `⟦0⟧` ships on screen. 89,994 of this
    # game's 90,195 units have an empty codes map, and `qa_scan` cannot see it
    # either, because an all-English line carrying a stray sentinel holds no
    # Japanese and is never re-exported.
    if codes.placeholder_ids(tl) - codes.placeholder_ids(src):
        out.append("invented-sentinel")

    # Restored control codes as a multiset. Position is deliberately free:
    # English word order legitimately moves a standalone code.
    cmap = u.get("codes") or {}
    if cmap:
        a = codes.code_multiset(codes.unmask_codes(src, cmap, pad_inserts=False))
        b = codes.code_multiset(codes.unmask_codes(tl, cmap, pad_inserts=False))
        if a != b:
            out.append("control-code")

    # Engine-level traps, checked on the string the ENGINE will parse. Every
    # one of these is a failure English can create and Japanese cannot, which
    # is exactly the class that survives every text-level check. The corpus was
    # audited clean on all of them (`tools/trap_audit.py`), so a hit here is
    # something the translation introduced. See `ENGINE-CODES.md`.
    restored = codes.unmask_codes(tl, cmap, pad_inserts=True)
    if u["kind"] == "text" and u.get("plate"):
        restored = codes.join_speaker(u.get("speaker_en") or u.get("speaker"),
                                      restored, u.get("plate"))
    for name, _hit in codes.output_traps(restored):
        out.append(name)

    # A `codearg` unit's translation is substituted INSIDE a code bracket by
    # `inject.render`, so it is bound by the bracket reader rather than by the
    # message parser. Nothing else checks these - `build_pairs` skips the kind
    # before it reaches `hard_issues` for the parent - so the check has to be
    # here, and `inject` has to call it for codeargs specifically.
    if u["kind"] == "codearg" and codes.safe_code_arg(tl):
        out.append("unsafe-code-arg")

    # A backslash the model invented. The source corpus has ZERO orphan
    # backslashes, so anything not restored from a sentinel is the model's, and
    # the engine substitutes 541 different backslash keywords at run time - a
    # stray one can silently become somebody's HP value on screen. There is no
    # safe repair (deleting it may destroy a code the model correctly restored
    # itself), so this is a hard failure.
    src_bs = codes.code_multiset(codes.unmask_codes(src, cmap, pad_inserts=False))
    tl_bs = codes.code_multiset(codes.unmask_codes(tl, cmap, pad_inserts=False))
    if sum(tl_bs.values()) > sum(src_bs.values()):
        out.append("invented-backslash")
    elif codes.unknown_escapes(restored):
        # A backslash run that is not one of the engine's 541 keywords. The
        # count check above misses the case where the model DROPPED one code
        # and INVENTED another, which nets to zero. Silent when the keyword
        # table was never loaded, so a caller that forgot gets no findings
        # rather than false ones.
        out.append("invented-backslash")

    if cfg is not None and m is not None and not out:
        prob = _overflow(u, cfg, m)
        if prob:
            out.append("overflow")
    return [c for c in out if c not in waived]


# Filled once by `load_budgets`, because building them reads `layout.tsv`.
_BUDGETS = {"by_key": {}, "by_field": {}, "rom_types": {}, "loaded": False}


def load_budgets(cfg, docs=None):
    """Read `layout.tsv` and the store, and build the per-widget pixel budgets.

    Optional on purpose. `layout.tsv` is produced by `BakinTL layout`; without
    it every overflow check is skipped and `validate` says so, rather than
    silently passing everything."""
    import os
    path = os.path.join(os.path.dirname(os.path.abspath(cfg.get("bakintl", "."))),
                        "..", "layout.tsv")
    path = cfg.get("layout_tsv") or os.path.normpath(path)
    if not os.path.exists(path):
        _BUDGETS["loaded"] = False
        return False
    rows = budgets.load_layout(path)
    # `R:<guid>:<field>` carries no rom TYPE, and the budget for a database
    # field is keyed on that type, so it has to come back from the unit's ctx.
    types = {}
    if docs is not None:
        for _p, doc in docs:
            for u in doc["units"]:
                if u["key"].startswith("R:"):
                    types[u["key"]] = (u.get("ctx") or "").split(".")[0]
    # The author's own widest value per field, which is what stops the
    # min-across-slots heuristic accusing the author. See `budgets.build`.
    shipped = budgets.shipped_widths(docs, measure.current(cfg), types)         if docs is not None else None
    by_key, by_field = budgets.build(rows, shipped)
    _BUDGETS.update(by_key=by_key, by_field=by_field, rom_types=types,
                    loaded=True)
    return True


_LAYOUT_METRICS = {}


def _is_layout_kind(u):
    """True for a unit drawn by the LAYOUT renderer rather than the message one."""
    return (u.get("key") or "").startswith("M:")


def _layout_metrics(cfg):
    """Metrics at `layout_font_size`, cached. None if the size is not configured."""
    size = (cfg or {}).get("layout_font_size")
    if not size:
        return None
    if size not in _LAYOUT_METRICS:
        _LAYOUT_METRICS[size] = measure.resolve(cfg, size)
    return _LAYOUT_METRICS[size]


def _overflow(u, cfg, m):
    r"""Bakin's fitting model, measured per widget rather than per kind.

    `BakinTL layout` reports every one of this game's 3,910 widgets as
    `sizeType = MANUAL` with `maxLineNum = 3`, and of the 2,569 that carry text
    only 118 word-wrap. The other 95% are ONE line: 1,783 are clipped at
    `size.X` (the text is LOST) and 668 are drawn past it into their
    neighbours. So there is nothing to re-flow to and the remedy is shortening.

    Message and telop text goes through `MessageReader.ReadMessage`, which
    word-wraps on real font metrics and then PAGINATES at `maxLineNum` - the
    decompiled `splitByLines` starts a new inherited `MessageEntry` per wrap
    rather than truncating. Width and height are both soft there, and a long
    translation costs the player extra key presses. That is a note, not a
    failure.

    The check is DIFFERENTIAL. `size.X` on a nested sub-element is often not
    the visual bound, so an absolute budget accuses the author; a slot is
    flagged only when the English is wider than the Japanese it replaced."""
    if not _BUDGETS["loaded"]:
        return ""
    tl = codes.clean_translation(u.get("tl") or "")
    if not tl.strip():
        return ""
    b = budgets.for_unit(u, _BUDGETS["by_key"], _BUDGETS["by_field"],
                         _BUDGETS["rom_types"])
    if b is None or not b.px:
        return ""
    restored = codes.unmask_codes(tl, u.get("codes") or {}, pad_inserts=True)
    src_restored = codes.unmask_codes(u.get("src") or "", u.get("codes") or {},
                                      pad_inserts=False)
    # A LAYOUT WIDGET IS NOT DRAWN AT THE MESSAGE SIZE. The engine has two
    # defaults and this build exposes neither as a rom resource: message text
    # measures at `font_size`, layout text at `layout_font_size` (24px, which is
    # `GraphicsCore.NORMAL_FONT_SIZE` and is independently confirmed by the
    # hand-centred menu group cohering to 1.2px there - see `recentre.py`).
    # Measuring a menu label at the message size understates every width by
    # roughly 9%.
    lm = _layout_metrics(cfg)
    mm = lm if _is_layout_kind(u) and lm is not None else m
    w_en = mm.width(restored)
    w_jp = mm.width(src_restored)
    if w_en <= b.px:
        return ""
    # If the SHIPPED JAPANESE already exceeds this box, the box is not the
    # visual bound - `size.X` on a nested or decorative sub-element routinely
    # is not - and the author is the ground truth. MEASURED here: of 551 UI
    # widgets with a declared box, **38 are already over it in Japanese** (it read 220 before the font was
    # calibrated and 70 before the budget arithmetic was corrected from
    # `size.X * scale.X` to `size.X / scale.X` - the count is a reading of the
    # MODEL, so re-derive it after any change to the model) and
    # only **4** are cases where the English alone exceeds it. One widget
    # declares 26px and draws a 503px label.
    #
    # A merely-differential test is not enough on its own: it let a 512px
    # English label through a 26px box because it was 9px wider than the 503px
    # Japanese, which is not "the patch broke it" by any reading. So a slot the
    # author already overflows is excluded outright and counted separately.
    if w_jp > b.px:
        _BUDGETS["already_over"] = _BUDGETS.get("already_over", 0) + 1
        return ""
    return "%.0fpx vs box %.0fpx (%s was %.0fpx)%s" % (
        w_en, b.px, "JP", w_jp, "  CLIPPED" if b.clips else "  collides")


# --------------------------------------------------------------------------
# soft warnings
# --------------------------------------------------------------------------
_MOB_ROLE_RE = re.compile(
    r"monster|generic|species|unit|mob|slime|goblin|orc|tentacle|ghost|spider",
    re.I)


def _gender_forms(glossary):
    out = []
    for jp, v in glossary.get("names", {}).items():
        if not isinstance(v, dict):
            continue
        g = (v.get("gender") or "").lower()
        if g not in ("male", "female"):
            continue
        if _MOB_ROLE_RE.search(v.get("role", "") or ""):
            continue
        for f in [jp] + list(v.get("aliases") or []):
            if len(f) >= 2 and codes.has_jp(f) and not re.search(r"[A-Za-z\[\]]", f):
                out.append((f, g))
    out.sort(key=lambda x: -len(x[0]))
    return out


def _all_gender_sets(glossary):
    out = {"male": set(), "female": set()}
    for jp, v in glossary.get("names", {}).items():
        if not isinstance(v, dict):
            continue
        g = (v.get("gender") or "").lower()
        if g in out:
            for f in [jp] + list(v.get("aliases") or []):
                if len(f) >= 2 and codes.has_jp(f):
                    out[g].add(f)
    return out


def soft_warnings(u, name_forms, all_forms):
    tl = u.get("tl") or ""
    if not tl.strip():
        return []
    warns = []
    raw = u.get("raw") or u.get("src") or ""
    has_he, has_she = bool(_HE_RE.search(tl)), bool(_SHE_RE.search(tl))
    if has_he or has_she:
        male_named = any(x in raw for x in all_forms["male"])
        female_named = any(x in raw for x in all_forms["female"])
        for jp, g in name_forms:
            if jp in raw:
                if g == "female" and has_he and not has_she and not male_named:
                    warns.append("possible misgender: %s is female, tl uses he/him" % jp)
                elif g == "male" and has_she and not has_he and not female_named:
                    warns.append("possible misgender: %s is male, tl uses she/her" % jp)
                break

    sv = len(codes.PH_RE.sub("", u.get("src") or "").strip())
    tv = len(codes.PH_RE.sub("", tl).strip())
    if sv >= 8:
        ratio = tv / float(sv)
        if ratio > 3.0 or ratio < 0.35:
            warns.append("length ratio %.2f (src %d -> tl %d)" % (ratio, sv, tv))

    if codes.ANY_JP_RE.search(tl) and not codes.has_untranslated_jp(tl):
        left = "".join(sorted({c for c in tl
                               if codes.ANY_JP_RE.search(c) and c not in "・ー〇"}))
        if left:
            warns.append("leftover cosmetic kana %r" % left)
    return warns


# --------------------------------------------------------------------------
# corpus-level checks
# --------------------------------------------------------------------------
def same_source_conflicts(docs, dedup_dialogue=True):
    """Units that share a dedup identity but came back with different English.

    Keyed on `store.dedup_key`, NOT on (kind, src). This game deduplicates
    dialogue on (speaker, src), so a body legitimately spoken by two different
    characters is two separate translations by design - 156 distinct bodies and
    3,175 units of them, almost all ellipses and moans. Keying on (kind, src)
    would report every one as a conflict, which is noise in a report whose
    whole value is that a human reads it."""
    groups = collections.OrderedDict()
    for _p, doc in docs:
        for u in doc["units"]:
            tl = (u.get("tl") or "").strip()
            if not tl or u.get("locked"):
                continue
            k = store.dedup_key(u, dedup_dialogue)
            if k is None:
                continue
            groups.setdefault(k, []).append(u)

    out = []
    for k, units in groups.items():
        variants = collections.OrderedDict()
        for u in units:
            variants.setdefault(u["tl"], []).append(u["id"])
        if len(variants) > 1:
            out.append((k[0], units[0]["src"], list(variants),
                        [ids[0] for ids in variants.values()]))
    return out


def romanization_near_misses(docs, glossary):
    """Rieselle / Riselle appearing in different scenes.

    The drifted spelling is not in the glossary at all, so every exact-match
    check passes it. Only names of 6+ characters with no space are checked -
    shorter names collide constantly and multiword ones are already caught."""
    # PROPER NAMES only. Feeding ordinary vocabulary in from `terms` makes the
    # check fire on real English: a `石像 -> statue` row flags every "Status" in
    # the menu as a drifted spelling of it.
    canon = set()
    for v in glossary.get("names", {}).values():
        en = store.name_en(v)
        if en and len(en) >= 6 and " " not in en:
            canon.add(en)
    if not canon:
        return []
    lower = {c.lower(): c for c in canon}
    seen = set()
    out = []
    for _doc, u in store.all_units(docs):
        for tok in _TOKEN_RE.findall(u.get("tl") or ""):
            t = tok[:-2] if tok.endswith(("'s", "’s")) else tok
            if t in canon or t in seen:
                continue
            tl = t.lower()
            for c in canon:
                if c[0].lower() != tl[:1]:
                    continue
                if tl == c.lower().rstrip("s") or tl.rstrip("s") == c.lower():
                    break
                if _edit1(tl, c.lower()):
                    seen.add(t)
                    out.append((t, c, u["id"]))
                    break
    return out


def _edit1(a, b):
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(1 for x, y in zip(a, b) if x != y) == 1
    lo, hi = (a, b) if len(a) < len(b) else (b, a)
    i = j = 0
    skipped = False
    while i < len(lo) and j < len(hi):
        if lo[i] != hi[j]:
            if skipped:
                return False
            skipped = True
            j += 1
            continue
        i += 1
        j += 1
    return True


# --------------------------------------------------------------------------
def glossary_issues(glossary, m=None, used=None, plate_px=None):
    r"""Problems in the NAME table itself, reported once instead of 42,000 times.

    A speaker's English name is written back inside `\NPL[...]`, so one bad
    glossary row fails every unit that character speaks - 42,695 of them for the
    protagonist. Without this the per-unit report is 42,695 identical lines and
    the actual cause, one row in one file, is invisible.

    `used` is `{jp_speaker: line_count}` when available. An UNTRANSLATED speaker
    that the game actually uses is the gap this closes: `name_lookup` falls back
    to the Japanese, so the line would ship with an English body under a
    Japanese nameplate, and no per-unit check looks at the nameplate at all -
    `hard_issues` reads `tl`, and the speaker is not in `tl`."""
    out = []
    for jp, n in sorted((used or {}).items(), key=lambda kv: -kv[1]):
        if not store.name_en((glossary.get("names") or {}).get(jp)):
            out.append("%s: NO approved English name, but it speaks %d line(s)"
                       " - they would ship with a Japanese nameplate. Run "
                       "`tl.py names`." % (jp, n))
    for jp, v in (glossary.get("names") or {}).items():
        en = store.name_en(v)
        if not en:
            continue
        for name, hit in codes.output_traps("\\NPL[%s]x" % en):
            out.append("%s -> %r: %s (%r)" % (jp, en, name, hit))
        if codes.has_untranslated_jp(en):
            out.append("%s -> %r: the English name still contains Japanese" % (jp, en))
        if m is not None:
            from . import budgets as _b
            budget = plate_px or _b.NAMEPLATE_PX
            w = m.width(en)
            if w > budget:
                out.append("%s -> %r: %.0fpx against a %.0fpx nameplate that "
                           "CLIPS - shorten it" % (jp, en, w, budget))
    return out


def run(cfg, store_dir, max_show=25, verbose=True):
    m = measure.reset(cfg)
    codes.load_keywords(cfg["keywords"]) if cfg.get("keywords") else None
    docs = store.load_docs(store_dir)
    have_layout = load_budgets(cfg, docs)
    glossary = store.load_glossary(store_dir)
    # `hard_issues` rebuilds the nameplate onto the restored string before
    # running the trap checks, and it reads `speaker_en`. Without this, VALIDATE
    # checks the Japanese name and INJECT checks the English one, so the two
    # commands can disagree about the same unit.
    from . import inject as _inject
    _inject.resolve_speakers(docs, glossary)
    used = collections.Counter()
    for _d, u in store.all_units(docs):
        if u.get("speaker"):
            used[u["speaker"]] += 1
    plate_px = budgets.nameplate_px(docs, m)
    gloss_bad = glossary_issues(glossary, m, used, plate_px)
    name_forms = _gender_forms(glossary)
    all_forms = _all_gender_sets(glossary)

    total = done = empty = 0
    tally = collections.Counter()
    hard, warns, waived = [], [], []
    for _doc, u in store.all_units(docs):
        total += 1
        for check, why in waivers(u).items():
            waived.append("%s [%s] %s" % (u["id"], check, why))
        issues = hard_issues(u, cfg, m)
        if issues == ["empty"]:
            empty += 1
            continue
        done += 1
        for c in issues:
            tally[c] += 1
            detail = ""
            if c == "residual-jp":
                detail = ": %r" % (u["tl"][:40],)
            elif c == "placeholder":
                detail = ": src%s tl%s" % (sorted(codes.placeholder_ids(u["src"])),
                                           sorted(codes.placeholder_ids(u["tl"])))
            elif c == "overflow":
                detail = ": " + _overflow(u, cfg, m)
            elif c == "number-drift":
                detail = ": src%s tl%s" % (_visible_numbers(u["src"]),
                                           _visible_numbers(u["tl"]))
            hard.append("[%s] %s%s" % (c, u["id"], detail))
        for w in soft_warnings(u, name_forms, all_forms):
            warns.append("%s: %s" % (u["id"], w))

    conflicts = same_source_conflicts(docs, cfg.get("dedup_dialogue", True))
    nearmiss = romanization_near_misses(docs, glossary)
    names_total = len(glossary.get("names", {}))
    names_done = sum(1 for v in glossary.get("names", {}).values() if store.name_en(v))

    if verbose:
        print("VALIDATION  files=%d units=%d" % (len(docs), total))
        pct = (100.0 * done / total) if total else 0.0
        print("  translated          : %d (%.1f%%)" % (done, pct))
        print("  untranslated        : %d" % empty)
        print("  %s" % m.describe())
        already = _BUDGETS.get("already_over", 0)
        if already:
            print("  slots ALREADY over their declared box in the shipped "
                  "JAPANESE, excluded from the overflow check: %d  (size.X on "
                  "a nested sub-element is often not the visual bound)"
                  % already)
        if not have_layout:
            print("  !! no layout.tsv - EVERY overflow check was skipped. Run "
                  "`BakinTL layout proj layout.tsv` first; 95% of this game's "
                  "text widgets are one line and 69% of those CLIP.")
        for k in ("identical", "residual-jp", "placeholder", "control-code",
                  "overflow", "number-drift", "degenerate",
                  "leaked-scaffolding", "placeholder-word",
                  "invented-backslash", "invented-sentinel",
                  "comma-in-code-arg",
                  "unsafe-code-arg", "blink-collision",
                  "tab-becomes-backslash", "trailing-backslash",
                  "bracket-after-bare-escape"):
            print("  %-24s: %d" % (k, tally[k]))
        print("  names translated    : %d/%d" % (names_done, names_total))
        print("  nameplate budget    : %.0fpx  (narrowest slot is %.0fpx, but "
              "the author ships up to this, so the slot is not the bound)"
              % (plate_px, budgets.NAMEPLATE_SLOT_PX))
        print("  BAD GLOSSARY NAMES  : %d  (each one fails every line that "
              "character speaks - fix the glossary, not the units)"
              % len(gloss_bad))
        for s in gloss_bad[:max_show]:
            print("   X " + s)
        if len(gloss_bad) > max_show:
            print("   ... (%d more)" % (len(gloss_bad) - max_show))
        print("  soft warnings       : %d" % len(warns))
        print("  same-source conflict: %d" % len(conflicts))
        print("  romanization drift  : %d" % len(nearmiss))
        print("  WAIVED checks       : %d (accepted by hand, listed below - a "
              "suppression nobody can see is worse than the false positive it "
              "hides)" % len(waived))
        for s in waived:
            print("   = " + s)
        for k, why in sorted(RETRY_EXCLUDE.items()):
            print("  REPORTED but NOT retried: %s" % k)
            for line in _wrap_reason(why):
                print("      " + line)
        if hard:
            print("\n  -- hard issues (fix with: tl.py retry) --")
            for s in hard[:max_show]:
                print("   - " + s)
            if len(hard) > max_show:
                print("   ... (%d more)" % (len(hard) - max_show))
        if warns:
            print("\n  -- soft warnings (review) --")
            for s in warns[:max_show]:
                print("   ? " + s)
            if len(warns) > max_show:
                print("   ... (%d more)" % (len(warns) - max_show))
        for kind, src, variants, ids in conflicts[:10]:
            print("   ~ [%s] %r -> %s  (%s)" % (kind, src[:40], variants, ids[:3]))
        for tok, canon, uid in nearmiss[:10]:
            print("   ~ %r looks like a drifted %r  (%s)" % (tok, canon, uid))

    blocking = (len(gloss_bad) + empty + tally["residual-jp"] + tally["placeholder"]
                + tally["control-code"] + tally["overflow"]
                + tally["degenerate"] + tally["leaked-scaffolding"]
                + tally["number-drift"] + tally["placeholder-word"]
                + tally["invented-backslash"] + tally["invented-sentinel"]
                + tally["comma-in-code-arg"]
                + tally["unsafe-code-arg"] + tally["blink-collision"]
                + tally["tab-becomes-backslash"] + tally["trailing-backslash"]
                + tally["bracket-after-bare-escape"])
    return 0 if blocking == 0 else 1


# Checks that are REPORTED but do not drive the retry queue, with the reason
# each one is here. This is not a mute: `validate` still counts and lists them,
# and the reason is printed next to the count. It only says "another round trip
# cannot fix this".
#
# EMPTY ON PURPOSE for this game. The entry that lived here was carried over
# from another title, where it was correct and evidenced: after canonicalising
# myriad grouping, ordinals, digit+scale and the `+` sign, that corpus's
# CONFLICT bucket - the one a real quantity error has to land in - was empty,
# so retrying the remaining flags could only produce a differently-restructured
# sentence.
#
# That is a per-game RULING, not code, and this game has not been measured yet.
# Waiving a check on somebody else's evidence is how a real quantity error
# ships. Re-derive it here after the first full run - bucket the flags into
# invented / dropped / reordered / conflict and look at what `conflict` holds -
# and write the number you measured, not this sentence.
RETRY_EXCLUDE = {
    "number-drift":
        "MEASURED on this corpus after the canonicaliser was tuned "
        "(audit/numbuckets.py): 276 distinct sources flagged, bucketed as "
        "CONFLICT 29 / invented 172 / dropped 75 / reordered 0. All 29 "
        "CONFLICT cases were read by hand and exactly ONE was a real quantity "
        "error - `400！ 400だ！！` rendered 'Four! Four hundred!!' - which was "
        "fixed directly rather than retried. The rest are the comparison, not "
        "the translation: a stutter ('Two, two, two hundred million'), "
        "'two point two million' for 220万, English ordinal words where the "
        "Japanese has no numeral, `消費MP8` whose 8 the Lv5/HP100 guard hides "
        "on the source side, and NFKC folding a circled ① into a digit that "
        "then joins the number beside it. A retry on any of those produces a "
        "differently-restructured sentence, not a fixed one. Two rules were "
        "ablated and left OFF because they GREW the CONFLICT bucket: kana "
        "numerals (+3 conflicts) and English ordinal words (+5).",
}


def _wrap_reason(text, width=72):
    words, line, out = text.split(), "", []
    for w in words:
        if len(line) + len(w) + 1 > width:
            out.append(line)
            line = w
        else:
            line = (line + " " + w) if line else w
    if line:
        out.append(line)
    return out


def failing_ids(cfg, store_dir, exclude=None):
    exclude = RETRY_EXCLUDE if exclude is None else exclude
    m = measure.reset(cfg)
    docs = store.load_docs(store_dir)
    load_budgets(cfg, docs)
    # The SAME setup `run` does. Without the keyword table `code_multiset`
    # falls back to the greedy regex and 16 correct UI option lists come back
    # as dropped control codes - so `validate` would report zero and `retry`
    # would queue sixteen, which is worse than either answer alone.
    if cfg.get("keywords"):
        codes.load_keywords(cfg["keywords"])
    glossary = store.load_glossary(store_dir)
    from . import inject as _inject
    _inject.resolve_speakers(docs, glossary)
    out = {}
    for _doc, u in store.all_units(docs):
        issues = [i for i in hard_issues(u, cfg, m) if i not in exclude]
        if issues:
            note = ", ".join(issues)
            if "overflow" in issues:
                note += " (" + _overflow(u, cfg, m) + ")"
            out[u["id"]] = note
    return out
