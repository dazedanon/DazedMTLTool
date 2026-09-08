#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
validate.py - what blocks injection, and what only asks for a look.

HARD failures (block, and drive the retry queue):

    empty                 no translation
    identical             byte-identical to the source
    residual-jp           hiragana or kanji left in the output
    placeholder           the ⟦n⟧ sentinel set changed
    control-code          the RESTORED codes changed as a multiset
    overflow              wrapped result exceeds the box in width OR rows
    degenerate            collapsed to one character, or a 45-long run
    leaked-scaffolding    `}Line1:` style output bleeding into player text
    number-drift          the visible numbers changed, in order
    bare-escape-eats-word a `\word` run the RGSS3 lexer swallows whole

SOFT warnings (review, never block): misgender, length ratio, leftover
cosmetic kana, same-source-different-translation, romanization near-miss,
cross-track conflict.

Length ratio is deliberately NOT blocking: Japanese to English routinely
triples, and forcing review on expansion drowns the queue in good lines.
"""

import io
import os
import re
import json
import unicodedata
import collections

from . import codes, store, wrap, measure, inject, scripts_rb

_HE_RE = re.compile(r"\b(?:he|him|his|himself)\b", re.I)
_SHE_RE = re.compile(r"\b(?:she|her|hers|herself)\b", re.I)
_SCAFFOLD_RE = re.compile(r"(?:^|[}\]])\s*Line\d+\s*:", re.I)
_DEGEN_RE = re.compile(r"(.)\1{44,}")
# The trailing-letter guard exists so `Lv5` and `3rd` are not read as bare
# quantities, but it also swallowed the multiplier form English actually
# uses for 倍: `2x`. That one letter is admitted explicitly.
_NUM_RE = re.compile(
    r"(?<![A-Za-z0-9_])[-+]?\d+(?:[.,]\d+)?x?(?![A-Za-z0-9_])")
_PLACEHOLDER_WORD_RE = re.compile(r"^\s*(placeholder|todo|n/?a|tbd)\s*$", re.I)

# `Window_Base#obtain_escape_code` is `text.slice!(/^[\$\.\|\^!><\{\}\\]|^[A-Z]+/i)`,
# so an escape is a backslash plus a RUN of letters: a stray `\Helen` parses as
# one unknown code named `helen` and the word is never drawn. V / N / P / G are
# substituted away earlier by `convert_escape_characters`, and this game's own
# script consumes NAME there too, so those four plus NAME are exempt.
_BARE_ESCAPE_RE = re.compile(r"\\(?!(?:NAME\[|[VNPGvnpg](?:\[|\b)))[A-Za-z]{2,}")


# --------------------------------------------------------------------------
# Number comparison
# --------------------------------------------------------------------------
# Quantity drift is the most damaging fluent-but-wrong output there is - 三日後
# as "in a few days", a quest needing 3 items described as needing 5 - and every
# one of those is grammatical English that spelling, grammar and placeholder
# checks wave straight through.
#
# But a naive digit-for-digit comparison is a false-positive generator, and a
# check that cries wolf is a check that gets switched off. Both sides are
# canonicalised first: CJK myriad grouping (5000万 IS 50 million), thousands
# separators, a trailing currency unit that would otherwise parse
# asymmetrically, English spelling numbers out ("a hundred years"), and English
# lexicalising them ("Doubles" for 2倍).
_MYRIAD = [("兆", 10 ** 12), ("億", 10 ** 8), ("万", 10 ** 4), ("千", 10 ** 3)]

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
_WORD_MULT = {"double": 2, "doubles": 2, "doubled": 2, "twice": 2,
              "triple": 3, "triples": 3, "tripled": 3, "thrice": 3,
              "quadruple": 4, "quadruples": 4}
# `once` is deliberately absent: it is an adverb far more often than a count.

_KANJI_DIGIT = {"〇": 0, "零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
                "六": 6, "七": 7, "八": 8, "九": 9}
_KANJI_SCALE = [("兆", 10 ** 12), ("億", 10 ** 8), ("万", 10 ** 4),
                ("千", 10 ** 3), ("百", 10 ** 2), ("十", 10)]
# 体 and 分 are deliberately NOT counters: 一体 is "what on earth" and 十分 is
# "enough", and admitting them invents a number on the source side of ordinary
# prose.
# 階 / 等 / 着 / 位 / 番 are POSITIONS, not quantities (2階 is "2F" or "the
# second floor", 2等市民 is "second-class citizens", 7着目 is "the seventh
# dress"), so they live in the ordinal rule below and NOT here.
_COUNTERS = "日人個回年月時秒匹枚本度倍円歳割層発晩撃号週杯滴粒名台束着番つ"
# `四つん這い` ("on all fours", a posture) is not a count of four things, and
# `つ` is otherwise a real counter, so the exclusion is the two-character
# sequence rather than the counter.
# `四つん這い` ("on all fours") and `二度と` ("never again") are fixed
# phrases, not counts, and both were flagging correct English.
_NOT_A_COUNT_RE = re.compile(
    r"[0-9〇零一二三四五六七八九十]つん"
    r"|[0-9〇零一二三四五六七八九十]度と"
    r"|[0-9〇零一二三四五六七八九十]度も"
    r"|[0-9〇零一二三四五六七八九十]つとない"
    r"|百発百中|一石二鳥|三日坊主|二束三文")
# 何 before a numeral makes it INDEFINITE (何百年 is "hundreds of years"), so
# the quantity is not comparable at all.
_KANJI_NUM_RE = re.compile(
    r"(?<![0-9何数])([〇零一二三四五六七八九十百千万億兆]{1,8})(?=["
    + _COUNTERS + r"])")


# Katakana numerals in skill names: `サウザンドアロー` is "Thousand Arrows" and
# `ダブルインパクト` is "Double Impact", so the English digit has a Japanese
# counterpart the kanji rules never see.
#
# The lookbehind is load-bearing. Without it `ミリオン` matches inside the place
# name `エミリオン` (Emilion) and every one of that town's map names claimed to
# contain the number 1,000,000 - twenty-odd false positives from one rule meant
# to fix two. A numeral only counts where a katakana word BEGINS.
_KATAKANA_NUMERALS = [
    ("サウザンド", 1000), ("ハンドレッド", 100), ("ミリオン", 1000000),
    ("ダブル", 2), ("トリプル", 3), ("クアドラ", 4),
]
_KATAKANA_NUM_RE = re.compile(
    r"(?<![ァ-ヴーｦ-ﾟ])(" + "|".join(k for k, _v in _KATAKANA_NUMERALS) + ")")
_KATAKANA_NUM_MAP = dict(_KATAKANA_NUMERALS)


def _kanji_to_int(s):
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


_UNITS_ALT = "|".join(sorted(_WORD_UNITS, key=len, reverse=True))
# `one` may CONTINUE a numeral ("twenty one") but may not LEAD one, because a
# leading "one" is usually the pronoun and "the one I took" was being read as
# the number 1.
_UNITS_LEAD = "|".join(sorted((k for k in _WORD_UNITS if k != "one"),
                              key=len, reverse=True))
_SCALES_ALT = "|".join(_WORD_SCALES)
_WORD_RE = re.compile(
    r"\b(?:"
    r"(?:a|an|one)[\s-]+(?:%s)"
    r"|(?:%s)(?:[\s-]+(?:%s|%s))*"
    r")\b" % (_SCALES_ALT, _UNITS_LEAD, _UNITS_ALT, _SCALES_ALT), re.I)
# `doubled OVER with stomach pain` and `doubled UP` are not the multiplier 2.
_MULT_RE = re.compile(r"\b(%s)\b(?!\s+(?:over|up|back|down))"
                      % "|".join(sorted(_WORD_MULT, key=len, reverse=True)),
                      re.I)
_BARE_SCALE_RE = re.compile(
    r"(?<!several )(?<!a few )(?<!many )(?<!some )(?<!countless )"
    r"\b(hundred|thousand|million)\b(?!s?\s+of)", re.I)


def _words_to_int(phrase):
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


# ORDINALS ARE POSITIONS, NOT QUANTITIES, and both languages mark them - so
# they are deleted from BOTH sides before comparing. Measured on this game's
# first real run: of 246 flags, 170 were an ordinal rendered idiomatically
# (`２回目` -> "Second time", `３０回目` -> "the thirtieth", `３１本目` ->
# "the 31st"). Mapping the English ordinal WORDS to digits instead would have
# been worse: "for a second" and "in a third of the time" would invent a
# quantity on the English side of prose that has none.
_JP_ORDINAL_COUNTERS = "回本人個度日番匹枚階層発晩撃号週杯滴粒名台束着つ"
# NOTATION, deleted on both sides: a floor number and a rank.
_JP_ORDINAL_RE = re.compile(
    r"[0-9〇零一二三四五六七八九十百千]+\s*[階等位級]")
# The ordinal MARKER only. The numeral in front of it survives and is
# converted by the counter rules like any other quantity.
_JP_ORDINAL_MARK_RE = re.compile(
    r"(?<=[0-9〇零一二三四五六七八九十百千])\s*目"
    r"|第(?=\s*[0-9〇零一二三四五六七八九十百千])")
# Deleted on the English side too: the same notation, in its English forms.
_EN_ORDINAL_RE = re.compile(
    r"(?<![A-Za-z0-9])B?\d+F\b"
    r"|\bfloor\s*\d+\b"
    r"|\b(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth"
    r"|tenth|eleventh|twelfth|top|ground|upper|lower)\s+floor\b"
    r"|\b\w+\s+basement\s+floor\b"
    r"|\b[\w]+(?:-|\s)class\b", re.I)

# CONVERTED: an English ordinal is the same quantity as its Japanese one.
# The article guard is what keeps "for a second" and "a third of it" from
# inventing a number - and "first" mapping to 1 is harmless, because 1 is
# dropped from the comparison on both sides anyway.
_EN_ORDINAL_WORDS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
    "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14,
    "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18,
    "nineteenth": 19, "twentieth": 20, "thirtieth": 30, "fortieth": 40,
    "fiftieth": 50, "sixtieth": 60, "seventieth": 70, "eightieth": 80,
    "ninetieth": 90, "hundredth": 100,
}
_EN_ORDINAL_WORD_RE = re.compile(
    r"(?<!\ba )(?<!\ban )(?<!more )(?<!single )(?<!one )(?<!every )"
    r"(?<!each )(?<!split )\b(" + "|".join(_EN_ORDINAL_WORDS) + r")\b", re.I)
_EN_ORDINAL_DIGIT_RE = re.compile(r"\b(\d+)(?:st|nd|rd|th)\b", re.I)

# A digit pair joined by a comma is a LIST in this corpus (`３，４本の触手` -
# "three or four tentacles"), not a decimal and not a thousands group. Only
# the well-formed thousands form is treated as one number, and that rule runs
# first.
_NUM_LIST_COMMA_RE = re.compile(r"(?<=\d)\s*[,，]\s*(?=\d)")


def _canonical_numbers(text, currency="G"):
    """Both sides reduced to the same digit form before comparison."""
    t = codes.PH_RE.sub("", text)
    t = re.sub(r"\\+[A-Za-z]+\[[^\]]*\]", "", t)
    t = unicodedata.normalize("NFKC", t)
    t = _JP_ORDINAL_RE.sub(" ", t)
    t = _EN_ORDINAL_RE.sub(" ", t)
    t = re.sub(r"第\s*([0-9〇零一二三四五六七八九十百千]+)",
               lambda m: " %s " % (_kanji_to_int(m.group(1))
                                   if not m.group(1).isdigit()
                                   else m.group(1)), t)
    t = _JP_ORDINAL_MARK_RE.sub(" ", t)
    t = _EN_ORDINAL_DIGIT_RE.sub(lambda m: " %s " % m.group(1), t)
    t = _EN_ORDINAL_WORD_RE.sub(
        lambda m: " %d " % _EN_ORDINAL_WORDS[m.group(1).lower()], t)
    t = _NOT_A_COUNT_RE.sub(" ", t)

    # Order matters: each step assumes the digits above it are settled.
    t = _KATAKANA_NUM_RE.sub(
        lambda m: " %d " % _KATAKANA_NUM_MAP[m.group(1)], t)
    t = _KANJI_NUM_RE.sub(
        lambda m: str(_kanji_to_int(m.group(1)) if _kanji_to_int(m.group(1))
                      is not None else m.group(1)), t)
    t = re.sub(r"(?<![\d,])\d{1,3}(?:,\d{3})+(?![\d,])",
               lambda m: m.group(0).replace(",", ""), t)
    # ...and only THEN split what is left: a surviving comma between digits is
    # the author listing two numbers.
    t = _NUM_LIST_COMMA_RE.sub(" ", t)
    for mark, scale in _MYRIAD:
        t = re.sub(r"(\d+)\s*" + mark,
                   lambda m, s=scale: str(int(m.group(1)) * s), t)
    if currency:
        t = re.sub(r"(?<=\d)\s*%s(?![A-Za-z])" % re.escape(currency), " ", t)
    t = re.sub(r"(?<![0-9〇零一二三四五六七八九十何数])倍", " 2 ", t)
    t = _MULT_RE.sub(lambda m: str(_WORD_MULT[m.group(1).lower()]), t)

    def _w(m):
        v = _words_to_int(m.group(0))
        return str(v) if v is not None else m.group(0)
    t = _WORD_RE.sub(_w, t)
    # A BARE scale word used as a count - `the hundred-troll punishment` for
    # `トロール１００匹` - with the plural-plus-`of` form excluded, because
    # "hundreds of years" is indefinite and its Japanese (何百年) is excluded
    # on the other side too.
    t = _BARE_SCALE_RE.sub(lambda m: str(_WORD_SCALES[m.group(1).lower()]), t)

    # THE VALUE 1 IS NOT COMPARABLE across these two languages and is dropped
    # from both sides: Japanese writes it as a counter (一匹 / 一人 / 一つ)
    # where English uses an article, a pronoun or nothing. The exemption is
    # symmetric, so a real drift still shows.
    #
    # The SIGN is dropped too. `[-+]?` exists for a real negative, and this
    # corpus has none - what it actually catches is the leading dash of an em-
    # dash run, so `―――３時間後―――` rendered `---Three hours later---`
    # compared '3' against '-3' and flagged fourteen correct scene headers.
    return [n.lstrip("-+").rstrip("x") for n in _NUM_RE.findall(t)
            if n.lstrip("-+").rstrip("x") not in ("1", "1.0", "")]


def _visible_numbers(text):
    """Numbers a player sees, canonicalised. Compared ORDERED, so "3 of the 5"
    becoming "5 of the 3" is still caught."""
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
    """Ordered cheapest-first."""
    tl = u.get("tl") or ""
    if not tl.strip():
        return ["empty"]
    out = []
    src = u.get("src") or ""
    waived = waivers(u)

    if tl.strip() == src.strip():
        out.append("identical")
    if _PLACEHOLDER_WORD_RE.match(tl):
        out.append("placeholder-word")
    if codes.has_untranslated_jp(tl):
        out.append("residual-jp")
    if codes.placeholder_ids(src) != codes.placeholder_ids(tl):
        out.append("placeholder")
    if _SCAFFOLD_RE.search(tl):
        out.append("leaked-scaffolding")
    if _DEGEN_RE.search(tl):
        out.append("degenerate")

    stripped = codes.PH_RE.sub("", tl).strip()
    if len(stripped) <= 1 and len(codes.PH_RE.sub("", src).strip()) > 3:
        out.append("degenerate")

    # Compared as a MULTISET, not as a sequence. English reorders clauses
    # freely - `３日間で１００回以上の絶頂と３００回` came back as "more than
    # 100 climaxes ... in three days" - and an ordered comparison calls that a
    # drift. A genuine swap of two quantities between their nouns survives
    # this check only if both numbers are still present, which is the price of
    # not flagging every re-ordered sentence; `number-order` reports it softly.
    if sorted(_visible_numbers(src)) != sorted(_visible_numbers(tl)):
        out.append("number-drift")

    if _BARE_ESCAPE_RE.search(tl) and not _BARE_ESCAPE_RE.search(src):
        out.append("bare-escape-eats-word")

    cmap = u.get("codes") or {}
    if cmap:
        a = codes.code_multiset(codes.unmask_codes(src, cmap, pad_inserts=False))
        b = codes.code_multiset(codes.unmask_codes(tl, cmap, pad_inserts=False))
        if a != b:
            out.append("control-code")

    if cfg is not None and m is not None and not out:
        if _overflow(u, cfg, m):
            out.append("overflow")
    return [c for c in out if c not in waived]


def overflow_detail(u, cfg, m):
    return _overflow(u, cfg, m)


# Rows beyond this are worth shortening even though the engine paginates:
# two full pages of automatic page break in one message box is a lot of
# clicking for one line of dialogue.
PAGINATION_TOLERANCE = 2


def _overflow(u, cfg, m):
    """WIDTH only - the failure that actually loses text."""
    tl = codes.clean_translation(u.get("tl") or "")
    if not tl.strip():
        return ""
    restored = codes.unmask_codes(tl, u.get("codes") or {}, pad_inserts=True)
    width, hard, rows = inject.budget(u, cfg)
    if u["kind"] in ("text", "desc", "profile"):
        f = wrap.fit(restored, width, rows, m)
        if f.widest > hard:
            return "widest line %d cells, hard cap %d" % (f.widest, hard)
        if rows and f.rows > rows * PAGINATION_TOLERANCE:
            return ("wraps to %d rows, box holds %d - that is %d engine page "
                    "breaks in one message" % (f.rows, rows, f.rows // rows))
        return ""
    w = m.cells(restored)
    return "%d cells, budget %d" % (w, width) if w > width else ""


def pagination(u, cfg, m):
    """How many extra engine page breaks this unit will cost the player.

    Not a failure: `Window_Message#process_new_line` calls `input_pause` and
    `new_page`, so the text continues on a fresh box after a click."""
    tl = codes.clean_translation(u.get("tl") or "")
    if not tl.strip() or u["kind"] not in ("text", "desc", "profile"):
        return 0
    restored = codes.unmask_codes(tl, u.get("codes") or {}, pad_inserts=True)
    width, _hard, rows = inject.budget(u, cfg)
    if not rows:
        return 0
    f = wrap.fit(restored, width, rows, m)
    return max(0, (f.rows - 1) // rows)


# --------------------------------------------------------------------------
# soft warnings
# --------------------------------------------------------------------------
_MOB_ROLE_RE = re.compile(
    r"monster|generic|species|unit|mob|slime|goblin|orc|tentacle|ghost|spider|"
    r"townsperson|villager|soldier|guard|crowd", re.I)


def _gender_forms(glossary):
    out = []
    for jp, v in glossary.get("names", {}).items():
        if not isinstance(v, dict):
            continue
        g = (v.get("gender") or "").lower()
        if g not in ("male", "female"):
            continue
        if _MOB_ROLE_RE.search((v.get("role") or "") + " " + (v.get("en") or "")):
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


def soft_warnings(u, name_forms, all_forms, cfg=None, m=None):
    tl = u.get("tl") or ""
    if not tl.strip():
        return []
    warns = []
    raw = u.get("raw") or u.get("src") or ""
    speaker = u.get("speaker") or ""
    has_he, has_she = bool(_HE_RE.search(tl)), bool(_SHE_RE.search(tl))
    if has_he or has_she:
        male_named = any(x in raw for x in all_forms["male"])
        female_named = any(x in raw for x in all_forms["female"])
        for jp, g in name_forms:
            if jp in raw or jp == speaker:
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

    if cfg is not None and m is not None:
        extra = pagination(u, cfg, m)
        if extra:
            warns.append("pagination: needs %d extra page break%s - the engine "
                         "pauses and continues, nothing is lost"
                         % (extra, "" if extra == 1 else "s"))

    src_nums = _visible_numbers(u.get("src") or "")
    tl_nums = _visible_numbers(tl)
    if src_nums != tl_nums and sorted(src_nums) == sorted(tl_nums):
        warns.append("number-order: %s -> %s (English re-ordered the clause; "
                     "check the numbers still belong to the same nouns)"
                     % (src_nums, tl_nums))

    if codes.ANY_JP_RE.search(tl) and not codes.has_untranslated_jp(tl):
        left = "".join(sorted({c for c in tl
                               if codes.ANY_JP_RE.search(c) and c not in "・ー〇"}))
        if left:
            warns.append("leftover cosmetic kana %r" % left)
    return warns


# --------------------------------------------------------------------------
# corpus-level checks
# --------------------------------------------------------------------------
def same_source_conflicts(docs):
    """One source string with two different translations.

    Invisible to every per-line validator, and exactly what makes a patch feel
    machine-made: a line that changes wording between two scenes that repeat
    it."""
    idx = collections.defaultdict(set)
    where = collections.defaultdict(list)
    for _doc, u in store.all_units(docs):
        tl = (u.get("tl") or "").strip()
        if tl:
            idx[(u["kind"], u["src"])].add(tl)
            where[(u["kind"], u["src"])].append(u["id"])
    return [(k[0], k[1], sorted(v), where[k][:6])
            for k, v in idx.items() if len(v) > 1]


_TOKEN_RE = re.compile(r"(?<![\w])[A-Z][A-Za-z'’]+(?![\w])")


def romanization_near_misses(docs, glossary):
    """`Rieselle` / `Riselle` in two different scenes.

    The drifted spelling is not in the glossary at all, so every exact-match
    check passes it. Only PROPER NAMES of 6+ characters with no space are
    checked: ordinary vocabulary from `terms` makes the check fire on real
    English."""
    canon = set()
    for v in glossary.get("names", {}).values():
        en = store.name_en(v)
        if en and len(en) >= 6 and " " not in en:
            canon.add(en)
    if not canon:
        return []
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


def cross_track_conflicts(docs, glossary, store_dir):
    """One Japanese string rendered one way in the units, another in the scripts.

    The two tracks are translated by separate passes, and nothing else compares
    them: マッスルーム shipped as "Mussroom" in 85 lines of dialogue and as
    "Muscleroom" on the world map, and every per-unit check passed both, because
    each track is internally consistent. Reported, never blocking - a map pin
    legitimately shortens what prose spells out (王都バロン is "the Royal
    Capital of Baron" in dialogue and "Baron" on an 11-cell pin)."""
    try:
        ledger = json.load(io.open(os.path.join(store_dir, scripts_rb.LEDGER),
                                   encoding="utf-8"))
    except (OSError, ValueError):
        return []

    script_en = {}
    for e in ledger.get("entries", []):
        jp, en = e.get("jp") or e.get("src"), (e.get("en") or "").strip()
        if e.get("translate") and jp and en:
            script_en.setdefault(jp, en)
    if not script_en:
        return []

    elsewhere = collections.defaultdict(set)
    for section in ("names", "terms"):
        for jp, v in (glossary.get(section) or {}).items():
            if jp not in script_en:
                continue
            en = v if isinstance(v, str) else store.name_en(v)
            if en:
                elsewhere[jp].add(("glossary", en))
    for _doc, u in store.all_units(docs):
        jp = (u.get("src") or "").strip()
        tl = (u.get("tl") or "").strip()
        if jp in script_en and tl:
            elsewhere[jp].add((u["kind"], tl))

    out = []
    for jp, en in sorted(script_en.items()):
        other = sorted({(w, t) for w, t in elsewhere.get(jp, ()) if t != en})
        if other:
            out.append((jp, en, other))
    return out


# A name the glossary never pinned is translated independently in every batch,
# and the batches disagree. おろち様 was in neither `names` nor `terms` and came
# out as "Orochi-sama" (98 units), "Lord Orochi" (91) and "Lady Orochi" (28),
# with masculine pronouns in 44 and feminine in 29 - on a deity the Japanese
# never genders at all. Cheap to catch BEFORE spending anything: list the
# recurring proper nouns nothing has pinned.
_HONORIFIC_RE = re.compile(u"([\u3041-\u3096\u30a1-\u30fa\u30fc\u4e00-\u9fff]{2,10})(?=\u69d8)")
_KATAKANA_RE = re.compile(u"[\u30a1-\u30fa\u30fc]{4,14}")


# 様 also attaches to kinship and rank, which are vocabulary, not names.
_NOT_A_NAME = ['お父', 'お母', '兄', '姉', '祖父', '祖母', 'お嬢', 'なた', '皇', '女王', '王', '神', '客', '皮肉']


def unpinned_terms(docs, glossary, min_units=20):
    """Recurring proper nouns that appear in no glossary section.

    A PRE-FLIGHT aid, not a gate: run it before spending, pin whatever it
    finds that is actually a name, ignore the rest. Reported, never blocking
    - some frequent katakana is ordinary vocabulary and no cheap rule
    separates スライム from ダメージ reliably.
    """
    pinned = set(glossary.get("names") or {}) | set(glossary.get("terms") or {})
    counts = collections.Counter()
    for _doc, u in store.all_units(docs):
        src = u.get("src") or ""
        if not src:
            continue
        found = set(_KATAKANA_RE.findall(src))
        for t in _HONORIFIC_RE.findall(src):
            if t not in _NOT_A_NAME:
                found.add(t)
        for t in found:
            counts[t] += 1
    out = []
    for t, n in counts.items():
        if n < min_units or t in _NOT_A_NAME:
            continue
        if any(t == p or t in p or p in t for p in pinned):
            continue
        out.append((t, n))
    return sorted(out, key=lambda x: (-x[1], x[0]))

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


def untranslated_speakers(glossary):
    """A `\\NAME[]` speaker with no English spelling ships a Japanese name
    plate over English dialogue - visible on screen, invisible to every
    per-unit check, because the tag is not part of any unit's text."""
    out = []
    for jp, v in glossary.get("names", {}).items():
        if not store.name_en(v):
            n = v.get("count", 0) if isinstance(v, dict) else 0
            out.append((jp, n))
    return sorted(out, key=lambda x: -x[1])


def unsafe_speaker_names(glossary):
    """An English name that cannot live inside the name-plate tag.

    `retag` refuses these at inject time, so the plate stays Japanese rather
    than corrupting the line - but the operator still has to know, because a
    silently-Japanese plate is what they will see in game and wonder about."""
    out = []
    for jp, v in glossary.get("names", {}).items():
        en = store.name_en(v)
        why = codes.name_is_safe(en) if en else ""
        if why:
            out.append((jp, en, why))
    return out


# --------------------------------------------------------------------------
def run(cfg, store_dir, max_show=25, verbose=True):
    m = measure.reset(cfg.font_path())
    docs = store.load_docs(store_dir)
    glossary = store.load_glossary(store_dir)
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
        for w in soft_warnings(u, name_forms, all_forms, cfg, m):
            warns.append("%s: %s" % (u["id"], w))

    conflicts = same_source_conflicts(docs)
    nearmiss = romanization_near_misses(docs, glossary)
    crosstrack = cross_track_conflicts(docs, glossary, store_dir)
    unpinned = unpinned_terms(docs, glossary)
    no_en = untranslated_speakers(glossary)
    names_total = len(glossary.get("names", {}))

    if verbose:
        print("VALIDATION  files=%d units=%d" % (len(docs), total))
        print("  translated          : %d (%.1f%%)"
              % (done, (100.0 * done / total) if total else 0.0))
        print("  untranslated        : %d" % empty)
        for k in ("identical", "residual-jp", "placeholder", "control-code",
                  "overflow", "number-drift", "degenerate",
                  "leaked-scaffolding", "placeholder-word",
                  "bare-escape-eats-word"):
            print("  %-20s: %d" % (k, tally[k]))
        print("  names translated    : %d/%d" % (names_total - len(no_en),
                                                 names_total))
        print("  soft warnings       : %d" % len(warns))
        print("  same-source conflict: %d" % len(conflicts))
        print("  romanization drift  : %d" % len(nearmiss))
        print("  cross-track conflict: %d" % len(crosstrack))
        print("  unpinned recurring  : %d" % len(unpinned))
        print("  WAIVED checks       : %d (accepted by hand, listed below)"
              % len(waived))
        for s in waived:
            print("   = " + s)
        if no_en:
            print("\n  -- speakers with no English name (the name PLATE stays "
                  "Japanese) --")
            for jp, n in no_en[:max_show]:
                print("   ? %s  (%d lines)" % (jp, n))
        unsafe = unsafe_speaker_names(glossary)
        if unsafe:
            print("\n  -- speaker names that CANNOT go in the name plate "
                  "(inject keeps the Japanese one instead) --")
            for jp, en, why in unsafe:
                print("   ! %s -> %r: %s" % (jp, en, why))
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
        if unpinned:
            print()
            print("  -- recurring proper nouns no glossary pins (each one "
                  "is translated per batch, so the batches drift) --")
            for t, n in unpinned[:max_show]:
                print("   ~ %s  in %d units" % (t, n))
        if crosstrack:
            print()
            print("  -- the scripts and the units disagree on one source "
                  "string --")
            for jp, en, other in crosstrack[:max_show]:
                print("   ~ %s  scripts=%r  %s"
                      % (jp, en, "  ".join("%s=%r" % o for o in other[:3])))

    blocking = (empty + tally["residual-jp"] + tally["placeholder"]
                + tally["control-code"] + tally["overflow"]
                + tally["degenerate"] + tally["leaked-scaffolding"]
                + tally["number-drift"] + tally["placeholder-word"]
                + tally["bare-escape-eats-word"])
    return 0 if blocking == 0 else 1


def failing_ids(cfg, store_dir):
    m = measure.reset(cfg.font_path())
    docs = store.load_docs(store_dir)
    out = {}
    for _doc, u in store.all_units(docs):
        issues = hard_issues(u, cfg, m)
        if issues:
            note = ", ".join(issues)
            if "overflow" in issues:
                note += " (" + _overflow(u, cfg, m) + ")"
            out[u["id"]] = note
    return out
