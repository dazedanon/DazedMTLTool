#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
codes.py — RPG Maker MV/MZ text handling primitives.

Responsibilities
----------------
- Detect Japanese text.
- Parse the speaker out of a message block (\\kw[name] / \\nw[name] name-window
  codes used by this game, plus \\n<name> and 【name】 fallbacks).
- Mask inline control codes (\\i[..], \\c[..], \\v[..], \\ow[..], \\r[a,b], pause
  codes …) behind sentinel placeholders so the translator never sees or mangles
  them, then restore them afterwards.
- Word-wrap translated text to a target width while ignoring the (zero-width)
  control codes — adapted from the reference util/dazedwrap.py.

These functions are intentionally engine-data agnostic: they operate on plain
strings.  extract.py / inject.py decide *where* the strings come from.
"""

import re
import unicodedata

# --------------------------------------------------------------------------
# Japanese detection
# --------------------------------------------------------------------------
# Hiragana, Katakana (+ half-width), CJK ideographs, CJK punctuation.
JP_RE = re.compile(
    r"[぀-ゟ゠-ヿㇰ-ㇿ㐀-䶿一-鿿"
    r"豈-﫿ｦ-ﾝ々〆〇]"
)


def has_jp(s) -> bool:
    return isinstance(s, str) and bool(JP_RE.search(s))


# "Real" untranslated Japanese = hiragana or kanji. A left-in JP sentence always
# contains one of these; whereas a lone katakana separator (・), sound-cutoff (ッ),
# or prolongation mark (ー) is cosmetic residue inside otherwise-English text and
# must NOT count as a hard "residual Japanese" failure (retry can never clear it).
UNTRANSLATED_JP_RE = re.compile(r"[぀-ゟ㐀-䶿一-鿿豈-﫿々〆〇]")

# Cosmetic kana the model leaves in romanized onomatopoeia/moans ("Nhagiッ!",
# "…………ッッッ!!"): a run of sokuon (っ/ッ) STRANDED among non-kana (Latin/symbols).
# The lookarounds ensure we never touch a sokuon inside a real katakana word
# (e.g. ベッド), only ones marooned in otherwise-English text.
_RESIDUAL_SOKUON_RE = re.compile(r"(?<![぀-ゟ゠-ヿｦ-ﾟ])[っッ]+(?![぀-ゟ゠-ヿｦ-ﾟ])")


def has_untranslated_jp(s) -> bool:
    return isinstance(s, str) and bool(UNTRANSLATED_JP_RE.search(s))


def strip_residual_kana(s: str) -> str:
    """Remove stranded sokuon (っ/ッ) left in romanized text. Safe on English
    output; leaves valid separators (・) and real katakana words intact."""
    return _RESIDUAL_SOKUON_RE.sub("", s) if isinstance(s, str) else s


# Japanese corner-bracket quotes left in finished English → straight double
# quotes (standard localization). Half-width ｢｣ are handled in clean_source;
# 【】 are intentionally NOT touched (they're used for name-box/UI templates).
_JP_QUOTE_MAP = {"「": '"', "」": '"', "『": '"', "』": '"'}
_JP_QUOTE_RE = re.compile("[「」『』]")


def normalize_quotes(s: str) -> str:
    return _JP_QUOTE_RE.sub(lambda m: _JP_QUOTE_MAP[m.group()], s) if isinstance(s, str) else s


# --------------------------------------------------------------------------
# Speaker (name-window) codes
# --------------------------------------------------------------------------
# Leading speaker codes for THIS game: \kw[name] (keep name window) and
# \nw[name] (name window).  The bracket content is the speaker's name.
#   \kw[クロア]  \nw[クロア＆あろま]
_SPEAKER_LEAD_RE = re.compile(r"^\s*\\+([knKN][wW])\[([^\]]*)\]")

# \n<name> style (a different engine convention) — kept as a fallback.
_SPEAKER_ANGLE_RE = re.compile(r"^\s*(\\+[nN][wWcC]?<)([^>]*)(>)")

# 【name】 at the very start, whole-line bracket or followed by dialogue.
_SPEAKER_BRACKET_RE = re.compile(r"^\s*【([^】]{1,30})】")


def parse_speaker(text: str):
    """Return (speaker_name, prefix_template, remainder).

    prefix_template is the original speaker markup with the name replaced by the
    sentinel ``{name}`` so inject can rebuild it with the translated name, e.g.
    ``"\\kw[{name}]"``.  If no speaker is found returns ("", "", text).
    """
    m = _SPEAKER_LEAD_RE.match(text)
    if m:
        code = m.group(1)
        name = m.group(2)
        # Preserve the exact backslash run the original used.
        lead = text[m.start():m.start() + (m.end() - m.start())]
        prefix = lead.replace("[" + name + "]", "[{name}]", 1)
        return name, prefix, text[m.end():]

    m = _SPEAKER_ANGLE_RE.match(text)
    if m:
        name = m.group(2)
        prefix = m.group(1) + "{name}" + m.group(3)
        return name, prefix, text[m.end():]

    m = _SPEAKER_BRACKET_RE.match(text)
    if m:
        name = m.group(1).strip()
        return name, "【{name}】", text[m.end():]

    return "", "", text


# --------------------------------------------------------------------------
# Inline control-code masking
# --------------------------------------------------------------------------
# Order matters: match bracketed codes first (\i[327], \r[a,b], \oc[black]),
# then doubled symbol/format codes, then bare single-letter codes.
_CODE_RE = re.compile(
    r"""
    \\+ [a-zA-Z]+ \[ [^\]]* \]        # \i[327] \c[2] \v[1] \n[4] \r[a,b] \ow[4] \oc[black] \fs[20] \px[1] \sw[1]
  | \\+ [.|!^<>{}$]                   # pause / format symbols: \. \| \! \^ \< \> \{ \} \$
  | \\+ [a-zA-Z]                      # bare letter codes: \g \G \\ etc.
  | % \d+                             # RPG Maker printf params in system messages: %1 %2
    """,
    re.VERBOSE,
)

# Sentinel brackets — mathematical white square brackets. Distinct, never appear
# in source/target text, and treated as opaque markup by the model.
_PH_OPEN, _PH_CLOSE = "⟦", "⟧"
_PH_RE = re.compile(_PH_OPEN + r"\s*(\d+)\s*" + _PH_CLOSE)


def mask_codes(text: str):
    """Replace inline control codes with ``⟦k⟧`` placeholders.

    Returns (masked_text, code_map) where code_map maps the placeholder string
    to the original code substring.
    """
    code_map = {}
    counter = [0]

    def repl(m):
        k = counter[0]
        counter[0] += 1
        ph = f"{_PH_OPEN}{k}{_PH_CLOSE}"
        code_map[ph] = m.group(0)
        return ph

    return _CODE_RE.sub(repl, text), code_map


def unmask_codes(text: str, code_map: dict) -> str:
    """Restore ``⟦k⟧`` placeholders to their original control codes.

    Tolerant of whitespace the model may insert inside the brackets. Unknown
    placeholders are dropped; codes the model dropped simply stay absent.
    """
    if not code_map:
        return text

    def repl(m):
        ph = f"{_PH_OPEN}{m.group(1)}{_PH_CLOSE}"
        return code_map.get(ph, "")

    return _PH_RE.sub(repl, text)


def placeholder_ids(text: str):
    """Set of placeholder indices present in text (for integrity checks)."""
    return {int(x) for x in _PH_RE.findall(text)}


# --------------------------------------------------------------------------
# Source cleanup (cosmetic, applied to the JP shown to the model)
# --------------------------------------------------------------------------
def clean_source(text: str) -> str:
    """Light normalisation of the JP text shown to the model.

    - full-width indentation space (　) → nothing
    - 「」 → straight quotes (more natural for EN output)
    Does NOT touch placeholders or meaning.
    """
    text = text.replace("　", "")
    text = text.replace("｢", '"').replace("｣", '"')  # 「 」
    return text


# --------------------------------------------------------------------------
# Word wrap (control-code aware) — adapted from util/dazedwrap.py
# --------------------------------------------------------------------------
def _cell_width(ch: str) -> int:
    """Monospace cell width of one char. M+ 1m (and RPG Maker MZ's renderer) draw
    East-Asian Wide/Fullwidth AND Ambiguous glyphs (CJK, kana, and punctuation
    like …, ♡, 。, ッ, ※) at full width = 2 cells; everything else = 1 cell."""
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F", "A") else 1


def _visible_len(text: str) -> int:
    """Rendered width in monospace CELLS, ignoring placeholders and control codes
    (full-width glyphs count as 2). This is what wrap_text budgets against."""
    t = _PH_RE.sub("", text)
    t = re.sub(r"\\+[a-zA-Z]+\[[^\]]*\]", "", t)
    t = re.sub(r"\\+[a-zA-Z.|!^<>{}$]", "", t)
    return sum(_cell_width(c) for c in t)


# Atom = one indivisible rendering unit: a ⟦n⟧ placeholder, a control code, or a
# single character. Used to hard-break a token that alone exceeds the wrap width
# (e.g. a long unbroken moan "Ahhhh♡ahhh♡…") WITHOUT splitting a code/placeholder.
_ATOM_RE = re.compile(r"⟦\d+⟧|\\+[a-zA-Z]+\[[^\]]*\]|\\+[a-zA-Z.|!^<>{}$]|.", re.S)


def _break_long(word: str, width: int):
    """Split one over-long word into <=width-cell pieces on atom boundaries."""
    lines, cur, cl = [], [], 0
    for a in _ATOM_RE.findall(word):
        w = _visible_len(a)
        if cur and cl + w > width:
            lines.append("".join(cur))
            cur, cl = [a], w
        else:
            cur.append(a)
            cl += w
    if cur:
        lines.append("".join(cur))
    return lines or [word]


def wrap_text(text: str, width: int) -> str:
    """Greedy word-wrap to `width` monospace CELLS, preserving hard \\n\\n breaks.
    A single word wider than `width` is hard-broken so nothing overflows."""
    if not text or width <= 0:
        return text or ""
    out_segments = []
    for segment in re.split(r"\n\n", text):
        lines, cur, cur_len = [], [], 0
        for word in segment.split():
            wl = _visible_len(word)
            if wl > width:                       # token alone exceeds the box -> hard-break
                if cur:
                    lines.append(" ".join(cur))
                    cur, cur_len = [], 0
                pieces = _break_long(word, width)
                lines.extend(pieces[:-1])
                cur, cur_len = [pieces[-1]], _visible_len(pieces[-1])
            elif cur and cur_len + wl + len(cur) > width:
                lines.append(" ".join(cur))
                cur, cur_len = [word], wl
            else:
                cur.append(word)
                cur_len += wl
        if cur:
            lines.append(" ".join(cur))
        out_segments.append("\n".join(lines))
    return "\n\n".join(out_segments)
