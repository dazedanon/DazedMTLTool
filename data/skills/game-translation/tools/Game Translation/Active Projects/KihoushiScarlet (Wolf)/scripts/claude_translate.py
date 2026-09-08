#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
claude_translate.py - translate the WolfDawn `mt-export` batch for
騎紅士スカーレット (Crimson Knight Scarlet) with Claude via the Message Batches API.

Adapted from Reference Pipelines\\Wolf RPG (Asuka)\\scripts\\claude_translate.py.
Differences that matter for THIS game:

  * Model is claude-sonnet-5. Sonnet 5 REJECTS temperature/top_p/top_k with a 400,
    so no sampling params are ever sent. Depth is controlled by output_config.effort.
  * The batch was exported with `--sentinel-mask`, so control codes are backslash-free
    {Wn} tokens. The integrity guard therefore counts SENTINELS, not \\codes.
  * DEDUPLICATION. 74,289 units collapse to 7,676 distinct sources (9.7x). One
    representative per (kind, source) is translated and the result is fanned out to
    every sibling. Fanout OVERWRITES - filling only blank siblings makes `retry`
    structurally incapable of repairing anything, because on a retry every sibling
    already carries the text that failed. Lines listed in tl/locks.json are exempt.
  * The speaker sits INSIDE the source as 【Name】\\n「body」, so the resume ladder
    strips that nameplate line before deciding whether a unit still needs work.

Pipeline:
    dryrun    request count / token estimate / cost, no spend (add --exact for
              server-side count_tokens on a sample instead of the local heuristic)
    selftest  offline fake-translate -> fanout -> validate; proves the wiring, no API
    run       phase 1 names, phase 2 everything else; polls to done; resumable
    validate  completeness / residual-JP / sentinel integrity / soft warnings
    retry     re-translate hard failures with scene context
    fanout    re-run the dedup fanout on its own (after hand edits to a representative)
    batches   list / cancel / usage for submitted Message Batches

Typical use:
    set ANTHROPIC_API_KEY=sk-...
    python scripts/claude_translate.py dryrun --show-sample
    python scripts/claude_translate.py selftest
    python scripts/claude_translate.py run
    python scripts/claude_translate.py validate
    python scripts/claude_translate.py retry
    python scripts/claude_translate.py batches usage
"""

import os
import re
import sys
import json
import time
import argparse
import collections

# Before anything can print. argparse writes --help straight to stdout, and this
# module's own docstring carries Japanese, so a late reconfigure means `--help`
# dies on cp1252 before it ever reaches main().
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BATCH_PATH = os.path.join(WS, "batch.json")
OUT_DIR = os.path.join(WS, "out")
TL_DIR = os.path.join(WS, "tl")
GLOSSARY_PATH = os.path.join(TL_DIR, "glossary.json")
LOCKS_PATH = os.path.join(TL_DIR, "locks.json")
HOLDOUT_PATH = os.path.join(TL_DIR, "holdout.json")
STATE_PATH = os.path.join(TL_DIR, "_batch_state.json")
GAME_PROMPT_NAMES = ("game_prompt.md", "game_prompt.txt")

MODEL_DEFAULT = "claude-sonnet-5"
EFFORT_DEFAULT = "low"       # translation is direct high-volume work; raise to
                             # 'medium' only if a validate/read-through says so
_EFFORT = EFFORT_DEFAULT
_EFFORT_LEVELS = {"low", "medium", "high", "xhigh", "max"}
_THINKING = "off"            # 'off' | 'adaptive'
# "" = no cache_control. See _system_blocks for the measurement behind this default.
_CACHE_TTL = ""

# USD per 1M tokens. batch_* = 50% off. cache_write at the 1h-TTL rate (2x base
# input), cache_read = 10% of base input; cache tokens are priced at the standard
# rate here, which over-states rather than under-states the bill.
PRICE_BY_MODEL = {
    "claude-sonnet-5":   {"in": 2.0, "out": 10.0, "batch_in": 1.0, "batch_out": 5.0,
                          "cache_write": 4.0, "cache_read": 0.20},
    "claude-sonnet-4-6": {"in": 3.0, "out": 15.0, "batch_in": 1.5, "batch_out": 7.5,
                          "cache_write": 6.0, "cache_read": 0.30},
    "claude-opus-5":     {"in": 5.0, "out": 25.0, "batch_in": 2.5, "batch_out": 12.5,
                          "cache_write": 10.0, "cache_read": 0.50},
    "claude-haiku-4-5":  {"in": 1.0, "out": 5.0, "batch_in": 0.5, "batch_out": 2.5,
                          "cache_write": 2.0, "cache_read": 0.10},
}

# Sonnet 5 / Opus 5 / the 4.6+ family reject temperature, top_p and top_k with a 400.
# Only genuinely older models still accept them.
_LEGACY_SAMPLING_RE = re.compile(
    r"claude-(?:3|2)|sonnet-4-5|haiku-4-5|opus-4-5|opus-4-1", re.I)

# --------------------------------------------------------------------------
# protected tokens
# --------------------------------------------------------------------------
# `wolf mt-export --sentinel-mask` replaced every control code AND every
# positional whitespace pad with a backslash-free {Wn} token, so the guard counts
# those. The \\code branch is kept as a backstop in case the batch is ever
# re-exported without masking - a source with no backslash contributes nothing.
SENTINEL_RE = re.compile(r"\{W\d+\}")
WOLF_CODE_RE = re.compile(
    r"\{W\d+\}"
    r"|\\r\[[^\]]*\]"
    r"|\\[A-Za-z]+\[[^\]]*\]"
    r"|\\[A-Za-z]"
    r"|\\[.!^\\<>|]"
    r"|@\d+"
)
_RUBY_RE = re.compile(r"^\\r\[[^\]]*\]$")

# A run of 2+ newlines is a page break: several textboxes packed into one string.
# Collapsing one silently destroys the pagination and no relayout can recover it.
# It must match CRLF as well as LF. This corpus is 64,108 lone-LF units and 109
# CRLF units, almost all of them database descriptions - and a plain `\n{2,}`
# sees only 2 of the 4 page breaks, because `\r\n\r\n` puts a \r between the two
# newlines. The two it misses are exactly the DB fields nobody plays past.
_PAGEBREAK_RE = re.compile(r"(?:\r?\n){2,}")
_CRLF_RE = re.compile(r"\r\n")

JP_RE = re.compile(r"[぀-ヿ一-鿿]")
# Hard residual = hiragana / katakana / kanji EXCEPT the cosmetic marks ・ ー and
# the iteration marks, which stranded in English are a soft problem, not a retry loop.
UNTRANSLATED_JP_RE = re.compile(r"[぀-ゟ゠-ヺ一-鿿]")

# The speaker lives inside the string: 【Name】\n「body」
NAMEPLATE_RE = re.compile(r"^【([^】\n]{1,24})】\n")


# Which sentinels insert a VALUE at runtime, and so need spacing in English.
# Japanese sets no space around an inserted noun, so a faithful translation keeps
# none and the player reads "NeroIs that alright?". The split is read off the
# engine's own code names in the legend, never guessed: \cself/\cdb/\udb/\v/\sysS
# substitute a database or variable value; @N, \c, \f, \i, \E, \>, \space, \ax,
# \ay and the whitespace pads are formatting and must never be padded.
_INSERT_CODE_RE = re.compile(r"^\\(?:cself|cdb|udb|sysS|self|v)\[")
_LEGEND_CACHE = {}


def insert_sentinels(batch=None):
    """{token: the code it stands for} for the value-inserting sentinels only."""
    if batch is None:
        if "default" not in _LEGEND_CACHE:
            _LEGEND_CACHE["default"] = insert_sentinels(load_batch())
        return _LEGEND_CACHE["default"]
    legend = batch.get("_sentinel_legend") or {}
    return {t: c for t, c in legend.items() if _INSERT_CODE_RE.match(c)}


def pagination_pads(batch=None):
    """Sentinels whose expansion is whitespace CONTAINING A NEWLINE.

    One token in this batch, {W63} = eleven 　 then \n then one 　: the author
    padding out the rest of a line, breaking it, and indenting the next one under
    the opening 「. That is Japanese pagination measured in Japanese cells, and
    English repaginates from scratch in `relayout`, so carrying it through is not
    preservation - it is a 22-cell gap and a stray indent on a line the engine was
    going to re-wrap anyway. Droppable for the same reason ruby is.

    A whitespace pad with NO newline is a different animal - it can be centring a
    label - so it stays in the must-preserve set and `restore_edge_whitespace` /
    `wolf layout-restore` keep it honest.
    """
    if batch is None:
        if "pads" not in _LEGEND_CACHE:
            _LEGEND_CACHE["pads"] = pagination_pads(load_batch())
        return _LEGEND_CACHE["pads"]
    legend = batch.get("_sentinel_legend") or {}
    return {t for t, c in legend.items()
            if c and not c.strip("　 \t\r\n") and "\n" in c}


def code_multiset(s):
    """Multiset of protected tokens. Ruby is droppable markup (English has no
    furigana) and so is a pagination pad (English repaginates), so neither enters
    the must-preserve set."""
    pads = pagination_pads()
    return sorted(m for m in WOLF_CODE_RE.findall(s)
                  if not _RUBY_RE.match(m) and m not in pads)


def pagebreaks(s):
    return len(_PAGEBREAK_RE.findall(s))


# --------------------------------------------------------------------------
# prompts
# --------------------------------------------------------------------------
SYSTEM_SHARED = (
    "You are an expert Japanese-to-English eroge (adult game) translator and localizer. You "
    "translate dialogue, narration, menu/UI text, database names and descriptions for a "
    "Japanese Wolf RPG Editor game into natural, fluent, idiomatic English.\n\n"
    "You receive a numbered list of segments from ONE game file. Each is tagged with its role "
    "(dialogue, narration, choice, UI, name, db field, ...). A character & term glossary and "
    "game-specific guidance follow in later blocks - read them first and apply ALL of it.\n\n"
    "OUTPUT FORMAT\n"
    "- Translate EVERY numbered segment. Output ONLY a JSON object mapping each number (as a "
    'string) to its English translation, e.g. {"1":"...","2":"..."}. No preamble, notes, '
    "romaji, or Japanese in the output. Use \\n inside JSON strings for line breaks.\n\n"
    "PROTECTED TOKENS - the single hardest requirement\n"
    "- Every token of the form {W0}, {W12}, {W49} is a masked game control code or a run of "
    "layout whitespace. Copy each one EXACTLY, keep the same COUNT of each, and keep them in "
    "the same relative position in the sentence. Never translate, renumber, reorder, merge, "
    "add or drop a {Wn} token. They are not words and they are not punctuation.\n"
    "- SOME {Wn} tokens insert a VALUE at runtime (a name, an item, a number); the rest are "
    "formatting (colour, font size, an icon, a line prefix, layout whitespace). The list of "
    "value-inserting tokens for this batch is given below. Around a VALUE token English needs "
    "a space where Japanese needs none - write \"the {W4} broke\", not \"the{W4}broke\" - but "
    "never add a space next to an apostrophe, hyphen or closing bracket, so {W4}'s and "
    "{W4}-chan stay tight. Around a FORMATTING token add nothing: {W47}Titfuck{W48} is a "
    "colour span and must stay flush.\n"
    "- Keep the line-break structure. A run of TWO OR MORE newlines is a page break between "
    "separate textboxes: keep exactly as many as the source has, never collapse them.\n"
    "- LEADING and TRAILING whitespace is layout, not slack. A menu label written as "
    "\"　スタート\" is centred by that leading ideographic space, so reproduce the same "
    "leading/trailing spaces around your translation instead of trimming them.\n\n"
    "- `<C>` and `<R>` are the engine's centre / right alignment tags, consumed by the "
    "renderer and never drawn. Keep them exactly where they are.\n\n"
    "SPEAKER NAMEPLATES\n"
    "- Most dialogue looks like 【スカーレット】\\n「body」 - the speaker's name is INSIDE the "
    "string in lenticular brackets, followed by a newline, and the body is inside corner "
    "brackets. Translate the name with the glossary and KEEP 【 】 「 」 and the newline "
    "exactly: 【スカーレット】\\n「…」 -> 【Scarlet】\\n\"…\" is WRONG; it must stay "
    "【Scarlet】\\n「…」. ？？？ -> ???\n\n"
    "LAYOUT\n"
    "- The message box fits roughly 4 rows. Keep the source's number of lines where you can; "
    "never turn a 2-line message into 5. Menu labels and database names are drawn in narrow "
    "columns - keep them terse.\n\n"
    "QUALITY & CONSISTENCY\n"
    "- Prefer natural, fluent English over literal gloss. Use the SAME English name for a "
    "character, skill, item or enemy EVERY time - the engine looks these up by name.\n"
    "- Japanese omits pronouns; resolve 彼 / 彼女 / こいつ / あいつ from the glossary's stated "
    "genders. Never call a female character \"guy\", \"man\" or \"dude\".\n"
    "- ・・・ -> \"...\". Keep ♥ ♡ ♪. Keep （） inner monologue as (parentheses).\n"
    "- No kana may survive into the English output, including in sound effects.\n\n"
    "ADULT CONTENT (18+ game - do NOT censor, soften, euphemize or moralize)\n"
    "- Translate explicit sexual content directly and vividly, matching the source register "
    "(clinical / vulgar / colloquial). Keep dominant speech dominant and submissive begging "
    "submissive. Anatomy words stay as blunt in English as they are in Japanese.\n"
    "- Erotic onomatopoeia is a large share of this game's text and must become evocative "
    "English sound writing, never romaji and never a description. See the game guidance.\n\n"
    "EXAMPLE\n"
    "Input:\n"
    "[1] (dialogue) 【スカーレット】\\n「くっ…！{W49}\\n　貴様、覚えていろ…！」\n"
    "[2] (choice) はい\n"
    "[3] (narration) {W47}パイズリ{W48}を覚えた！\n"
    "Output:\n"
    '{"1":"【Scarlet】\\n「Guh…!{W49}\\n　You bastard, I won\'t forget this…!」",'
    '"2":"Yes","3":"Learned {W47}Titfuck{W48}!"}'
)

NAMES_HEADER = (
    "These segments are NAMES from the game's databases (characters, items, skills, enemies, "
    "statuses, equipment, animations, locations). Translate each to a clean, short, consistent "
    "English name using the glossary; romanize unknown proper nouns consistently (Hepburn). "
    "Keep any bracketed/parenthesized tags and {Wn} tokens exactly. Terse - these are LABELS "
    "drawn in narrow menu columns, not sentences. Two different Japanese names must never "
    "collapse to the same English string: the engine looks rows up BY NAME and a collision is "
    "a runtime break, not a style nit."
)

KIND_LABEL = {
    "dialogue": "dialogue", "narration": "narration", "choice": "choice",
    "ui": "UI", "name": "name", "db": "db field", "system": "system",
}


def _sampling_params(model):
    return {"temperature": 0} if _LEGACY_SAMPLING_RE.search(model or "") else {}


def _output_config():
    return {"output_config": {"effort": _EFFORT}} if _EFFORT in _EFFORT_LEVELS else {}


def _thinking_params(model):
    if _THINKING == "adaptive":
        return {"thinking": {"type": "adaptive"}}
    if _LEGACY_SAMPLING_RE.search(model or ""):
        return {}                       # older models: omitting = no thinking
    return {"thinking": {"type": "disabled"}}


def price_for(model):
    m = (model or "").lower()
    for key, pr in PRICE_BY_MODEL.items():
        if key in m:
            return pr
    return PRICE_BY_MODEL[MODEL_DEFAULT]


# --------------------------------------------------------------------------
# store: batch.json + glossary + locks + state
# --------------------------------------------------------------------------
def load_batch():
    with open(BATCH_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_batch(batch):
    tmp = BATCH_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(batch, f, ensure_ascii=False, indent=1)
    os.replace(tmp, BATCH_PATH)


def _load_json(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def load_glossary():
    return _load_json(GLOSSARY_PATH, {"names": {}, "terms": {}, "do_not_translate": []})


_HOLDOUT_CACHE = {}


def load_holdout():
    """tl/holdout.json is the ONLY source of held-out units. An empty file means
    the whole corpus is on the automated path."""
    if "v" not in _HOLDOUT_CACHE:
        h = _load_json(HOLDOUT_PATH, {}) or {}
        for k in ("speakers", "db_names", "line_ids"):
            h.setdefault(k, [])
        _HOLDOUT_CACHE["v"] = h
    return _HOLDOUT_CACHE["v"]


def is_held_out(l):
    """Units deliberately kept off the automated path.

    Not a filter, a DECLARED exclusion: held-out units are reported by dryrun, run
    and validate rather than quietly dropped. A pipeline that bounds its own
    coverage and says nothing reads as "covered everything" when it did not.
    """
    h = load_holdout()
    if l["id"] in (h.get("line_ids") or []):
        return True
    m = NAMEPLATE_RE.match(l["source"])
    if m and m.group(1) in (h.get("speakers") or []):
        return True
    if is_names_file(l["file"]) and l["source"].strip() in (h.get("db_names") or []):
        return True
    return False


def holdout_count(lines):
    return sum(1 for l in lines if is_held_out(l))


def load_locks():
    """Line ids whose `text` was hand-authored: never overwritten by fanout."""
    return set(_load_json(LOCKS_PATH, {"locked_ids": []}).get("locked_ids", []))


def load_game_prompt():
    for name in GAME_PROMPT_NAMES:
        p = os.path.join(TL_DIR, name)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return f.read().strip()
    return ""


def load_state():
    return _load_json(STATE_PATH, None)


def save_state(state):
    os.makedirs(TL_DIR, exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_PATH)


def dnt_set(glossary):
    return {s.strip() for s in glossary.get("do_not_translate", []) if s.strip()}


def is_names_file(fname):
    return fname.replace("\\", "/").endswith("names.json")


def line_kind(l):
    if is_names_file(l["file"]):
        return "name"
    sp = l.get("speaker") or ""
    if sp == "Narration":
        return "dialogue" if NAMEPLATE_RE.match(l["source"]) else "narration"
    if sp == "Choice":
        return "choice"
    if sp == "UI":
        return "ui"
    if sp.startswith("["):
        return "dialogue"
    if "GameDat" in l["file"]:
        return "system"
    return "db"


# --------------------------------------------------------------------------
# resume ladder - what counts as already translated
# --------------------------------------------------------------------------
# `source` stays Japanese forever, so every resume decision comes from `text`.
# Japanese left inside a nameplate the model echoed does not mean the body is
# untranslated; the naive "text still contains Japanese" test retranslates the
# whole game on every pass.
def _body_of(text):
    """Strip the 【Name】 nameplate line and every {Wn} token."""
    s = NAMEPLATE_RE.sub("", text)
    return SENTINEL_RE.sub("", s)


def is_done(l, dnt=None):
    tl = l.get("text") or ""
    if not tl.strip():
        return False
    # A denylisted row is DONE when it equals its source - that is the whole point
    # of the denylist. Without this the generic "text == source means untranslated"
    # rung fires on every pre-filled line and sends it to the API anyway, so
    # `apply_dnt` reports 47 lines protected and protects none of them.
    if dnt is None:
        dnt = _dnt()
    if (l["source"] or "").strip() in dnt:
        return tl == l["source"]
    if tl.strip() == (l["source"] or "").strip():
        return False
    if not UNTRANSLATED_JP_RE.search(tl):
        return True
    return not UNTRANSLATED_JP_RE.search(_body_of(tl))


_DNT_CACHE = {}


def _dnt():
    if "v" not in _DNT_CACHE:
        _DNT_CACHE["v"] = dnt_set(load_glossary())
    return _DNT_CACHE["v"]


def pending(l, retranslate_all=False):
    return retranslate_all or not is_done(l, _dnt())


# --------------------------------------------------------------------------
# dedup: one representative per (kind, source), fanned out afterwards
# --------------------------------------------------------------------------
def dedup_key(l):
    return (line_kind(l), l["source"])


def build_groups(lines):
    """{key: [line indices]} in first-seen order."""
    groups = collections.OrderedDict()
    for i, l in enumerate(lines):
        groups.setdefault(dedup_key(l), []).append(i)
    return groups


def representatives(lines, groups, retranslate_all=False):
    """One index per group that still needs work.

    The representative is a PENDING member where one exists, so a group whose
    representative was hand-fixed but whose siblings are stale does not get
    re-billed; otherwise the group is already satisfied and contributes nothing.
    """
    reps = []
    for _k, idxs in groups.items():
        want = [i for i in idxs
                if pending(lines[i], retranslate_all) and not is_held_out(lines[i])]
        if want:
            reps.append(want[0])
    return reps


def fanout(batch, locked=None, verbose=False):
    """Copy each group representative's translation onto every sibling.

    OVERWRITES. Filling only empty siblings is silently useless on every pass
    after the first: on a retry each sibling already holds the text that failed,
    so the representative gets repaired and the rest keep the defect.
    """
    locked = locked if locked is not None else load_locks()
    lines = batch["lines"]
    groups = build_groups(lines)
    changed = skipped = 0
    for _k, idxs in groups.items():
        if len(idxs) == 1:
            continue
        # prefer a member that passed the resume ladder; fall back to any non-empty
        # one so an ASCII-only row (legitimately identical to its source) still spreads
        src = next((i for i in idxs if is_done(lines[i], _dnt())), None)
        if src is None:
            src = next((i for i in idxs if (lines[i].get("text") or "").strip()), None)
        if src is None:
            continue
        tl = lines[src]["text"]
        for i in idxs:
            if i == src:
                continue
            if lines[i]["id"] in locked or is_held_out(lines[i]):
                skipped += 1
                continue
            if lines[i].get("text") != tl:
                lines[i]["text"] = tl
                changed += 1
    if verbose:
        print(f"fanout: {changed} sibling line(s) updated, {skipped} locked line(s) left alone.")
    return changed


# --------------------------------------------------------------------------
# scene labels from the extract JSONs (event names give the model context)
# --------------------------------------------------------------------------
_scene_labels_cache = None


def scene_labels():
    """{(batch-file-string, scene-index): event/scene name} from out/*.json."""
    global _scene_labels_cache
    if _scene_labels_cache is not None:
        return _scene_labels_cache
    labels = {}
    batch_files = set()
    try:
        for l in load_batch()["lines"]:
            batch_files.add(l["file"])
    except Exception:
        pass
    for bf in batch_files:
        path = os.path.join(WS, bf.replace("/", os.sep))
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
        except Exception:
            continue
        for i, sc in enumerate(doc.get("scenes") or []):
            nm = sc.get("name") or ""
            ev = sc.get("event")
            if nm:
                labels[(bf, i)] = f"{nm}" + (f" (event {ev})" if ev is not None else "")
        for i, g in enumerate(doc.get("groups") or []):
            nm = g.get("name") or g.get("type") or ""
            if nm:
                labels[(bf, i)] = nm
    _scene_labels_cache = labels
    return labels


_PTR_RE = re.compile(r"/(scenes|groups)/(\d+)/")


def scene_key(l):
    """Group key: one event page / db group = one scene. Names group per-file."""
    if is_names_file(l["file"]):
        return (l["file"], "names")
    m = _PTR_RE.search(l["id"])
    if m:
        return (l["file"], f"{m.group(1)}/{m.group(2)}")
    return (l["file"], "misc")


def scene_label(l):
    m = _PTR_RE.search(l["id"])
    if m:
        return scene_labels().get((l["file"], int(m.group(2))), "")
    return ""


# --------------------------------------------------------------------------
# request building
# --------------------------------------------------------------------------
def sanitize_id(s):
    return re.sub(r"[^A-Za-z0-9_-]", "-", s)[:48]


def _unique_id(stem, seq, used):
    """custom_id must be globally unique, and the stem alone is not.

    Every non-ASCII char folds to '-', so `map_タイトル` and `map_メイン街` both
    become `map_----`. Keying id_maps on a colliding id drops one file's lines
    silently - it cost the title-screen menu on the first build. The sequence
    number is global for that reason; `used` is the belt-and-braces check.
    """
    cid = f"{stem}__{seq:04d}"
    if cid in used:
        raise AssertionError(f"duplicate custom_id {cid!r} - id generation is broken")
    used.add(cid)
    return cid


def build_chunks(lines, max_units, retranslate_all, phase, dedupe=True):
    """Scene-aligned chunks over the lines that will actually be billed.

    With dedupe on, only one representative per (kind, source) is billed; the rest
    are filled by `fanout` afterwards.
    """
    if dedupe:
        groups = build_groups(lines)
        todo = representatives(lines, groups, retranslate_all)
    else:
        todo = [i for i, l in enumerate(lines)
                if pending(l, retranslate_all) and not is_held_out(l)]

    chunks = []
    used_ids = set()
    seq = [0]
    by_file = collections.OrderedDict()
    for i in todo:
        l = lines[i]
        nm = is_names_file(l["file"])
        if phase == "names" and not nm:
            continue
        if phase == "text" and nm:
            continue
        by_file.setdefault(l["file"], []).append((i, l))

    for fname, items in by_file.items():
        stem = sanitize_id(os.path.splitext(os.path.basename(fname))[0])
        scenes, cur = [], None
        for i, l in items:
            k = scene_key(l)
            if k != cur:
                scenes.append([])
                cur = k
            scenes[-1].append((i, l))

        buf = []

        def emit(sub, context=None):
            chunks.append({
                "custom_id": _unique_id(stem, seq[0], used_ids),
                "items": sub, "file": fname, "context": context or [],
                "names": is_names_file(fname),
            })
            seq[0] += 1

        def flush():
            if buf:
                emit(list(buf))
                buf.clear()

        for sc in scenes:
            if len(sc) > max_units:
                flush()
                for s in range(0, len(sc), max_units):
                    ctx = [l for _i, l in sc[max(0, s - 3):s]] if s > 0 else []
                    emit(sc[s:s + max_units], ctx)
            else:
                if buf and len(buf) + len(sc) > max_units:
                    flush()
                buf.extend(sc)
        flush()
    return chunks


def build_user_text(chunk):
    """Numbered segment list; returns (text, id_map[idx-1] = line index in batch)."""
    lines = ["Translate every numbered segment below. Return ONLY the JSON object."]
    if chunk["names"]:
        lines.append("\n" + NAMES_HEADER)
    ctx = chunk.get("context") or []
    if ctx:
        lines.append("\nCONTEXT - earlier lines of this SAME scene, for reference only; "
                     "do NOT translate or include these in the output:")
        for l in ctx:
            shown = (l.get("text") or l["source"]).replace("\n", " ")
            lines.append(f"  {shown[:160]}")
        lines.append("")
    id_map = []
    last_scene = None
    for i, l in chunk["items"]:
        sk = scene_key(l)
        if sk != last_scene and not chunk["names"]:
            lbl = scene_label(l)
            if lbl:
                lines.append(f"# scene: {lbl}")
            last_scene = sk
        id_map.append(i)
        idx = len(id_map)
        kind = line_kind(l)
        tag = KIND_LABEL.get(kind, kind)
        m = NAMEPLATE_RE.match(l["source"])
        if m:
            tag = f"dialogue; {m.group(1)}"
        note = (l.get("note") or "").replace("\r\n", " ").replace("\n", " ").strip()
        if note:
            tag += f"; {note[:70]}"
        src = l["source"].replace("\n", "\\n")
        lines.append(f"[{idx}] ({tag}) {src}")
    lines.append('\nJSON object {"1":"...", ...} with a translation for every number above. '
                 "Use \\n for the line breaks shown as \\n in the source. Every {Wn} token "
                 "must reappear, the same number of times, in the same order.")
    return "\n".join(lines), id_map


def _glossary_block(glossary, extra_terms, chunk_text="", inserts=None):
    lines = []
    name_lines = []
    for jp, v in glossary.get("names", {}).items():
        en = v.get("en") if isinstance(v, dict) else str(v)
        if not en:
            continue
        meta = []
        if isinstance(v, dict):
            # `note` is human-facing documentation and is intentionally NOT sent.
            for key in ("gender", "role", "register"):
                if v.get(key):
                    meta.append(str(v[key]))
            for alias in (v.get("aliases") or []):
                meta.append(f"aka {alias}")
        suffix = f"  ({'; '.join(meta)})" if meta else ""
        name_lines.append(f"  {jp} -> {en}{suffix}")
    if name_lines:
        lines.append("# Characters (use these English names and genders consistently)")
        lines += name_lines

    term_lines = []
    merged = dict(glossary.get("terms", {}))
    merged.update(extra_terms or {})
    for jp, en in merged.items():
        # Only the terms this chunk can actually use. Resident-glossary was the
        # right call ONLY while the prefix was cached; with caching off it puts
        # 33k tokens of unusable rows in front of every request.
        if en and (not chunk_text or jp in chunk_text):
            term_lines.append(f"  {jp} -> {en}")
    if term_lines:
        lines.append("# Terms (translate consistently - the engine looks these up by name)")
        lines += term_lines

    dnt = glossary.get("do_not_translate") or []
    if dnt:
        lines.append("# Do not translate (copy verbatim if encountered)")
        lines += [f"  {s}" for s in dnt]

    ins = [t for t in sorted(inserts or {}, key=lambda s: int(s[2:-1]))
           if not chunk_text or t in chunk_text]
    if ins:
        lines.append("# These {Wn} tokens INSERT A VALUE at runtime - give them a space in "
                     "English where the sentence needs one. Every other {Wn} in these "
                     "segments is formatting: leave it flush.")
        lines.append("  " + " ".join(ins))

    if not lines:
        return "Character & term glossary: (none yet - romanize names consistently)."
    return "Character & term glossary - apply consistently:\n" + "\n".join(lines)


def _system_blocks(glossary_text, game_prompt):
    """Build the system prompt. Caching is OFF by default, and that is a MEASURED
    decision, not a default carried over from somewhere.

    Reasoning that looked right and was wrong: the system prompt is byte-identical
    across every request, so put the whole glossary behind a 1 h cache breakpoint
    and pay one cache write plus N-1 reads at a tenth of the input rate.

    What the bill said, on a 192-request text batch with a 56,911-token prefix:

        cache_write  6,238,116 tok  = 110 full writes    $24.95
        cache_read   5,320,746 tok  =  93 reads          $ 1.06
        input          440,463 tok                       $ 0.44
        output         287,398 tok                       $ 1.44
                                                        -------
                                                         $27.89

    **Message Batch requests are processed in PARALLEL.** Roughly 110 of the 192
    started before any cache entry existed, so the prefix was written 110 times and
    read only 93. A cache write costs 2x base input (4x the batch input rate), so
    caching a large prefix under batch parallelism is worse than not caching at all:
    the same run with no `cache_control` would have been $12.80, and with the term
    glossary chunk-filtered instead of resident it is around $4.

    Caching still pays for interactive/serial traffic, where the first request
    genuinely warms the prefix for the rest. It does not pay here. `--cache 1h`
    or `--cache 5m` re-enables it if the traffic shape ever changes.
    """
    blocks = [{"type": "text", "text": SYSTEM_SHARED}]
    if game_prompt:
        blocks.append({"type": "text", "text": "GAME-SPECIFIC GUIDANCE:\n" + game_prompt})
    if glossary_text:
        blocks.append({"type": "text", "text": glossary_text})
    if _CACHE_TTL:
        blocks[-1]["cache_control"] = {"type": "ephemeral", "ttl": _CACHE_TTL}
    return blocks


def build_request(chunk, model, glossary, extra_terms, game_prompt, inserts=None):
    user_text, id_map = build_user_text(chunk)
    n = len(id_map)
    src_chars = sum(len(l["source"]) for _i, l in chunk["items"])
    max_tokens = min(32000, max(2000, int(src_chars * 1.4) + n * 32))
    return {
        "custom_id": chunk["custom_id"],
        "params": {
            "model": model,
            "max_tokens": max_tokens,
            **_sampling_params(model),
            **_thinking_params(model),
            **_output_config(),
            "system": _system_blocks(
                _glossary_block(glossary, extra_terms, user_text, inserts), game_prompt),
            "messages": [{"role": "user", "content": user_text}],
        },
    }, id_map


def names_extra_terms(batch, max_len=40):
    """Translated names.json lines as extra glossary terms for the text phase."""
    out = {}
    for l in batch["lines"]:
        if is_names_file(l["file"]) and (l.get("text") or "").strip():
            src = l["source"].strip()
            if 0 < len(src) <= max_len and src != l["text"].strip():
                out[src] = l["text"].strip()
    return out


def apply_dnt(batch, glossary):
    """Pre-fill do_not_translate lines with their source so they never hit the API."""
    dnt = dnt_set(glossary)
    n = 0
    for l in batch["lines"]:
        if not (l.get("text") or "").strip() and l["source"].strip() in dnt:
            l["text"] = l["source"]
            n += 1
    return n


def build_all(batch, model, max_units, retranslate_all, phase, dedupe=True):
    glossary = load_glossary()
    game_prompt = load_game_prompt()
    extra_terms = names_extra_terms(batch) if phase == "text" else {}
    inserts = insert_sentinels(batch)
    requests, id_maps = [], {}
    for ch in build_chunks(batch["lines"], max_units, retranslate_all, phase, dedupe):
        req, idmap = build_request(ch, model, glossary, extra_terms, game_prompt, inserts)
        requests.append(req)
        id_maps[ch["custom_id"]] = idmap
    return glossary, requests, id_maps


# --------------------------------------------------------------------------
# anthropic client + response parsing
# --------------------------------------------------------------------------
def get_client():
    try:
        from anthropic import Anthropic
    except ImportError:
        sys.exit("ERROR: pip install anthropic")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        # The SDK also resolves ANTHROPIC_AUTH_TOKEN and an `ant auth login` profile,
        # so an unset key is not proof there are no credentials - try, then explain.
        try:
            return Anthropic()
        except Exception:
            sys.exit("ERROR: no Anthropic credentials found.\n"
                     "  set ANTHROPIC_API_KEY=sk-ant-...   (PowerShell: $env:ANTHROPIC_API_KEY='sk-ant-...')\n"
                     "  or run `ant auth login` if you have the Anthropic CLI installed.")
    return Anthropic()


# Walks escapes left-to-right so a valid pair (\\, \n, \uXXXX) is consumed
# atomically and never re-inspected from its middle character.
_ESC_RE = re.compile(r'\\u[0-9a-fA-F]{4}|\\[\\/"bfnrt]|\\(.)', re.S)


def _repair_json_escapes(s):
    """Double every backslash that does not start a valid JSON escape. The sentinel
    mask makes this rare, but a model that writes a stray backslash still kills the
    whole request's parse and takes 80 good translations with it."""
    return _ESC_RE.sub(
        lambda m: m.group(0) if m.group(1) is None else "\\\\" + m.group(1), s)


_EDGE_WS_RE = re.compile(r"^(\s*)(.*?)(\s*)$", re.S)


def restore_edge_whitespace(src, tl):
    """Put back the leading/trailing whitespace run the model trimmed.

    Models trim edges - it reads like tidying. Here the edges are DATA. Two database
    rows in this game differ only by a trailing CRLF (`井戸王` and `井戸王\\r\\n`), so a
    trimmed translation makes them collide on one English string, which is a by-name
    lookup break rather than a style nit. Leading pads centre a menu label the same way.

    Unambiguous by construction: only the edges are touched, the core is untouched,
    and a translation that already carries the source's edges is left alone.
    """
    if not tl.strip():
        return tl
    ms, mt = _EDGE_WS_RE.match(src), _EDGE_WS_RE.match(tl)
    if not ms or not mt:
        return tl
    lead, core, trail = ms.group(1), mt.group(2), ms.group(3)
    if mt.group(1) == lead and mt.group(3) == trail:
        return tl
    return lead + core + trail


# The one 　 that opens a continuation line is doing TWO jobs, and only one of them
# is visible. On screen it is a two-cell indent under a halfwidth `"` - the "line 2
# starts with a space for no reason" defect. In the toolchain it is
# `wolf relayout`'s deliberate-row marker: `deliberate_row()` is
# `blank || code-only || starts_with('　')`, and a message with one gets each row
# wrapped on its own, while a message WITHOUT one has every row merged and refilled
# to the full box width.
#
# So the pad must survive into relayout and be stripped after it, by
# `build.py deindent`. Removing it from the store instead does not just remove an
# indent - it silently converts 26,281 units from "keep the author's layout" to
# "reflow as free prose", which is how a message the author broke at 26/42/42 cells
# came back as one 76-cell line running under the standing portrait that scene draws.
#
# The model renders the same pad two ways and only the fullwidth one is a marker:
# 8,315 lines kept 　 and 20,118 folded it to an ASCII space, so more than two
# thirds of the author's own breaks were being discarded before this ran. Restoring
# them is copy-from-source, never invention - over the whole corpus there are 0
# lines where the model dropped the pad entirely, and messages whose line count no
# longer matches the source (292) are left alone because there is nothing to align.
_ROW_PAD_RE = re.compile(r"^[　 ]+")


def restore_row_markers(src, tl):
    """Re-fullwidth the author's continuation-row pads so relayout still sees them."""
    if "　" not in src:
        return tl
    s_lines, t_lines = src.split("\n"), tl.split("\n")
    if len(s_lines) < 2 or len(s_lines) != len(t_lines):
        return tl
    changed = False
    for j in range(1, len(s_lines)):
        if not s_lines[j].startswith("　"):
            continue
        m = _ROW_PAD_RE.match(t_lines[j])
        if not m or "　" in m.group(0):
            continue
        t_lines[j] = "　" + t_lines[j][len(m.group(0)):]
        changed = True
    return "\n".join(t_lines) if changed else tl


# The one code in this game whose COUNT may be repaired deterministically.
# \i[126] draws an 18x24 pink heart (build/icon126_big.png) - pure decoration. It is
# not stateful, so a miscount cannot mis-colour, hang the parser or break a lookup,
# unlike \c[n] or \f[n] where reinserting at a plausible position is a real defect.
# English merges clauses Japanese punctuates separately, so the model emits one heart
# where the source had two; it also sometimes adds one. The author already STACKS
# them - 15,317 source units contain {W2}{W2} - so padding at the clause end is this
# game's own idiom rather than an invention.
#
# This is the fourth entry in the graded-guard list (font size / ruby removal /
# closing a malformed code being the three the engine reference already allows).
# It fires ONLY when the heart is the sole drifting token.
_HEART_CODE = "\\i[126]"


def _heart_token(batch):
    for tok, code in (batch.get("_sentinel_legend") or {}).items():
        if code == _HEART_CODE:
            return tok
    return None


def repair_heart_count(src, tl, tok):
    """Match the translation's heart count to the source's, or return None.

    Returns None - meaning "not mine to fix" - whenever any token other than the
    heart differs, so a genuinely corrupted line still reaches the guard and `retry`.
    """
    if not tok:
        return None
    sm = collections.Counter(code_multiset(src))
    tm = collections.Counter(code_multiset(tl))
    if (sm - tm) - collections.Counter({tok: 10 ** 6}) or \
       (tm - sm) - collections.Counter({tok: 10 ** 6}):
        return None                      # something other than the heart drifted
    delta = sm[tok] - tm[tok]
    if delta == 0:
        return None
    if delta > 0:
        # Pad at the end of the last text line, inside a closing 」 when there is one.
        i = tl.rfind("」")
        at = i if i != -1 else len(tl.rstrip())
        return tl[:at] + tok * delta + tl[at:]
    out, remove = tl, -delta
    while remove and tok in out:          # drop the rightmost surplus first
        i = out.rfind(tok)
        out = out[:i] + out[i + len(tok):]
        remove -= 1
    return out


def restore_newline_style(src, tl):
    """Put the source's CRLF back when the model answered in bare LF.

    JSON transport and the model both normalize to \\n, so a database description
    authored with CRLF comes back with LF and the injected field silently changes
    line-ending style. Repaired only where it is UNAMBIGUOUS - every newline in the
    source is a CRLF, the translation carries no \\r at all, and the break counts
    match. A mismatch is left alone rather than guessed at.
    """
    if "\r\n" not in src or "\r" in tl:
        return tl
    if src.count("\r\n") == src.count("\n") and src.count("\n") == tl.count("\n"):
        return tl.replace("\n", "\r\n")
    return tl


def parse_json_object(text):
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?", "", s).strip()
        s = re.sub(r"```$", "", s).strip()
    i, j = s.find("{"), s.rfind("}")
    if i != -1 and j != -1 and j > i:
        s = s[i:j + 1]
    # strict=False accepts raw control characters (literal newlines) in strings,
    # which the model occasionally emits instead of \n.
    try:
        return json.loads(s, strict=False)
    except json.JSONDecodeError:
        return json.loads(_repair_json_escapes(s), strict=False)


def apply_results(batch, results, id_maps):
    applied = 0
    errors = []
    lines = batch["lines"]
    for cid, obj in results.items():
        idmap = id_maps.get(cid, [])
        for k, v in obj.items():
            try:
                idx = int(k)
            except ValueError:
                continue
            if 1 <= idx <= len(idmap) and isinstance(v, str):
                l = lines[idmap[idx - 1]]
                v = restore_edge_whitespace(l["source"], v)
                v = restore_newline_style(l["source"], v)
                l["text"] = restore_row_markers(l["source"], v)
                applied += 1
            else:
                errors.append(f"{cid}: index {k} out of range")
    return applied, errors


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------
def hard_issues(l, dnt):
    src = l["source"]
    tl = l.get("text") or ""
    if not tl.strip():
        return ["empty"]
    if src.strip() in dnt or not JP_RE.search(src):
        return []           # verbatim / ascii-only lines are legitimately identical
    out = []
    if tl.strip() == src.strip():
        out.append("identical")
    # A do_not_translate term kept verbatim is not residual Japanese - but strip it
    # only from a unit that IS a dnt unit. This list is asset-registry row names
    # (SEリスト / BGMリスト / 職業設定 ...), and several are ordinary words: 射精, 絶頂,
    # 正解, 回復, カメラ. Stripping those globally would blind the residual-Japanese
    # check to them across all 74,289 lines, which is exactly how untranslated text
    # ships with every counter green. A denylist is scoped to a POSITION, not to a
    # string; here the position is "the whole unit is this key".
    tl_scan = _body_of(tl)
    if src.strip() in dnt:
        for term in sorted(dnt, key=len, reverse=True):
            tl_scan = tl_scan.replace(term, "")
    if UNTRANSLATED_JP_RE.search(tl_scan):
        out.append("residual_jp")
    if code_multiset(src) != code_multiset(tl):
        out.append("codes")
    if pagebreaks(src) != pagebreaks(tl):
        out.append("pagebreaks")
    return out


def _name_gender_forms(glossary):
    out = []
    for jp, v in glossary.get("names", {}).items():
        if not isinstance(v, dict):
            continue
        g = (v.get("gender") or "").lower()
        if g not in ("male", "female"):
            continue
        for f in [jp] + list(v.get("aliases") or []):
            if len(f) >= 2 and JP_RE.search(f):
                out.append((f, g))
    out.sort(key=lambda x: -len(x[0]))
    return out


def _gender_sets(glossary):
    out = {"male": set(), "female": set()}
    for jp, v in glossary.get("names", {}).items():
        if not isinstance(v, dict):
            continue
        g = (v.get("gender") or "").lower()
        if g in out:
            for f in [jp] + list(v.get("aliases") or []):
                if len(f) >= 2 and JP_RE.search(f):
                    out[g].add(f)
    return out


_HE_RE = re.compile(r"\b(?:he|him|his|himself)\b", re.I)
_SHE_RE = re.compile(r"\b(?:she|her|hers|herself)\b", re.I)
# A gendered NOUN predicated of the addressee is a misgender no pronoun check sees.
_MALE_NOUN_RE = re.compile(
    r"\b(?:guy|guys|man|men|dude|bro|buddy|sir|mister|mr|lad|boy|gentleman)\b", re.I)
_2ND_PERSON_JP_RE = re.compile(r"貴様|お前|おまえ|君|きみ|あんた|あなた|テメェ|てめえ")
# The engine lexes a backslash escape greedily, but the sentinel mask means the
# only backslash a translation can carry is one the model invented.
_STRAY_BS_RE = re.compile(r"\\")
# A number pressed against a letter reads as "Add a fair amount3 used".
# Scoped to the VALUE-inserting sentinels only. Fired over all 86 tokens it returns
# 22 hits here and 59,249 over the whole corpus, nearly all of them \c[] colour
# spans and \i[] icons that must stay flush - a list nobody reads is not a check.
_GLUED_NUM_RE = re.compile(r"(?<=[A-Za-z])\{W\d+\}(?=[A-Za-z])")


def _glued_inserts(tl):
    inserts = insert_sentinels()
    return any(m.group(0) in inserts for m in _GLUED_NUM_RE.finditer(tl))


def soft_warnings(l, name_forms, gender_sets):
    tl = l.get("text") or ""
    warns = []
    if not tl.strip():
        return warns
    src = l["source"]
    has_he, has_she = bool(_HE_RE.search(tl)), bool(_SHE_RE.search(tl))
    if has_he or has_she:
        male_named = any(m in src for m in gender_sets["male"])
        female_named = any(f in src for f in gender_sets["female"])
        # Names are looked for in the BODY, never in the 【nameplate】. A speaker
        # naming themself is no evidence about who a third-person pronoun refers
        # to, and it is the overwhelmingly common case: the female protagonist
        # heads 60% of the corpus and talks about a male partner throughout, so
        # scanning the whole source flagged 1,133 correct lines here against 26.
        src_body = NAMEPLATE_RE.sub("", src)
        for jp, g in name_forms:
            if jp in src_body:
                if g == "female" and has_he and not has_she and not male_named:
                    warns.append(f"possible misgender: '{jp}' is female but tl uses he/him")
                elif g == "male" and has_she and not has_he and not female_named:
                    warns.append(f"possible misgender: '{jp}' is male but tl uses she/her")
                break
    m = NAMEPLATE_RE.match(src)
    # Same rule for the noun: 【Milking Man】 / 【Wank Guy】 / 【Lewd Gentleman】 put
    # the male noun in the nameplate the check is supposed to look past.
    if m and _MALE_NOUN_RE.search(_body_of(tl)) and _2ND_PERSON_JP_RE.search(src):
        spk = m.group(1)
        if spk != "スカーレット":
            warns.append(f"male noun addressed to 'you' by {spk} - check the addressee's gender")
    if _STRAY_BS_RE.search(tl) and not _STRAY_BS_RE.search(src):
        warns.append("translation invented a backslash the source never had")
    if _glued_inserts(tl):
        warns.append("a {Wn} value insert is glued between two letters - needs a space")
    if line_kind(l) == "choice" and "," in tl and "," not in src:
        warns.append("comma added to a CHOICE label - a comma can split one option into two")
    sv, tv = len(src.strip()), len(tl.strip())
    if sv >= 8 and tv > sv * 6:
        warns.append(f"over-expansion: tl {tv} chars vs src {sv}")
    if tl.count("\n") > src.count("\n") + 1:
        warns.append(f"line-count growth: src {src.count(chr(10)) + 1} -> tl {tl.count(chr(10)) + 1}")
    if JP_RE.search(_body_of(tl)) and not UNTRANSLATED_JP_RE.search(_body_of(tl)):
        warns.append("leftover cosmetic kana mark (・/ー)")
    return warns


def cmd_validate(max_issues=25, dedupe=True):
    batch = load_batch()
    glossary = load_glossary()
    dnt = dnt_set(glossary)
    name_forms = _name_gender_forms(glossary)
    gender_sets = _gender_sets(glossary)
    lines = batch["lines"]
    total = len(lines)
    groups = build_groups(lines)
    done = empty = 0
    tally = collections.Counter()
    hard_list, warn_list = [], []
    for l in lines:
        issues = hard_issues(l, dnt)
        if issues == ["empty"]:
            empty += 1
            continue
        done += 1
        for code in issues:
            tally[code] += 1
            detail = f": {l['text'][:40]!r}" if code == "residual_jp" else ""
            if code == "codes":
                detail = f": src{code_multiset(l['source'])} tl{code_multiset(l['text'])}"
            hard_list.append(f"[{code}] {l['file']} {l['id']}{detail}")
        for w in soft_warnings(l, name_forms, gender_sets):
            warn_list.append(f"{l['file']} {l['id']}: {w}")

    # a group whose members disagree means a fanout was never run, or a hand edit
    # landed on one sibling only
    split = 0
    for _k, idxs in groups.items():
        if len({lines[i].get("text") or "" for i in idxs}) > 1:
            split += 1

    held = holdout_count(lines)
    print(f"VALIDATION  lines={total}  dedup groups={len(groups)}")
    if held:
        print(f"  HELD OUT           : {held} (never sent; counted as untranslated below, "
              "which is correct - they are not done)")
    print(f"  translated         : {done} ({100.0 * done / total if total else 0:.1f}%)")
    print(f"  untranslated       : {empty}")
    print(f"  identical-to-source: {tally['identical']}")
    print(f"  residual-Japanese  : {tally['residual_jp']}")
    print(f"  sentinel-broken    : {tally['codes']}")
    print(f"  pagebreak-broken   : {tally['pagebreaks']}")
    print(f"  groups disagreeing : {split}   (run `fanout` if non-zero and unintended)")
    print(f"  soft warnings      : {len(warn_list)}")
    for title, rows, mark in (("hard issues (fix with: retry)", hard_list, "-"),
                              ("soft warnings (review by hand)", warn_list, "?")):
        if rows:
            print(f"  -- {title} --")
            for s in rows[:max_issues]:
                print(f"   {mark} {s}")
            if len(rows) > max_issues:
                print(f"   ... ({len(rows) - max_issues} more)")
    hard_fail = (empty - held) + tally["residual_jp"] + tally["codes"] + tally["pagebreaks"]
    if held:
        print(f"  (the {held} held-out unit(s) are excluded from the pass/fail gate, "
              "but they are still untranslated and still ship in Japanese)")
    if hard_fail == 0:
        print("\nOK - next: wolf mt-import batch.json out/*.json")
    return 0 if hard_fail == 0 else 1


# --------------------------------------------------------------------------
# dryrun
# --------------------------------------------------------------------------
def _heuristic_counter():
    """Fallback only. A JP char is ~1 token, ASCII ~0.28. Used when no credential
    is available; `--exact` measures the real thing with count_tokens instead."""
    def count(s):
        jp = sum(1 for c in s if ord(c) > 0x2E7F)
        return max(1, int(jp + (len(s) - jp) * 0.28))
    return count


def _exact_counter(model, sample_requests):
    """Calibrate the local heuristic against server-side count_tokens on a sample.

    Counting all ~1,600 requests server-side would be its own long job, so a
    sample fixes the scale factor and the heuristic carries the rest.
    """
    client = get_client()
    h = _heuristic_counter()
    ratios = []
    for req in sample_requests:
        p = req["params"]
        try:
            r = client.messages.count_tokens(
                model=model, system=p["system"], messages=p["messages"])
        except Exception as e:
            print(f"  ! count_tokens failed ({e}); falling back to the heuristic.")
            return h, None
        est = sum(h(b["text"]) for b in p["system"]) + h(p["messages"][0]["content"])
        if est:
            ratios.append(r.input_tokens / est)
    if not ratios:
        return h, None
    k = sum(ratios) / len(ratios)
    return (lambda s: max(1, int(h(s) * k))), k


def cmd_dryrun(model, max_units, retranslate_all, show_sample=False, exact=False, dedupe=True):
    batch = load_batch()
    glossary = load_glossary()
    apply_dnt(batch, glossary)
    all_requests = []
    for phase in ("names", "text"):
        _g, reqs, id_maps = build_all(batch, model, max_units, retranslate_all, phase, dedupe)
        all_requests.append((phase, reqs, id_maps))

    flat = [r for _p, rs, _m in all_requests for r in rs]
    if not flat:
        print("Nothing pending - the batch is already filled.")
        return 0

    counter, k = _heuristic_counter(), None
    if exact:
        counter, k = _exact_counter(model, flat[:8])

    prefix_count = collections.defaultdict(int)
    prefix_tok = {}
    dyn_in_tok = out_scaffold = src_tok = n_units = 0
    sample = None
    for phase, reqs, id_maps in all_requests:
        for req in reqs:
            blocks = req["params"]["system"]
            cut = len(blocks)
            for i, b in enumerate(blocks):
                if "cache_control" in b:
                    cut = i + 1
                    break
            prefix = "".join(b["text"] for b in blocks[:cut])
            dyn = "".join(b["text"] for b in blocks[cut:])
            prefix_count[prefix] += 1
            prefix_tok.setdefault(prefix, counter(prefix))
            usr = req["params"]["messages"][0]["content"]
            dyn_in_tok += counter(dyn) + counter(usr) + 8
            n = len(id_maps.get(req["custom_id"], []))
            n_units += n
            out_scaffold += counter("".join('"%d":"",' % i for i in range(1, n + 1)))
            if sample is None and phase == "text":
                sample = usr
    for _p, reqs, id_maps in all_requests:
        for req in reqs:
            for li in id_maps.get(req["custom_id"], []):
                src_tok += counter(batch["lines"][li]["source"])

    lines = batch["lines"]
    n_pending = sum(1 for l in lines if pending(l, retranslate_all))
    groups = build_groups(lines)
    cache_write_tok = sum(prefix_tok[p] for p in prefix_count)
    cache_read_tok = sum(prefix_tok[p] * (prefix_count[p] - 1) for p in prefix_count)
    raw_in_tok = sum(prefix_tok[p] * prefix_count[p] for p in prefix_count) + dyn_in_tok
    n_req = len(flat)
    gp = load_game_prompt()

    print(f"model={model}  effort={_EFFORT}  thinking={_THINKING}  dedupe={'on' if dedupe else 'OFF'}")
    print(f"corpus       : {len(lines):,} units, {len(groups):,} distinct (kind,source) "
          f"-> {len(lines) / max(1, len(groups)):.2f}x")
    held = holdout_count(lines)
    print(f"pending      : {n_pending:,} units  ->  BILLED {n_units:,} representatives")
    if held:
        h = load_holdout()
        print(f"HELD OUT     : {held:,} unit(s) are NOT sent - speakers "
              f"{h.get('speakers')}, db names {h.get('db_names')}")
        print(f"               reason: {h.get('_reason', '(none recorded)')[:200]}")
    print(f"requests     : {n_req} (names {len(all_requests[0][1])}, text {len(all_requests[1][1])})")
    print(f"game prompt  : {('loaded, ' + str(len(gp)) + ' chars') if gp else '*** MISSING ***'}")
    print(f"glossary     : {len(glossary.get('names', {}))} names, "
          f"{len(glossary.get('terms', {}))} terms, "
          f"{len(glossary.get('do_not_translate', []))} do-not-translate")
    print(f"cached prefix: {cache_write_tok:,} tok, re-read {n_req - len(prefix_count)}x")
    if cache_write_tok < 1024:
        # Below the model's minimum cacheable prefix the breakpoint is silently
        # ignored - no error, just no cache_read_input_tokens on any response.
        print("  ! under ~1024 tokens the cache breakpoint is silently ignored. "
              "Loading tl/game_prompt.md pushes the prefix over the line.")
    print(f"dynamic input: {dyn_in_tok:,} tok   |  raw input w/o cache: {raw_in_tok:,} tok")
    print(f"JP source-only tokens: {src_tok:,}")

    pr = price_for(model)
    # Measured on this game: a 192-request batch WROTE its prefix 110 times and read
    # it 93. Batch requests run in PARALLEL, so most start before any cache entry
    # exists. Modelling "1 write, N-1 reads" under-quoted the real bill by 6x.
    WRITE_FRACTION = 0.57
    n_pref = sum(prefix_count.values())
    avg_pref = sum(prefix_tok[p] for p in prefix_count) / max(1, len(prefix_count))
    w = int(n_pref * WRITE_FRACTION)
    print("")
    print(f"cache: {'OFF' if not _CACHE_TTL else _CACHE_TTL + ' TTL'}"
          f"   (under batch parallelism a cached prefix is WRITTEN on ~{WRITE_FRACTION:.0%} "
          "of requests, not once)")
    print("Cost estimate (batch = 50% off). Output ratio is the uncertain half:")
    for r in (1.0, 1.4, 1.8):
        out = int(src_tok * r) + out_scaffold
        out_cost = out / 1e6 * pr["batch_out"]
        nocache = raw_in_tok / 1e6 * pr["batch_in"] + out_cost
        cached = (avg_pref * (w * pr["cache_write"] + (n_pref - w) * pr["cache_read"]) / 1e6
                  + dyn_in_tok / 1e6 * pr["batch_in"] + out_cost)
        live, alt = ((cached, nocache) if _CACHE_TTL else (nocache, cached))
        label, other = (("with cache", "if cache were off") if _CACHE_TTL
                        else ("no cache ", "if cache were on"))
        print(f"  out/in ratio {r}: out~{out:,} tok   "
              f"{label} = ${live:.2f}   ({other} ${alt:.2f})")
    if k:
        print(f"\ntoken counts calibrated against server-side count_tokens "
              f"(heuristic x{k:.3f} over {min(8, n_req)} sampled requests)")
    else:
        print("\ntoken counts are a LOCAL HEURISTIC. Re-run with --exact (needs a credential) "
              "to calibrate against count_tokens.")
    print("Input estimates are reliable; output estimates are not. "
          "Check the real bill once with: batches usage")
    if show_sample and sample:
        print("\n----- SAMPLE USER PROMPT -----\n" + sample[:3000])
    return 0


# --------------------------------------------------------------------------
# submit / status / fetch / run / retry / selftest
# --------------------------------------------------------------------------
def _submit(client, model, requests, id_maps, phase):
    b = client.messages.batches.create(requests=requests)
    print(f"[{phase}] submitted batch {b.id} ({len(requests)} requests).")
    save_state({
        "batch_id": b.id, "model": model, "phase": phase, "id_maps": id_maps,
        "n_requests": len(requests), "created": str(getattr(b, "created_at", "") or ""),
    })
    return b


def cmd_submit(model, max_units, retranslate_all, phase, dedupe=True):
    batch = load_batch()
    glossary = load_glossary()
    n_dnt = apply_dnt(batch, glossary)
    if n_dnt:
        save_batch(batch)
    _g, requests, id_maps = build_all(batch, model, max_units, retranslate_all, phase, dedupe)
    if not requests:
        sys.exit(f"Nothing to translate in phase '{phase}'.")
    client = get_client()
    _submit(client, model, requests, id_maps, phase)
    print("Track with: status / fetch")
    return 0


def cmd_status():
    state = load_state()
    if not state:
        sys.exit("No batch state - run submit first.")
    client = get_client()
    b = client.messages.batches.retrieve(state["batch_id"])
    print(f"batch {b.id} [{state.get('phase')}] : {b.processing_status}")
    rc = getattr(b, "request_counts", None)
    if rc:
        print("  counts:", rc)
        print("  (request_counts is not a progress bar - it can read "
              "processing=N, succeeded=0 for the whole run while tokens are already spent)")
    return 0 if b.processing_status == "ended" else 2


def _fetch(client, state, dedupe=True):
    batch = load_batch()
    results, errored = {}, []
    for r in client.messages.batches.results(state["batch_id"]):
        cid = r.custom_id
        res = r.result
        if res.type != "succeeded":
            detail = res.type
            err = getattr(res, "error", None)
            if err is not None:
                inner = getattr(err, "error", err)
                detail = (f"{res.type} | {getattr(inner, 'type', '')}: "
                          f"{getattr(inner, 'message', '') or str(err)[:200]}")
            errored.append((cid, detail))
            continue
        msg = res.message
        text = "".join(getattr(b, "text", "") for b in msg.content if b.type == "text")
        if getattr(msg, "stop_reason", None) == "max_tokens":
            errored.append((cid, "truncated at max_tokens - the tail of this chunk is lost"))
        try:
            results[cid] = parse_json_object(text)
        except Exception as e:
            errored.append((cid, f"parse_error: {e}"))
    applied, errs = apply_results(batch, results, state.get("id_maps", {}))
    if dedupe:
        fanout(batch, verbose=True)
    save_batch(batch)
    return applied, errored, errs


def cmd_fetch(dedupe=True):
    state = load_state()
    if not state:
        sys.exit("No batch state - run submit first.")
    client = get_client()
    applied, errored, errs = _fetch(client, state, dedupe)
    print(f"Applied {applied} translations.")
    for cid, why in errored[:30]:
        print(f"  ! request {cid}: {why}")
    for e in errs[:20]:
        print(f"  ! {e}")
    return 0


def _run_phase(client, model, requests, id_maps, poll, phase, dedupe=True):
    _submit(client, model, requests, id_maps, phase)
    state = load_state()
    print(f"[{phase}] polling every {poll}s (Ctrl-C is safe - resume with: fetch)...")
    while True:
        b = client.messages.batches.retrieve(state["batch_id"])
        rc = getattr(b, "request_counts", None)
        print(f"  {time.strftime('%H:%M:%S')}  {b.processing_status}"
              + (f"  {rc}" if rc else ""), flush=True)
        if b.processing_status == "ended":
            break
        time.sleep(poll)
    applied, errored, errs = _fetch(client, state, dedupe)
    print(f"[{phase}] applied {applied} translations ({len(errored)} request errors).")
    for cid, why in errored[:30]:
        print(f"  ! {cid}: {why}")
    return applied


def cmd_run(model, max_units, retranslate_all, poll, dedupe=True):
    client = get_client()
    batch = load_batch()
    glossary = load_glossary()
    if not load_game_prompt():
        print("WARNING: tl/game_prompt.md is missing - translating without the game bible.")
    held = holdout_count(batch["lines"])
    if held:
        print(f"NOTE: {held} unit(s) are held out of this run (tl/holdout.json) and will "
              "remain untranslated.")
    n_dnt = apply_dnt(batch, glossary)
    if n_dnt:
        save_batch(batch)
        print(f"{n_dnt} do_not_translate lines pre-filled verbatim.")

    # Phase 1 - names first, so the text phase can lock DB names as terms
    # (a skill or item name embedded in a usage message then matches the menu).
    _g, name_reqs, name_maps = build_all(batch, model, max_units, retranslate_all, "names", dedupe)
    if name_reqs:
        _run_phase(client, model, name_reqs, name_maps, poll, "names", dedupe)
    else:
        print("[names] nothing pending.")

    # Phase 2 - dialogue / DB / UI with the translated names as extra glossary terms.
    batch = load_batch()
    _g, requests, id_maps = build_all(batch, model, max_units, retranslate_all, "text", dedupe)
    if not requests:
        print("[text] nothing pending.")
        return 0
    _run_phase(client, model, requests, id_maps, poll, "text", dedupe)
    print("Next: python scripts/claude_translate.py validate")
    return 0


def cmd_retry(model, max_units, poll, max_rounds, dedupe=True):
    client = get_client()
    glossary = load_glossary()
    game_prompt = load_game_prompt()
    dnt = dnt_set(glossary)
    for rnd in range(1, max_rounds + 1):
        batch = load_batch()
        extra_terms = names_extra_terms(batch)
        lines = batch["lines"]
        fail_idx = {i for i, l in enumerate(lines)
                    if hard_issues(l, dnt) and not is_held_out(l)}
        if not fail_idx:
            print("[retry] nothing failing - batch is clean.")
            return 0
        # bill one representative per failing group, not every sibling
        if dedupe:
            groups = build_groups(lines)
            keep = set()
            for _k, idxs in groups.items():
                f = [i for i in idxs if i in fail_idx]
                if f:
                    keep.add(f[0])
            fail_idx = keep
        # one chunk per scene containing a failure; translated neighbours as context
        by_scene = collections.OrderedDict()
        for i, l in enumerate(lines):
            by_scene.setdefault(scene_key(l), []).append(i)
        chunks = []
        used_ids = set()
        part = 0
        for sk, idxs in by_scene.items():
            fails = [i for i in idxs if i in fail_idx]
            if not fails:
                continue
            ctx = [lines[i] for i in idxs
                   if i not in fail_idx and (lines[i].get("text") or "").strip()][:8]
            for s in range(0, len(fails), max_units):
                chunks.append({
                    "custom_id": _unique_id(f"retry{rnd}", part, used_ids),
                    "items": [(i, lines[i]) for i in fails[s:s + max_units]],
                    "file": sk[0], "context": ctx, "names": is_names_file(sk[0]),
                })
                part += 1
        requests, id_maps = [], {}
        inserts = insert_sentinels(batch)
        for ch in chunks:
            req, idmap = build_request(ch, model, glossary, extra_terms, game_prompt, inserts)
            requests.append(req)
            id_maps[ch["custom_id"]] = idmap
        print(f"[retry round {rnd}/{max_rounds}] {len(fail_idx)} failing representatives "
              f"-> {len(requests)} requests.")
        _run_phase(client, model, requests, id_maps, poll, f"retry{rnd}", dedupe)
    batch = load_batch()
    still = sum(1 for l in batch["lines"] if hard_issues(l, dnt))
    print(f"[retry] done. {still} lines still failing - run `validate` to inspect.")
    return 0


def cmd_repair():
    """Deterministic post-fetch repairs over the whole store, then re-fanout.

    Everything here is unambiguous by construction and idempotent. Nothing that
    needs a judgement call belongs in this pass - a missing or reordered sentinel
    is left to the guard and fixed by `retry`, because a repair that guesses where
    a code went mis-colours or hangs the line.
    """
    batch = load_batch()
    glossary = load_glossary()
    dnt = dnt_set(glossary)
    lines = batch["lines"]

    reverted = edges = newlines = hearts = markers = 0
    tok = _heart_token(batch)
    for l in lines:
        src, tl = l["source"], l.get("text") or ""
        if not tl:
            continue
        # 1. a denylisted row ships as itself, whatever came back
        if src.strip() in dnt and tl != src:
            l["text"] = src
            reverted += 1
            continue
        # 2. the model trims edges; the edges are layout data
        fixed = restore_edge_whitespace(src, tl)
        if fixed != tl:
            edges += 1
            tl = fixed
        # 3. CRLF the JSON transport flattened to LF
        fixed = restore_newline_style(src, tl)
        if fixed != tl:
            newlines += 1
            tl = fixed
        # 4. decorative-heart COUNT only; anything else is left to the guard
        fixed = repair_heart_count(src, tl, tok)
        if fixed is not None and fixed != tl:
            hearts += 1
            tl = fixed
        # 5. the author's deliberate-row marker, folded to a halfwidth space by the
        #    model. relayout only recognises the fullwidth one. `build.py deindent`
        #    takes it back out after relayout has used it.
        fixed = restore_row_markers(src, tl)
        if fixed != tl:
            markers += 1
            tl = fixed
        l["text"] = tl

    print(f"repair: {reverted} denylisted row(s) restored to source, "
          f"{edges} edge-whitespace fix(es), {newlines} CRLF restoration(s), "
          f"{hearts} heart-count fix(es), {markers} row-marker restoration(s)")
    if hearts:
        print(f"  ({tok} = {_HEART_CODE}, a decorative icon. Count matched to the "
              "source; any line where a NON-heart token drifted was left for `retry`.)")
    fanout(batch, verbose=True)
    save_batch(batch)
    return 0


def cmd_fanout():
    batch = load_batch()
    n = fanout(batch, verbose=True)
    if n:
        save_batch(batch)
    return 0


def cmd_selftest(model, max_units, dedupe=True):
    """Offline proof of the wiring: build -> fake-translate -> fanout -> validate.

    The point is that it CALLS the same functions that decide what ships
    (`build_all`, `apply_results`, `fanout`, `hard_issues`). A suite that only
    exercises the primitives certifies its own bugs.
    """
    batch = load_batch()
    glossary = load_glossary()
    apply_dnt(batch, glossary)
    results, id_maps_all = {}, {}
    total_reqs = 0
    for phase in ("names", "text"):
        _g, requests, id_maps = build_all(batch, model, max_units, False, phase, dedupe)
        total_reqs += len(requests)
        id_maps_all.update(id_maps)
        for req in requests:
            cid = req["custom_id"]
            out = {}
            for i, li in enumerate(id_maps[cid], 1):
                # JP -> 'e' keeps every {Wn} token, bracket and line break intact.
                out[str(i)] = re.sub(r"[぀-ヿ一-鿿！-～]", "e", batch["lines"][li]["source"])
            results[cid] = out
    applied, errs = apply_results(batch, results, id_maps_all)
    fanned = fanout(batch, verbose=False) if dedupe else 0

    dnt = dnt_set(glossary)
    filled = [l for l in batch["lines"] if (l.get("text") or "").strip()]
    bad = [l for l in filled
           if [c for c in hard_issues(l, dnt) if c in ("residual_jp", "codes", "pagebreaks")]]
    total = len(batch["lines"])

    # batch.json itself is NOT touched - the fake-filled copy goes to a side file.
    side = os.path.join(TL_DIR, "_selftest_batch.json")
    os.makedirs(TL_DIR, exist_ok=True)
    with open(side, "w", encoding="utf-8") as f:
        json.dump(batch, f, ensure_ascii=False, indent=1)

    print(f"selftest: {total_reqs} requests built")
    print(f"  applied to representatives : {applied}")
    print(f"  fanned out to siblings     : {fanned}")
    print(f"  filled / total             : {len(filled)} / {total}")
    print(f"  index-map errors           : {len(errs)}")
    print(f"  sentinel / JP / pagebreak failures: {len(bad)}")
    for l in bad[:10]:
        print(f"  ! {l['file']} {l['id']}: src{code_multiset(l['source'])} "
              f"tl{code_multiset(l['text'])}")
    held = holdout_count(batch["lines"])
    expected = total - held
    if held:
        print(f"  held out (never sent)      : {held}")
    ok = (not errs) and (not bad) and applied > 0 and len(filled) == expected
    if len(filled) != expected:
        print(f"  ! {expected - len(filled)} line(s) were neither filled nor held out - "
              "a dedup group or a chunk was dropped")
    print("SELFTEST", "PASS" if ok else "FAIL")
    print(f"(fake-filled copy written to {side}; batch.json untouched)")
    return 0 if ok else 1


# --------------------------------------------------------------------------
# batches utility (list / cancel / usage)
# --------------------------------------------------------------------------
def cmd_batches(action, ids, limit, model):
    client = get_client()
    state = load_state() or {}
    mine = state.get("batch_id")
    if action == "list":
        print(f"{'BATCH ID':<28} {'STATUS':<12} {'CREATED':<22}")
        for b in client.messages.batches.list(limit=limit):
            mark = "  <- yours" if b.id == mine else ""
            created = str(getattr(b, "created_at", "") or "")[:22]
            print(f"{b.id:<28} {b.processing_status:<12} {created:<22}{mark}")
        return 0
    if action == "cancel":
        targets = ids or ([mine] if mine else [])
        if not targets:
            sys.exit("No batch id given and none in state.")
        for t in targets:
            try:
                b = client.messages.batches.cancel(t)
                print(f"cancel requested: {t} -> {b.processing_status}")
            except Exception as e:
                print(f"! {t}: {e}")
        return 0
    if action == "usage":
        bid = (ids[0] if ids else mine)
        if not bid:
            sys.exit("Give a batch id (or submit first).")
        tot = collections.Counter()
        ok = err = 0
        for r in client.messages.batches.results(bid):
            res = r.result
            if getattr(res, "type", None) != "succeeded":
                err += 1
                continue
            ok += 1
            u = res.message.usage
            tot["in"] += getattr(u, "input_tokens", 0) or 0
            tot["out"] += getattr(u, "output_tokens", 0) or 0
            tot["cache_write"] += getattr(u, "cache_creation_input_tokens", 0) or 0
            tot["cache_read"] += getattr(u, "cache_read_input_tokens", 0) or 0
        pr = price_for(model)
        cost = (tot["in"] / 1e6 * pr["batch_in"] + tot["out"] / 1e6 * pr["batch_out"]
                + tot["cache_write"] / 1e6 * pr["cache_write"]
                + tot["cache_read"] / 1e6 * pr["cache_read"])
        print(f"batch {bid} ({ok} succeeded, {err} errored)  model={model}")
        for k in ("in", "cache_write", "cache_read", "out"):
            print(f"  {k:<12}: {tot[k]:>12,}")
        billed_in = tot["in"] + tot["cache_write"] + tot["cache_read"]
        if billed_in:
            print(f"  out/in ratio: {tot['out'] / billed_in:.2f}")
        print(f"  estimated cost: ${cost:.2f}")
        return 0
    return 1


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main():
    global _EFFORT, _THINKING, _CACHE_TTL
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_batch_args(p):
        p.add_argument("--model", default=MODEL_DEFAULT)
        p.add_argument("--max-units", dest="max_units", type=int, default=60)
        p.add_argument("--retranslate-all", dest="retranslate_all", action="store_true")
        p.add_argument("--effort", default=EFFORT_DEFAULT, choices=sorted(_EFFORT_LEVELS))
        p.add_argument("--thinking", default="off", choices=["off", "adaptive"])
        p.add_argument("--cache", default="off", choices=["off", "5m", "1h"],
                       help="prompt-cache the system prefix. OFF by default: batch "
                            "requests run in parallel, so the prefix is WRITTEN "
                            "~110 times and read ~93, and a write costs 4x the "
                            "batch input rate. Measured, not assumed.")
        p.add_argument("--no-dedupe", dest="dedupe", action="store_false", default=True,
                       help="bill every unit instead of one per distinct (kind,source). "
                            "10x more expensive on this game.")

    p = sub.add_parser("dryrun")
    add_batch_args(p)
    p.add_argument("--show-sample", dest="show_sample", action="store_true")
    p.add_argument("--exact", action="store_true",
                   help="calibrate token counts against server-side count_tokens "
                        "(needs a credential; still free)")

    p = sub.add_parser("submit")
    add_batch_args(p)
    p.add_argument("--phase", default="text", choices=["names", "text"])

    sub.add_parser("status")
    p = sub.add_parser("fetch")
    p.add_argument("--no-dedupe", dest="dedupe", action="store_false", default=True)

    p = sub.add_parser("run")
    add_batch_args(p)
    p.add_argument("--poll", type=int, default=60)

    p = sub.add_parser("validate")
    p.add_argument("--max-issues", dest="max_issues", type=int, default=25)

    p = sub.add_parser("retry")
    add_batch_args(p)
    p.add_argument("--poll", type=int, default=60)
    p.add_argument("--max-rounds", dest="max_rounds", type=int, default=2)

    p = sub.add_parser("selftest")
    add_batch_args(p)

    sub.add_parser("fanout")
    sub.add_parser("repair")

    p = sub.add_parser("batches")
    p.add_argument("action", choices=["list", "cancel", "usage"])
    p.add_argument("ids", nargs="*")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--model", default=MODEL_DEFAULT)

    args = ap.parse_args()
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if getattr(args, "effort", None):
        _EFFORT = args.effort
    if getattr(args, "thinking", None):
        _THINKING = args.thinking
    c = getattr(args, "cache", "off")
    _CACHE_TTL = "" if c == "off" else c
    dedupe = getattr(args, "dedupe", True)

    if args.cmd == "dryrun":
        return cmd_dryrun(args.model, args.max_units, args.retranslate_all,
                          args.show_sample, args.exact, dedupe)
    if args.cmd == "submit":
        return cmd_submit(args.model, args.max_units, args.retranslate_all, args.phase, dedupe)
    if args.cmd == "status":
        return cmd_status()
    if args.cmd == "fetch":
        return cmd_fetch(dedupe)
    if args.cmd == "run":
        return cmd_run(args.model, args.max_units, args.retranslate_all, args.poll, dedupe)
    if args.cmd == "validate":
        return cmd_validate(args.max_issues)
    if args.cmd == "retry":
        return cmd_retry(args.model, args.max_units, args.poll, args.max_rounds, dedupe)
    if args.cmd == "selftest":
        return cmd_selftest(args.model, args.max_units, dedupe)
    if args.cmd == "fanout":
        return cmd_fanout()
    if args.cmd == "repair":
        return cmd_repair()
    if args.cmd == "batches":
        return cmd_batches(args.action, args.ids, args.limit, args.model)
    return 1


if __name__ == "__main__":
    sys.exit(main() or 0)
