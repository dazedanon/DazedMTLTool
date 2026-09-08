#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prompts.py - the system prompt, the glossary block, and the per-kind
instruction templates.

Ownership is enforced (see the skill's glossary reference): the base rules live
here, the game bible lives in `tl/game_prompt.md`, cross-cutting voice lives in
`tl/quirks.md`, and per-character register lives in `glossary.json`. Nothing is
restated across two of them, because copies start fighting.

Cache layout - a block earns a breakpoint only if its bytes are byte-identical
across every request:

    system[0]  base rules + bible + quirks     cached (1h for batch, 5m live)
    system[1]  the FULL character roster       cached, same breakpoint
    system[2]  per-request matched terms       NOT cached, emitted only when
                                               non-empty
    messages   the units                       not cached

The correction to an earlier belief that matters here: a block whose bytes
change per request is never re-read at all and bills the cache-WRITE multiplier
(1.25x at 5m, 2x at 1h) on every single request. So the matched-terms slice
stays uncached - but stays in the SYSTEM role, because demoting it into the
user turn makes the model read approved spellings as suggestions.
"""

import os
import re

from . import store

KIND_LABEL = {
    "text": "dialogue",
    "choice": "menu choice",
    "name": "database name",
    "desc": "database description",
    "affix": "name prefix/suffix",
    "term": "system UI wording",
    "ui": "layout widget label",
    "title": "game title",
    "mapname": "location name",
    "message": "battle/status message",
    "telop": "full-screen telop",
    "strvar": "string variable fragment",
    "sptext": "on-screen coordinate label",
    "codearg": "text inside a control code",
}

# One instruction template per field type. A name field that comes back as a
# sentence corrupts the data file, and one generic "translate this" is why
# patches ship menu buttons reading "The Strongest Equipment Set".
KIND_INSTRUCTION = {
    "text": (
        "Dialogue or narration in the message window. Natural, in-character "
        "English. The speaker is given; write in that character's voice. The "
        "engine word-wraps this box for you, so do NOT insert line breaks the "
        "source does not have - but a line break the source DOES have is the "
        "author's beat and is kept."
    ),
    "choice": (
        "A menu choice the player clicks, drawn in a fixed-width button. "
        "Terse, title-case, ideally 1-4 words, never a sentence and never "
        "final punctuation. Translate the ACTION, not the grammar: a short "
        "verb rendered as the wrong part of speech sends the player the "
        "opposite way (訂正する is 'Re-enter', not 'Correct')."
    ),
    "name": (
        "A database NAME - an item, skill, cast member, status condition, "
        "battle command, element or class - drawn in a narrow list column. "
        "Title case, no final punctuation, keep it short."
    ),
    "desc": (
        "An item or skill description drawn in a help panel. Keep it to the "
        "same number of lines as the source. Every number in the source must "
        "survive exactly."
    ),
    "affix": (
        "A prefix or suffix concatenated onto an item name at run time. "
        "Translate the fragment alone; it is never a sentence."
    ),
    "term": (
        "System UI wording from the engine's own glossary - a button, a "
        "window header, a stat name, a confirmation line. Use the conventional "
        "English an RPG player expects (Item, Skill, Equip, Status, Save, "
        "Options, Attack, Guard, Weapon, Armor, Cancel, Buy, Sell, Max HP, "
        "Max MP, Agility, Luck, Evasion). Terse, no final punctuation. "
        "{0} and {1} are runtime substitutions - keep them."
    ),
    "ui": (
        "A label on a layout widget. Most of these widgets are ONE line and "
        "are CUT at their box edge, so brevity is a correctness requirement, "
        "not a style preference. Terse, title case, no final punctuation."
    ),
    "title": "The game's title or subtitle. No trailing period.",
    "mapname": (
        "A location name. Evocative, title case, 1-4 words. Some of these are "
        "also shown as a banner when the player enters the map."
    ),
    "message": (
        "A battle or status message drawn in the combat log. {0} is a runtime "
        "substitution - keep it and keep its position meaningful in English. "
        "Match the source's tense and exclamation."
    ),
    "telop": (
        "A full-screen telop between scenes - the game's own chapter card. "
        "It is drawn 1280px wide over three lines with the engine wrapping it, "
        "so write it as prose and keep the source's blank lines."
    ),
    "strvar": (
        "A fragment stored into a string variable and printed later, usually "
        "concatenated with other fragments. Translate the fragment on its own "
        "terms and do not add punctuation that would collide with whatever "
        "follows it."
    ),
    "sptext": (
        "A label drawn at a FIXED screen coordinate with no box and no "
        "wrapping. As terse as English allows. Keep a trailing colon if the "
        "source has one, because a number is drawn right after it."
    ),
    "codearg": (
        "The display text INSIDE a control code - either furigana, or a "
        "template where {0} {1} {2} are runtime numbers. Keep every brace "
        "placeholder exactly as written, keep it very short, and never emit a "
        "] character, which would terminate the code early."
    ),
}


BASE_RULES = """\
You are an expert Japanese-to-English localizer working on an adult (R18) RPG \
built in RPG Developer Bakin. You translate dialogue, narration, menu and UI \
text, item names and descriptions into natural, fluent, idiomatic English.

You receive a numbered list of segments from ONE part of the game. Each carries \
its role (dialogue, menu choice, database name, UI label, ...) and, for \
dialogue, the speaker and the scene. A character and term glossary follows - \
read it first and apply ALL of it.

OUTPUT FORMAT
- Translate EVERY numbered segment. Output ONLY a JSON object mapping each \
number, as a string, to its English translation: {"1":"...","2":"..."}.
- No preamble, no notes, no romaji, no commentary, no Japanese in the output.

PROTECTED CODES
- Tokens like ⟦0⟧ and ⟦1⟧ are game control codes (a variable \
value, an item count, a timing pause). Keep every one EXACTLY as written and \
in the same relative position. Never translate, renumber, reorder, add or drop \
one.
- Some sentinels stand for a WORD or a NUMBER the engine inserts at run time. \
Japanese needs no space around one, so the source has none. English does. Put \
a space either side unless the neighbour is an apostrophe, a hyphen or a \
decoration mark.
- NEVER write a backslash of your own. The engine substitutes 541 different \
backslash keywords at run time, so a stray `\\` in your output can silently \
turn into somebody's HP value on screen. The source text you are given \
contains no bare backslashes at all - only the ⟦n⟧ sentinels.
- `{0}` `{1}` `{2}` brace placeholders in a system message are runtime values. \
Keep every one, and keep the order meaningful in English.

NO JAPANESE MAY SURVIVE, NOT EVEN AS DECORATION
- っ and ッ are a glottal catch; ぅ ぉ ぇ ぃ ぁ are \
a vowel dragged out. Render them with Latin letters - a doubled vowel, an -h, \
a hyphen - and delete the kana. `Ogh゛っ♥` is WRONG. `Ogh-♥` \
is right. The dakuten ゛ may stay; it reads as distortion.
- ❤ ♥ ♡ hearts, … ellipses and ～ wave dashes are \
punctuation, not Japanese - keep them where the source has them.
- 〇 and ● are CENSOR MASKS and must survive: うん〇 is \
`sh〇t`, and a name written ●●● stays ●●●.

CHARACTERS, GENDER AND PRONOUNS
- Japanese omits pronouns constantly. Infer the subject from context and the \
glossary. Resolve 彼 / 彼女 / あいつ / こいつ \
/ コイツ against the referenced character's stated gender.
- Verify grammatical person from the source before writing. Second-person \
address (お前 / 君 / あなた) and third-person narration \
get flipped into first-person routinely, and it is always wrong.
- A character who refers to themselves by name keeps that in English.

HONORIFICS
- Preserve -san, -kun, -chan, -sama, -senpai, -sensei, -dono, -tan.
- 兄者 is "brother" and おじさん is "old man" - those \
are not honorifics in English usage and are translated normally.

PARENTHESES ARE INNER MONOLOGUE
- A line wrapped in （ ） is the speaker thinking, not speaking. Keep \
it wrapped in ( ) in English. Do not turn it into spoken dialogue.

ADULT CONTENT - this is an 18+ game
- Translate explicit sexual content directly and vividly, matching the source \
register (clinical / vulgar / colloquial / tender). Do NOT euphemise, soften, \
moralise or add content warnings. Keep dominant speech dominant and begging \
submissive. Non-consensual scenes are translated as written.
- Erotic onomatopoeia (ぴちゃ ぐちゅ じゅぽ \
くちゅ ぬぷ くぱぁ) become evocative English \
sounds. Moans and climax cues (あぁ んっ はぁ \
イく イっちゃう) render expressively: "Aah...", \
"Ngh...", "I'm cumming...", "I'm gonna cum...".

QUALITY
- Prefer natural fluent English over literal gloss. Never merge or split \
segments. Never add quotes, speaker names or notes the source does not have.
- Quantities are load-bearing: 三日後 is "three days later", not \
"in a few days", and a number in the source appears unchanged in the output.
- A full-width space inside a line is a pacing gap, not indentation. Render it \
as a space; do not run the phrases together.
"""

NAME_SYSTEM = """\
You are localizing an adult Japanese RPG. For each Japanese \
CHARACTER NAME below, give the clean, consistent English name that will appear \
in dialogue and name windows, plus your best guess of the character's gender \
(male / female / unknown).

Transliterate a proper name; do not turn it into a common English word based \
only on its sound. Translate an occupational or generic label normally \
(店主 -> Shopkeeper). No honorifics unless part of the name.

Output ONLY a JSON object mapping each number, as a string, to an object \
{"en": "<english name>", "gender": "male|female|unknown"}, e.g. \
{"1":{"en":"Mineria","gender":"female"},"2":{"en":"Shopkeeper","gender":"male"}}.
"""


# --------------------------------------------------------------------------
def load_side_file(store_dir, *names):
    for n in names:
        p = os.path.join(store_dir, n)
        if os.path.exists(p):
            with open(p, encoding="utf-8-sig") as f:
                t = f.read().strip()
            if t:
                return t
    return ""


def stable_prefix(store_dir):
    """The bytes that must be identical on every request for caching to work."""
    parts = [BASE_RULES]
    bible = load_side_file(store_dir, "game_prompt.md", "game_prompt.txt")
    if bible:
        parts.append("GAME BIBLE\n" + bible)
    quirks = load_side_file(store_dir, "quirks.md")
    if quirks:
        parts.append("CROSS-CUTTING VOICE RULES\n" + quirks)
    return "\n\n".join(parts)


# A roster row is a compressed one-liner by design. The glossary FILE holds the
# full evidence - a paragraph of role and a paragraph of register - because a
# human curates it there; the cached block is not the place for the essay.
#
# Measured on this game: 146 rows of untruncated role+register are 12,317
# tokens, which would take the cached prefix from 11.7k to 24k. On a batch most
# requests WRITE that prefix rather than read it, so the roster is the single
# largest avoidable line on the bill. The prose for the main cast is in the
# bible's voice-cues section anyway, which is where the model reads it as
# guidance rather than as a lookup table.
ROSTER_FIELD_CHARS = 150


def _clip(s, n=ROSTER_FIELD_CHARS):
    s = " ".join(str(s).split())
    if len(s) <= n:
        return s
    cut = s.rfind(" ", 0, n)
    return s[:cut if cut > n * 0.6 else n].rstrip(" ,;.") + "..."


def roster_block(glossary, roster_min=0, field_chars=ROSTER_FIELD_CHARS):
    """The character roster. Identical on every request, so it caches.

    `roster_min` drops speakers with fewer than that many lines. The dropped
    tail is NOT unenforced - it reaches the model through `matched_terms` on
    the requests where it actually occurs."""
    lines = []
    for jp, v in glossary.get("names", {}).items():
        en = store.name_en(v)
        if not en:
            continue
        if roster_min and isinstance(v, dict) and (v.get("lines") or 0) < roster_min:
            continue
        meta = []
        if isinstance(v, dict):
            # `note` is human-facing evidence and is deliberately NOT sent.
            for key in ("gender", "role", "register"):
                if v.get(key):
                    meta.append(_clip(v[key], field_chars))
            for a in (v.get("aliases") or []):
                meta.append("aka " + a)
        lines.append("  %s -> %s%s" % (jp, en, ("  (" + "; ".join(meta) + ")") if meta else ""))
    dnt = glossary.get("do_not_translate") or []
    out = []
    if lines:
        out.append("CHARACTERS - use these English names and genders "
                   "consistently:\n" + "\n".join(lines))
    if dnt:
        out.append("NEVER TRANSLATE these strings - something reads them back "
                   "as a key:\n" + "\n".join("  " + d for d in dnt))
    return "\n\n".join(out) if out else ""


# Script-aware term matching. A pure-katakana term gets a negative lookaround
# built from its own class, so キス stops firing inside テキスト. Naive
# substring matching floods the prompt with irrelevant approved terms that cost
# tokens and actively mislead.
_KATA = r"ァ-ヴーｦ-ﾟ"
_HIRA = r"ぁ-ゖ"
_KANJI = r"一-鿿々〆"


def _term_pattern(term):
    if re.fullmatch("[" + _KATA + "]+", term):
        cls = _KATA
    elif re.fullmatch("[" + _HIRA + "]+", term):
        cls = _HIRA
    elif re.fullmatch("[" + _KANJI + "]+", term):
        cls = _KANJI
    else:
        return re.compile(re.escape(term))
    return re.compile("(?<![" + cls + "])" + re.escape(term) + "(?![" + cls + "])")


_TERM_CACHE = {}


def _match_one(jp, payload):
    for part in re.split(r"[,、]", jp):
        part = part.strip()
        if not part:
            continue
        rx = _TERM_CACHE.get(part)
        if rx is None:
            rx = _TERM_CACHE[part] = _term_pattern(part)
        if rx.search(payload):
            return True
    return False


def matched_terms(glossary, payload, roster_min=0):
    """Only the glossary rows that actually occur in THIS request.

    Carries two things: approved terminology, and any character the roster
    budget left out. Without the second half a `roster_min` above 0 would be a
    silent quality regression - a rare speaker's name would be unconstrained on
    exactly the requests where it appears."""
    hits = []
    for jp, en in (glossary.get("terms") or {}).items():
        if en and _match_one(jp, payload):
            hits.append("  %s -> %s" % (jp, en))

    tail = []
    if roster_min:
        for jp, v in (glossary.get("names") or {}).items():
            en = store.name_en(v)
            if not en:
                continue
            if isinstance(v, dict) and (v.get("lines") or 0) >= roster_min:
                continue                       # already in the cached roster
            if not _match_one(jp, payload):
                continue
            meta = []
            if isinstance(v, dict):
                for key in ("gender", "role", "register"):
                    if v.get(key):
                        meta.append(_clip(v[key]))
            tail.append("  %s -> %s%s"
                        % (jp, en, ("  (" + "; ".join(meta) + ")") if meta else ""))

    out = []
    if hits:
        out.append("Approved terminology appearing in this request - use "
                   "exactly these renderings:\n" + "\n".join(hits))
    if tail:
        out.append("Additional characters appearing in this request - use "
                   "exactly these English names:\n" + "\n".join(tail))
    return "\n\n".join(out)
