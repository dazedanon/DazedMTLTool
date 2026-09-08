#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
codes.py - RPG Maker VX Ace text primitives for this game.

Responsibilities
----------------
* Japanese detection - three different questions, three different tests.
* Split the `\NAME[...]` name-plate tag off a message so the model never sees
  it and inject re-prepends it byte-exact.
* Mask the remaining inline codes to `⟦n⟧` sentinels and restore them, padding
  the ones that insert a word.
* Sanitise the Japanese shown to the model, and the English written back.

THE ACE ESCAPE SET
------------------
`Window_Base#convert_escape_characters` (the game's copy is stock) rewrites
every `\` to `\e` first, then substitutes:

    \V[n]  variable value        \N[n]  actor name      \P[n]  party member
    \G     currency unit

and `process_escape_character` then consumes, at draw time:

    \C[n]  colour   \I[n]  icon    \{ \}  font bigger / smaller
    \$     open the gold window    \.  \|  waits
    \!     wait for input          \>  \<  instant on / off    \^  no input wait

This game's own `メッセージウィンドウ` script adds `\NAME[...]`, which is
consumed in `convert_escape_characters` BEFORE drawing, so it costs no width
and can sit anywhere in the line.

Of that set the corpus uses only `\NAME[..]` (11,484), `\G` (19) and `\$` (11).
The rest are masked anyway: a hand edit or a model that invents one must not be
able to corrupt a file silently.
"""

import re
import unicodedata

# --------------------------------------------------------------------------
# Japanese detection - three tests, deliberately different
# --------------------------------------------------------------------------

# 1. "Does this string contain source-language text at all?" The extraction
#    gate. Fullwidth Latin and halfwidth katakana are IN: this game writes
#    `ＯＰ`, `Ｇ` and `１０年` with fullwidth characters, and a kana/kanji-only
#    class is blind to them.
LANG_RE = re.compile(r"[一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９｡-ﾟ々〆〇]")

# 2. "Is this string still untranslated?" The hard validation gate, with the
#    three carve-outs a plain CJK class gets wrong:
#      * 〇 and ● are CENSOR MASKS (`うん〇` -> `sh〇t`) and are SUPPOSED to
#        survive; flagging them sends good lines into a retry loop that can
#        only reproduce them.
#      * U+3099-U+309C, the voiced sound marks, are kept as distortion on a
#        slurred moan (`Agh゛-♡`), so the hiragana class stops at ゖ U+3096.
#      * a LONE katakana is cosmetic residue an English line can carry (a stray
#        ッ, a ・ separator, a ー dash); a run of TWO OR MORE is a real word
#        that was never translated, and that is the thing worth failing on.
UNTRANSLATED_RE = re.compile(
    r"[ぁ-ゖゝゞ㐀-䶿一-鿿豈-﫿々〆]"
    r"|[ァ-ヺ]{2,}")

# 3. "Is there any CJK left at all?" Soft review only.
ANY_JP_RE = re.compile(r"[぀-ゟ゠-ヿㇰ-ㇿ㐀-䶿一-鿿豈-﫿ｦ-ﾝ々〆〇]")


def has_jp(s):
    return isinstance(s, str) and bool(LANG_RE.search(s))


def has_untranslated_jp(s):
    return isinstance(s, str) and bool(UNTRANSLATED_RE.search(s))


# A sokuon marooned among non-kana: `Nhagiッ!` -> `Nhagi-!`. The lookarounds
# keep a sokuon inside a real katakana word (ベッド) untouched, and the classes
# are kana LETTERS only so a preceding dakuten does not read as "inside a word".
_STRANDED_SOKUON_RE = re.compile(r"(?<![ぁ-ゖァ-ヺｦ-ﾝ])[っッ]+(?![ぁ-ゖァ-ヺｦ-ﾝ])")

SMALL_KANA = {
    "ぁ": "a", "ぃ": "i", "ぅ": "u", "ぇ": "e", "ぉ": "o",
    "ァ": "a", "ィ": "i", "ゥ": "u", "ェ": "e", "ォ": "o",
    "ゃ": "ya", "ゅ": "yu", "ょ": "yo", "ャ": "ya", "ュ": "yu", "ョ": "yo",
    "ゎ": "wa", "ヮ": "wa",
}
_FULLSIZE_KANA_RE = re.compile(r"[ぁ-んァ-ン]")


def strip_residual_kana(s):
    """Deterministic cleanup of kana the model left as decoration on a moan.

    Bails out unchanged if any FULL-SIZE kana or kanji survives once the small
    kana and sokuon are removed: that is a real translation miss and belongs
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
    # rendering is `Agh-♡`, not `Agh♡`.
    return re.sub(r"-+(?=\s|$)", "", out)


_JP_QUOTE_MAP = {"「": '"', "」": '"', "『": '"', "』": '"', "｢": '"', "｣": '"'}
_JP_QUOTE_RE = re.compile("[「」『』｢｣]")


def normalize_quotes(s):
    return _JP_QUOTE_RE.sub(lambda m: _JP_QUOTE_MAP[m.group()], s) \
        if isinstance(s, str) else s


# --------------------------------------------------------------------------
# The name-plate tag
# --------------------------------------------------------------------------
# `/\eNAME\[(.*?)\]/i` in the game's own script, so the match is
# case-insensitive and non-greedy, and it may appear anywhere in the text.
# In this corpus it always opens the first line of a message; the regex does
# not assume that, because a hand edit could move it and a tag left in the body
# would be shown to the model as text.
NAME_TAG_RE = re.compile(r"\\+NAME\[([^\]]*)\]", re.I)
LEADING_NAME_RE = re.compile(r"^\s*(\\+NAME\[[^\]]*\])", re.I)


def split_nametag(text):
    """('\\NAME[エリス]', 'the rest') or ('', text), byte-exact.

    Returned verbatim so inject can re-prepend it without ever having shown it
    to the model. Sending it is how a speaker tag gets paraphrased into the
    dialogue; dropping it is how the name plate stops appearing."""
    m = LEADING_NAME_RE.match(text)
    if not m:
        return "", text
    return m.group(1), text[m.end():]


def nametag_name(tag):
    m = NAME_TAG_RE.search(tag or "")
    return m.group(1) if m else ""


def name_is_safe(en_name):
    r"""'' if the name can go inside `\NAME[...]`, else why not.

    The engine's own regex is `/\eNAME\[(.*?)\]/i` - NON-GREEDY - so a `]`
    inside the name closes the tag early: `\NAME[Eris [the Knight]]Hello`
    draws the plate as `Eris [the Knight` and prints `]Hello` into the message.
    A backslash starts a new escape and a newline splits the line. Proven
    against the shipped script by `tools/trace_parser.py` probe 5."""
    if not en_name:
        return "empty"
    if "]" in en_name or "[" in en_name:
        return "contains a bracket, which closes the tag early"
    if "\\" in en_name:
        return "contains a backslash, which starts another escape"
    if "\n" in en_name or "\r" in en_name:
        return "contains a newline"
    return ""


def retag(tag, en_name):
    """Rewrite a captured tag with the English name, keeping its exact form.

    Returns the tag UNCHANGED when the name cannot safely live inside it -
    a Japanese plate is a cosmetic defect, a broken tag is a corrupted line."""
    if not tag or not en_name or name_is_safe(en_name):
        return tag
    return NAME_TAG_RE.sub(lambda m: m.group(0)[:m.start(1) - m.start(0)]
                           + en_name + "]", tag, count=1)


# --------------------------------------------------------------------------
# Inline control-code masking
# --------------------------------------------------------------------------
PH_OPEN, PH_CLOSE = "\u27e6", "\u27e7"           # ⟦ ⟧
PH_RE = re.compile(PH_OPEN + r"\s*(\d+)\s*" + PH_CLOSE)

_CODE_RE = re.compile(
    r"""
      \\+ [A-Za-z]+ \[ [^\]]* \]     # \NAME[エリス]  \V[12]  \C[2]  \I[64]
    | \\+ [.|!^<>{}$]                # \.  \|  \!  \^  \<  \>  \{  \}  \$
    | \\+ [A-Za-z]                   # \G  \\
    | % \d+                          # printf slots in Vocab-style templates
    """,
    re.VERBOSE,
)

# Sentinels standing for a code that inserts a WORD or a NUMBER at run time.
# Japanese sets no space around one, so a faithful translation keeps none and
# the player reads `Mana25` or `ErisIs that alright?`. English needs the space,
# and it is enforced here rather than only asked for in the prompt.
_WORD_INSERT_RE = re.compile(r"\\+[VvNnPpGg](?:\[\d+\])?$|^%\d+$")


def is_word_insert(code):
    return bool(_WORD_INSERT_RE.search(code))


def _needs_pad(ch):
    """A space goes in only where the insert is glued to a WORD.

    That is the whole failure mode. Padding against punctuation produces
    `%3 !`, and padding between two adjacent sentinels turns `%1\\G` into
    `100 G`. Both neighbours are read from the MASKED text, so the character
    before a sentinel is `⟧` rather than the last digit of whatever the
    previous sentinel restores to."""
    return bool(ch) and ch.isalnum() and ord(ch) < 0x3000


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

    Tolerates whitespace the model puts inside the brackets. A sentinel the
    model dropped simply stays absent (validation catches it); one it invented
    restores to nothing. Pass `pad_inserts=False` when restoring purely to
    compare code multisets, so the two sides are measured identically."""
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
    from collections import Counter
    return Counter(m.group(0) for m in _CODE_RE.finditer(text))


# --------------------------------------------------------------------------
# Source sanitation (what the model is shown)
# --------------------------------------------------------------------------
_QUOTE_FOLD = str.maketrans({
    "\u201c": "'", "\u201d": "'", "\uff02": "'",
    "\u2018": "'", "\u2019": "'", "\u201b": "'",
    "\u02bc": "'", "\uff07": "'",
})


def clean_source(text):
    """Normalise the Japanese shown to the model without changing meaning.

    U+3000 IDEOGRAPHIC SPACE is used two ways in this corpus: as the indent
    that opens a continuation line (`　向かわせたエクソシストは、…`) and as an
    intra-sentence pacing gap (`エリスちゃん、どうしたんだい！？　ずいぶん…`).
    A leading run is dropped, an interior one becomes one ASCII space. Deleting
    both would run the phrases together; keeping both puts an invisible
    double-width character in front of the model."""
    if not isinstance(text, str):
        return text
    lines = []
    for line in text.split("\n"):
        line = line.rstrip("\u3000 \t").lstrip("\u3000")
        line = line.replace("\u3000", " ")
        lines.append(line)
    text = "\n".join(lines)
    # Halfwidth-kana spans only: a whole-string NFKC would flatten the
    # fullwidth Latin and digits the author uses on purpose (`ＯＰ`, `１０年`).
    text = re.sub(r"[｡-ﾟ]+",
                  lambda m: unicodedata.normalize("NFKC", m.group(0)), text)
    return text.translate(_QUOTE_FOLD)


# --------------------------------------------------------------------------
# Translation sanitation (what goes into the file)
# --------------------------------------------------------------------------
_POST = [
    (re.compile(r"\.\.\.(?:。)+"), "..."),
    (re.compile(r"(?:。){2,}"), "..."),
    # Japanese sets no space after ！ / ？, so the model omits it in English too.
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
    text = text.replace("！", "!").replace("？", "?").replace("、", ",")
    text = re.sub(r"。(?=\s|$)", ".", text)
    for rx, rep in _POST:
        text = rx.sub(rep, text)
    return "\n".join(l.rstrip() for l in text.split("\n"))
