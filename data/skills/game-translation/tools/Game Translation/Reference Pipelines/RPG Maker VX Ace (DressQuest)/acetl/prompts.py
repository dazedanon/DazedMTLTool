#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
prompts.py - the system prompt, the glossary block and the per-kind
instructions.

Ownership is enforced: the base rules live here, the game bible lives in
`tl\game_prompt.md`, cross-cutting voice lives in `tl\quirks.md`, and
per-character register lives in `glossary.json`. Nothing is restated across two
of them, because copies start fighting.

Cache layout - a block earns a breakpoint only if its bytes are identical on
every request:

    system[0]  base rules + bible + quirks     cached (1h batch, 5m live)
    system[1]  the FULL character roster       cached, same breakpoint
    system[2]  terms matched in THIS request   NOT cached, emitted only when
                                               non-empty
    messages   the units                       not cached

A block whose bytes change per request is never re-read and bills the
cache-WRITE multiplier every time, so the matched-terms slice stays uncached -
but stays in the SYSTEM role, because demoting it into the user turn makes the
model read approved spellings as suggestions.
"""

import os
import re

from . import store

KIND_LABEL = {
    "text": "dialogue",
    "choice": "menu choice",
    "name": "item/skill/equipment name",
    "desc": "item/skill description",
    "term": "UI label",
    "type": "category label",
    "title": "game title",
    "currency": "currency unit",
    "mapname": "location name banner",
    "message": "battle-log message fragment",
    "profile": "character profile",
    "script": "UI string from the game's script",
    "cename": "scene title in the Recollection gallery",
}

KIND_INSTRUCTION = {
    "text": (
        "Dialogue and narration in a four-line message box. Natural, "
        "in-character English. Keep the line's register exactly - this game "
        "moves between light fantasy adventure, humiliation and explicit "
        "non-consensual erotica, and the register is the point. A line wrapped "
        "in （ ） is inner monologue: keep it in ( )."
    ),
    "choice": (
        "A menu choice the player clicks. Terse, title case, ideally one to "
        "four words, never a sentence and never final punctuation. Translate "
        "the ACTION, not the grammar: a short verb rendered as the wrong part "
        "of speech sends the player the opposite way (訂正する is \"Re-enter\", "
        "not \"Correct\")."
    ),
    "name": (
        "An item / skill / weapon / armour NAME as it appears in an inventory "
        "list about 30 half-width characters wide. Title case, no final "
        "punctuation, keep it short."
    ),
    "desc": (
        "A description drawn in a help window that is 64 half-width cells wide "
        "and exactly TWO lines tall. Numbers, prices and (upper limit N) "
        "parentheticals must survive exactly."
    ),
    "term": (
        "A UI label on a button or window header. Use RPG Maker's own official "
        "English where one exists (Item, Skill, Equip, Status, Formation, "
        "Save, Game End, Fight, Escape, Attack, Guard, Weapon, Armor, Key "
        "Items, Optimize, Clear, New Game, Continue, To Title, Cancel, Max HP, "
        "Max MP, Attack, Defense, M.Attack, M.Defense, Agility, Luck). Terse, "
        "no final punctuation."
    ),
    "type": "A single category label - an element, a skill type, an equipment "
            "type. One or two words, title case.",
    "title": "The game's title. No trailing period.",
    "currency": "The currency unit, drawn immediately after a number.",
    "mapname": (
        "A location name shown as a banner when the player walks onto the map. "
        "Evocative, title case, one to four words. Places recur across the "
        "game, so the same Japanese place name must always come back the same."
    ),
    "message": (
        "A battle-log FRAGMENT that the engine draws immediately after a "
        "character's name, with no space: `は倒れた！` renders as "
        "`Eris has fallen!`. The dummy name at the front of the source is "
        "there to give you a subject and is stripped from your answer - write "
        "the whole sentence WITH that name and it will be removed, so keep the "
        "wording natural around it."
    ),
    "profile": "A character profile shown on the status screen.",
    "cename": (
        "A scene title listed in the Recollection (CG gallery) menu. It names the scene for a player choosing what to replay: short, title case, no final punctuation, and explicit where the source is explicit."
    ),
    "script": (
        "A UI string read out of the game's own RGSS3 script - a button, a "
        "prompt, a window header. Terse, no final punctuation, and it must fit "
        "the width stated in the note."
    ),
}


BASE_RULES = """\
You are an expert Japanese-to-English localizer working on an adult (R18) RPG \
Maker VX Ace game. You translate dialogue, narration, menu and UI text, item \
names and descriptions into natural, fluent, idiomatic English.

You receive a numbered list of segments from ONE game file. Each carries its \
role (dialogue, menu choice, item name, UI label, ...) and, for dialogue, the \
speaker and the scene. A character and term glossary follows - read it first \
and apply ALL of it.

OUTPUT FORMAT
- Translate EVERY numbered segment. Output ONLY a JSON object mapping each \
number, as a string, to its English translation: {"1":"...","2":"..."}.
- No preamble, no notes, no romaji, no commentary, no Japanese in the output.

PROTECTED CODES
- Tokens like ⟦0⟧ and ⟦1⟧ are game control codes (a currency unit, a variable \
value, a timing pause). Keep every one EXACTLY as written and in the same \
relative position. Never translate, renumber, reorder, add or drop one.
- A sentinel that stands for a WORD or a NUMBER the engine inserts at run time \
needs a space around it in English; Japanese needs none, so the source has \
none. Skip the space next to an apostrophe, a hyphen or a decoration mark.

LINE BREAKS
- Write each segment as ONE flowing line unless the source has a real \
paragraph break. The tool re-wraps everything to the message box afterwards, \
so a line break you invent only gets in the way.

NO JAPANESE MAY SURVIVE, NOT EVEN AS DECORATION
- っ and ッ are a glottal catch; ぅ ぉ ぇ ぃ ぁ are a vowel dragged out. Render \
them with Latin letters - a doubled vowel, an -h, a hyphen - and delete the \
kana. `Agh゛っ♡` is WRONG; `Agh-♡` is right. The dakuten ゛ may stay; it reads \
as distortion.
- ❤ ♥ ♡ hearts, … ellipses and ～ wave dashes are punctuation, not Japanese - \
keep them where the source has them.
- 〇 and ● are CENSOR MASKS and must survive: うん〇 is `sh〇t`, and a name \
written ●●● stays ●●●.

CHARACTERS, GENDER AND PRONOUNS
- Japanese omits pronouns constantly. Infer the subject from context and the \
glossary. Resolve 彼 / 彼女 / あいつ / こいつ / コイツ against the referenced \
character's stated gender.
- Verify grammatical person from the source before writing. Second-person \
address (お前 / 君 / あなた) and third-person narration get flipped into \
first person routinely, and it is always wrong.
- A character who refers to themselves by name keeps that in English.

HONORIFICS
- Preserve -san, -kun, -chan, -sama, -senpai, -sensei, -dono.
- 兄者 is "brother", おじさん is "old man", 姫様 is "Princess" - those are not \
honorifics in English usage and are translated normally.

ADULT CONTENT - this is an 18+ game
- Translate explicit sexual content directly and vividly, matching the source \
register (clinical / vulgar / colloquial / tender). Do NOT euphemise, soften, \
moralise or add content warnings. Keep dominant speech dominant and begging \
submissive. Non-consensual scenes are translated as written.
- Erotic onomatopoeia (ぴちゃ ぐちゅ じゅぽ くちゅ ぬぷ くぱぁ) become \
evocative English sounds. Moans and climax cues (あぁ んっ はぁ イく \
イっちゃう) render expressively: "Aah...", "Ngh...", "I'm cumming...", \
"I'm gonna cum...".

QUALITY
- Prefer natural fluent English over literal gloss. Never merge or split \
segments. Never add quotes, speaker names or notes the source does not have.
- Japanese 「」 quotation marks around a whole spoken line are the engine's \
convention for speech; render the line as plain English dialogue and only use \
quotation marks where a speaker is quoting someone.
- Quantities are load-bearing: 三日後 is "three days later", not "in a few \
days", and a number in the source appears unchanged in the output.
- A full-width space inside a line is a pacing gap, not indentation. Render it \
as a space; do not run the phrases together.
"""

NAME_SYSTEM = """\
You are localizing an adult Japanese RPG Maker game. For each Japanese \
CHARACTER NAME or SPEAKER LABEL below, give the clean, consistent English form \
that will appear in the name plate above the message box and in dialogue, plus \
your best guess of the character's gender (male / female / unknown).

Many of these are not personal names but ROLE LABELS the game uses as a \
speaker: 町人 (townsperson), モンスター (monster), 村の男 (village man), \
賭博受付 (betting clerk). Translate those as natural English role labels, \
title case, and keep them SHORT - they are drawn in a small name plate. \
Transliterate an actual personal name; do not turn it into an English word \
that merely sounds like it. Numbered variants (トロール１ / トロール２) keep \
their number as a plain digit (Troll 1 / Troll 2).

Output ONLY a JSON object mapping each number, as a string, to an object \
{"en": "<english>", "gender": "male|female|unknown"}, e.g. \
{"1":{"en":"Eris","gender":"female"},"2":{"en":"Townsperson","gender":"unknown"}}.
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
    bible = load_side_file(store_dir, "game_prompt.md")
    if bible:
        parts.append("GAME BIBLE\n" + bible)
    quirks = load_side_file(store_dir, "quirks.md")
    if quirks:
        parts.append("CROSS-CUTTING VOICE RULES\n" + quirks)
    return "\n\n".join(parts)


def roster_block(glossary, min_count=0):
    """The character roster. Identical on every request, so it caches.

    `min_count` trims one-line walk-on speakers out of the cached block when
    the roster gets long; their name still reaches the model as the segment's
    speaker field, and the glossary still fixes their spelling on inject."""
    lines = []
    for jp, v in glossary.get("names", {}).items():
        en = store.name_en(v)
        if not en:
            continue
        if min_count and isinstance(v, dict) and (v.get("count") or 0) < min_count:
            continue
        meta = []
        if isinstance(v, dict):
            # `note` is human-facing evidence and is deliberately NOT sent.
            for key in ("gender", "role", "register"):
                if v.get(key):
                    meta.append(str(v[key]))
            for a in (v.get("aliases") or []):
                meta.append("aka " + a)
        lines.append("  %s -> %s%s"
                     % (jp, en, ("  (" + "; ".join(meta) + ")") if meta else ""))
    dnt = glossary.get("do_not_translate") or []
    out = []
    if lines:
        out.append("CHARACTERS AND SPEAKERS - use these English names and "
                   "genders consistently:\n" + "\n".join(lines))
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
