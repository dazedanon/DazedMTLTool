#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate.py - what blocks injection, what only asks for a look.

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
    space-in-plugin-arg   an ASCII space inside a space-delimited argument
    bare-escape-eats-word a backslash+letters run the MV lexer swallows whole

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

from . import codes, store, wrap, measure

_HE_RE = re.compile(r"\b(?:he|him|his|himself)\b", re.I)
_SHE_RE = re.compile(r"\b(?:she|her|hers|herself)\b", re.I)
_SCAFFOLD_RE = re.compile(r"(?:^|[}\]])\s*Line\d+\s*:", re.I)
_DEGEN_RE = re.compile(r"(.)\1{44,}")
_NUM_RE = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d+(?:[.,]\d+)?(?![A-Za-z0-9_])")
_PLACEHOLDER_WORD_RE = re.compile(r"^\s*(placeholder|todo|n/?a|tbd)\s*$", re.I)
# A backslash directly against a Latin letter, where the code is NOT one the
# engine substitutes away first (V/N/P/G are consumed by
# convertEscapeCharacters before the lexer ever sees them).
_BARE_ESCAPE_RE = re.compile(r"\\(?![VNPGvnpg](?:\[|\b))[A-Za-z]{2,}")


# --------------------------------------------------------------------------
# Number comparison
# --------------------------------------------------------------------------
# Quantity drift is the most damaging class of fluent-but-wrong output - 三日後
# as "in a few days", a quest needing 3 items described as needing 5 - and every
# one of those is grammatical English that spelling, grammar and placeholder
# checks wave straight through.
#
# But a naive digit-for-digit comparison produced SEVEN false positives on this
# game's first run and zero true ones, and a check that cries wolf is a check
# that gets switched off. All three failures were the comparison's, not the
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
# Lexicalised multipliers. `2倍 -> "Doubles"` is a correct rendering, not a
# dropped number.
_WORD_MULT = {"double": 2, "doubles": 2, "doubled": 2, "twice": 2,
              "triple": 3, "triples": 3, "tripled": 3, "thrice": 3,
              "quadruple": 4, "quadruples": 4}
# `once` is deliberately absent. It is an adverb far more often than a count in
# this corpus - "once my power's back", "at once", "once more", "once attached
# to the dungeon" - and mapping it to 1 flagged sixteen correct lines.

# Kanji numerals, converted only when a COUNTER follows. `三日後` is a quantity
# and is the canonical damaging case ("in a few days"). `一番`, `一体`, `一緒`,
# `一人前` are lexical, and converting those would invent a number on the source
# side that no correct translation contains - turning the check into a false
# positive generator, which is how a check gets switched off.
_KANJI_DIGIT = {"〇": 0, "零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
                "六": 6, "七": 7, "八": 8, "九": 9}
_KANJI_SCALE = [("兆", 10 ** 12), ("億", 10 ** 8), ("万", 10 ** 4),
                ("千", 10 ** 3), ("百", 10 ** 2), ("十", 10)]
# Two characters are deliberately NOT counters here, because in this corpus
# they are overwhelmingly part of an ordinary word:
#   体  `一体` is "what on earth", not "one body"
#   分  `十分` is じゅうぶん "enough" / "thoroughly", not じゅっぷん "ten minutes"
#       (`もう十分お持ちのようですね`, `魔力切れには十分注意`)
# Admitting either invents a number on the source side of perfectly ordinary
# prose, and a check that cries wolf is a check that gets switched off.
_COUNTERS = "日人個回年月時秒匹枚本階度倍円歳割層つ"
# `何` before a numeral makes it INDEFINITE - 何百年 is "hundreds of years",
# not 100 years - so the quantity is not comparable.
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

    # 1. kanji numerals, counter-gated
    def _k(m):
        v = _kanji_to_int(m.group(1))
        return str(v) if v is not None else m.group(1)
    t = _KANJI_NUM_RE.sub(_k, t)

    # 2. 1,234,567 -> 1234567, only where the grouping is well formed so a real
    #    decimal comma survives
    t = re.sub(r"(?<![\d,])\d{1,3}(?:,\d{3})+(?![\d,])",
               lambda m: m.group(0).replace(",", ""), t)

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

    # 5. English lexicalisations and spelled-out numerals
    t = _MULT_RE.sub(lambda m: str(_WORD_MULT[m.group(1).lower()]), t)

    def _w(m):
        v = _words_to_int(m.group(0))
        return str(v) if v is not None else m.group(0)
    t = _WORD_RE.sub(_w, t)

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

    if _visible_numbers(src) != _visible_numbers(tl):
        out.append("number-drift")

    # MV lexes an escape as `\` plus a RUN of letters
    # (Window_Base.obtainEscapeCode: /^[\$\.\|\^!><\{\}\\]|^[A-Z]+/i), so
    # `\Helen` parses as one unknown code named `helen` and the word is never
    # drawn. Japanese never trips this because kana terminates the code;
    # translating into English is what CREATES it, and it survives every other
    # check - token counts match, no residual Japanese, clean JSON diff, and
    # the word is simply invisible in game. Proven with tools/trace_parser.py.
    if _BARE_ESCAPE_RE.search(tl) and not _BARE_ESCAPE_RE.search(src):
        out.append("bare-escape-eats-word")

    if u["kind"] == "ptext" and re.search(r"[ \t]", tl):
        # Not fatal - inject converts to NBSP - but worth surfacing, because a
        # long popup label is the shape that pushed a plugin argument over.
        out.append("space-in-plugin-arg")

    # Restored control codes as a multiset. Position is deliberately free:
    # English word order legitimately moves a standalone code.
    cmap = u.get("codes") or {}
    if cmap:
        a = codes.code_multiset(codes.unmask_codes(src, cmap, pad_inserts=False))
        b = codes.code_multiset(codes.unmask_codes(tl, cmap, pad_inserts=False))
        if a != b:
            out.append("control-code")

    if cfg is not None and m is not None and not out:
        prob = _overflow(u, cfg, m)
        if prob:
            out.append("overflow")
    return [c for c in out if c not in waived]


def overflow_detail(u, cfg, m):
    return _overflow(u, cfg, m)


def _overflow(u, cfg, m):
    kind = u["kind"]
    tl = codes.clean_translation(u.get("tl") or "")
    if not tl.strip():
        return ""
    restored = codes.unmask_codes(tl, u.get("codes") or {},
                                  pad_inserts=(kind != "ptext"))
    if kind == "text":
        width, rows = cfg.width, cfg.max_rows
    elif kind == "desc":
        width, rows = cfg.list_width, cfg.list_max_rows
    elif kind == "choice":
        width, rows = cfg.choice_width, 1
    elif kind == "ptext":
        width, rows = cfg.ptext_width, 1
    else:
        width, rows = cfg.list_width, 1

    if kind in ("text", "desc"):
        f = wrap.fit(restored, width, rows, m)
        if f.overflow_rows:
            return "wraps to %d rows, box holds %d" % (f.rows, rows)
        if f.widest > cfg.hard_width:
            return "widest line %d cells, hard cap %d" % (f.widest, cfg.hard_width)
        return ""
    w = m.cells(restored)
    if w > width:
        return "%d cells, budget %d" % (w, width)
    return ""


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
def same_source_conflicts(docs):
    """One source string with two different translations.

    Invisible to every per-line validator, and exactly what makes a patch feel
    machine-made: a menu label that changes name between screens."""
    idx = collections.defaultdict(set)
    where = collections.defaultdict(list)
    for _doc, u in store.all_units(docs):
        tl = (u.get("tl") or "").strip()
        if tl:
            idx[(u["kind"], u["src"])].add(tl)
            where[(u["kind"], u["src"])].append(u["id"])
    out = []
    for key, variants in idx.items():
        if len(variants) > 1:
            out.append((key[0], key[1], sorted(variants), where[key][:6]))
    return out


_TOKEN_RE = re.compile(r"(?<![\w])[A-Z][A-Za-z'’]+(?![\w])")


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
def run(cfg, store_dir, max_show=25, verbose=True):
    m = measure.reset(cfg.font_path)
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
        for w in soft_warnings(u, name_forms, all_forms):
            warns.append("%s: %s" % (u["id"], w))

    conflicts = same_source_conflicts(docs)
    nearmiss = romanization_near_misses(docs, glossary)
    names_total = len(glossary.get("names", {}))
    names_done = sum(1 for v in glossary.get("names", {}).values() if store.name_en(v))

    if verbose:
        print("VALIDATION  files=%d units=%d" % (len(docs), total))
        pct = (100.0 * done / total) if total else 0.0
        print("  translated          : %d (%.1f%%)" % (done, pct))
        print("  untranslated        : %d" % empty)
        for k in ("identical", "residual-jp", "placeholder", "control-code",
                  "overflow", "number-drift", "degenerate",
                  "leaked-scaffolding", "placeholder-word",
                  "space-in-plugin-arg", "bare-escape-eats-word"):
            print("  %-20s: %d" % (k, tally[k]))
        print("  names translated    : %d/%d" % (names_done, names_total))
        print("  soft warnings       : %d" % len(warns))
        print("  same-source conflict: %d" % len(conflicts))
        print("  romanization drift  : %d" % len(nearmiss))
        print("  WAIVED checks       : %d (accepted by hand, listed below - a "
              "suppression nobody can see is worse than the false positive it "
              "hides)" % len(waived))
        for s in waived:
            print("   = " + s)
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

    blocking = (empty + tally["residual-jp"] + tally["placeholder"]
                + tally["control-code"] + tally["overflow"]
                + tally["degenerate"] + tally["leaked-scaffolding"]
                + tally["number-drift"] + tally["placeholder-word"]
                + tally["bare-escape-eats-word"])
    return 0 if blocking == 0 else 1


def failing_ids(cfg, store_dir):
    m = measure.reset(cfg.font_path)
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
