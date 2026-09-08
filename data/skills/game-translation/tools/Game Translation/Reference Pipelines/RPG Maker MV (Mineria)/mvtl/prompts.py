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
    "name": "item/equipment name",
    "desc": "item/equipment description",
    "term": "UI label",
    "type": "type label",
    "title": "game title",
    "currency": "currency unit",
    "mapname": "location name banner",
    "message": "battle/menu message template",
    "note": "note tag",
    "ptext": "on-screen popup text",
    "plugin": "plugin UI label",
}

# One instruction template per field type. A name field that comes back as a
# sentence corrupts the data file, and one generic "translate this" is why
# patches ship menu buttons reading "The Strongest Equipment Set".
KIND_INSTRUCTION = {
    "text": (
        "Dialogue and narration. Natural, in-character English. Keep the "
        "line's emotional register exactly - this game swings between comedy, "
        "haughty demon-lord bluster and explicit non-consensual erotica, and "
        "the register is the joke."
    ),
    "choice": (
        "A menu choice the player clicks. Terse, title-case, ideally 1-4 "
        "words, never a sentence and never final punctuation. Translate the "
        "ACTION, not the grammar: a short verb rendered as the wrong part of "
        "speech sends the player the opposite way."
    ),
    "name": (
        "An item / weapon / armour NAME as it appears in the inventory list. "
        "Title case, no final punctuation, keep it under about 20 characters."
    ),
    "desc": (
        "An item description drawn in a help window that is 68 cells wide and "
        "exactly TWO lines tall. Keep the source's own line break if it has "
        "one. Numbers and the (NNNG) price / (upper limit N) parentheticals "
        "must survive exactly."
    ),
    "term": (
        "A UI label on a button or window header. Use RPG Maker's own official "
        "English where one exists (Item, Skill, Equip, Status, Formation, "
        "Save, Game End, Options, Fight, Escape, Attack, Guard, Weapon, "
        "Armor, Key Items, Optimize, Clear, New Game, Continue, To Title, "
        "Cancel, Buy, Sell, Max HP, Max MP, M.Attack, M.Defense, Agility, "
        "Luck, Hit, Evasion). Terse. No final punctuation."
    ),
    "type": "A single type / category label. One or two words, title case.",
    "title": "The game's title. No trailing period.",
    "currency": "The currency unit drawn immediately after a number.",
    "mapname": (
        "A location name shown as a banner when the player enters the map. "
        "Evocative, title case, 1-4 words."
    ),
    "message": (
        "A battle or menu message TEMPLATE. %1 and %2 are runtime "
        "substitutions - keep them, and keep their order meaningful in "
        "English. Remove no punctuation the engine needs. Never emit a literal "
        "newline or a double quote."
    ),
    "ptext": (
        "Text for a small on-screen popup, passed as ONE space-delimited "
        "plugin argument. Keep it to one or two short words. Any space you "
        "write is converted to a non-breaking space on the way in, so prefer a "
        "form that reads well either way."
    ),
    "plugin": "A plugin UI label. Terse, title case, no final punctuation.",
}


BASE_RULES = """\
You are an expert Japanese-to-English localizer working on an adult (R18) RPG \
Maker MV game. You translate dialogue, narration, menu and UI text, item names \
and descriptions into natural, fluent, idiomatic English.

You receive a numbered list of segments from ONE game file. Each carries its \
role (dialogue, menu choice, item name, UI label, ...) and, for dialogue, the \
speaker and the scene. A character and term glossary follows - read it first \
and apply ALL of it.

OUTPUT FORMAT
- Translate EVERY numbered segment. Output ONLY a JSON object mapping each \
number, as a string, to its English translation: {"1":"...","2":"..."}.
- No preamble, no notes, no romaji, no commentary, no Japanese in the output.

PROTECTED CODES
- Tokens like ⟦0⟧ and ⟦1⟧ are game control codes (a variable \
value, a currency unit, a timing pause). Keep every one EXACTLY as written and \
in the same relative position. Never translate, renumber, reorder, add or drop \
one.
- Some sentinels stand for a WORD or a NUMBER the engine inserts at run time. \
Japanese needs no space around one, so the source has none. English does. Put \
a space either side unless the neighbour is an apostrophe, a hyphen or a \
decoration mark.

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
You are localizing an adult Japanese RPG Maker game. For each Japanese \
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


def roster_block(glossary):
    """The FULL character roster. Identical on every request, so it caches."""
    lines = []
    for jp, v in glossary.get("names", {}).items():
        en = store.name_en(v)
        if not en:
            continue
        meta = []
        if isinstance(v, dict):
            # `note` is human-facing evidence and is deliberately NOT sent.
            for key in ("gender", "role", "register"):
                if v.get(key):
                    meta.append(str(v[key]))
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


def matched_terms(glossary, payload):
    """Only the glossary terms that actually occur in THIS request."""
    hits = []
    for jp, en in (glossary.get("terms") or {}).items():
        if not en:
            continue
        for part in re.split(r"[,、]", jp):
            part = part.strip()
            if not part:
                continue
            rx = _TERM_CACHE.get(part)
            if rx is None:
                rx = _TERM_CACHE[part] = _term_pattern(part)
            if rx.search(payload):
                hits.append("  %s -> %s" % (jp, en))
                break
    if not hits:
        return ""
    return ("Approved terminology appearing in this request - use exactly "
            "these renderings:\n" + "\n".join(hits))
