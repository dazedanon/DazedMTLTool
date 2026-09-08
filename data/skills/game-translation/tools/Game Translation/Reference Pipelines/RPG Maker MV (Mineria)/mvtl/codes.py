#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
codes.py - RPG Maker MV text primitives for this game.

Responsibilities
----------------
* Japanese detection (three different questions, three different tests).
* Split a 401 line's LEADING presentation-code run (LL_StandingPictureMV
  `\\F[..]` / `\\FF[..]` / `\\AA[..]` / `\\M[..]` / `\\FH[..]`) off as a nametag
  that the model never sees and inject re-prepends byte-exact.
* Mask the remaining inline codes to `⟦n⟧` sentinels and restore them.
* Pre- and post-model text sanitation.

Control-code inventory for THIS game, counted over every 401/102/356 and every
database description (see docs/CENSUS.md):

    \\F[..]   1247   standing picture 1   (ALWAYS a leading run)
    \\FF[..]    15   standing picture 2   (ALWAYS a leading run)
    \\V[..]     67   variable value       (inline CONTENT - mask, pad)
    \\.         17   quarter-second wait  (inline - mask, never pad)
    \\^          7   close without input
    \\G          4   currency unit        (inline CONTENT - mask, pad)
    \\|          2   one-second wait

    Absent: \\C \\I \\N \\P \\{ \\} \\FS \\r %1 -- and there is not one orphan
    backslash in the corpus, so the `\\Helen` failure class cannot arise here.
"""

import re
import unicodedata

# --------------------------------------------------------------------------
# Japanese detection - three tests, deliberately different
# --------------------------------------------------------------------------

# 1. "Does this string contain source-language text at all?" Extraction gate.
#    Fullwidth Latin and halfwidth katakana are IN, because authors use them
#    for UI labels and a kana/kanji-only class is blind to those.
LANG_RE = re.compile(r"[一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９｡-ﾟ々〆〇]")

# 2. "Is this string still untranslated?" Hard validation gate.
#    Three deliberate carve-outs, each of which a plain CJK class gets wrong:
#      * U+3007 〇 and ● are CENSOR MASKS (うん〇 -> sh〇t) and are SUPPOSED to
#        survive. Flagging them sends good lines to a retry that can only
#        reproduce them.
#      * U+3099-U+309C, the voiced/semi-voiced sound marks, are kept as
#        distortion on a slurred moan (`Ogh゛-❤`), so the hiragana range stops
#        at ゖ U+3096 instead of running to U+309F.
#      * A LONE katakana is cosmetic residue an English line can carry
#        (a stray ッ, a ・ separator, a ー dash) and a retry can never clear it.
#        A run of TWO OR MORE katakana letters is a real word that was never
#        translated, so that is the thing worth failing on.
#    ゝゞ ARE included: the skill's exemption for a single iteration mark
#    applies only to a preserved kaomoji, never in general.
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
# a sokuon inside a real katakana word (ベッド) untouched.
# The classes are kana LETTERS only (ぁ-ゖ, ァ-ヺ, ｦ-ﾝ) and deliberately exclude
# the voiced sound marks U+3099-U+309C: `Ogh゛っ❤` has a dakuten immediately
# before the sokuon, and a class that ran to U+309F would read that as "inside
# a kana word" and refuse to convert the one case this exists for.
_STRANDED_SOKUON_RE = re.compile(r"(?<![ぁ-ゖァ-ヺｦ-ﾝ])[っッ]+(?![ぁ-ゖァ-ヺｦ-ﾝ])")

# Small kana the model keeps as "slur decoration" on moans. Deterministic
# transliteration; only applied when NO full-size kana or kanji remains, so a
# real miss still goes back to the model instead of being papered over.
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
    # punctuation or a heart is the cut-off itself and stays - the reference
    # rendering is `Ogh-♡`, not `Ogh♡`.
    out = re.sub(r"-+(?=\s|$)", "", out)
    return out


_JP_QUOTE_MAP = {"「": '"', "」": '"', "『": '"', "』": '"', "｢": '"', "｣": '"'}
_JP_QUOTE_RE = re.compile("[「」『』｢｣]")


def normalize_quotes(s):
    if not isinstance(s, str):
        return s
    return _JP_QUOTE_RE.sub(lambda m: _JP_QUOTE_MAP[m.group()], s)


# --------------------------------------------------------------------------
# Leading presentation-code run (LL_StandingPictureMV)
# --------------------------------------------------------------------------
# The negated class deliberately omits nothing here because this game's inline
# CONTENT codes are \V and \G, neither of which takes the F/AA/M/FH shape.
PORTRAIT_RUN_RE = re.compile(
    r"^\s*((?:\\+(?:F{1,4}|FF{0,3}|AA|M{1,4}|FH)\[[^\]]*\]\s*)+)")

PORTRAIT_ID_RE = re.compile(r"\\+F{1,4}\[([^\]]*)\]")


def split_portrait(text):
    """('\\\\F[C_Fun3]', 'rest of the line') or ('', text).

    Returns the run byte-exact so inject can re-prepend it without ever having
    shown it to the model. Sending it is how a portrait code gets paraphrased;
    deleting it is how the portrait stops appearing."""
    m = PORTRAIT_RUN_RE.match(text)
    if not m:
        return "", text
    return m.group(1), text[m.end():]


def portrait_ids(text):
    return PORTRAIT_ID_RE.findall(text)


# --------------------------------------------------------------------------
# Inline control-code masking
# --------------------------------------------------------------------------
PH_OPEN, PH_CLOSE = "\u27e6", "\u27e7"           # ⟦ ⟧
PH_RE = re.compile(PH_OPEN + r"\s*(\d+)\s*" + PH_CLOSE)

_CODE_RE = re.compile(
    r"""
      \\+ [A-Za-z]+ \[ [^\]]* \]     # \V[66]  \F[C_Fun3]  \AA[F]
    | \\+ [.|!^<>{}$]                # \.  \|  \!  \^  \<  \>  \{  \}  \$
    | \\+ [A-Za-z]                   # \G  \g
    | % \d+                          # printf params (System.json messages)
    """,
    re.VERBOSE,
)

# Sentinels standing for a code that inserts a WORD or a NUMBER at runtime.
# Japanese sets no space around one, so a faithful translation keeps none and
# the player reads "Mana25". English needs the space, and it has to be enforced
# on inject, not only asked for in the prompt.
_WORD_INSERT_RE = re.compile(r"\\+[VvGgNnPp](?:\[\d+\])?$|^%\d+$")

def _needs_pad(ch):
    """A space is added only where the insert is glued to a WORD.

    That is the entire failure mode - `NeroIs that alright?`, `Mana25` - and
    nothing else. Padding against punctuation instead produces `%3 !`, and
    padding between two adjacent sentinels turns `%1\\G` into `100 G`. Both
    neighbours are read from the MASKED text, so the character before a
    sentinel is `\u27e7` rather than the last digit of whatever the previous
    sentinel restored to."""
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

    U+3000 IDEOGRAPHIC SPACE is used two ways in this corpus: as trailing
    line padding (`ひにゃぁぁ！！　`) and as an intra-sentence pacing gap
    (`（鉄格子……？　`). Deleting both runs the phrases together; keeping both
    puts an invisible double-width space in front of the model. Trailing runs
    are dropped, interior ones become one ASCII space."""
    if not isinstance(text, str):
        return text
    lines = []
    for line in text.split("\n"):
        line = line.rstrip("\u3000 \t")
        line = line.replace("\u3000", " ")
        lines.append(line)
    text = "\n".join(lines)
    # Halfwidth-kana spans only: whole-string NFKC would flatten the fullwidth
    # Latin and digits authors use to align columns.
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
    punctuation. That is how a whole-file normaliser once shipped
    `アウレリオ"エステル 大丈夫ですか！"` - Japanese wearing English quotes,
    with no translation behind it, and every unit-level check green."""
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
# Single-token enforcement for space-delimited plugin arguments
# --------------------------------------------------------------------------
# MV's Game_Interpreter.command356 does `this._params[0].split(" ")`, splitting
# on ASCII space ONLY. mplus-1m ships U+00A0 at half width (advance 500), so an
# NBSP renders as a normal space and survives the split intact.
NBSP = "\u00a0"


def to_single_token(text):
    """Make a translation safe as one space-delimited plugin argument."""
    if not isinstance(text, str):
        return text
    return re.sub(r"[ \t]+", NBSP, text.strip())
