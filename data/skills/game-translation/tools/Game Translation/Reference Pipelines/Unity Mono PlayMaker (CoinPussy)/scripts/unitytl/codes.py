#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
codes.py — text primitives: Japanese detection, markup masking, validation.

Delivery for this game is a runtime JP->EN dictionary (BepInEx/Harmony on the
`UI.Text.text` / `TMP_Text.text` setters), so the dictionary KEY must be the
game's string byte-for-byte. `raw` is therefore always preserved untouched;
masking only ever applies to `src`, the copy shown to the translator.
"""

import re

# Hiragana, katakana (+ half-width), CJK ideographs, CJK punctuation.
JP_RE = re.compile(r"[぀-ゟ゠-ヿㇰ-ㇿ㐀-䶿"
                   r"一-鿿豈-﫿ｦ-ﾟ々〆〇]")

# "Real" untranslated Japanese: hiragana or kanji. A lone ・ / ッ / ー stranded in
# otherwise-English output is cosmetic residue, never a hard failure — retry could
# never clear it.
#
# 〇 (U+3007) is deliberately NOT here. This game censors obscenities by
# masking a character with it (うん〇, ウ●コ) and names the heroine ●●●,
# so a correct English line keeps the mask ("sh〇t"). Flagging it sends
# good translations to retry, which can only ever produce the same output.
UNTRANSLATED_JP_RE = re.compile(r"[぀-ゟ㐀-䶿一-鿿"
                                r"豈-﫿々〆]")


def has_jp(s) -> bool:
    return isinstance(s, str) and bool(JP_RE.search(s))


def has_untranslated_jp(s) -> bool:
    return isinstance(s, str) and bool(UNTRANSLATED_JP_RE.search(s))


# --------------------------------------------------------------------------
# markup masking
# --------------------------------------------------------------------------
# TextMeshPro rich text (<color=#fff>, </color>, <size=120%>, <sprite=3>, <b>…),
# .NET composite-format holes ({0}), and printf holes. Ordered longest-first so a
# tag is never split by the format rules.
_MARKUP_RE = re.compile(
    r"(<\s*/?\s*[A-Za-z][^<>\n]{0,60}>"      # TMP / Unity rich-text tag
    r"|\{\d+(?::[^}\n]{0,20})?\}"            # {0}, {0:D2}
    r"|%[sdif]"                              # printf hole
    r")"
)

_PH_OPEN, _PH_CLOSE = "⟦", "⟧"      # ⟦ ⟧
_PH_RE = re.compile(_PH_OPEN + r"(\d+)" + _PH_CLOSE)


def mask(text: str):
    """Replace markup with ⟦n⟧ sentinels. Returns (masked, {sentinel: original})."""
    if not isinstance(text, str) or not text:
        return text, {}
    codes = {}
    order = {}

    def repl(m):
        tok = m.group(0)
        if tok not in order:
            order[tok] = len(order)
        i = order[tok]
        ph = f"{_PH_OPEN}{i}{_PH_CLOSE}"
        codes[ph] = tok
        return ph

    return _MARKUP_RE.sub(repl, text), codes


def unmask(text: str, codes: dict) -> str:
    if not codes or not isinstance(text, str):
        return text
    return _PH_RE.sub(lambda m: codes.get(m.group(0), m.group(0)), text)


def placeholder_ids(text: str):
    return {int(x) for x in _PH_RE.findall(text or "")}


def strip_placeholders(text: str) -> str:
    return _PH_RE.sub("", text or "")


def markup_tokens(text: str):
    return _MARKUP_RE.findall(text or "")


# --------------------------------------------------------------------------
# shape helpers used for classification and validation
# --------------------------------------------------------------------------
# An asset/state/animation identifier rather than prose: ASCII-prefixed keys
# (`H_M字ピース`, `S_胸かくし`, `Vo_じゅる4`), or a bare label with a trailing
# index (`悲鳴1`, `フレーム 14`). Used only to CLASSIFY, never to silently drop:
# every rejection is written to the exclusion log with its reason.
IDENTIFIER_RE = re.compile(
    r"^(?:[A-Za-z][A-Za-z0-9]*_[^\s]*"        # H_…, S_…, Vo_…, O_…
    r"|[^\s]{1,12}\s?\d{1,3})$"               # 悲鳴1, フレーム 14
)


def display_lines(s: str) -> list:
    """The lines as displayed: CRLF normalised, trailing terminator dropped."""
    t = (s or "").replace("\r\n", "\n").replace("\r", "\n")
    if t.endswith("\n"):
        t = t[:-1]
    return t.split("\n")


def line_count(s: str) -> int:
    """Displayed line count.

    A trailing terminator is not an extra line. CSV cells here routinely end with a
    stray \\r, and CsvReader drops every \\r before the text is ever shown, so
    counting it produced phantom "2 -> 1" layout warnings on correct translations.
    """
    return len(display_lines(s))
