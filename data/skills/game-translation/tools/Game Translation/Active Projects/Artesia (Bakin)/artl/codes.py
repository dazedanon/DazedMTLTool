#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
codes.py - Bakin text primitives for THIS game.

Responsibilities
----------------
* Japanese detection (three different questions, three different tests).
* Split the SPEAKER off a dialogue unit. On Bakin the speaker is not a
  convention, it is markup: `\NPL[アルテシア]` at the head of the line, and
  71,519 of 83,999 dialogue units carry one. That makes speaker recovery exact
  rather than heuristic - the opposite of the RPG Maker pipelines, where the
  nameplate is a rendered row and has to be guessed at.
* Mask the remaining inline codes to `⟦n⟧` sentinels and restore them.
* Pre- and post-model text sanitation.

Control-code inventory for THIS game, counted over all 90,188 extracted units
by `tools/code_census.py`. The engine's own table
(`Yukar.Common.Rom.GameContentParser.keyWords`) has **541** regex entries; the
game uses **20 shapes**, and that is the list the masker has to be right about:

    \NPL[name]                        71519   DISPLAY TEXT - the nameplate
    \$[var]                             116   KEY - a variable name
    \n                                   32   bare line break
    \z[n]                                23   KEY - a numeric delay
    \innpriceG                           18   content getter, inserts a NUMBER
    \currentitemnum                       8   content getter, inserts a NUMBER
    \r[ruby]                              4   DISPLAY TEXT - furigana
    \selectshopitemnum                    4   content getter, inserts a NUMBER
    \#[var]                               2   KEY - a variable name
    \currentskillconsumptionhp[tmpl]      2   DISPLAY TEXT inside the bracket
    \currentskillconsumptionmp[tmpl]      2   DISPLAY TEXT inside the bracket
    \currentskillconsumptionitem[tmpl]    2   DISPLAY TEXT inside the bracket
    \selecshoptitemcategory               2   content getter, inserts a WORD
    \currentskillconsumptionmp             2   content getter, inserts a NUMBER
    \$[var][idx]                          2   KEY
    \currentlearnskillconsumption{hp,mp}   1   content getter
    \selectskillconsumption{hp,mp}         1   content getter
    \currentitemname                       1   content getter, inserts a WORD

`tools/backslash_audit.py` proves the inventory is complete: 71,743 backslashes
in the corpus, 71,743 claimed by the pattern below, **zero** unclaimed and zero
literal `\\` pairs. So the `\GWhat` failure class cannot arise from the source.
It can still arise from a TRANSLATION that writes a backslash of its own, which
`validate.py` checks on the restored text.
"""

import re
import unicodedata

# --------------------------------------------------------------------------
# Japanese detection - three tests, deliberately different
# --------------------------------------------------------------------------

# 1. "Does this string contain source-language text at all?" Extraction gate.
#    Matches BakinTL's own HasJp so the two sides of the pipeline agree on what
#    a unit is. Fullwidth Latin and halfwidth katakana are IN.
LANG_RE = re.compile(r"[一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９｡-ﾟ々〆〇]")

# 2. "Is this string still untranslated?" Hard validation gate.
#    Three carve-outs a plain CJK class gets wrong:
#      * U+3007 〇 and ● are CENSOR MASKS and are SUPPOSED to survive.
#      * U+3099-U+309C, the voiced sound marks, are kept as distortion on a
#        slurred moan (`お゛ッ`), so the hiragana range stops at ゖ U+3096.
#      * A LONE katakana is cosmetic residue an English line can carry; a run
#        of TWO OR MORE is a real word that was never translated.
UNTRANSLATED_RE = re.compile(
    r"[ぁ-ゖゝゞ㐀-䶿一-鿿豈-﫿々〆]"
    r"|[ァ-ヺ]{2,}")

# 3. "Is there any CJK left at all?" Soft review only.
ANY_JP_RE = re.compile(r"[぀-ゟ゠-ヿㇰ-ㇿ㐀-䶿一-鿿豈-﫿ｦ-ﾝ々〆〇]")


def has_jp(s):
    return isinstance(s, str) and bool(LANG_RE.search(s))


def has_untranslated_jp(s):
    return isinstance(s, str) and bool(UNTRANSLATED_RE.search(s))


# Sokuon marooned among non-kana: "Nhagiッ!" -> "Nhagi-!". The lookarounds keep
# a sokuon inside a real katakana word (ベッド) untouched, and deliberately
# exclude the voiced sound marks U+3099-U+309C - `お゛っ` has a dakuten right
# before the sokuon, and a class running to U+309F would read that as "inside a
# kana word" and refuse to convert the one case this exists for.
_STRANDED_SOKUON_RE = re.compile(r"(?<![ぁ-ゖァ-ヺｦ-ﾝ])[っッ]+(?![ぁ-ゖァ-ヺｦ-ﾝ])")

SMALL_KANA = {
    "ぁ": "a", "ぃ": "i", "ぅ": "u", "ぇ": "e", "ぉ": "o",
    "ァ": "a", "ィ": "i", "ゥ": "u", "ェ": "e", "ォ": "o",
    "ゃ": "ya", "ゅ": "yu", "ょ": "yo", "ャ": "ya", "ュ": "yu", "ョ": "yo",
    "ゎ": "wa", "ヮ": "wa",
}
_FULLSIZE_KANA_RE = re.compile(r"[ぁ-んァ-ン]")


# `ゔ` / `ヴ` (vu) stranded among Latin letters is a growled vowel, not a word -
# the model writes "so goodゔ!" and "Cum for meゔ!!" where the Japanese had a
# dakuten-distorted vowel. It is a FULL kana letter, so unlike the dakuten mark
# itself it is real residual Japanese and the validator is right to flag it.
# Fixing it is a deterministic transliteration, and the skill is explicit that a
# third round trip buys nothing for stranded kana: drop it and keep any
# neighbouring dakuten, which already carries the distortion.
_STRANDED_VU_RE = re.compile(r"(?<![ぁ-ゖァ-ヺｦ-ﾝ])[ゔヴ]+"
                             r"(?![ぁ-ゖァ-ヺｦ-ﾝ])")


def strip_residual_kana(s):
    """Deterministic cleanup of kana the model left as decoration.

    Bails out unchanged if any FULL-SIZE kana or kanji survives once the small
    kana, the sokuon and a stranded vu are removed - that is a real translation
    miss and belongs back in the retry queue, not papered over here."""
    if not isinstance(s, str):
        return s
    rest = s
    for k in SMALL_KANA:
        rest = rest.replace(k, "")
    rest = _STRANDED_VU_RE.sub("", rest)
    rest = rest.replace("っ", "").replace("ッ", "")
    if UNTRANSLATED_RE.search(rest) or _FULLSIZE_KANA_RE.search(rest):
        return s
    out = _STRANDED_VU_RE.sub("", s)
    out = _STRANDED_SOKUON_RE.sub("-", out)
    for k, v in SMALL_KANA.items():
        out = out.replace(k, v)
    out = re.sub(r"-{2,}", "-", out)
    # A trailing hyphen before whitespace or end-of-string is noise; one before
    # punctuation or a heart is the cut-off itself and stays.
    out = re.sub(r"-+(?=\s|$)", "", out)
    return out


_JP_QUOTE_MAP = {"「": '"', "」": '"', "『": '"', "』": '"', "｢": '"', "｣": '"'}
_JP_QUOTE_RE = re.compile("[「」『』｢｣]")


def normalize_quotes(s):
    if not isinstance(s, str):
        return s
    return _JP_QUOTE_RE.sub(lambda m: _JP_QUOTE_MAP[m.group()], s)


# --------------------------------------------------------------------------
# Speaker: the \NPL[...] nameplate code
# --------------------------------------------------------------------------
# Three nameplate codes exist in the engine's table - left, centre and right -
# and this game uses only the left one. All three are handled anyway, because
# a single scene added in a later version would otherwise strand a raw code in
# the middle of a translated line.
NAMEPLATE_RE = re.compile(r"^\s*\\(NPL|NPC|NPR)\[([^\]\r\n]*)\]")


# Any nameplate, anywhere in the string - not only the leading one that
# `NAMEPLATE_RE` anchors on. `inject.render` uses this to rewrite a
# mid-body nameplate from the glossary.
NAMEPLATE_ANY_RE = re.compile(r"\\(NPL|NPC|NPR|NP)\[([^\]\r\n]*)\]")


def split_speaker(text):
    r"""('アルテシア', 'rest', 'NPL') or ('', text, '').

    Exact, not heuristic: the nameplate is markup the engine parses, so there
    is no guessing and no false-positive class. Contrast the RPG Maker
    pipelines, where the first physical line of a message block MIGHT be a
    nameplate and four separate gates are needed to decide."""
    if not isinstance(text, str):
        return "", text, ""
    m = NAMEPLATE_RE.match(text)
    if not m:
        return "", text, ""
    return m.group(2), text[m.end():], m.group(1)


def join_speaker(speaker_en, body, kind_code="NPL"):
    r"""Rebuild `\NPL[Artesia]body`. The nameplate is drawn in its own plate,
    so the English name goes back INSIDE the code, never as a prefix on the
    line - which is the `[Kurone]: ` artifact the other pipelines have to strip
    back off."""
    if not speaker_en:
        return body
    return "\\%s[%s]%s" % (kind_code or "NPL", speaker_en, body)


# --------------------------------------------------------------------------
# Inline control-code masking
# --------------------------------------------------------------------------
PH_OPEN, PH_CLOSE = "\u27e6", "\u27e7"           # ⟦ ⟧
PH_RE = re.compile(PH_OPEN + r"\s*(\d+)\s*" + PH_CLOSE)

# One pattern, matched longest-first the way the engine's own 541-entry table
# is ordered. The bracketed forms have to come before the bare letter run or
# `\z` would match and leave `[200]` as visible text.
_CODE_RE = re.compile(
    r"""
      \\ [A-Za-z_#$]+ (?: \[ [^\]\r\n]* \] )+   # \NPL[..]  \$[..][..]  \z[..]
    | \\ [A-Za-z_#$]+                           # \n  \innpriceG  \currentitemnum
    | \\ .                                      # anything else, so nothing leaks
    """,
    re.VERBOSE,
)

# Sentinels standing for a code that inserts a WORD or a NUMBER at run time.
# Japanese sets no space around one, so a faithful translation keeps none and
# the player reads `Price:100G` as `Price:100G` but `You have5 left`. English
# needs the space, and it has to be enforced on inject, not merely asked for in
# the prompt - the model never sees the code, only the sentinel.
#
# Derived from the engine's keyword table: every getter whose value is a number
# or a name, none of the layout codes.
_WORD_INSERT_NAMES = (
    "innpriceg", "currentitemnum", "currentitemname", "selectshopitemnum",
    "selecshoptitemcategory", "currentskillconsumptionhp",
    "currentskillconsumptionmp", "currentskillconsumptionsp",
    "currentskillconsumptionitem", "currentlearnskillconsumptionhp",
    "currentlearnskillconsumptionmp", "selectskillconsumptionhp",
    "selectskillconsumptionmp", "money", "currency", "time", "map", "title",
    "subtitle", "currentpage", "maximumpage", "partyname", "currentpartyname",
    "skillname", "itemname", "castname", "currentitemdes",
)
_INSERT_RE = re.compile(
    r"^\\(" + "|".join(_WORD_INSERT_NAMES) + r")(?:\[|$)", re.I)


def _needs_pad(ch):
    """A space is added only where the insert is glued to a WORD or DIGIT.

    That is the entire failure mode. Padding against punctuation produces
    `You have 5 .`, and padding between two adjacent sentinels turns `100\\G`
    into `100 G` twice over. Both neighbours are read from the MASKED text, so
    the character beside a sentinel is `⟧` rather than whatever the previous
    sentinel restores to."""
    return bool(ch) and ch.isalnum() and ord(ch) < 0x3000


def is_word_insert(code):
    return bool(_INSERT_RE.match(code))


def mask_codes(text):
    """Replace inline codes with `⟦k⟧`. Returns (masked, {ph: code}).

    The nameplate code is NOT masked here - `extract.py` peels it off into the
    unit's `speaker` field first, so the model is told who is talking instead
    of being handed an opaque sentinel it cannot reason about."""
    code_map = {}
    n = [0]

    def repl(m):
        k = n[0]
        n[0] += 1
        ph = "%s%d%s" % (PH_OPEN, k, PH_CLOSE)
        code_map[ph] = m.group(0)
        return ph

    return _CODE_RE.sub(repl, text), code_map


def unmask_codes(text, code_map, pad_inserts=True):
    """Restore `⟦k⟧` sentinels.

    Tolerates whitespace the model inserts inside the brackets. A sentinel the
    model dropped simply stays absent (validation catches it). A sentinel the
    model invented restores to nothing.

    `pad_inserts` adds the English space around a word/number insert. Pass
    False when restoring purely to validate, so the multiset check compares the
    string the player actually sees."""
    if not code_map:
        return text

    out = []
    pos = 0
    for m in PH_RE.finditer(text):
        ph = "%s%s%s" % (PH_OPEN, m.group(1), PH_CLOSE)
        code = code_map.get(ph, "")
        out.append(text[pos:m.start()])
        if pad_inserts and code and is_word_insert(code):
            before = text[m.start() - 1:m.start()] if m.start() else ""
            after = text[m.end():m.end() + 1]
            if _needs_pad(before):
                out.append(" ")
            out.append(code)
            if _needs_pad(after):
                out.append(" ")
        else:
            out.append(code)
        pos = m.end()
    out.append(text[pos:])
    return "".join(out)


def placeholder_ids(text):
    return {int(x) for x in PH_RE.findall(text)}


def code_multiset(text):
    r"""Counter of the control codes present, for the restored-text check.

    Lexed the way the ENGINE lexes, via `_match_escape`, NOT with `_CODE_RE`.
    `_CODE_RE` is right for masking the SOURCE, where a code is always followed
    by kana and the greedy letter run stops on its own. It is wrong for a
    RESTORED translation, where the next character is Latin: `\n速い` lexes as
    `\n`, but the English `\nFast` lexes as one token `\nFast`, so the two
    multisets differ and 16 correct UI option lists were reported as dropped
    control codes.

    Falls back to `_CODE_RE` when the keyword table has not been loaded, so the
    behaviour is the old one rather than nothing."""
    from collections import Counter
    text = text or ""
    if not _KEYWORDS:
        return Counter(m.group(0) for m in _CODE_RE.finditer(text))
    out = Counter()
    i = 0
    while True:
        i = text.find("\\", i)
        if i < 0:
            return out
        n = _match_escape(text, i)
        if not n:
            out[text[i:i + 2]] += 1
            i += 1
            continue
        tok = text[i:i + n]
        i += n
        # A bracketed argument belongs to the code that opened it.
        while i < len(text) and text[i] == "[":
            j = text.find("]", i)
            if j < 0:
                break
            tok += text[i:j + 1]
            i = j + 1
        out[tok] += 1


# Codes whose BRACKET CONTENT is display text rather than a key. Masking these
# opaquely would ship the Japanese inside them; `extract.py` therefore lifts
# them out as their own units.
DISPLAY_ARG_CODES = {
    "r",                                # \r[furigana]
    "currentskillconsumptionhp",
    "currentskillconsumptionmp",
    "currentskillconsumptionsp",
    "currentskillconsumptionitem",
    "currentlearnskillconsumptionhp",
    "currentlearnskillconsumptionmp",
    "selectskillconsumptionhp",
    "selectskillconsumptionmp",
}
_ARG_CODE_RE = re.compile(r"\\([A-Za-z_#$]+)\[([^\]\r\n]*)\]")


def display_args(text):
    """[(whole, name, arg)] for codes whose bracket holds player-visible text."""
    out = []
    for m in _ARG_CODE_RE.finditer(text or ""):
        if m.group(1).lower() in DISPLAY_ARG_CODES:
            out.append((m.group(0), m.group(1), m.group(2)))
    return out


# --------------------------------------------------------------------------
# Source sanitation (what the model is shown)
# --------------------------------------------------------------------------
def resolve_ruby(text):
    r"""Replace a ruby code with its BASE spelling and do not restore it.

    Bakin has two forms, and the one-argument form is the dangerous one: it
    binds to exactly ONE character AFTER the closing bracket, which sits in the
    visible text where the model can move it away from its code. All 4
    occurrences in this game are that form - the emphasis-dot idiom
    `\r[・]カ\r[・]モ` over カモ - and English has no equivalent typography, so
    the right answer is the skill's tier-1 masking rule: resolve to the base
    spelling and drop the code.

    Returns (text, n_dropped)."""
    if not isinstance(text, str) or "\\r[" not in text:
        return text, 0
    n = [0]

    def two(m):
        n[0] += 1
        return m.group(1)                       # \r[base,ruby] -> base

    def one(m):
        n[0] += 1
        return m.group(2)                       # \r[ruby]X -> X

    text = re.sub(r"\\r\[([^,\]\r\n]*),([^\]\r\n]*)\]", two, text)
    text = re.sub(r"\\r\[([^\]\r\n]*)\](.)", one, text)
    return text, n[0]


# Message bodies use real CRLF, not the `\n` code: 106,302 CRLF pairs in
# `Script.commands[].attrList[].value` against 32 uses of `\n`, and those 32
# are all in layout option lists. The model is shown LF and the rom gets its
# CRLF back, so a translated line break is byte-identical in shape to the
# author's.
def to_lf(text):
    return text.replace("\r\n", "\n").replace("\r", "\n") \
        if isinstance(text, str) else text


def to_crlf(text):
    return to_lf(text).replace("\n", "\r\n") if isinstance(text, str) else text


def clean_source(text):
    """Normalise the JP shown to the model without changing meaning.

    U+3000 IDEOGRAPHIC SPACE is used two ways in this corpus: as trailing line
    padding, and as an intra-sentence pacing gap between gasps
    (`ぱんぱんっ！♡　ぱんぱんっ！♡` - 186 units of it). Deleting both runs the
    phrases together; keeping both puts an invisible double-width space in
    front of the model. Trailing runs are dropped, interior ones become one
    ASCII space."""
    if not isinstance(text, str):
        return text
    text = to_lf(text)
    lines = []
    for line in text.split("\n"):
        line = line.rstrip("\u3000 \t")
        line = line.replace("\u3000", " ")
        lines.append(line)
    text = "\n".join(lines)
    # Halfwidth-kana spans only: whole-string NFKC would flatten the fullwidth
    # Latin and digits this author uses to align columns.
    text = re.sub(r"[｡-ﾟ]+",
                  lambda m: unicodedata.normalize("NFKC", m.group(0)), text)
    # Fancy quotes the model reads as an ASCII double quote and then loses.
    text = text.translate(_QUOTE_FOLD)
    return text


_QUOTE_FOLD = str.maketrans({
    "\u201c": "'", "\u201d": "'", "\uff02": "'",
    "\u2018": "'", "\u2019": "'", "\u201b": "'",
    "\u02bc": "'", "\uff07": "'",
})


# --------------------------------------------------------------------------
# Translation sanitation (what goes into the rom)
# --------------------------------------------------------------------------
_POST = [
    (re.compile(r"\.\.\.(?:。)+"), "..."),
    (re.compile(r"(?:。){2,}"), "..."),
    # JP sets no space after ！ / ？, so the model omits it in English too.
    (re.compile(r"([!?])([A-Z])"), r"\1 \2"),
    (re.compile(r'"-\s"'), '"-"'),
    (re.compile(r"[ \t]{2,}"), " "),
]


def clean_translation(text):
    """Cosmetic repair of a FINISHED translation.

    Guarded on "is this still Japanese": a unit that failed and still holds
    source text must be written back byte-exact, not dressed in English
    punctuation. That is how a whole-corpus normaliser once shipped Japanese
    wearing English quotes with every unit-level check green."""
    if not isinstance(text, str):
        return text
    # The kana strip runs BEFORE the untranslated guard, not after it.
    #
    # The guard exists so a unit that failed and still holds source text is
    # written back byte-exact rather than dressed in English punctuation. But
    # `ゔ` growled onto the end of an English word IS residual Japanese by that
    # test, so the guard fired first and the cleanup that exists precisely for
    # stranded kana was never reached - 152 occurrences across 116 units, each
    # one a correct translation the validator then reported.
    #
    # Running it first is safe because `strip_residual_kana` is itself
    # guarded: the moment any FULL-SIZE kana or kanji survives its own removal
    # pass it returns the input unchanged. So it can only ever clear
    # decoration, never paper over a real miss.
    text = strip_residual_kana(text)
    if has_untranslated_jp(text):
        return text
    text = normalize_quotes(text)
    # Fullwidth punctuation converts offline - no model call needed.
    text = text.replace("！", "!").replace("？", "?").replace("、", ",")
    text = re.sub(r"。(?=\s|$)", ".", text)
    for rx, rep in _POST:
        text = rx.sub(rep, text)
    return "\n".join(l.rstrip() for l in text.split("\n"))


# --------------------------------------------------------------------------
# Bare-escape safety on the WRITE path
# --------------------------------------------------------------------------
# Bakin's parser matches an alternation of 541 regexes built from
# `GameContentParser.keyWords`, ordered so a longer keyword is tried before a
# shorter prefix of it. That is structurally safer than RPG Maker's greedy
# `[A-Za-z]+` lexer: an unrecognised `\xyz` is left as literal text rather than
# swallowing the following word.
#
# The residual risk runs the OTHER way, and only English can trigger it: a
# translation that writes a backslash of its own can accidentally SPELL one of
# the 541 keywords and have it substituted at run time. The source corpus has
# zero orphan backslashes (`tools/backslash_audit.py`), so any backslash in an
# output that is not a restored sentinel is by construction something the model
# invented. `validate.py` treats that as a hard failure rather than trying to
# repair it, because there is no safe repair: deleting it may destroy a code
# the model correctly restored itself.
#
# Beyond that, decompiling `MessageReader.MessageEntry.separateByCommands`
# found five ways an ENGLISH string can break a renderer that Japanese never
# touches. Every one is checked on the RESTORED output, because that is the
# string the engine parses. Evidence and IL offsets are in `ENGINE-CODES.md`.
_TRAPS = [
    # `func()` always does `.Split(',')` and every consumer reads `array[0]`,
    # so `\NPL[Smith, Jr.]` renders as `Smith`. The source corpus contains
    # ZERO ASCII commas inside a bracket (Japanese writes 、 and ，), so any
    # comma the patch ships inside one is ours.
    ("comma-in-code-arg",
     re.compile(r"\\[A-Za-z_#$]+\[[^\]\r\n]*,[^\]\r\n]*\]")),
    #
    # `bracket-in-code-arg` is deliberately NOT a whole-line regex. The obvious
    # one - `\CODE\[[^\]]*\][^\r\n]*\]` - is unanchored on its tail and matches
    # ACROSS two codes on one line, so `\NPL[Artesia]You have \$[gold] left`
    # trips it. Run over this game's own source it flagged 22 correctly
    # rendering author lines, which is a false-positive machine on lines that
    # can never be fixed.
    #
    # The real failure is at CONSTRUCTION: a value we are about to place inside
    # a bracket contains a `]`, which would close the argument early. That is
    # what `safe_code_arg` below checks, at the two places a translated value
    # ever enters a bracket - the nameplate and a code argument.
    # `commands = {blink, blspd, blrate, lipspd, lip, NP}` is matched with a
    # bare StartsWith BEFORE the single-char switch and with no requirement
    # that `[` follow, then indexes `func()[0]` on an empty array. `\blinked`
    # is an IndexOutOfRangeException at run time.
    ("blink-collision", re.compile(r"\\b(?=link|lspd|lrate)")),
    # `replaceForFormat` parks `\\` on a TAB while it parses and converts every
    # TAB back to a backslash, so a real TAB is drawn as a visible `\`.
    ("tab-becomes-backslash", re.compile(r"\t")),
    # CR/LF are tested before the escape flag and neither clears it, so a
    # trailing backslash eats the first character of the next line.
    ("trailing-backslash", re.compile(r"\\(?=\r|\n|$)")),
    # Every single-letter escape invokes the bracket reader before the char
    # switch, so `\b[whispering]` toggles bold and DELETES the bracket group.
    ("bracket-after-bare-escape", re.compile(r"\\[nbiu!^<>]\[")),
]


def output_traps(text):
    """[(name, match)] for engine-level traps in a RESTORED translation."""
    out = []
    for name, rx in _TRAPS:
        m = rx.search(text or "")
        if m:
            out.append((name, m.group(0)))
    return out


# Characters that cannot survive inside a bracketed code argument. Checked on
# the VALUE before it is placed, which is the only place the check can be
# precise - see the note in `_TRAPS`.
#
#   ]   closes the argument early; the rest becomes visible text
#   ,   the bracket reader splits on it and consumers read element 0, so
#       `\NPL[Smith, Jr.]` renders as `Smith`
#   CR/LF/TAB  the parser tests line ends before the escape flag, and a TAB is
#       converted back into a visible backslash
_UNSAFE_IN_ARG = {"]": "closes the argument early",
                  ",": "the engine splits the argument on comma and keeps only "
                       "what precedes it",
                  "\r": "a line end inside a code argument",
                  "\n": "a line end inside a code argument",
                  "\t": "a TAB is drawn as a visible backslash"}


def safe_code_arg(value):
    """[] when `value` may go inside `\\CODE[...]`, else [(char, why)]."""
    return [(ch, why) for ch, why in _UNSAFE_IN_ARG.items()
            if ch in (value or "")]


_KEYWORDS = None

# Pass 2, `MessageReader.MessageEntry.separateByCommands`. These are NOT in
# `GameContentParser.keyWords` - that table is pass 1 only - so a check built
# on the keyword table alone calls every one of them unknown. On this game that
# meant flagging `\NPL` on 71,513 lines, 78% of the corpus, as an invented
# backslash.
_MULTI_COMMANDS = ("blink", "blspd", "blrate", "lipspd", "lip",
                   "NPL", "NPC", "NPR", "NP")
_SINGLE_COMMANDS = set("!<>^bcinruwz")
# Pass 1, `GameMain.replaceForFormat`, bracketed and keyed.
_VAR_COMMANDS = ("$L", "Variable", "$", "#", "v", "s", "h", "H")


def load_keywords(path):
    """Read the engine's own keyword table (`BakinApi static ... keyWords`)."""
    global _KEYWORDS
    names = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            if "\t" not in line:
                continue
            pat = line.split("\t", 1)[1].strip()
            m = re.match(r"\\\\([A-Za-z0-9_]+)", pat)
            if m:
                names.add(m.group(1))
    _KEYWORDS = names
    return names


def _match_escape(text, i):
    r"""Length of the code starting at `text[i] == '\\'`, or 0 if unknown.

    Models the engine's dispatch ORDER, which is not a greedy `[A-Za-z]+` lexer
    - Bakin compares characters. Getting this wrong in the other direction is
    just as bad: a greedy regex reads `\nfast` as one unknown token when the
    engine reads `\n` followed by the word "fast", and this game's output
    contains exactly that."""
    rest = text[i + 1:]
    if rest.startswith("\\"):
        return 2                                   # escaped literal backslash
    for c in _MULTI_COMMANDS:                      # longest-first by construction
        if rest.startswith(c):
            return 1 + len(c)
    for c in _VAR_COMMANDS:
        if rest.startswith(c):
            return 1 + len(c)
    # GameContentParser keywords, longest first so `\partyname` is not read as
    # a prefix of `\partynameicon`.
    if _KEYWORDS:
        for kw in sorted((k for k in _KEYWORDS if rest.startswith(k)),
                         key=len, reverse=True):
            return 1 + len(kw)
    if rest[:1] in _SINGLE_COMMANDS:
        return 2
    return 0


def unknown_escapes(text):
    r"""Backslash runs the engine does not define.

    An unknown escape is not a corruption - `separateByCommands` preserves it
    literally, so `\q` draws as the two characters `\q` - but it is still two
    wrong characters on screen and the source has none.

    Returns [] when the keyword table has not been loaded, so a caller that
    forgot to load it gets no findings rather than false ones."""
    if not _KEYWORDS:
        return []
    out = []
    text = text or ""
    i = 0
    while True:
        i = text.find("\\", i)
        if i < 0:
            break
        n = _match_escape(text, i)
        if n:
            i += n
        else:
            out.append(text[i:i + 8])
            i += 1
    return out
