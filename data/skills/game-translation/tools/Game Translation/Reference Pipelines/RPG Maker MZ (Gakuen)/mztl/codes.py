#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
codes.py - RPG Maker MZ text primitives for this game.

Responsibilities
----------------
* Japanese detection (three different questions, three different tests).
* Split the SPEAKER off a 401 run. This game writes the speaker as the first
  physical line of the block, with the dialogue opening on the next line -
  it is a rendered row, not markup, and it is a glossary entry rather than a
  translation unit.
* Mask the remaining inline codes to `⟦n⟧` sentinels and restore them.
* Pre- and post-model text sanitation.

Control-code inventory for THIS game, counted over every 401/102 and every
database and System field (`audit/CENSUS2.txt`):

    \C[n]    84   text colour            (inline - mask, never pad)
    \|       64   one-second wait
    \.       39   quarter-second wait
    \V[n]    33   variable value         (inline CONTENT - mask, PAD)
    \SM[k]   16   sprite motion  (CharacterPictureManager: pop/nod/stamp/...)
    \CM[k]   16   camera motion
    \SE[n]   14   sprite expression (0..6: しかめつら/困り顔/恥じらい/泣き/...)
    \{        4   font size up
    \G        1   currency unit          (inline CONTENT - mask, PAD)

    Absent from the corpus: \I \N \P \} \FS \r \p \$ \< \> \^ and %1.
    (%1/%2 DO occur in System.json terms.messages and in plugin parameters,
    so the mask pattern keeps them.)

    There is not one orphan backslash anywhere in data/ once the codes above
    are masked out - verified in `audit/CENSUS3.txt` - so the `\Helen` failure
    class cannot arise from the source. It can still arise from a TRANSLATION
    that puts a Latin letter against a bare `\{`, which `validate.py` checks.
"""

import re
import unicodedata

# Shared with the wrapper and measurer. LL_StandingPicture also accepts F1-F8
# and M1-M8, and F3[\V[1]] contains a nested bracket pair. A partial match of
# just \F still round-trips, but exposes the portrait ID to translation.
# This covers one nested pair, as used by the verified plugin; deeper syntax
# needs its own consumer audit rather than a claim of arbitrary nesting.
BRACKET_CODE_PATTERN = r"\\+(?:[FMfm][1-8]|[A-Za-z]+)\[(?:[^\[\]]|\[[^\[\]]*\])*\]"

# --------------------------------------------------------------------------
# Japanese detection - three tests, deliberately different
# --------------------------------------------------------------------------

# 1. "Does this string contain source-language text at all?" Extraction gate.
#    Fullwidth Latin and halfwidth katakana are IN: this game writes UI labels
#    with them (`ＢＥＴ`, `Ｇ`, `ﾊﾞﾆｰ`) and a kana/kanji-only class is blind.
LANG_RE = re.compile(r"[一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９｡-ﾟ々〆〇]")

# 2. "Is this string still untranslated?" Hard validation gate.
#    Three deliberate carve-outs, each of which a plain CJK class gets wrong:
#      * U+3007 〇 and ● are CENSOR MASKS (ちん〇 -> c〇ck) and are SUPPOSED to
#        survive. Flagging them sends good lines to a retry that can only
#        reproduce them.
#      * U+3099-U+309C, the voiced/semi-voiced sound marks, are kept as
#        distortion on a slurred moan (`お゛ッ`), so the hiragana range stops at
#        ゖ U+3096 rather than running to U+309F.
#      * A LONE katakana is cosmetic residue an English line can carry (a stray
#        ッ, a ・ separator, a ー dash) and a retry can never clear it. A run of
#        TWO OR MORE katakana letters is a real word that was never translated.
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
# a sokuon inside a real katakana word (ベッド) untouched. The classes are kana
# LETTERS only and deliberately exclude the voiced sound marks U+3099-U+309C:
# `お゛っ` has a dakuten immediately before the sokuon, and a class running to
# U+309F would read that as "inside a kana word" and refuse to convert the one
# case this exists for.
_STRANDED_SOKUON_RE = re.compile(r"(?<![ぁ-ゖァ-ヺｦ-ﾝ])[っッ]+(?![ぁ-ゖァ-ヺｦ-ﾝ])")

SMALL_KANA = {
    "ぁ": "a", "ぃ": "i", "ぅ": "u", "ぇ": "e", "ぉ": "o",
    "ァ": "a", "ィ": "i", "ゥ": "u", "ェ": "e", "ォ": "o",
    "ゃ": "ya", "ゅ": "yu", "ょ": "yo", "ャ": "ya", "ュ": "yu", "ョ": "yo",
    "ゎ": "wa", "ヮ": "wa",
}
_FULLSIZE_KANA_RE = re.compile(r"[ぁ-んァ-ン]")


def strip_residual_kana(s):
    """Deterministic cleanup of kana the model left as decoration.

    Bails out unchanged if any FULL-SIZE kana or kanji survives once the small
    kana and sokuon are removed - that is a real translation miss and belongs
    back in the retry queue, not papered over here."""
    if not isinstance(s, str):
        return s
    rest = s
    for k in SMALL_KANA:
        rest = rest.replace(k, "")
    rest = rest.replace("っ", "").replace("ッ", "")
    if UNTRANSLATED_RE.search(rest) or _FULLSIZE_KANA_RE.search(rest):
        return s
    out = _STRANDED_SOKUON_RE.sub("-", s)
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
# Speaker: the first physical line of the 401 run
# --------------------------------------------------------------------------
# Not "the line is short". A lone first line is a nameplate only if the NEXT
# line opens a quote. Too loose and the first line of every narration block is
# deleted as a speaker name, which is unrecoverable in a shipped patch.
_LEADING_CODE_RUN = re.compile(r"^(?:" + BRACKET_CODE_PATTERN + r"|\\+[A-Za-z.|!^<>{}$]|\s)+")

_OPENERS = "「『“\"'(（｢*[.…【"

# A nameplate is a noun phrase. It never carries sentence-terminal punctuation,
# and requiring that is what separates `催眠術師` from the narration line
# `おずおずと男の股間のモノに触れる。`, which is 20 characters long, contains
# Japanese, and happens to be followed by a line that opens a quote - so it
# passed every other gate. Three such false positives were in the first run;
# rejecting a terminated candidate loses no text, it only declines to attribute
# the block, which is the correct failure mode.
_SENTENCE_END = "。．？！?!、，,"


def _strip_leading_codes(s):
    return _LEADING_CODE_RUN.sub("", s)


def split_speaker(text, max_len=24, openers=_OPENERS):
    """('アズサ', '「…」\\n…') or ('', text).

    Four gates, all required:
      1. the candidate is non-empty, at most `max_len` characters, contains
         Japanese, and does NOT itself open with a quote - without that last
         clause a 「…」 line whose successor is also 「…」 is eaten as a name,
         which happened three times in this corpus;
      2. it carries no sentence-terminal punctuation anywhere;
      3. there IS a following line with visible content;
      4. after stripping its leading escape-code run, that line's first
         character opens a quote, a parenthetical or an ellipsis.
    """
    if not isinstance(text, str):
        return "", text
    parts = text.split("\n")
    if len(parts) < 2:
        return "", text
    cand = _strip_leading_codes(parts[0]).strip()
    if not cand or len(cand) > max_len or not has_jp(cand):
        return "", text
    if cand[0] in openers or "「" in cand or "」" in cand:
        return "", text
    if any(ch in _SENTENCE_END for ch in cand):
        return "", text
    for nxt in parts[1:]:
        body = _strip_leading_codes(nxt).strip()
        if body:
            if body[0] in openers:
                return parts[0], "\n".join(parts[1:])
            return "", text
    return "", text


# --------------------------------------------------------------------------
# Inline control-code masking
# --------------------------------------------------------------------------
PH_OPEN, PH_CLOSE = "\u27e6", "\u27e7"           # ⟦ ⟧
PH_RE = re.compile(PH_OPEN + r"\s*(\d+)\s*" + PH_CLOSE)

_CODE_RE = re.compile(
    BRACKET_CODE_PATTERN + r"""
    | \\+ [.|!^<>{}$]                # \.  \|  \!  \^  \<  \>  \{  \}  \$
    | \\+ (?:name|count|gold)\b      # TorigoyaMZ_NotifyMessage inserts
    | \\+ [A-Za-z]                   # \G  \g
    | % \d+                          # printf params (System.json messages)
    """,
    re.VERBOSE,
)

# Sentinels standing for a code that inserts a WORD or a NUMBER at runtime.
# Japanese sets no space around one, so a faithful translation keeps none and
# the player reads "SEX回数" -> "SEXcount25". English needs the space, and it
# has to be enforced on inject, not only asked for in the prompt.
_WORD_INSERT_RE = re.compile(
    r"\\+[VvGgNnPp](?:\[\d+\])?$|\\+(?:name|count|gold)$|^%\d+$")


def _needs_pad(ch):
    """A space is added only where the insert is glued to a WORD.

    That is the entire failure mode - `NeroIs that alright?`, `Mana25` - and
    nothing else. Padding against punctuation produces `%3 !`, and padding
    between two adjacent sentinels turns `%1\\G` into `100 G`. Both neighbours
    are read from the MASKED text, so the character before a sentinel is `⟧`
    rather than the last digit of whatever the previous sentinel restored to."""
    return bool(ch) and (ch.isalnum() and ord(ch) < 0x3000)


def is_word_insert(code):
    return bool(_WORD_INSERT_RE.search(code))


def mask_codes(text):
    """Replace inline codes with `⟦k⟧`. Returns (masked, {ph: code})."""
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

    `pad_inserts` adds the English space around a word/number insert, skipping
    it next to an apostrophe, hyphen or decoration. Pass False when restoring
    purely to validate, so the multiset check compares the string the player
    actually sees."""
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
    """Counter of the control codes present, for the restored-text check."""
    from collections import Counter
    return Counter(m.group(0) for m in _CODE_RE.finditer(text))


# --------------------------------------------------------------------------
# Source sanitation (what the model is shown)
# --------------------------------------------------------------------------
def clean_source(text):
    """Normalise the JP shown to the model without changing meaning.

    U+3000 IDEOGRAPHIC SPACE is used two ways in this corpus: as trailing line
    padding (`んあああっ！！ 　`) and as an intra-sentence pacing gap. Deleting
    both runs the phrases together; keeping both puts an invisible double-width
    space in front of the model. Trailing runs are dropped, interior ones
    become one ASCII space."""
    if not isinstance(text, str):
        return text
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
# Translation sanitation (what goes into the file)
# --------------------------------------------------------------------------
_POST = [
    (re.compile(r"\.\.\.(?:。)+"), "..."),
    (re.compile(r"(?:。){2,}"), "..."),
    # JP sets no space after ！ / ？, so the model omits it in English too.
    (re.compile(r"([!?])([A-Z])"), r"\1 \2"),
    # One space before a whole RUN of pause codes, never inside the run.
    (re.compile(r"([^\s\\])((?:\\[.!|^])+)"), r"\1 \2"),
    (re.compile(r'"-\s"'), '"-"'),
    (re.compile(r"[ \t]{2,}"), " "),
]


def clean_translation(text):
    """Cosmetic repair of a FINISHED translation.

    Guarded on "is this still Japanese": a unit that failed and still holds
    source text must be written back byte-exact, not dressed in English
    punctuation. That is how a whole-file normaliser once shipped Japanese
    wearing English quotes with every unit-level check green."""
    if not isinstance(text, str):
        return text
    if has_untranslated_jp(text):
        return text
    text = normalize_quotes(text)
    text = strip_residual_kana(text)
    # Fullwidth punctuation converts offline - no model call needed.
    text = text.replace("！", "!").replace("？", "?").replace("、", ",")
    text = re.sub(r"。(?=\s|$)", ".", text)
    for rx, rep in _POST:
        text = rx.sub(rep, text)
    return "\n".join(l.rstrip() for l in text.split("\n"))


# --------------------------------------------------------------------------
# Bare-escape safety on the WRITE path
# --------------------------------------------------------------------------
# MZ's Window_Base.obtainEscapeCode lexes `\` plus `/^[$.|^!><{}\\]|^[A-Z]+/i`,
# so `\{What` parses as one unknown code named `{`... no - `\{` is matched by
# the punctuation branch first and is safe. The dangerous shape is a bare
# letter escape (`\G`, `\g`) directly against a Latin letter, where the `[A-Z]+`
# branch swallows the following word. Japanese never trips this because kana
# terminates the code; translating into English is what CREATES the bug, and it
# survives every text-level check because the first word is simply not drawn.
#
# The escape names that are REAL and longer than one letter must be matched
# FIRST, or this function splits them down the middle. `\gold` is the
# TorigoyaMZ money insert; the naive rule saw `\g` followed by `o` and emitted
# `\g old`, which renders as the gold value followed by the literal word "old" -
# the shipped notification read "Got G oldG!". `\name` became `\n ame` and
# `\count` became `\c ount` the same way.
#
# So: recognise the known multi-letter escapes, leave them alone, and only then
# consider a genuinely bare single-letter escape.
# Every escape NAME this game's engine and plugins actually define, without
# brackets. `obtainEscapeCode` lexes `\` plus a GREEDY `[A-Za-z]+`, so the run
# has to be split after the longest name that really exists - not after the
# first letter, and not at all when the run IS a name.
#
# Getting this wrong is not theoretical: the naive "split after one letter"
# rule turned `\gold` into `\g old`, and the shipped money notification read
# **"Got G oldG!"** - the gold value, the literal word "old", then the currency
# unit. `\name` became `\n ame` and `\count` became `\c ount` the same way.
_ESCAPE_NAMES = (
    # multi-letter first; the table is sorted longest-first below anyway
    "count", "gold", "name",
    "sm", "cm", "se", "ac", "cl", "fs", "px",
    "c", "i", "v", "n", "p", "g",
)
_ESCAPE_BY_LEN = tuple(sorted(_ESCAPE_NAMES, key=len, reverse=True))
_LETTER_RUN_RE = re.compile(r"\\(?![A-Za-z]*\[)([A-Za-z]+)")


def space_bare_escapes(text):
    r"""Separate a real escape from the English word the engine would swallow.

    MZ's `Window_Base.obtainEscapeCode` lexes `\` plus a greedy `[A-Za-z]+`, so
    `\GWhat` is read as one unknown code named `GWHAT` and the word is never
    drawn. Japanese never trips this because kana terminates the code -
    translating into English is what CREATES the bug, and it survives every
    text-level check because the word is simply invisible on screen.

    Fix by inserting a space, never by deleting the code, and split after the
    LONGEST real escape name so `\gold` stays `\gold` and `\ac` stays `\ac`."""
    if not isinstance(text, str):
        return text

    def repl(m):
        run = m.group(1)
        low = run.lower()
        for name in _ESCAPE_BY_LEN:
            if low == name:
                return m.group(0)               # the run IS a code
            if low.startswith(name):
                return "\\" + run[:len(name)] + " " + run[len(name):]
        return m.group(0)                       # no known code - leave it

    return _LETTER_RUN_RE.sub(repl, text)


# --------------------------------------------------------------------------
# Single-token enforcement for space-delimited plugin arguments
# --------------------------------------------------------------------------
# Not used by this game (code 356 is absent and MZ 357 args are a JSON object,
# not a space-delimited string), but CBR_EroStatus splits on the FIRST hyphen
# via `A.split(/\-(.*)/, 2)`, so a hyphen is safe anywhere after the prefix and
# no token-joining is needed there either. Kept for the note it carries.
NBSP = "\u00a0"


def to_single_token(text):
    if not isinstance(text, str):
        return text
    return re.sub(r"[ \t]+", NBSP, text.strip())
