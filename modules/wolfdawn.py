"""Translate WolfDawn extraction JSON.

This module consumes the JSON produced by the vendored WolfDawn ``wolf`` CLI
(``strings-extract`` / ``names-extract``) and fills in the ``text`` fields with
translations, leaving ``source`` untouched so WolfDawn's inject drift-guard can
match each line back to its original.

Supported document ``kind``s (all share the ``{source, text}`` leaf pattern):
    map / common  -> scenes[].lines[]
    db            -> groups[].lines[]
    gamedat       -> lines[]
    txt           -> lines[]
    txt-dir       -> files[].lines[]
    names         -> names[]

Only entries whose ``source`` contains target-language (Japanese by default)
text are sent to the model; everything else keeps ``text == source`` so inject
is a no-op for it.

names.json safety: WolfDawn's ``names-extract`` groups every value name under a
``note`` category, and many categories are logic keys (variable / file / event
names) that break the game if translated. So for ``kind == "names"`` documents,
only entries whose ``note`` is in the opt-in safe list (``SAFE_NOTES``, from
``data/wolf_safe_notes.json`` via :mod:`util.wolf_names`) are translated; the rest
are left as source. The list is empty by default, so nothing is translated until
the user opts categories in from the workflow. After translating names.json, the
safe entries are harvested into ``vocab.txt`` (grouped by ``note``, with bilingual
headers) so later phases (DB descriptions, dialogue) keep item / skill / term
names consistent - the WOLF equivalent of RPGMaker's DB-first glossary seeding.

Text wrapping: translated dialogue is re-wrapped to a character width (like the
RPGMaker module, via :mod:`util.dazedwrap`) so English fits WOLF's message box.
Wrapping is applied to the dialogue *body* only - a speaker's nameplate line (the
``\n`` right after a name) is kept on its own line and never folded into the body.
Configurable from the workflow (``.env``: ``wolfWrap`` / ``wolfWidth``); a width of
0 (or ``wolfWrap=false``) writes the model output back verbatim.

Speakers: WolfDawn tags each line with ``speaker`` / ``speaker_src``. For the
first-line formats (``literal_line1`` / ``literal_line1_lowconf``) the speaker
name is baked into line 1 of ``source``. Those lines are reshaped into the shared
``[Speaker]: line`` convention (which the prompt already translates) and restored
to WOLF's native ``Speaker\nline`` layout on write-back. See ``util.speakers``.
Detection is WolfDawn's, so the reliable nameplate (``literal_line1``) is always
reshaped; only the low-confidence guess (``literal_line1_lowconf``) is gated by a
per-game, AI-recommended setting from the workflow.
"""

import json
import os
import re
import threading
import time
import traceback

from colorama import Fore
from tqdm import tqdm

import util.dazedwrap as dazedwrap
from util.paths import PROMPT_PATH, VOCAB_PATH
from util.translation import (
    TranslationConfig,
    translateAI as sharedtranslateAI,
    getPricingConfig,
    calculateCost,
)
from util import speakers as wolf_speakers
from util import vocab as wolf_vocab
from util import wolf_names

# Globals (mirror the other engine modules; populated from .env at import time)
MODEL = os.getenv("model")
TIMEOUT = int(os.getenv("timeout"))
LANGUAGE = os.getenv("language").capitalize()

PROMPT = PROMPT_PATH.read_text(encoding="utf-8")
VOCAB = VOCAB_PATH.read_text(encoding="utf-8")
LOCK = threading.Lock()
MAXHISTORY = 10
ESTIMATE = ""
TOKENS = [0, 0]
MISMATCH = []  # Files that hit a length-mismatch during translation
FILENAME = None

# Regex - default matches Japanese (kanji, kana, full-width forms).
LANGREGEX = r"[一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９\uFF61-\uFF9F]+"

# Speaker handling: for first-line-speaker formats, reshape the line into the
# shared "[Speaker]: line" transport before translating and restore WOLF's
# native "Speaker\nline" layout on write-back. Which formats are reshaped is
# configurable from the workflow (data/wolf_speakers.json).
SPEAKER_CONFIG = wolf_speakers.load_config()

# names.json safety: WolfDawn tags every value name with a ``note`` category. Many
# categories are logic keys (variable/file/event names) that break the game if
# translated, so only entries whose ``note`` is in this opt-in list are sent to
# the model; the rest keep text == source. Empty by default = translate nothing.
# Configured from the workflow (data/wolf_safe_notes.json).
SAFE_NOTES = wolf_names.load_safe_notes()

# Text wrapping: rewrap translated dialogue to a character width the same way the
# RPGMaker module does (util.dazedwrap), so English lines fit WOLF's message box.
# Only the dialogue *body* is wrapped - the speaker's name line (the "\n" after a
# nameplate) is kept on its own line and never merged into the body. Configurable
# from the workflow (.env: wolfWrap / wolfWidth). Width <= 0 disables wrapping.
WRAP = (os.getenv("wolfWrap", "true").strip().lower() == "true")
try:
    WRAPWIDTH = int(os.getenv("wolfWidth") or 0)
except ValueError:
    WRAPWIDTH = 0

# Pricing / batching from the configured model
PRICING_CONFIG = getPricingConfig(MODEL)
INPUTAPICOST = PRICING_CONFIG["inputAPICost"]
OUTPUTAPICOST = PRICING_CONFIG["outputAPICost"]
BATCHSIZE = PRICING_CONFIG["batchSize"]
FREQUENCY_PENALTY = PRICING_CONFIG["frequencyPenalty"]

# tqdm / progress globals (PBAR is polled by util/subprocess_runner.py)
BAR_FORMAT = "{l_bar}{bar:10}{r_bar}{bar:-10b}"
POSITION = 0
LEAVE = False
PBAR = None

TRANSLATION_CONFIG = TranslationConfig(
    model=MODEL,
    language=LANGUAGE,
    prompt=PROMPT,
    vocab=VOCAB,
    langRegex=LANGREGEX,
    batchSize=BATCHSIZE,
    maxHistory=MAXHISTORY,
    estimateMode=False,
)


def handleWolfDawn(filename, estimate):
    """Entry point used by the CLI/GUI dispatchers. Returns a summary string or 'Fail'."""
    global ESTIMATE, TOKENS, FILENAME, SAFE_NOTES, SPEAKER_CONFIG, VOCAB
    ESTIMATE = estimate
    FILENAME = filename
    # Re-read workflow-configured settings so edits made this session take effect
    # even when translation runs in-process (the module import is cached).
    SAFE_NOTES = wolf_names.load_safe_notes()
    SPEAKER_CONFIG = wolf_speakers.load_config()
    # Reload the glossary so a later phase (DB text / dialogue) picks up names
    # that an earlier Phase 0 (names) harvested into vocab.txt.
    VOCAB = VOCAB_PATH.read_text(encoding="utf-8")
    TRANSLATION_CONFIG.vocab = VOCAB

    start = time.time()
    translatedData = openFiles(filename)

    if not estimate:
        try:
            with open("translated/" + filename, "w", encoding="utf-8", newline="\n") as outFile:
                json.dump(translatedData[0], outFile, ensure_ascii=False, indent=4)
        except Exception:
            traceback.print_exc()
            return "Fail"

    end = time.time()
    tqdm.write(getResultString(translatedData, end - start, filename))
    with LOCK:
        TOKENS[0] += translatedData[1][0]
        TOKENS[1] += translatedData[1][1]

    totalString = getResultString(["", TOKENS, None], end - start, "TOTAL")
    if len(MISMATCH) > 0:
        return totalString + Fore.RED + f"\nMismatch Errors: {MISMATCH}" + Fore.RESET
    return totalString


def openFiles(filename):
    """Load the extraction JSON, translate it in place, and return [data, tokens, error]."""
    with open("files/" + filename, "r", encoding="utf-8-sig") as f:
        data = json.load(f)

    kind = data.get("kind")
    if kind not in ("map", "common", "db", "gamedat", "txt", "txt-dir", "names"):
        raise NameError(
            f"{filename}: unrecognised WolfDawn document (kind={kind!r}). "
            "Expected a strings-extract or names-extract JSON."
        )
    return parseDocument(data, filename)


def collectEntries(data):
    """Return the list of leaf {source, text} dicts for a WolfDawn document.

    The returned dicts are live references into ``data`` so mutating ``text``
    updates the document that gets written back out.
    """
    kind = data.get("kind")
    entries = []

    if kind in ("map", "common"):
        for scene in data.get("scenes") or []:
            for line in scene.get("lines") or []:
                entries.append(line)
    elif kind == "db":
        for group in data.get("groups") or []:
            for line in group.get("lines") or []:
                entries.append(line)
    elif kind in ("gamedat", "txt"):
        for line in data.get("lines") or []:
            entries.append(line)
    elif kind == "txt-dir":
        for fileDoc in data.get("files") or []:
            for line in fileDoc.get("lines") or []:
                entries.append(line)
    elif kind == "names":
        for name in data.get("names") or []:
            entries.append(name)

    return entries


def _wrap_body(body):
    """Word-wrap a dialogue body to WRAPWIDTH (no-op when wrapping is disabled)."""
    if not WRAP or WRAPWIDTH <= 0 or not isinstance(body, str) or not body:
        return body
    return dazedwrap.wrapText(body, WRAPWIDTH)


def _wrap_plain(text, is_firstline):
    """Wrap a non-reshaped entry, protecting a nameplate first line if present.

    ``is_firstline`` is True for first-line-speaker formats that are turned off in
    the config: their model output is still ``Speaker\\nbody``, so line 1 (the
    name) is kept intact and only the body is wrapped. Any leading ``@<option>``
    window prefix is also preserved.
    """
    if not WRAP or WRAPWIDTH <= 0 or not isinstance(text, str) or not text:
        return text
    prefix, rest = wolf_speakers.split_window_prefix(text)
    if is_firstline and "\n" in rest:
        name, body = rest.split("\n", 1)
        return prefix + name + "\n" + _wrap_body(body)
    return prefix + _wrap_body(rest)


def parseDocument(data, filename):
    """Translate every translatable leaf entry and return [data, tokens, error]."""
    global PBAR
    totalTokens = [0, 0]

    entries = collectEntries(data)
    is_names = data.get("kind") == "names"

    def _translatable(e):
        src = e.get("source")
        if not (isinstance(src, str) and re.search(LANGREGEX, src)):
            return False
        # names.json: only translate categories the user marked safe (by note).
        if is_names and not wolf_names.is_note_safe(e.get("note", ""), SAFE_NOTES):
            return False
        return True

    # Only translate entries that actually contain target-language text (and, for
    # names.json, sit in a safe note category); the rest keep text == source so
    # WolfDawn treats them as untouched on inject.
    translatable = [e for e in entries if _translatable(e)]

    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=len(translatable), leave=LEAVE) as pbar:
        pbar.desc = filename
        PBAR = pbar
        if not translatable:
            return [data, totalTokens, None]

        # Reshape first-line-speaker lines into the shared "[Speaker]: line"
        # transport format. plans[i] carries what is needed to restore each
        # entry after translation.
        sources = []
        plans = []  # (entry, prefix, has_speaker, is_firstline)
        for entry in translatable:
            src = entry["source"]
            is_firstline = entry.get("speaker_src", "") in wolf_speakers.FIRSTLINE_SRCS
            split = wolf_speakers.split_source(src, entry.get("speaker_src", ""), SPEAKER_CONFIG)
            if split is not None:
                prefix, speaker, body = split
                sources.append(wolf_speakers.to_prefixed(speaker, body))
                plans.append((entry, prefix, True, is_firstline))
            else:
                sources.append(src)
                plans.append((entry, "", False, is_firstline))

        try:
            response = translateAI(sources, [])
        except Exception as e:
            return [data, totalTokens, e]

        translated, tokens = response[0], response[1]
        totalTokens[0] += tokens[0]
        totalTokens[1] += tokens[1]

        # Write translations back (skip in estimate mode: translated == sources).
        if not ESTIMATE and isinstance(translated, list) and len(translated) == len(plans):
            for (entry, prefix, has_speaker, is_firstline), text in zip(plans, translated):
                if not isinstance(text, str):
                    continue
                if has_speaker:
                    speaker_en, body_en = wolf_speakers.parse_prefixed(text)
                    if speaker_en is not None:
                        # Wrap only the body; the name stays on its own line.
                        entry["text"] = wolf_speakers.restore_source(
                            prefix, speaker_en, _wrap_body(body_en)
                        )
                    else:
                        # Model dropped the [Speaker]: prefix; keep its output as-is.
                        entry["text"] = prefix + _wrap_body(text)
                else:
                    entry["text"] = _wrap_plain(text, is_firstline)

    # Phase 0 feeds the glossary: harvest the just-translated safe name values
    # into vocab.txt (grouped by note) so the DB-text and dialogue phases keep
    # item/skill/term names consistent. Mirrors the RPGMaker DB-first strategy.
    if is_names and not ESTIMATE:
        _harvest_names_to_vocab(data)

    return [data, totalTokens, None]


def _harvest_names_to_vocab(data):
    """Write translated safe names.json entries into vocab.txt, grouped by note.

    Each note category becomes a bilingual ``# English · 日本語`` section (English
    sourced from the staged DB labels, else a static map, else JP-only). Only
    safe notes with an actual translation are written; the base vocab section is
    preserved by :func:`util.vocab.update_vocab_section`.
    """
    try:
        db_labels = wolf_names.derive_db_labels("files")
        by_note: dict[str, list] = {}
        for entry in data.get("names") or []:
            note = entry.get("note", "")
            if not wolf_names.is_note_safe(note, SAFE_NOTES):
                continue
            src, dst = entry.get("source"), entry.get("text")
            if not isinstance(src, str) or not isinstance(dst, str):
                continue
            by_note.setdefault(note, []).append((src, dst))
        for note, pairs in by_note.items():
            wolf_vocab.update_vocab_section(wolf_names.note_header(note, db_labels), pairs)
    except Exception:
        traceback.print_exc()


def getResultString(translatedData, translationTime, filename):
    """Format the per-file / total cost + status line for the console log."""
    cost = calculateCost(translatedData[1][0], translatedData[1][1], MODEL)
    totalTokenstring = (
        Fore.YELLOW + "[Input: " + str(translatedData[1][0]) + "]"
        "[Output: " + str(translatedData[1][1]) + "]"
        "[Cost: ${:,.4f}".format(cost) + "]"
    )
    timeString = Fore.BLUE + "[" + str(round(translationTime, 1)) + "s]"

    if translatedData[2] is None:
        return filename + ": " + totalTokenstring + timeString + Fore.GREEN + " \u2713 " + Fore.RESET
    try:
        raise translatedData[2]
    except Exception as e:
        traceback.print_exc()
        errorString = str(e) + Fore.RED
        return (
            filename + ": " + totalTokenstring + timeString
            + Fore.RED + " \u2717 " + errorString + Fore.RESET
        )


def translateAI(text, history, history_ctx=None):
    """Thin wrapper around the shared translation entry point."""
    global PBAR, MISMATCH, FILENAME
    TRANSLATION_CONFIG.estimateMode = bool(ESTIMATE)
    return sharedtranslateAI(
        text=text,
        history=history,
        config=TRANSLATION_CONFIG,
        filename=FILENAME,
        pbar=PBAR,
        lock=LOCK,
        mismatchList=MISMATCH,
    )
