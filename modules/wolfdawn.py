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
is a no-op for it. When ``IGNORETLTEXT`` is on (default), entries whose ``text``
is already translated are skipped so Phase 2 can resume a partial run without
retranslating completed lines. Skip looks past Japanese nameplates on line 1
and Japanese embedded only in WOLF control codes (e.g. ``\\r[...]`` ruby).

names.json safety: WolfDawn tags every value name with a static ``safety`` badge
(``safe``, ``refs``, or ``verify``). For ``kind == "names"`` documents, only
entries whose badge is ``safe`` are translated; ``refs`` and ``verify`` names and
legacy entries without a badge keep ``text == source``. After translating
names.json, short name-like entries are harvested into ``vocab.txt`` (grouped by
``note``, with bilingual headers). After foundation DB sheets are translated,
short label fields (map names, titles, etc.) are merged into the same glossary
so later phases keep place / term names consistent without overwriting names.json.

Database sheet filter (Step 4): optional ``wolfDbIncludeGroups`` or
``wolfDbIncludeTiers`` in ``.env`` limit which ``kind: db`` lines are collected.
When unset, all database lines are translated.

Speakers: WolfDawn tags each line with ``speaker`` / ``speaker_src``. For the
first-line formats (``literal_line1`` / ``literal_line1_lowconf``) the speaker
name is baked into line 1 of ``source``. Those lines are reshaped into the shared
``[Speaker]: line`` convention (which the prompt already translates) and restored
to WOLF's native ``Speaker\nline`` layout on write-back. See ``util.speakers``.
Detection is WolfDawn's, so the reliable nameplate (``literal_line1``) is always
reshaped; only the low-confidence guess (``literal_line1_lowconf``) is gated by a
per-game, AI-recommended setting from the workflow.

Layout restore: after each file is written to ``translated/``, ``wolf
layout-restore`` copies unambiguous positional whitespace pads from ``source``
onto ``text`` (status-card ``<pad>\\nNAME`` fields the model often strips).
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
from util import vocab as wolf_vocab
from util import wolfdawn
from util.wolfdawn import codes as wolf_codes
from util.wolfdawn import db_classify as wolf_db
from util.wolfdawn import names as wolf_names

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

# Skip lines whose ``text`` is already translated. WolfDawn keeps Japanese in
# ``source`` forever, so skip-translated must look at ``text``, not ``source``.
# Set False for a forced full retranslate.
IGNORETLTEXT = True

# Control codes that can embed Japanese inside an otherwise-translated line
# (ruby ``\r[kanji,kana]``, colour / font indexes, ``\cself[n]``, etc.).
_WOLF_CODE_RE = re.compile(
    r"\\(?:r\[[^\]]*\]|c(?:self)?\[[^\]]*\]|[A-Za-z]+\[[^\]]*\]|[A-Za-z])"
)

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


def _batch_phase() -> str:
    """Current Anthropic batch phase from the GUI subprocess env (``collect`` / ``consume``)."""
    return (os.getenv("BATCH_PHASE") or "").strip().lower()


def handleWolfDawn(filename, estimate):
    """Entry point used by the CLI/GUI dispatchers. Returns a summary string or 'Fail'."""
    global ESTIMATE, TOKENS, FILENAME, SPEAKER_CONFIG, VOCAB
    ESTIMATE = estimate
    FILENAME = filename
    # Re-read workflow-configured settings so edits made this session take effect
    # even when translation runs in-process (the module import is cached).
    SPEAKER_CONFIG = wolf_speakers.load_config()
    # Reload the glossary so a later phase (DB text / dialogue) picks up names
    # that an earlier Phase 0 (names) harvested into vocab.txt.
    VOCAB = VOCAB_PATH.read_text(encoding="utf-8")
    TRANSLATION_CONFIG.vocab = VOCAB

    start = time.time()
    translatedData = openFiles(filename)

    # Batch collect only queues API requests; text is still Japanese. Writing
    # translated/ here would overwrite prior work with source echoed back.
    # Real English is written on the consume pass (or a live non-batch run).
    if not estimate and _batch_phase() != "collect":
        out_path = "translated/" + filename
        try:
            with open(out_path, "w", encoding="utf-8", newline="\n") as outFile:
                json.dump(translatedData[0], outFile, ensure_ascii=False, indent=4)
        except Exception:
            traceback.print_exc()
            return "Fail"
        # Restore positional whitespace pads the model dropped (status-card
        # ``<pad>\nNAME`` fields, etc.). WolfDawn edits the JSON in place.
        try:
            res = wolfdawn.layout_restore(out_path)
            if not res.ok:
                tqdm.write(
                    Fore.YELLOW
                    + f"{filename}: layout-restore exited {res.returncode}"
                    + (f" ({res.stderr.strip()})" if res.stderr.strip() else "")
                    + Fore.RESET
                )
            else:
                fixed = wolfdawn.parse_layout_restore_counts(res.stdout, res.stderr)
                if fixed:
                    tqdm.write(
                        Fore.CYAN
                        + f"{filename}: layout-restore fixed {fixed} line(s)"
                        + Fore.RESET
                    )
        except Exception:
            traceback.print_exc()

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
        include_tiers, include_groups = wolf_db.load_db_filter_config()
        json_file = wolf_db.json_file_from_doc(data)
        for group in data.get("groups") or []:
            type_name = str(group.get("typeName") or "")
            if not wolf_db.group_matches_filter(
                json_file, type_name, include_tiers, include_groups
            ):
                continue
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


def _text_check_body(text: str, speaker_src: str = "") -> str:
    """Body text used for skip-translated checks (nameplates / codes ignored).

    Already-translated WOLF dialogue often keeps a Japanese speaker name on
    line 1 (``司祭\\nSorry to keep you...``) and may embed Japanese only inside
    control codes like ``\\r[我,わ]``. Those lines are finished translations.
    """
    if not isinstance(text, str):
        return ""
    _prefix, rest = wolf_speakers.split_window_prefix(text)
    if "\n" in rest:
        first, body = rest.split("\n", 1)
        # Known first-line speaker formats, or a short nameplate-like first line.
        if (
            speaker_src in wolf_speakers.FIRSTLINE_SRCS
            or speaker_src in ("ui", "narration")
            or (0 < len(first.strip()) <= 20 and re.search(LANGREGEX, first))
        ):
            rest = body
    return _WOLF_CODE_RE.sub("", rest)


def _text_still_needs_translation(entry) -> bool:
    """True when ``text`` still needs the model (empty, Japanese, or identical)."""
    txt = entry.get("text")
    if not isinstance(txt, str) or not txt.strip():
        return True
    src = entry.get("source")
    # Fresh / unfinished extract: text still mirrors Japanese source.
    if isinstance(src, str) and txt == src:
        return True
    # Fully English (no Japanese chars at all).
    if not re.search(LANGREGEX, txt):
        return False
    # Japanese only in the nameplate / control codes while the body is done.
    return bool(re.search(LANGREGEX, _text_check_body(txt, entry.get("speaker_src", ""))))


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
        # Already translated: look at ``text`` (source stays Japanese forever).
        # Fresh extracts keep ``text == source``, so they still queue.
        if IGNORETLTEXT and not _text_still_needs_translation(e):
            return False
        # names.json: only translate WolfDawn safe entries (per-name badge).
        if is_names and not wolf_names.is_name_translatable(e):
            return False
        return True

    # Only translate entries that still need work; names.json also requires a
    # safe badge. Untouched leaves keep ``text == source`` so WolfDawn
    # treats them as no-ops on inject.
    translatable = [e for e in entries if _translatable(e)]

    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=len(translatable), leave=LEAVE) as pbar:
        pbar.desc = filename
        PBAR = pbar
        if translatable:
            # Reshape first-line-speaker lines into the shared "[Speaker]: line"
            # transport format. plans[i] carries what is needed to restore each
            # entry after translation.
            sources = []
            plans = []  # (entry, prefix, has_speaker, is_firstline, code_map)
            for entry in translatable:
                src = entry["source"]
                protected_src, code_map = wolf_codes.protect_wolf_codes(src)
                is_firstline = entry.get("speaker_src", "") in wolf_speakers.FIRSTLINE_SRCS
                split = wolf_speakers.split_source(
                    protected_src, entry.get("speaker_src", ""), SPEAKER_CONFIG
                )
                if split is not None:
                    prefix, speaker, body = split
                    sources.append(wolf_speakers.to_prefixed(speaker, body))
                    plans.append((entry, prefix, True, is_firstline, code_map))
                else:
                    sources.append(protected_src)
                    plans.append((entry, "", False, is_firstline, code_map))

            try:
                response = translateAI(sources, [])
            except Exception as e:
                return [data, totalTokens, e]

            translated, tokens = response[0], response[1]
            totalTokens[0] += tokens[0]
            totalTokens[1] += tokens[1]

            # Write translations back. Skip estimate mode, and skip the batch
            # collect pass (response is still the Japanese source list — wrapping
            # it into ``text`` only reflows JP and is what poisoned translated/).
            collecting = _batch_phase() == "collect"
            if (
                not ESTIMATE
                and not collecting
                and isinstance(translated, list)
                and len(translated) == len(plans)
            ):
                for (entry, prefix, has_speaker, is_firstline, code_map), text, src in zip(
                    plans, translated, sources
                ):
                    if not isinstance(text, str):
                        continue
                    # Model / collect echoed the sent payload — leave the entry alone.
                    if text == src:
                        continue
                    text = wolf_codes.restore_wolf_code_placeholders(text, code_map)
                    if has_speaker:
                        speaker_en, body_en = wolf_speakers.parse_prefixed(text)
                        if speaker_en is not None:
                            entry["text"] = wolf_speakers.restore_source(
                                prefix, speaker_en, body_en
                            )
                        else:
                            entry["text"] = prefix + text
                    else:
                        entry["text"] = text
                    wolf_codes.repair_entry(entry)

    # Phase 0 feeds the glossary: harvest safe name values into vocab.txt
    # (grouped by note) so the DB-text and dialogue phases keep item/skill/term
    # names consistent. Runs even when every name was already translated (skip),
    # so a resume still seeds vocab. Mirrors the RPGMaker DB-first strategy.
    if is_names and not ESTIMATE:
        _harvest_names_to_vocab(data)
    # Foundation DB label fields (map names, titles) merge into vocab.txt without
    # replacing entries already seeded from names.json.
    elif data.get("kind") == "db" and not ESTIMATE:
        _harvest_db_to_vocab(data)

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


def _harvest_db_to_vocab(data):
    """Merge short foundation DB labels into vocab.txt, grouped by sheet.

    Uses merge mode so names.json-seeded entries for the same section stay put.
    Descriptions and narrative dialogue are filtered out.
    """
    try:
        include_tiers, include_groups = wolf_db.load_db_filter_config()
        by_sheet = wolf_db.collect_db_vocab_pairs(
            data,
            include_tiers=include_tiers,
            include_groups=include_groups,
        )
        for type_name, pairs in by_sheet.items():
            wolf_vocab.update_vocab_section(type_name, pairs, merge=True)
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
