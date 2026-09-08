"""Japanese detection, control-code masking, and translation validation.

Everything the model ever sees has had its KAG tags and HTML markup replaced by
``U+27E6 n U+27E7`` sentinels. The sentinel multiset is the contract: if it
changes between source and translation the unit is a hard failure and is retried.
"""
from __future__ import annotations

import re
import unicodedata

# Real Japanese script. Deliberately excludes:
#   U+3007  〇  eroge censor mask (うん〇 -> sh〇t is a *correct* localization)
#   U+309B ゛ / U+309C ゜  standalone (han)dakuten, used here as a slur diacritic
#                          on moans (イグ゛) and legitimately survives into EN
#   U+30FB ・ / U+30FC ー  separator and prolonged-sound marks
# and deliberately includes 々 U+3005 and 〆 U+3006, which are real Japanese
# marks that must not survive translation.
JP_CHARS = (
    "々〆"
    "ぁ-ゖゝ-ゟ"
    "ァ-ヺヽ-ヿ"
    "㐀-䶿一-鿿豈-﫿"
    "ｦ-ﾝ"  # halfwidth katakana
)
JP_RE = re.compile(f"[{JP_CHARS}]")

# Fullwidth latin/digits are not Japanese script but are still JP typography.
FULLWIDTH_RE = re.compile(r"[！-～　-〃〈-】〔-〟]")

SENTINEL_OPEN = "⟦"
SENTINEL_CLOSE = "⟧"
SENTINEL_RE = re.compile(f"{SENTINEL_OPEN}(\\d+){SENTINEL_CLOSE}")

# A KAG tag: [name ...params...]. Quoted param values may contain ']'.
TAG_RE = re.compile(r"\[(\w+)((?:[^\]\"']|\"[^\"]*\"|'[^']*')*)\]")
# HTML the scripts embed inside message text.
HTML_RE = re.compile(r"</?[a-zA-Z][^<>]*>|&[a-zA-Z]+;|&#\d+;")

MASK_RE = re.compile(f"{TAG_RE.pattern}|{HTML_RE.pattern}")


def has_jp(text: str) -> bool:
    return bool(JP_RE.search(text))


def has_fullwidth_punct(text: str) -> bool:
    return bool(re.search(r"[！？：；（）、。]", text))


def mask(text: str) -> tuple[str, list[str]]:
    """Replace every KAG tag / HTML token with a numbered sentinel.

    Returns ``(masked_text, tokens)`` where ``tokens[i]`` is the literal text the
    sentinel ``i`` stands for.
    """
    tokens: list[str] = []

    def sub(m: re.Match[str]) -> str:
        tokens.append(m.group(0))
        return f"{SENTINEL_OPEN}{len(tokens) - 1}{SENTINEL_CLOSE}"

    return MASK_RE.sub(sub, text), tokens


def restore(text: str, tokens: list[str]) -> str:
    def sub(m: re.Match[str]) -> str:
        index = int(m.group(1))
        if index >= len(tokens):
            raise ValueError(f"sentinel {index} out of range (have {len(tokens)})")
        return tokens[index]

    return SENTINEL_RE.sub(sub, text)


def split_affixes(masked: str) -> tuple[str, str, str]:
    """Peel a leading and trailing run of bare sentinels off a masked line.

    ``[cm][s_e6]Hello[p]`` masks to ``<0><1>Hello<2>``; the model only needs to
    see ``Hello``. Sentinels that sit *inside* the text (an inline ``[emb]``)
    stay in the middle where their position matters.
    """
    spans = [(m.start(), m.end()) for m in SENTINEL_RE.finditer(masked)]

    lead = 0
    for start, end in spans:
        if start != lead:
            break
        lead = end

    tail = len(masked)
    for start, end in reversed(spans):
        if end != tail or start < lead:
            break
        tail = start

    return masked[:lead], masked[lead:tail], masked[tail:]


def sentinels(text: str) -> list[str]:
    return sorted(SENTINEL_RE.findall(text))


def placeholders_ok(src: str, dst: str) -> bool:
    return sentinels(src) == sentinels(dst)


def stray_sentinel(text: str) -> str:
    """A sentinel bracket that is not part of a well-formed ``\u27e6n\u27e7``.

    Comparing the sentinel *sets* is not enough on its own: a reply that drops
    one bracket, or invents a named one like ``\u27e6item\u27e7``, leaves the set
    unchanged and ships the brackets to the screen.
    """
    rest = SENTINEL_RE.sub("", text)
    for ch in (SENTINEL_OPEN, SENTINEL_CLOSE):
        if ch in rest:
            start = max(0, rest.index(ch) - 12)
            return rest[start:rest.index(ch) + 13]
    return ""


def residual_jp(text: str) -> list[str]:
    """Japanese characters that survived translation, deduped, in order."""
    seen: list[str] = []
    for ch in text:
        if JP_RE.match(ch) and ch not in seen:
            seen.append(ch)
    return seen


# Fullwidth punctuation that is purely typographic and can be converted with no
# model call at all. Fullwidth space U+3000 is NOT here: inside a moan it is a
# pacing gap between gasps, and collapsing it runs the phrases together.
PUNCT_MAP = {
    "！": "!",   # ！
    "？": "?",   # ？
    "。": ".",   # 。
    "、": ", ",  # 、
    "，": ", ",  # ，
    "：": ": ",  # ：
    "；": "; ",  # ；
    "（": " (",  # （
    "）": ") ",  # ）
    "「": "“",  # 「
    "」": "”",  # 」
    "『": "“",  # 『
    "』": "”",  # 』
}


def convert_punct(text: str) -> str:
    """Mechanical fullwidth->ASCII punctuation, then tidy the spacing.

    Leading and trailing whitespace is authored indentation in these scripts and
    is put back untouched; only the spacing the mapping itself introduces (the
    ``", "`` after a comma, say) is normalised.
    """
    head = text[:len(text) - len(text.lstrip(" \t　"))]
    tail = text[len(text.rstrip(" \t　")):]
    core = text[len(head):len(text) - len(tail)]
    out = "".join(PUNCT_MAP.get(ch, ch) for ch in core)
    out = re.sub(r"[ \t]+([,.;:!?])", r"\1", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    return head + out.strip(" ") + tail


#: U+FF3F FULLWIDTH LOW LINE is this author's trailing-off marker: a drawn-out
#: silence at the end of a beat, used where a Western script would put an
#: ellipsis. It is not a Japanese character, so neither the extraction nor the
#: residual-Japanese check objects to it surviving translation, and it reaches
#: the screen looking like a fill-in-the-blank instead:
#:
#:     You'd better rest quietly in your room＿＿＿ hm?
#:
#: The author writes it in ASCII too - ``翌日____``, ``何時間か経った頃_____`` -
#: and those runs mean exactly the same thing, so they convert the same way.
#:
#: One block in rankou.ks uses it for something else - separating a speaker's
#: name from their line, the way a colon does. That use is told apart by the run
#: of spaces that always follows it, and becomes a colon.
LOWLINE = "＿"
SPEAKER_LOWLINE_RE = re.compile(f"{LOWLINE}([ 　]{{2,}})")
#: any spaces in front of the run go with it, so "pleasure ＿＿＿" does not
#: come out as "pleasure ..."
PAUSE_LOWLINE_RE = re.compile(f"[ 　]*(?:{LOWLINE}+|_{{2,}})")


def convert_lowline(text: str) -> str:
    """Trailing-off low lines to an ellipsis; the speaker form to a colon.

    ASCII ``__`` is folded in too: the model romanised the marker that way in a
    few replies rather than carrying it across.
    """
    out = SPEAKER_LOWLINE_RE.sub(lambda m: ":" + m.group(1), text)
    out = PAUSE_LOWLINE_RE.sub("...", out)
    # the marker often sat where a comma would have gone, and an ellipsis
    # already does that job. Only a comma - a following period is
    # indistinguishable from one of the author's own longer runs.
    return re.sub(r"(?<!\.)\.\.\.,", "...", out)


#: ``parseScenario`` dispatches on the first character of the *trimmed* line:
#: ``;`` comment, ``*`` label, ``@`` bare tag, ``#`` chara_ptext, and ``_``
#: which it strips as KAG's literal-leading-space marker. A translation that
#: opens a line with one of these stops being dialogue: ボロンッ came back as
#: ``*fwip*`` and the parser filed it as a label named ``fwip*[p``, so the sound
#: effect never appeared at all.
LINE_SPECIAL = ";*@#_"


def normalize(text: str) -> str:
    """Key normalisation for dictionary lookups: strip BOM and edge whitespace."""
    return text.replace("﻿", "").strip()


def display_width(text: str) -> int:
    """Terminal/report width in cells (CJK counts as 2). Not a pixel measure."""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


# Small kana that survive translation are a *sound*, not a word: a glottal catch
# or a dragged-out vowel hung on the end of a moan. The model gets most of them
# but leaves a handful stranded, and they are mechanical to convert - no reason
# to spend another request on it.
SMALL_KANA = {
    "ぁ": "a", "ァ": "a", "ぃ": "i", "ィ": "i", "ぅ": "u", "ゥ": "u",
    "ぇ": "e", "ェ": "e", "ぉ": "o", "ォ": "o",
    "ゃ": "ya", "ャ": "ya", "ゅ": "yu", "ュ": "yu", "ょ": "yo", "ョ": "yo",
    "ゎ": "wa", "ヮ": "wa",
}
SOKUON = "っッ"

_LETTER_RE = re.compile(r"[A-Za-z]")


def romanise_stranded_kana(text: str) -> str:
    """Convert leftover small kana to Latin. Returns ``text`` unchanged if any
    *full-size* kana or kanji is present - that is a real miss, not residue, and
    must go back to the model rather than be papered over."""
    leftovers = residual_jp(text)
    if any(ch not in SMALL_KANA and ch not in SOKUON for ch in leftovers):
        return text

    out: list[str] = []
    for ch in text:
        if ch in SMALL_KANA:
            out.append(SMALL_KANA[ch])
        elif ch in SOKUON:
            # a glottal catch only reads as one when it closes a word; between
            # decorations it is noise and simply goes
            previous = next((c for c in reversed(out) if c.strip()), "")
            out.append("-" if _LETTER_RE.match(previous) else "")
        else:
            out.append(ch)
    return re.sub(r"-{2,}", "-", "".join(out))


# TyranoScript's tag parser deletes every literal space inside a quoted attribute
# value. From kag.parser.js, makeTag():
#
#     if (flag_quot_c != "") { "="==c && (c="#"); " "==c && (c=""); tmp_str+=c }
#
# It does that because it then splits the whole tag on spaces to separate the
# parameters; "=" is swapped for "#" and restored afterwards, but the space is
# simply dropped and never comes back. Japanese never noticed - it does not use
# spaces. English comes out as "Thistitlecontainscross-sectionviews."
#
# Verified against the game's own parser: U+00A0 passes through untouched, and
# renders as an ordinary space in every consumer - .html(), .text() and
# document.title alike. The `&nbsp;` entity also survives the parser but only
# renders in HTML contexts, and the game's own author used it as a workaround in
# macro.ks. U+3000 survives too but is double width.
NBSP = " "


def protect_spaces(text: str) -> str:
    """Make spaces survive the KAG tag parser. Only for quoted attribute values."""
    return text.replace(" ", NBSP)


def unprotect_spaces(text: str) -> str:
    return text.replace(NBSP, " ")


# Some inline tags expand to a *word* at run time rather than doing something to
# the display: [name2] becomes the player's name, [ig_tntn] picks a lewd noun out
# of a randomised array, [emb] evaluates any expression. Japanese needs no space
# around an inserted word, so the source has none and a faithful translation
# keeps none - which is how "NeroIs that alright?" reaches the screen.
#
# Everything else that arrives as a sentinel ([p], [r], [cm], the face-change
# macros) must NOT gain spaces, so the emitters are identified from the project's
# own macro definitions rather than guessed.
WORD_RE = re.compile(r"[0-9A-Za-z]")
#: sentence punctuation that wants a following space before an inserted word
CLOSE_PUNCT = ".?!,;:"

MACRO_RE = re.compile(r'\[macro\s+name="?([\w]+)"?\](.*?)\[endmacro\]', re.S)
#: A tag's quoted value can itself contain "]" - the lewd-word macros index with
#: [emb exp="f.ingo_tinko[f.ingo_LV][tf.rd]"] - so these have to be matched with
#: the quote-aware TAG_RE, not a naive [^\]]* run.
_EMITTER_BODY_SKIP = ("getrand", "eval", "if", "endif")


def inline_emitters(macro_source: str) -> set[str]:
    """Tags that expand to a word inline: ``emb`` plus every macro whose whole
    body is one ``[emb]`` (a leading ``[getrand]`` is just picking the index).

    A macro that also carries ``[cm]`` or ``[p]`` emits a whole line, not a word,
    and is deliberately left out - ``like_lv1`` is the example here.
    """
    found = {"emb"}
    for name, body in MACRO_RE.findall(macro_source):
        tags = [m for m in TAG_RE.finditer(body)]
        kept = [m.group(1) for m in tags if m.group(1) not in _EMITTER_BODY_SKIP]
        # whatever is left outside the tags must be nothing but whitespace, or
        # the macro emits literal text of its own and is not a bare word insert
        literal = TAG_RE.sub("", body).strip()
        if kept == ["emb"] and not literal:
            found.add(name)
    return found


def tag_name(token: str) -> str:
    m = re.match(r"\[(\w+)", token)
    return m.group(1) if m else ""


def space_around_inserts(text: str, is_emitter) -> str:
    """Put a space either side of an inserted word where English needs one.

    ``is_emitter(index)`` says whether sentinel ``index`` expands to a word.
    Nothing is inserted next to an apostrophe (possessives), a hyphen, a heart or
    another sentinel - only next to letters, digits, and sentence punctuation.
    """
    out: list[str] = []
    position = 0
    for match in SENTINEL_RE.finditer(text):
        out.append(text[position:match.start()])
        if is_emitter(int(match.group(1))):
            before = out[-1][-1:] if out and out[-1] else ""
            if before and (WORD_RE.match(before) or before in CLOSE_PUNCT):
                out.append(" ")
            out.append(match.group(0))
            after = text[match.end():match.end() + 1]
            if after and WORD_RE.match(after):
                out.append(" ")
        else:
            out.append(match.group(0))
        position = match.end()
    out.append(text[position:])
    return "".join(out)
