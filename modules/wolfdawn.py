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
is a no-op for it. Translated text is written back verbatim (no re-wrapping) to
keep WolfDawn's inline-code and byte-exact guards happy.

Speakers: WolfDawn tags each line with ``speaker`` / ``speaker_src``. For the
first-line formats (``literal_line1`` / ``literal_line1_lowconf``) the speaker
name is baked into line 1 of ``source``. Those lines are reshaped into the shared
``[Speaker]: line`` convention (which the prompt already translates) and restored
to WOLF's native ``Speaker\nline`` layout on write-back. See ``util.speakers``;
which formats are reshaped is configurable from the workflow.
"""

import json
import os
import re
import threading
import time
import traceback

from colorama import Fore
from tqdm import tqdm

from util.paths import PROMPT_PATH, VOCAB_PATH
from util.translation import (
    TranslationConfig,
    translateAI as sharedtranslateAI,
    getPricingConfig,
    calculateCost,
)
from util import speakers as wolf_speakers

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
    global ESTIMATE, TOKENS, FILENAME
    ESTIMATE = estimate
    FILENAME = filename

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


def parseDocument(data, filename):
    """Translate every translatable leaf entry and return [data, tokens, error]."""
    global PBAR
    totalTokens = [0, 0]

    entries = collectEntries(data)
    # Only translate entries that actually contain target-language text; the rest
    # keep text == source so WolfDawn treats them as untouched on inject.
    translatable = [
        e for e in entries
        if isinstance(e.get("source"), str) and re.search(LANGREGEX, e["source"])
    ]

    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=len(translatable), leave=LEAVE) as pbar:
        pbar.desc = filename
        PBAR = pbar
        if not translatable:
            return [data, totalTokens, None]

        # Reshape first-line-speaker lines into the shared "[Speaker]: line"
        # transport format. plans[i] carries what is needed to restore each
        # entry after translation.
        sources = []
        plans = []  # (entry, prefix, has_speaker)
        for entry in translatable:
            src = entry["source"]
            split = wolf_speakers.split_source(src, entry.get("speaker_src", ""), SPEAKER_CONFIG)
            if split is not None:
                prefix, speaker, body = split
                sources.append(wolf_speakers.to_prefixed(speaker, body))
                plans.append((entry, prefix, True))
            else:
                sources.append(src)
                plans.append((entry, "", False))

        try:
            response = translateAI(sources, [])
        except Exception as e:
            return [data, totalTokens, e]

        translated, tokens = response[0], response[1]
        totalTokens[0] += tokens[0]
        totalTokens[1] += tokens[1]

        # Write translations back (skip in estimate mode: translated == sources).
        if not ESTIMATE and isinstance(translated, list) and len(translated) == len(plans):
            for (entry, prefix, has_speaker), text in zip(plans, translated):
                if not isinstance(text, str):
                    continue
                if has_speaker:
                    speaker_en, body_en = wolf_speakers.parse_prefixed(text)
                    if speaker_en is not None:
                        entry["text"] = wolf_speakers.restore_source(prefix, speaker_en, body_en)
                    else:
                        # Model dropped the [Speaker]: prefix; keep its output as-is.
                        entry["text"] = prefix + text
                else:
                    entry["text"] = text

    return [data, totalTokens, None]


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
