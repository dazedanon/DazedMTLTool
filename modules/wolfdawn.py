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

names.json safety: WolfDawn tags every value name with a static ``safety`` badge
(``safe``, ``refs``, or ``verify``). For ``kind == "names"`` documents, only
entries whose badge is ``safe`` or ``refs`` are translated; ``verify`` names and
legacy entries without a badge keep ``text == source``. After translating
names.json, translatable entries are harvested into ``vocab.txt`` (grouped by
``note``, with bilingual headers) so later phases keep item / skill / term names
consistent.

Text wrapping: optional advanced ``wolfWrap`` / ``wolfWidth`` (via :mod:`util.dazedwrap`)
can still re-wrap dialogue bodies at translate time, but the normal Wolf workflow
leaves JSON line breaks alone and runs WolfDawn ``relayout`` after inject (Step 5)
to fit the message box. Defaults to off (``wolfWrap=false``).

names.json category wrap (Step 3): selected ``note`` categories can be re-wrapped
with dazedwrap at a dedicated width (``.env``: ``wolfNameWrap``,
``wolfNameWrapWidth``, ``wolfNameWrapNotes``). Other name categories keep the
model output verbatim.

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

# names.json: translate per-entry safe/refs badges only (see util.wolf_names).

# Text wrapping: optional advanced rewrap via dazedwrap (wolfWrap/wolfWidth). Defaults
# off - the workflow uses WolfDawn relayout after inject instead.
WRAP = (os.getenv("wolfWrap", "false").strip().lower() == "true")
try:
    WRAPWIDTH = int(os.getenv("wolfWidth") or 0)
except ValueError:
    WRAPWIDTH = 0

# names.json: optional per-category dazedwrap (Step 3 workflow UI).
NAME_WRAP_ENABLED, NAME_WRAP_WIDTH, NAME_WRAP_NOTES = wolf_names.load_name_wrap_config()


def reload_name_wrap_config() -> None:
    """Re-read names.json category wrap settings from ``.env``."""
    global NAME_WRAP_ENABLED, NAME_WRAP_WIDTH, NAME_WRAP_NOTES
    NAME_WRAP_ENABLED, NAME_WRAP_WIDTH, NAME_WRAP_NOTES = wolf_names.load_name_wrap_config()

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
    global ESTIMATE, TOKENS, FILENAME, SPEAKER_CONFIG, VOCAB
    ESTIMATE = estimate
    FILENAME = filename
    # Re-read workflow-configured settings so edits made this session take effect
    # even when translation runs in-process (the module import is cached).
    SPEAKER_CONFIG = wolf_speakers.load_config()
    reload_name_wrap_config()
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


def _wrap_names_entry(text, entry):
    """Apply dazedwrap to a names.json entry when its ``note`` is selected in Step 3."""
    if not NAME_WRAP_ENABLED or NAME_WRAP_WIDTH <= 0:
        return text
    if not isinstance(text, str) or not text:
        return text
    note = str(entry.get("note", ""))
    if note not in NAME_WRAP_NOTES:
        return text
    return dazedwrap.wrapText(text, NAME_WRAP_WIDTH)


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
        # names.json: only translate WolfDawn safe/refs entries (per-name badge).
        if is_names and not wolf_names.is_name_translatable(e):
            return False
        return True

    # Only translate entries that actually contain target-language text (and, for
    # names.json, carry a translatable safety badge); the rest keep text == source so
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
                if is_names:
                    entry["text"] = _wrap_names_entry(text, entry)
                elif has_speaker:
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
    """Write short translated name labels into vocab.txt, grouped by note.

    Profile blurbs and other content-shaped names are translated in names.json but
    skipped here. Categories with no harvestable terms remove any stale section.
    """
    try:
        db_labels = wolf_names.derive_db_labels("files")
        by_note: dict[str, list] = {}
        touched_notes: set[str] = set()
        for entry in data.get("names") or []:
            if not wolf_names.is_name_translatable(entry):
                continue
            note = str(entry.get("note", ""))
            touched_notes.add(note)
            if not wolf_names.is_vocab_harvest_candidate(entry):
                continue
            src, dst = entry.get("source"), entry.get("text")
            if not isinstance(src, str) or not isinstance(dst, str):
                continue
            by_note.setdefault(note, []).append((src, dst))
        for note in touched_notes:
            header = wolf_names.note_header(note, db_labels)
            pairs = by_note.get(note, [])
            if pairs:
                wolf_vocab.update_vocab_section(header, pairs)
            else:
                wolf_vocab.remove_vocab_section(header)
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
