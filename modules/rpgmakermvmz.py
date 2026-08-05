# Libraries
import json
import os
import re
import util.dazedwrap as dazedwrap
import threading
import time
import traceback
import copy
from pathlib import Path
import shutil
from colorama import Fore
from dotenv import load_dotenv
from retry import retry
from tqdm import tqdm
from util.translation import TranslationConfig, translateAI as sharedtranslateAI, getPricingConfig, calculateCost, getPricingConfig, calculateCost, get_var_translation, set_var_translations_batch, convert_corner_brackets, parseVocabWithCategories, last_translation_had_mismatch
from util.speakers import SPEAKER_BRACKET_INNER, strip_speaker_prefix
from util.skills import ctx, load_system_prompt
from util.paths import active_glossary_path, read_active_glossary

# Globals
MODEL = os.getenv("model")
TIMEOUT = int(os.getenv("timeout"))
LANGUAGE = os.getenv("language").capitalize()

PROMPT = load_system_prompt()
VOCAB_PATH = active_glossary_path()
VOCAB = read_active_glossary()
LOCK = threading.Lock()
THREAD_CTX = threading.local()
WIDTH = int(os.getenv("width"))
FACEWIDTH = max(
    1,
    min(WIDTH, int(os.getenv("faceWidth", str(max(1, WIDTH - 10))))),
)
LISTWIDTH = int(os.getenv("listWidth"))
NOTEWIDTH = int(os.getenv("noteWidth"))
MAXHISTORY = 10
ESTIMATE = ""
TOKENS = [0, 0]
MISMATCH = []  # Lists files that throw a mismatch error (Length of GPT list response is wrong)
PBAR = None
FILENAME = None
TIMETOTAL = 0  # Total Time Taken for all translations
PREFLIGHT_COUNT_MODE = False  # When True, translateAI wrapper only counts units and never calls API

# Speakers
NAMESLIST = []
SPEAKER_PARSE_MODE = False
_speakerCache = {}
_speakerCacheLock = threading.Lock()
SPEAKER_COLLECTED = []  # Original speaker names collected during parse mode (untranslated)
_speakerVocabLock = threading.Lock()
_speakerVocabSource = None
_speakerVocabExact = {}
_speakerVocabCharacterPairs = []

# Actor variable substitution (\n[X] -> name before AI, name -> \n[X] after)
_ACTOR_MAP_CACHE: dict | None = None
_ACTOR_MAP_CACHE_LOCK = threading.Lock()
_VAR_ACTOR_RE = re.compile(r"\\n\[(\d+)\]", re.IGNORECASE)

# Regex - Need to change this if you want to translate from/to other languages. Default is Japanese Regex
LANGREGEX = r"[\u3000\u3002-\u3009\u300C-\u303F\u3040-\u309A\u309C-\u30FA\u31F0-\u31FF\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\uFF61-\uFF9F]+"

# Get pricing configuration based on the model
PRICING_CONFIG = getPricingConfig(MODEL)
INPUTAPICOST = PRICING_CONFIG["inputAPICost"]
OUTPUTAPICOST = PRICING_CONFIG["outputAPICost"]
BATCHSIZE = PRICING_CONFIG["batchSize"]
FREQUENCY_PENALTY = PRICING_CONFIG["frequencyPenalty"]

# tqdm Globals
BAR_FORMAT = "{desc}: {percentage:3.0f}%|{bar:10}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}{postfix}]"
POSITION = 0

# Initialize Translation Config
TRANSLATION_CONFIG = TranslationConfig(
    model=MODEL,
    language=LANGUAGE,
    prompt=PROMPT,
    vocab=VOCAB,
    langRegex=LANGREGEX,
    batchSize=BATCHSIZE,
    maxHistory=MAXHISTORY,
    estimateMode=False  # Will be set dynamically based on ESTIMATE
)
LEAVE = False


def refreshRuntimeConfig():
    """Refresh import-time translation settings for in-process GUI workflows."""
    global MODEL, TIMEOUT, LANGUAGE, PROMPT, VOCAB_PATH, VOCAB
    global PRICING_CONFIG, INPUTAPICOST, OUTPUTAPICOST, BATCHSIZE, FREQUENCY_PENALTY

    MODEL = os.getenv("model") or MODEL
    LANGUAGE = os.getenv("language", LANGUAGE or "English").capitalize()
    try:
        TIMEOUT = int(os.getenv("timeout", str(TIMEOUT)))
    except (TypeError, ValueError):
        pass
    PROMPT = load_system_prompt()
    VOCAB_PATH = active_glossary_path()
    try:
        from util.vocab import (
            BATCH_GLOSSARY_FREEZE_FILE,
            batch_glossary_phase,
            read_translation_glossary,
        )

        # Collect pins prompts to the freeze (same as live at collect start).
        # Consume loads the live glossary so sequential harvests from earlier
        # files are visible; paid result keys still use the freeze separately.
        if (
            batch_glossary_phase() == "collect"
            and BATCH_GLOSSARY_FREEZE_FILE.is_file()
        ):
            VOCAB = read_translation_glossary()
        else:
            VOCAB = read_active_glossary()
    except Exception:
        VOCAB = read_active_glossary()
    PRICING_CONFIG = getPricingConfig(MODEL)
    INPUTAPICOST = PRICING_CONFIG["inputAPICost"]
    OUTPUTAPICOST = PRICING_CONFIG["outputAPICost"]
    BATCHSIZE = PRICING_CONFIG["batchSize"]
    FREQUENCY_PENALTY = PRICING_CONFIG["frequencyPenalty"]

    TRANSLATION_CONFIG.model = MODEL
    TRANSLATION_CONFIG.language = LANGUAGE
    TRANSLATION_CONFIG.prompt = PROMPT
    TRANSLATION_CONFIG.vocab = VOCAB
    TRANSLATION_CONFIG.batchSize = BATCHSIZE
    TRANSLATION_CONFIG.convertQuotes = os.getenv(
        "convertQuotes", "true"
    ).strip().lower() in ("true", "1", "yes")
    TRANSLATION_CONFIG.useSfxReference = os.getenv(
        "useSfxReference", "true"
    ).strip().lower() in ("true", "1", "yes")
    return TRANSLATION_CONFIG

# Config (Default)
# FIRSTLINESPEAKERS: Guess speaker from first line.
FIRSTLINESPEAKERS = True
# INLINE401SPEAKERS: Extract speaker from "Name「dialogue」" inline format on 401 lines.
INLINE401SPEAKERS = False
# FACENAME101: Map face name -> speaker.
FACENAME101 = False
# Face name -> speaker mapping for FACENAME101.
# Matching: if face string contains "_talk", split on it and look up the prefix;
# otherwise try startswith against each key (longest key first).
FACENAME101_MAP = {
    "_Daijin": "Minister",
    "__HA": "Count Bampton",
    "__Labyrinth": "Labyrinth",
    "___Nimurda": "Nimurda",
    "___Ren": "Ren",
    "___prince": "Prince Elliot",
    "___princess1": "Lilifa",
    "___princess2": "Lilifa",
    "___princess2_2": "Lilifa",
    "___princess3": "Lilifa",
    "___princess4": "Lilifa",
    "___princess5": "Lilifa",
    "__opHA": "Count Bampton",
    "__opRen": "Ren",
    "__opλ": "Lambda",
    "__λ": "Lambda",
    "_girl": "Receptionist",
    "_guard_F": "Female Guard",
    "_guard_M": "Guard",
    "_guard_M1": "Guard 1",
    "_guard_M10": "Guard 2",
    "_king": "King",
    "_knight": "Guard 3",
    "_made1": "Maid 3",
    "_made2": "Maid 2",
    "_made3": "Maid 1",
    "_queen": "Queen",
    "_toy": "Toy Store Manager",
    "made2": "Maid 2",
}
# Pre-sorted by key length descending so longer prefixes match first.
FACENAME101_MAP_SORTED = sorted(FACENAME101_MAP.items(), key=lambda x: len(x[0]), reverse=True)
# BRFLAG: Newlines -> <br>.
BRFLAG = False
# FIXTEXTWRAP: Rewrap text to WIDTH/NOTEWIDTH.
FIXTEXTWRAP = True
# IGNORETLTEXT: Skip Translated Text.
IGNORETLTEXT = True
# PRESERVEORIGINAL: Store Japanese source in _original fields (maps + database) for re-run safety.
PRESERVEORIGINAL = True
# TLSYSTEMVARIABLES: Translate System Variables. (Optional but sometimes necessary. Can break stuff.)
TLSYSTEMVARIABLES = False
# TLSYSTEMSWITCHES: Translate System Switches. (Optional. Translates switch names in System.json.)
TLSYSTEMSWITCHES = False
# Join 408 codes into a single string like 401.
JOIN408 = False

# Dialogue / Scroll / Choices (Main Codes)
CODE101 = True
CODE401 = True
CODE405 = True
CODE102 = True

# Optional
CODE408 = False

# Variables
CODE122 = False
CODE122_VAR_MIN = 0
CODE122_VAR_MAX = 2000

# Plugins / Scripts
CODE355655 = False
CODE357 = False
CODE657 = False
CODE356 = False
CODE320 = False
CODE324 = False
CODE325 = False
CODE111 = False
CODE108 = False

# ─── Plugin Manager ──────────────────────────────────────────────────────────
# All known code-357 headerMapping entries. Enable entries via ENABLED_PLUGINS_357.
# The GUI reads this dict to build the checkbox list dynamically.
HEADER_MAPPINGS_357 = {
    "LL_InfoPopupWIndow": (["messageText"], None),
    "QuestSystem": (["DetailNote"], None),
    "BalloonInBattle": (["text"], None),
    "MNKR_CommonPopupCoreMZ": (["text"], None),
    "DestinationWindow": (["destination"], None),
    "_TMLogWindowMZ": (["text"], None),
    "TorigoyaMZ_NotifyMessage": (["message"], None),
    "SoR_GabWindow": (["arg1"], None),
    "DarkPlasma_CharacterText": (["text"], None),
    "DTextPicture": (["text"], None),
    "TextPicture": (["text"], None),
    "TRP_SkitMZ": (["name"], None),
    "LogMessage": (["text"], None),
    "LogWindow": (["text"], None),
    "BattleLogOutput": (["message"], None),
    "TorigoyaMZ_NotifyMessage_CommandMessage": (["message"], None),
    "NUUN_SaveScreen": (["AnyName"], None),
    "build/ARPG_Core": (["Text", "SkillByName"], None),
    "EventLabel": (["text"], None),
    "KN_MapBattle": (["enemyName"], None),
    "KN_Shop": (["goodsType"], None),
    "KN_StillManager": (["label"], None),  # OPEN_GALLERY category label in parameters[3]
    "Mano_CurrencyUnit": (["unit"], None),
    "SceneGlossary": (["category"], None),
}
# Subset of HEADER_MAPPINGS_357 keys that should be processed (empty = none).
ENABLED_PLUGINS_357: set = {"BattleLogOutput", "LogMessage"}

# All known code-355/655 script patterns. Enable entries via ENABLED_PATTERNS_355655.
PATTERNS_355655 = {
    "テキスト-": (r"テキスト-(.+)", False),
    "CBR-エロステータス": (r"テキスト-(.+)", True),
    "=": (r'=\s?(.*)",', False),
    "var text": (r'var\stext\d+\s=\s\"(.+)\"', False),
    "logtxt = ": (r"logtxt\s=\s'(.+)'", False),
    ".setNickname": (r'.setNickname\(\\?"(.+?)\\?"\)', False),
    "_subject=": (r'_subject=(.+?)(?=[_\\"\]])', False),
    "text =": (r"text\s*=\s*'(.+[^\\])'", False),
    "const text": (r'(const\stext\s?=\s?"(.+)";?)', False),
    "ex_a_name": (r'ex_a_name\(\d+,"(.+)"\)', False),
    "gameVariables.setValue": (r'\$gameVariables\.setValue\(\d+,\s*"([^"]*)"\)', False),
    "$gameVariables._data": (r"\$gameVariables\._data(?:\[[^\]]+\])+\s*=\s*['\"]((?:\\.|[^'\"\\])*)['\"]", False),
    "$gameMessage.show(this,": (r"'((?:\\.|[^'\\])*)'\s*\)", True),
    "$gameMessage.add": (r"\$gameMessage\.add\(.+?\)(.+?)", True),
    "if (BattleManager.canEscape())": (
        r'\$gameMessage\.add\(\s*"((?:\\.|[^"\\])*)"\s*\)',
        True,
    ),
    "BattleManager._logWindow.push('addText'": (r"BattleManager._logWindow.push\('addText',\s'(.+)'\)", False),
    # Supports addText('msg'), addText("msg"), and addText(expr+'msg') where expr contains () e.g. .members()
    "BattleManager._logWindow.addText": (
        r"BattleManager\._logWindow\.addText\(\s*(?:(?:[^()]|\([^)]*\))*\+\s*)?(['\"])((?:\\.|(?!\1).)*)\1\s*\)",
        True,
    ),
    "let out": (r"let\s+out\d+\s*=\s*\(.+?\)(.+?)", True),
    "moji": (r"(?:let\s+)?moji\s*\+?=\s*(.+)", True),
    "this.BLogAdd": (r'this\.BLogAdd\?(.+?\\?"(.+?)\\?"\)', False),
    "Fuki_Set": (r'Fuki_Set\([\s,\d\w\W]+?"(.+?)",', False),
    "_EventSetting": (r'_EventSetting[\s,\d\w\W]+?"(.+?)";', False),
    "this.Menu_SexTxtSet(": (r'"(.+)"', True),
    "Rn_RsltTxtArr": (r'"(.+)"', True),
    "_章切り替えStart": (r'_章切り替えStart\(\s*\\?"\s?,?.+?\\?"\s?,?\s?\\?"(.+?)\\?"', False),
    "SkillLogAdd": (r'SkillLogAdd\((?:.+?\+\s*)?\\?"(?:\\\\+[A-Za-z]\[\d+\])?(.+?)\\?"', False),
    "MobNameSet": (r'MobNameSet\(\\?"(.+?)\\?"\)', False),
    "AddAddress": (r'AddAddress\(\d+,\s*\\?"(.+?)\\?"', False),
}
# Subset of PATTERNS_355655 keys that should be processed (empty = none).
ENABLED_PATTERNS_355655: set = {"$gameMessage.show(this,", "BattleManager._logWindow.push('addText'"}


def _pat355655_captured_text(match):
    """Substring to translate for PATTERNS_355655; last capture group is always the visible text."""
    return match.group(match.lastindex)


def _pat355655_replace_captured(source: str, match, replacement: str) -> str:
    """Replace only the visible capture, even when it also occurs in plugin syntax."""
    start, end = match.span(match.lastindex)
    return source[:start] + replacement + source[end:]


def _escape_single_quoted_script_text(text: str) -> str:
    """Keep translated text valid inside a single-quoted JavaScript string."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", r"\n")
    escaped = []
    preceding_backslashes = 0
    for char in text:
        if char == "'" and preceding_backslashes % 2 == 0:
            escaped.append("\\")
        escaped.append(char)
        preceding_backslashes = preceding_backslashes + 1 if char == "\\" else 0
    return "".join(escaped)


def _decode_game_message_show_text(text: str) -> str:
    """Expose JavaScript newline escapes to the translator as real line breaks."""
    return text.replace(r"\n", "\n")


def _reload_vocab():
    """Reload the active game's glossary so recent edits take effect."""
    global VOCAB
    try:
        from util.vocab import (
            BATCH_GLOSSARY_FREEZE_FILE,
            batch_glossary_phase,
            read_translation_glossary,
        )

        if (
            batch_glossary_phase() == "collect"
            and BATCH_GLOSSARY_FREEZE_FILE.is_file()
        ):
            VOCAB = read_translation_glossary()
            TRANSLATION_CONFIG.vocab = VOCAB
            return
    except Exception:
        pass
    vocab_path = active_glossary_path() or VOCAB_PATH
    try:
        VOCAB = vocab_path.read_text(encoding="utf-8") if vocab_path else read_active_glossary()
    except (FileNotFoundError, OSError):
        VOCAB = read_active_glossary()
    TRANSLATION_CONFIG.vocab = VOCAB


def handleMVMZ(filename, estimate):
    global ESTIMATE, TOKENS, FILENAME, MISMATCH, PROMPT
    ESTIMATE = estimate
    FILENAME = filename
    MISMATCH = []  # Reset per-file; prevents cross-file contamination in CLI mode
    # Also record per-thread filename to avoid cross-thread interference
    try:
        THREAD_CTX.filename = filename
    except Exception:
        pass

    # Refresh settings and per-game context even when this module is cached in
    # the long-lived GUI process.
    refreshRuntimeConfig()

    # Translate
    start = time.time()
    translatedData = openFiles(filename)

    # Translate
    # Skip writing output file during speaker-parse mode
    if not estimate and not SPEAKER_PARSE_MODE:
        try:
            with open("translated/" + filename, "w", encoding="utf-8", newline="\n") as outFile:
                json.dump(translatedData[0], outFile, ensure_ascii=False, indent=4)
        except Exception:
            traceback.print_exc()
            return "Fail"

    # Print File
    end = time.time()
    tqdm.write(getResultString(translatedData, end - start, filename))
    with LOCK:
        TOKENS[0] += translatedData[1][0]
        TOKENS[1] += translatedData[1][1]

    # Print Total
    totalString = getResultString(["", TOKENS, None], end - start, "TOTAL")

    # Print any errors on maps
    if len(MISMATCH) > 0:
        return totalString + Fore.RED + f"\nMismatch Errors: {MISMATCH}" + Fore.RESET
    else:
        return totalString


def openFiles(filename):
    with open("files/" + filename, "r", encoding="utf-8-sig") as f:
        data = json.load(f)

        # Map Files
        if "Map" in filename and "MapInfos" not in filename:
            translatedData = parseMap(data, filename)

        # CommonEvents Files
        elif "CommonEvents" in filename:
            translatedData = parseCommonEvents(data, filename)

        # Actor File
        elif "Actors" in filename:
            translatedData = parseNames(data, filename, "Actors")

        # Armor File
        elif "Armors" in filename:
            translatedData = parseNames(data, filename, "Armors")

        # Weapons File
        elif "Weapons" in filename:
            translatedData = parseNames(data, filename, "Weapons")

        # Classes File
        elif "Classes" in filename:
            translatedData = parseNames(data, filename, "Classes")

        # Enemies File
        elif "Enemies" in filename:
            translatedData = parseNames(data, filename, "Enemies")

        # Items File
        elif "Items" in filename:
            translatedData = parseNames(data, filename, "Items")

        # MapInfo File
        elif "MapInfos" in filename:
            translatedData = parseNames(data, filename, "MapInfos")

        # Skills File
        elif "Skills" in filename:
            translatedData = parseNames(data, filename, "Skills")

        # Troops File
        elif "Troops" in filename:
            translatedData = parseTroops(data, filename)

        # States File
        elif "States" in filename:
            translatedData = parseSS(data, filename)

        # System File
        elif "System" in filename:
            translatedData = parseSystem(data, filename)

        # Scenario File
        elif "Scenario" in filename:
            translatedData = parseScenario(data, filename)

        else:
            raise NameError(filename + " Not Supported")

    return translatedData


def getResultString(translatedData, translationTime, filename):
    global TIMETOTAL
    # File Print String
    cost = calculateCost(translatedData[1][0], translatedData[1][1], MODEL)
    totalTokenstring = (
        Fore.YELLOW + "[Input: " + str(translatedData[1][0]) + "]"
        "[Output: "
        + str(translatedData[1][1])
        + "]" "[Cost: ${:,.4f}".format(cost)
        + "]"
    )
    if filename != "TOTAL":
        timeString = Fore.BLUE + "[" + str(round(translationTime, 1)) + "s]"
        TIMETOTAL += round(translationTime, 1)
    else:
        timeString = Fore.BLUE + "[" + str(round(TIMETOTAL, 1)) + "s]"

    if translatedData[2] is None:
        # Success
        return filename + ": " + totalTokenstring + timeString + Fore.GREEN + " \u2713 " + Fore.RESET
    else:
        # Fail
        try:
            raise translatedData[2]
        except Exception as e:
            traceback.print_exc()
            errorString = str(e) + Fore.RED
            return filename + ": " + totalTokenstring + timeString + Fore.RED + " \u2717 " + errorString + Fore.RESET


def saveProgress(data, filename):
    """Atomically write current data to translated/filename to avoid progress loss.
    Skips when running in estimate mode.
    """
    try:
        # Also skip progress saves during speaker-parse mode
        if ESTIMATE or SPEAKER_PARSE_MODE:
            return
        os.makedirs("translated", exist_ok=True)
        # Use a unique temp file name to avoid collisions across threads/processes
        tmp_path = os.path.join(
            "translated",
            f"{filename}.{os.getpid()}.{threading.get_ident()}.tmp",
        )
        final_path = os.path.join("translated", filename)
        with open(tmp_path, "w", encoding="utf-8", newline="\n") as outFile:
            json.dump(data, outFile, ensure_ascii=False, indent=4)
            outFile.flush()
            try:
                os.fsync(outFile.fileno())
            except Exception:
                # fsync may not be available on some platforms; ignore best-effort
                pass

        # Replace atomically when possible, with retries to mitigate transient locks on Windows
        attempts = 6
        delay = 0.1
        last_err = None
        for attempt in range(attempts):
            try:
                os.replace(tmp_path, final_path)
                last_err = None
                break
            except PermissionError as e:
                last_err = e
                # Try to relax permissions on target if it exists, then back off
                try:
                    if os.path.exists(final_path):
                        os.chmod(final_path, 0o666)
                except Exception:
                    pass
                time.sleep(delay)
                delay = min(1.0, delay * 2)
            except Exception as e:
                last_err = e
                break
        if last_err is not None:
            # Fallback: try move via shutil (not guaranteed atomic), then raise on failure
            try:
                shutil.move(tmp_path, final_path)
            except Exception:
                # Ensure tmp is cleaned up if move failed
                try:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except Exception:
                    pass
                raise last_err
    except Exception:
        # Best-effort; don't crash the translation if saving fails
        traceback.print_exc()


def _scalar_original(cmd) -> str | None:
    """Return scalar _original on an event command, or None if absent/empty."""
    orig = cmd.get("_original")
    if orig is not None and not isinstance(orig, list) and str(orig).strip():
        return str(orig)
    return None


def _text_needs_translation(current) -> bool:
    """Return whether a live value should be translated under the skip setting."""
    if current is None or not str(current).strip():
        return False
    return not IGNORETLTEXT or bool(re.search(LANGREGEX, str(current)))


def _param_current(cmd, index: int) -> str:
    """Return the current event-command parameter without consulting _original."""
    params = cmd.get("parameters") or []
    if index < len(params) and params[index] is not None:
        return str(params[index])
    return ""


def _param_source(cmd, index: int) -> str:
    """Prefer scalar _original; else parameters[index] (401/405 dialogue lines)."""
    orig = _scalar_original(cmd)
    if orig is not None:
        return orig
    params = cmd.get("parameters") or []
    if index < len(params) and params[index] is not None:
        return str(params[index])
    return ""


def _group_source(codeList, start: int, end: int) -> str:
    """Join source text for a merged 401/405 group (indices start..end inclusive)."""
    if start < len(codeList):
        orig = _scalar_original(codeList[start])
        if orig is not None:
            return orig
    parts = []
    for idx in range(start, end + 1):
        if idx >= len(codeList):
            break
        cmd = codeList[idx]
        if not cmd or cmd.get("code") not in (401, 405, -1):
            continue
        params = cmd.get("parameters") or []
        if not params:
            continue
        src = _param_source(cmd, 0)
        if src.strip():
            parts.append(src)
    return "\n".join(parts)


def _group_raw_source(codeList, group_start: int, source_parts: list[str]) -> str:
    """Batch source for merged 401/405; anchor _original wins on re-run."""
    if group_start < len(codeList):
        orig = _scalar_original(codeList[group_start])
        if orig is not None:
            return orig
    return "\n".join(source_parts)


def _group_current(codeList, start: int, end: int) -> str:
    """Join current visible text for a 401/405/408 group."""
    parts = []
    for idx in range(start, end + 1):
        if idx >= len(codeList):
            break
        current = _param_current(codeList[idx], 0)
        if current.strip():
            parts.append(current)
    return "\n".join(parts)


def _text_group_end(codeList, start: int, allowed_codes: tuple[int, ...]) -> int:
    """Return the last command joined into a contiguous visible-text group."""
    end = start
    while end + 1 < len(codeList):
        current = codeList[end]
        following = codeList[end + 1]
        if following.get("code") not in allowed_codes:
            break
        if not current.get("parameters") or not following.get("parameters"):
            break
        if re.match(
            r"^(\s*[\\]+[aAbBdDeEfFgGhHjJlLmMoOpPqQrRsStTuUwWxXyYzZ]+\[[\w\d\[\]\\]+\])",
            str(following["parameters"][0]),
        ):
            break
        end += 1
    return end


def _apply_original(cmd, raw_source: str) -> None:
    """Set scalar _original only when not already present (re-run safe)."""
    if not PRESERVEORIGINAL:
        return
    if not raw_source or not str(raw_source).strip():
        return
    if _scalar_original(cmd) is not None:
        return
    cmd["_original"] = raw_source


def _choice_source(cmd, index: int) -> str:
    """Prefer _original[index] for code 102 choices; else parameters[0][index]."""
    orig_list = cmd.get("_original")
    if isinstance(orig_list, list) and index < len(orig_list):
        slot = orig_list[index]
        if slot is not None and str(slot).strip():
            return str(slot)
    params = cmd.get("parameters") or [[]]
    choices = params[0] if params else []
    if isinstance(choices, list) and index < len(choices) and choices[index] is not None:
        return str(choices[index])
    return ""


def _choice_current(cmd, index: int) -> str:
    """Return the current visible choice without consulting _original."""
    params = cmd.get("parameters") or [[]]
    choices = params[0] if params else []
    if isinstance(choices, list) and index < len(choices) and choices[index] is not None:
        return str(choices[index])
    return ""


def _apply_choice_original(cmd, index: int, raw_source: str) -> None:
    """Set _original[index] for code 102 only when that slot is empty."""
    if not PRESERVEORIGINAL:
        return
    if not raw_source or not str(raw_source).strip():
        return
    params = cmd.get("parameters") or [[]]
    choices = params[0] if params else []
    n = len(choices) if isinstance(choices, list) else 0
    orig_list = cmd.get("_original")
    if not isinstance(orig_list, list):
        orig_list = [None] * n
        cmd["_original"] = orig_list
    while len(orig_list) < n:
        orig_list.append(None)
    if index < len(orig_list):
        existing = orig_list[index]
        if existing is not None and str(existing).strip():
            return
        orig_list[index] = raw_source


def _choice_condition_end(text: str, start: int) -> int | None:
    """Return the end of a balanced lowercase ``if(...)``/``en(...)`` clause."""
    if not isinstance(text, str) or not text.startswith(("if(", "en("), start):
        return None

    depth = 0
    for index in range(start + 2, len(text)):
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index + 1
            if depth < 0:
                break
    return None


def _split_choice_condition_prefix(text: str) -> tuple[str, str]:
    """Split a leading lowercase ``if(...)``/``en(...)`` plugin condition safely.

    Conditions can contain nested calls such as ``if($gameSwitches.value(1))``.
    Return the input untouched when the prefix is absent or unbalanced.
    """
    if not isinstance(text, str):
        return "", text

    end = _choice_condition_end(text, 0)
    if end is not None:
        return text[:end], text[end:]
    return "", text


def _split_choice_condition_suffix(text: str) -> tuple[str, str]:
    """Split trailing plugin condition clauses while preserving their exact bytes.

    A suffix can contain one or more whitespace-delimited ``if(...)``/``en(...)``
    clauses, including nested calls. Unbalanced or mixed trailing text is left
    untouched so visible choice text cannot be removed accidentally.
    """
    if not isinstance(text, str):
        return text, ""

    for match in re.finditer(r"\s+(?=(?:if|en)\()", text):
        suffix_start = match.start()
        cursor = match.end()

        while True:
            end = _choice_condition_end(text, cursor)
            if end is None:
                break
            cursor = end

            whitespace_start = cursor
            while cursor < len(text) and text[cursor].isspace():
                cursor += 1

            if cursor == len(text):
                return text[:suffix_start], text[suffix_start:]
            if whitespace_start == cursor:
                break

    return text, ""


def _122_inner_source(cmd) -> str | None:
    """Inner quoted value for code 122: _original or extract from parameters[4]."""
    orig = _scalar_original(cmd)
    if orig is not None:
        return orig
    params = cmd.get("parameters") or []
    if len(params) <= 4:
        return None
    jaString = params[4]
    if not isinstance(jaString, str):
        return None
    if len(re.findall(r"([\'\"\`])", jaString)) >= 2:
        matchedText = re.search(r"[\'\"\`](.*)[\'\"\`]", jaString)
        if matchedText and matchedText.group(1).strip():
            return matchedText.group(1)
    return None


def _122_inner_current(cmd) -> str | None:
    """Extract the current quoted value for code 122 without consulting _original."""
    params = cmd.get("parameters") or []
    if len(params) <= 4 or not isinstance(params[4], str):
        return None
    matched = re.search(r"['\"`](.*)['\"`]", params[4])
    if matched and matched.group(1).strip():
        return matched.group(1)
    return None


def _101_name_source(cmd, is_var: bool) -> str:
    """Speaker name field for code 101: _original or parameters[4]/[0]."""
    orig = _scalar_original(cmd)
    if orig is not None:
        return orig
    params = cmd.get("parameters") or []
    if is_var and len(params) > 0 and params[0] is not None:
        return str(params[0])
    if not is_var and len(params) > 4 and params[4] is not None:
        return str(params[4])
    return ""


def _101_name_current(cmd, is_var: bool) -> str:
    """Return the current code-101 name field without consulting _original."""
    params = cmd.get("parameters") or []
    if is_var and len(params) > 0 and params[0] is not None:
        return str(params[0])
    if not is_var and len(params) > 4 and params[4] is not None:
        return str(params[4])
    return ""


def _101_speaker_name(raw_name: str) -> str:
    """Return the translatable name inside a code-101 display wrapper.

    Parameter 4 may use ``【Name】`` as its visible name-window styling.  Those
    brackets belong in the 101 field, not in the ``[Speaker]:`` transport prefix
    temporarily attached to the following 401 dialogue.
    """
    name = str(raw_name or "").strip()
    name = re.sub(r"^(?:[\\]+[cC]\[\d+\]\s*)+", "", name)
    bracketed = re.match(r"^【\s*([^】]+?)\s*】", name)
    if bracketed:
        return bracketed.group(1).strip()
    plain = re.match(r"^([^\\]+)", name)
    return plain.group(1).strip() if plain else ""


def _facename101_speaker(cmd) -> str | None:
    """Resolve an unnamed code-101 speaker from its face filename."""
    params = cmd.get("parameters") or []
    if len(params) == 0:
        return None

    # The face is only a fallback. An explicit name-window value is more
    # authoritative, even when the face filename also has a known prefix.
    if len(params) > 4 and _101_speaker_name(params[4]):
        return None

    face_name = params[0]
    if not isinstance(face_name, str) or not face_name:
        return None

    if "_talk" in face_name:
        prefix = face_name.split("_talk", 1)[0]
        matched = FACENAME101_MAP.get(prefix)
        if matched is not None:
            return matched

    for prefix, name in FACENAME101_MAP_SORTED:
        if face_name.startswith(prefix):
            return name
    return None


def _101_has_face_graphic(cmd) -> bool:
    """Return whether a standard code-101 command reserves face-image space."""
    params = cmd.get("parameters") or []
    return (
        len(params) >= 4
        and isinstance(params[0], str)
        and bool(params[0].strip())
    )


def _entry_orig(entry) -> dict:
    """Return _original dict on a database entry, or empty dict if absent."""
    orig = entry.get("_original") if isinstance(entry, dict) else None
    return orig if isinstance(orig, dict) else {}


def _entry_field_source(entry, field: str) -> str:
    """Prefer _original[field]; else entry[field] (database scalar fields)."""
    if not isinstance(entry, dict):
        return ""
    orig = _entry_orig(entry)
    slot = orig.get(field)
    if slot is not None and not isinstance(slot, (dict, list)) and str(slot).strip():
        return str(slot)
    val = entry.get(field)
    if val is not None:
        return str(val)
    return ""


def _entry_field_needs_translation(entry, field: str) -> bool:
    """Decide skip status from the current value, not preserved source text."""
    if not isinstance(entry, dict):
        return False
    return _text_needs_translation(entry.get(field))


def _apply_entry_field_original(entry, field: str, raw: str) -> None:
    """Set _original[field] only when empty and raw contains Japanese."""
    if not PRESERVEORIGINAL:
        return
    if not isinstance(entry, dict) or not raw or not str(raw).strip():
        return
    if not re.search(LANGREGEX, raw):
        return
    orig = entry.get("_original")
    if not isinstance(orig, dict):
        orig = {}
        entry["_original"] = orig
    existing = orig.get(field)
    if existing is not None and not isinstance(existing, (dict, list)) and str(existing).strip():
        return
    orig[field] = raw


def _system_orig(data) -> dict:
    """Get or create root _original dict on System.json."""
    orig = data.get("_original") if isinstance(data, dict) else None
    if isinstance(orig, dict):
        return orig
    orig = {}
    data["_original"] = orig
    return orig


def _system_scalar_source(data, field: str) -> str:
    """Prefer root _original[field]; else data[field]."""
    if not isinstance(data, dict):
        return ""
    orig = data.get("_original")
    if isinstance(orig, dict):
        slot = orig.get(field)
        if slot is not None and not isinstance(slot, (dict, list)) and str(slot).strip():
            return str(slot)
    val = data.get(field)
    if val is not None:
        return str(val)
    return ""


def _apply_system_scalar_original(data, field: str, raw: str) -> None:
    """Set root _original[field] only when empty and raw contains Japanese."""
    if not PRESERVEORIGINAL:
        return
    if not raw or not str(raw).strip() or not re.search(LANGREGEX, raw):
        return
    orig = _system_orig(data)
    existing = orig.get(field)
    if existing is not None and not isinstance(existing, (dict, list)) and str(existing).strip():
        return
    orig[field] = raw


def _system_list_source(data, list_name: str, index: int) -> str:
    """Prefer _original[list_name][str(index)]; else data[list_name][index]."""
    if not isinstance(data, dict):
        return ""
    orig = data.get("_original")
    if isinstance(orig, dict):
        list_orig = orig.get(list_name)
        if isinstance(list_orig, dict):
            slot = list_orig.get(str(index))
            if slot is not None and str(slot).strip():
                return str(slot)
    lst = data.get(list_name) or []
    if index < len(lst) and lst[index] is not None:
        return str(lst[index])
    return ""


def _apply_system_list_original(data, list_name: str, index: int, raw: str) -> None:
    """Set _original[list_name][str(index)] only when empty and raw contains Japanese."""
    if not PRESERVEORIGINAL:
        return
    if not raw or not str(raw).strip() or not re.search(LANGREGEX, raw):
        return
    orig = _system_orig(data)
    list_orig = orig.get(list_name)
    if not isinstance(list_orig, dict):
        list_orig = {}
        orig[list_name] = list_orig
    key = str(index)
    existing = list_orig.get(key)
    if existing is not None and str(existing).strip():
        return
    list_orig[key] = raw


def _system_terms_source(data, category: str, index: int) -> str:
    """Prefer _original.terms[category][str(index)]; else terms[category][index]."""
    if not isinstance(data, dict):
        return ""
    orig = data.get("_original")
    if isinstance(orig, dict):
        terms_orig = orig.get("terms")
        if isinstance(terms_orig, dict):
            cat_orig = terms_orig.get(category)
            if isinstance(cat_orig, dict):
                slot = cat_orig.get(str(index))
                if slot is not None and str(slot).strip():
                    return str(slot)
    term_list = (data.get("terms") or {}).get(category)
    if isinstance(term_list, list) and index < len(term_list) and term_list[index] is not None:
        return str(term_list[index])
    return ""


def _apply_system_terms_original(data, category: str, index: int, raw: str) -> None:
    """Set _original.terms[category][str(index)] only when empty and raw contains Japanese."""
    if not PRESERVEORIGINAL:
        return
    if not raw or not str(raw).strip() or not re.search(LANGREGEX, raw):
        return
    orig = _system_orig(data)
    terms = orig.get("terms")
    if not isinstance(terms, dict):
        terms = {}
        orig["terms"] = terms
    cat = terms.get(category)
    if not isinstance(cat, dict):
        cat = {}
        terms[category] = cat
    key = str(index)
    existing = cat.get(key)
    if existing is not None and str(existing).strip():
        return
    cat[key] = raw


def _system_terms_message_source(data, key: str) -> str:
    """Prefer _original.terms.messages[key]; else terms.messages[key]."""
    if not isinstance(data, dict):
        return ""
    orig = data.get("_original")
    if isinstance(orig, dict):
        terms_orig = orig.get("terms")
        if isinstance(terms_orig, dict):
            msg_orig = terms_orig.get("messages")
            if isinstance(msg_orig, dict):
                slot = msg_orig.get(key)
                if slot is not None and str(slot).strip():
                    return str(slot)
    messages = (data.get("terms") or {}).get("messages") or {}
    val = messages.get(key)
    if val is not None:
        return str(val)
    return ""


def _apply_system_terms_message_original(data, key: str, raw: str) -> None:
    """Set _original.terms.messages[key] only when empty and raw contains Japanese."""
    if not PRESERVEORIGINAL:
        return
    if not raw or not str(raw).strip() or not re.search(LANGREGEX, raw):
        return
    orig = _system_orig(data)
    terms = orig.get("terms")
    if not isinstance(terms, dict):
        terms = {}
        orig["terms"] = terms
    msg = terms.get("messages")
    if not isinstance(msg, dict):
        msg = {}
        terms["messages"] = msg
    existing = msg.get(key)
    if existing is not None and str(existing).strip():
        return
    msg[key] = raw


def _normalize_system_message_translation(key: str, translated: str) -> str:
    """Repair narrowly known English RPG Maker system-message failures."""
    text = str(translated or "").strip()
    target = str(LANGUAGE or "").strip().casefold().replace("_", "-")
    is_english = target in {"en", "eng", "english"} or target.startswith("en-")
    if key == "escapeFailure" and is_english and re.fullmatch(
        r"but\s+couldn['’]t\s+escape!?", text, flags=re.IGNORECASE
    ):
        return "But escape failed!"
    return text


_COLOR_SPEAKER_RE = re.compile(
    r"^[\\]+[cC]\[\d+\]【?(.+?)】?[\\]+[cC]\[\d+\](?:[\\]+[A-Za-z]+(?:\[[^\]]*\])?)*[\\]*$"
)


def _replace_speaker_in_param(param_str: str, source_name: str, translated_name: str) -> str:
    """Replace a speaker name inside a 401/101 parameter while keeping colour/bracket wrappers."""
    if not param_str or not translated_name:
        return param_str
    m = _COLOR_SPEAKER_RE.match(param_str)
    if m:
        return param_str.replace(m.group(1), translated_name, 1)
    bracket_disp = re.findall(r"【(.+?)】", param_str)
    if bracket_disp:
        return param_str.replace(bracket_disp[0], translated_name, 1)
    if source_name and source_name in param_str:
        return param_str.replace(source_name, translated_name, 1)
    return param_str


def checkSave(data, filename, tokens):
    """Save progress only if the given tokens reflect an actual translation.
    tokens should be a [input_tokens, output_tokens] pair returned by a search/translate call.
    """
    try:
        # Never save progress to translated/ during speaker-parse mode
        if SPEAKER_PARSE_MODE:
            return
        if not tokens:
            return
        if (isinstance(tokens, (list, tuple)) and len(tokens) >= 2 and (tokens[0] or tokens[1])):
            saveProgress(data, filename)
    except Exception:
        # Don't let saving issues affect the translation flow
        traceback.print_exc()


def update_vocab_section(category: str, pairs: list[tuple[str, str]]):
    """Harvest translated DB names into the shared game glossary helper."""
    try:
        from util.vocab import update_vocab_section as _shared_update_vocab_section

        _shared_update_vocab_section(category, pairs)
    except Exception:
        traceback.print_exc()


def parseMap(data, filename):
    totalTokens = [0, 0]
    events = data["events"]
    global LOCK

    # --- Preflight: estimate exact progress total using the same translation batching ---
    class _CountingBar:
        def __init__(self):
            self.n = 0
        def update(self, n=1):
            try:
                self.n += int(n) if n is not None else 1
            except Exception:
                self.n += 1
        def write(self, *args, **kwargs):
            # Silent during preflight
            pass
        def refresh(self):
            pass

    def _estimate_map_units(d, fname) -> int:
        # Avoid deep copy - just count items directly
        count = 0
        try:
            # Count display name TL (1 unit if present)
            if "Map" in fname and isinstance(d.get("displayName", None), str):
                count += 1

            # Notes and pages - count actual translatable items
            evts = d.get("events", []) or []
            for evt in evts:
                if not evt:
                    continue
                note_val = evt.get("note") or ""
                if not isinstance(note_val, str):
                    note_val = str(note_val) if note_val is not None else ""

                # Count note-based translations
                if "<LB>" in note_val:
                    name_val = evt.get("name") or ""
                    if isinstance(name_val, str) and name_val:
                        count += 1

                if "<msgText:" in note_val:
                    matches = re.findall(r"<msgText:\"(.*?)\">", note_val, re.DOTALL)
                    count += len(matches)

                if "<namePop:" in note_val:
                    matches = re.findall(r"<namePop:\s?([\w一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９\uFF61-\uFF9F]+)", note_val)
                    count += len(matches)
                if "<LB:" in note_val:
                    matches = re.findall(r"<LB:(.*?)\s?>.*", note_val)
                    count += len(matches)
                if "<dn:" in note_val:
                    matches = re.findall(r"<dn:\s*(.*)>.*", note_val)
                    count += len(matches)

                # Count commands in pages (rough estimate)
                for page in (evt.get("pages", []) or []):
                    if page and "list" in page:
                        # Count translatable codes
                        for cmd in page.get("list", []):
                            if cmd and "code" in cmd:
                                code = cmd["code"]
                                # Count common translatable codes
                                if code in [401, 405, 102, 122, 408, 355, 655, 356, 357, 320, 324, 325, 111, 108, 657]:
                                    count += 1

            return count if count > 0 else 1
        except Exception:
            return 1

    # Translate displayName for Map files
    if "Map" in filename:
        response = translateAI(
            data["displayName"],
            ctx("names.location"),
            False,
        )
        totalTokens[0] += response[1][0]
        totalTokens[1] += response[1][1]
        data["displayName"] = response[0].replace('"', "")

    # Compute accurate total using preflight (includes speakers, choices, groups, and notes)
    totalLines = _estimate_map_units(data, filename)
    if not isinstance(totalLines, int) or totalLines <= 0:
        # Fallback to naive count so a bar still renders
        totalLines = 0
        for event in events:
            if event:
                for page in event.get("pages", []) or []:
                    try:
                        totalLines += len(page.get("list", []))
                    except Exception:
                        pass
    global PBAR

    # Process each page synchronously with progress updates
    with tqdm(total=totalLines, bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE, desc=filename) as pbar:
        PBAR = pbar
        
        # Batch translate <LB> event names
        lbTokens = translateLBNames(events)
        totalTokens[0] += lbTokens[0]
        totalTokens[1] += lbTokens[1]
        
        for event in events:
            if event is not None:
                # Normalize note to a safe string
                note_val = event.get("note") or ""
                if not isinstance(note_val, str):
                    note_val = str(note_val) if note_val is not None else ""

                # This translates ID of events. (May break the game)
                if "<namePop:" in note_val:
                    tok = translateNoteOmitSpace(event, r"<namePop:\s?([\w一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９\uFF61-\uFF9F]+)")
                    if tok and isinstance(tok, (list, tuple)):
                        totalTokens[0] += tok[0]
                        totalTokens[1] += tok[1]
                if "<LB:" in note_val:
                    tok = translateNoteOmitSpace(event, r"<LB:(.*?)\s?>.*")
                    if tok and isinstance(tok, (list, tuple)):
                        totalTokens[0] += tok[0]
                        totalTokens[1] += tok[1]
                if "<dn:" in note_val:
                    tok = translateNoteOmitSpace(event, r"<dn:\s*(.*)>.*")
                    if tok and isinstance(tok, (list, tuple)):
                        totalTokens[0] += tok[0]
                        totalTokens[1] += tok[1]

                for page in event["pages"]:
                    if page is not None:
                        totalTokensPage = [0, 0]
                        try:
                            totalTokensPage = searchCodes(page, pbar, [], filename)
                            totalTokens[0] += totalTokensPage[0]
                            totalTokens[1] += totalTokensPage[1]
                        except Exception as e:
                            traceback.print_exc()
                            return [data, totalTokens, e]
                        finally:
                            # Persist progress only if this page produced tokens
                            checkSave(data, filename, totalTokensPage)
    return [data, totalTokens, None]


def _normalize_sg_desc(text: str) -> str:
    """Normalize SG description text before AI translation.

    Japanese body text is hard-wrapped at screen width using bare \\n.
    This collapses those intra-paragraph newlines into spaces so the AI
    receives clean prose paragraphs, while preserving:
      - \\n\\n paragraph / section breaks
      - ◆ / ・ / • / ● header lines (kept on their own line)
    """
    HEADER_CHARS = ("◆", "・", "•", "●")
    blocks = text.split("\n\n")
    normalized_blocks = []
    for block in blocks:
        lines = block.split("\n")
        result_lines: list[str] = []
        body_buf: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(HEADER_CHARS):
                if body_buf:
                    result_lines.append(" ".join(body_buf))
                    body_buf = []
                result_lines.append(stripped)
            elif stripped:
                body_buf.append(stripped)
        if body_buf:
            result_lines.append(" ".join(body_buf))
        normalized_blocks.append("\n".join(result_lines))
    return "\n\n".join(normalized_blocks)
# For notes that can't have spaces.
def translateNoteOmitSpace(event, regex):
    # Regex that only matches text inside LB.
    jaString = event.get("note") or ""
    if not isinstance(jaString, str):
        jaString = str(jaString) if jaString is not None else ""

    match = re.findall(regex, jaString, re.DOTALL)
    if match:
        oldJAString = match[0]
        # Remove any textwrap
        jaString = re.sub(r"\n", " ", oldJAString)

        # Translate
        response = translateAI(
            jaString,
            ctx("names.location_short"),
            False,
        )
        # Defend against unexpected response shapes
        try:
            translatedText = response[0]
            token_info = response[1] if isinstance(response, (list, tuple)) and len(response) > 1 else [0, 0]
            if not (isinstance(token_info, (list, tuple)) and len(token_info) >= 2):
                token_info = [0, 0]
        except Exception:
            translatedText = str(response) if response is not None else ""
            token_info = [0, 0]

        translatedText = translatedText.replace('"', "")
        translatedText = translatedText.replace(" ", "_")
        # Safely update the note if it exists and is a string
        current_note = event.get("note")
        if isinstance(current_note, str):
            event["note"] = current_note.replace(oldJAString, translatedText)
        return token_info
    return [0, 0]


def translateLBNames(events):
    """Batch translate event names for events with <LB> tag.
    Collects all names, translates in a single batch, then applies results.
    Returns [input_tokens, output_tokens].
    """
    totalTokens = [0, 0]
    
    # Collect events with <LB> tag that have translatable names
    lb_events = []  # List of (event_index, original_name)
    for idx, event in enumerate(events):
        if event is None:
            continue
        note_val = event.get("note") or ""
        if not isinstance(note_val, str):
            note_val = str(note_val) if note_val is not None else ""
        
        if "<LB>" in note_val:
            name_val = event.get("name") or ""
            if isinstance(name_val, str) and name_val and re.search(LANGREGEX, name_val):
                lb_events.append((idx, name_val))
    
    # Batch translate if we have any
    if lb_events:
        names_to_translate = [item[1] for item in lb_events]
        response = translateAI(
            names_to_translate,
            ctx("names.generic"),
            True,
        )
        translated_names = response[0] if isinstance(response[0], list) else [response[0]]
        totalTokens[0] += response[1][0]
        totalTokens[1] += response[1][1]
        
        # Apply translations back to events
        for i, (evt_idx, _) in enumerate(lb_events):
            if i < len(translated_names):
                events[evt_idx]["name"] = translated_names[i].replace('"', "").replace(" ", "_")
    
    return totalTokens


def parseCommonEvents(data, filename):
    totalTokens = [0, 0]
    global LOCK

    # --- Preflight: estimate exact progress total using same batching ---
    class _CountingBar:
        def __init__(self):
            self.n = 0
        def update(self, n=1):
            try:
                self.n += int(n) if n is not None else 1
            except Exception:
                self.n += 1
        def write(self, *args, **kwargs):
            pass
        def refresh(self):
            pass

    def _estimate_units(pages, fname) -> int:
        # Avoid deep copy - just count commands directly
        count = 0
        try:
            for page in pages:
                if page is not None and "list" in page:
                    for cmd in page.get("list", []):
                        if cmd and "code" in cmd:
                            code = cmd["code"]
                            if code in [401, 405, 102, 122, 408, 355, 655, 356, 357, 320, 324, 325, 111, 108, 657]:
                                count += 1
            return count if count > 0 else 1
        except Exception:
            return 1

    totalLines = _estimate_units(data, filename)
    if not isinstance(totalLines, int) or totalLines <= 0:
        # Fallback to naive command count
        totalLines = 0
        for page in data:
            if page is not None:
                try:
                    totalLines += len(page.get("list", []))
                except Exception:
                    pass
    global PBAR

    with tqdm(total=totalLines, bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE, desc=filename) as pbar:
        PBAR = pbar
        for page in data:
            if page is not None:
                totalTokensPage = [0, 0]
                try:
                    totalTokensPage = searchCodes(page, pbar, [], filename)
                    totalTokens[0] += totalTokensPage[0]
                    totalTokens[1] += totalTokensPage[1]
                except Exception as e:
                    traceback.print_exc()
                    return [data, totalTokens, e]
                finally:
                    # Persist progress only if this page produced tokens
                    checkSave(data, filename, totalTokensPage)
    return [data, totalTokens, None]


def parseTroops(data, filename):
    totalTokens = [0, 0]
    global LOCK

    # --- Preflight total using same code paths ---
    class _CountingBar:
        def __init__(self):
            self.n = 0
        def update(self, n=1):
            try:
                self.n += int(n) if n is not None else 1
            except Exception:
                self.n += 1
        def write(self, *args, **kwargs):
            pass
        def refresh(self):
            pass

    def _estimate_units(troops, fname) -> int:
        # Avoid deep copy - just count commands directly
        count = 0
        try:
            for troop in troops:
                if troop is None:
                    continue
                for page in (troop.get("pages", []) or []):
                    if page is not None and "list" in page:
                        for cmd in page.get("list", []):
                            if cmd and "code" in cmd:
                                code = cmd["code"]
                                if code in [401, 405, 102, 122, 408, 355, 655, 356, 357, 320, 324, 325, 111, 108, 657]:
                                    count += 1
            return count if count > 0 else 1
        except Exception:
            return 1

    totalLines = _estimate_units(data, filename)
    if not isinstance(totalLines, int) or totalLines <= 0:
        totalLines = 0
        for troop in data:
            if troop is not None:
                for page in troop.get("pages", []) or []:
                    try:
                        totalLines += len(page.get("list", []))
                    except Exception:
                        pass
    global PBAR

    with tqdm(total=totalLines, bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE, desc=filename) as pbar:
        PBAR = pbar
        for troop in data:
            if troop is not None:
                for page in troop["pages"]:
                    if page is not None:
                        totalTokensPage = [0, 0]
                        try:
                            totalTokensPage = searchCodes(page, pbar, [], filename)
                            totalTokens[0] += totalTokensPage[0]
                            totalTokens[1] += totalTokensPage[1]
                        except Exception as e:
                            traceback.print_exc()
                            return [data, totalTokens, e]
                        finally:
                            # Persist progress only if this page produced tokens
                            checkSave(data, filename, totalTokensPage)
    return [data, totalTokens, None]


def parseNames(data, filename, context):
    totalTokens = [0, 0]

    # --- Preflight: custom estimator that mirrors searchNames increments (incl. notes/messages) ---
    class _CountingBar:
        def __init__(self):
            self.n = 0
        def update(self, n=1):
            try:
                self.n += int(n) if n is not None else 1
            except Exception:
                self.n += 1
        def write(self, *args, **kwargs):
            pass
        def refresh(self):
            pass

    def _estimate_names_units(entries, ctx, fname) -> int:
        # Avoid deep copy - just count fields directly
        count = 0
        try:
            note_regexes = [
                (r"<note:(.*?)>", False),
                (r"<PE拡張:(.*?)>", False),
                (r"<[Hh]int:(.*?)>", False),
                (r"<SGDescription:(.*?)>", False),
                (r"<SG説明:\n?(.*?)>", True),
                (r"<SG説明2:\n?(.*?)>", False),
                (r"<SG説明3:\n?(.*?)>", False),
                (r"<SG説明4:\n?(.*?)>", False),
                (r"<SG説明:.+?Client\s?:.+?\n\n(.*?)>", True),
                (r"<SGカテゴリ:(.*?)>", False),
                (r"<Switch Shop Description>\n(.*)\n", False),
                (r"<MapText:(.*?)>", False),
                (r"WATs:(.+?)>", False),
                (r"ADTs?:(.+?)>", False),
                (r"<detail:(.*?)>", False),
                (r"<Name:(.*?)>", False),
                (r"<sub_1:([^>]+)", True),
                (r"<sub_2:([^>]+)", True),
                (r"<sub_3:([^>]+)", True),
                (r"<infowindow:(.*?)>", True),
                (r"<ExtendDesc:(.*?)>", True),
                (r"<desc\d:(.*?)>", False),
                (r"<拡張説明:(.+?)>", False),
                (r"<STS DESC>\n(.+?)\n<", False),
                (r"text:(.+)>", False),
                (r"<Skill\d+:(?:\d+,)?([^,>\d][^,>]*)", False),
                (r"<ClassMessage>\n?(.*?)</ClassMessage>", False),
                (r"<コメント:\n?(.*?)>", True),
            ]

            for entry in entries:
                if not entry:
                    continue
                nm = entry.get("name") or ""
                ds = entry.get("description") or ""
                nn = entry.get("nickname") or ""
                pf = entry.get("profile") or ""
                if ctx == "Actors":
                    if nm: count += 1
                    if nn: count += 1
                    if pf: count += 1
                elif ctx in ["Armors", "Weapons", "Items"]:
                    if nm: count += 1
                    if ds: count += 1
                elif ctx == "Skills":
                    if nm: count += 1
                    if ds: count += 1
                    for k in range(1,5):
                        if entry.get(f"message{k}"): count += 1
                elif ctx in ["Enemies", "Classes", "MapInfos"]:
                    if nm: count += 1

                # Notes counting
                note = entry.get("note") or ""
                if isinstance(note, str) and note:
                    for regex, _ww in note_regexes:
                        try:
                            matches = re.findall(regex, note, re.DOTALL)
                        except Exception:
                            matches = []
                        if regex.startswith(r"<SG説明:"):
                            for m in matches:
                                s = m if isinstance(m, str) else (m[0] if m else "")
                                if "Client:" in s or "Client :" in s:
                                    continue
                                count += 1
                        else:
                            count += len(matches)

            return count if count > 0 else 1
        except Exception:
            return 1

    total_units = _estimate_names_units(data, context, filename)
    if not isinstance(total_units, int) or total_units <= 0:
        # Reasonable fallback: count visible fields/messages (no notes)
        total_units = 0
        for entry in data:
            if not entry:
                continue
            if entry.get("name"): total_units += 1
            if context in ["Armors", "Weapons", "Items", "Skills"] and entry.get("description"): total_units += 1
            if context == "Actors":
                if entry.get("nickname"): total_units += 1
                if entry.get("profile"): total_units += 1
            if context == "Skills":
                for k in range(1,5):
                    if entry.get(f"message{k}"): total_units += 1
    global PBAR

    with tqdm(total=total_units, bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE, desc=filename) as pbar:
        PBAR = pbar
        try:
            # Thread the filename through so progress saves write to the right file
            result = searchNames(data, pbar, context, filename)
            totalTokens[0] += result[0]
            totalTokens[1] += result[1]
        except Exception as e:
            traceback.print_exc()
            return [data, totalTokens, e]
        finally:
            # Persist progress only if this names pass produced tokens
            checkSave(data, filename, totalTokens)
    return [data, totalTokens, None]


def parseSS(data, filename):
    totalTokens = [0, 0]

    # --- Preflight using searchSS over deep copy ---
    class _CountingBar:
        def __init__(self):
            self.n = 0
        def update(self, n=1):
            try:
                self.n += int(n) if n is not None else 1
            except Exception:
                self.n += 1
        def write(self, *args, **kwargs):
            pass
        def refresh(self):
            pass

    def _estimate_units(states, fname) -> int:
        # Avoid deep copy - just count fields directly
        count = 0
        try:
            for st in states:
                if not st:
                    continue
                if st.get("name"): count += 1
                if st.get("description"): count += 1
                for n in range(1,5):
                    if st.get(f"message{n}"): count += 1
            return count if count > 0 else 1
        except Exception:
            return 1

    total_units = _estimate_units(data, filename)
    if not isinstance(total_units, int) or total_units <= 0:
        total_units = 0
        for st in data:
            if not st:
                continue
            if st.get("name"): total_units += 1
            if st.get("description"): total_units += 1
            for n in range(1,5):
                if st.get(f"message{n}"): total_units += 1
    global PBAR

    with tqdm(total=total_units, bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE, desc=filename) as pbar:
        PBAR = pbar
        for ss in data:
            if ss is not None:
                try:
                    result = searchSS(ss, pbar)
                    totalTokens[0] += result[0]
                    totalTokens[1] += result[1]
                except Exception as e:
                    traceback.print_exc()
                    return [data, totalTokens, e]
                finally:
                    # Persist progress only if this state produced tokens
                    checkSave(data, filename, result)
    return [data, totalTokens, None]


def parseSystem(data, filename):
    totalTokens = [0, 0]

    # --- Preflight: call searchSystem on deep copy to count increments ---
    class _CountingBar:
        def __init__(self):
            self.n = 0
        def update(self, n=1):
            try:
                self.n += int(n) if n is not None else 1
            except Exception:
                self.n += 1
        def write(self, *args, **kwargs):
            pass
        def refresh(self):
            pass

    def _estimate_units(sysobj, fname) -> int:
        # Avoid deep copy - just count fields directly
        count = 0
        try:
            for term in sysobj.get("terms", {}) or {}:
                termList = sysobj["terms"][term]
                if isinstance(termList, list):
                    count += len(termList)
            gt = sysobj.get("gameTitle")
            if isinstance(gt, str) and gt:
                count += 1
            count += len(sysobj.get("variables", []) or [])
            count += len(sysobj.get("switches", []) or [])
            count += len(sysobj.get("weaponTypes", []) or [])
            count += len(sysobj.get("armorTypes", []) or [])
            count += len(sysobj.get("skillTypes", []) or [])
            count += len(sysobj.get("equipTypes", []) or [])
            return count if count > 0 else 1
        except Exception:
            return 1

    total_units = _estimate_units(data, filename)
    if not isinstance(total_units, int) or total_units <= 0:
        # Fallback: rough count of strings
        total_units = 0
        if data.get("gameTitle"): total_units += 1
        terms = data.get("terms", {}) or {}
        for k,v in terms.items():
            if k == "messages":
                continue
            if isinstance(v, list):
                total_units += sum(1 for x in v if x is not None)
        total_units += len(data.get("armorTypes", []) or [])
        total_units += len(data.get("skillTypes", []) or [])
        total_units += len(data.get("equipTypes", []) or [])
        total_units += len((terms.get("messages", {}) or {}))
    global PBAR

    with tqdm(total=total_units, bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE, desc=filename) as pbar:
        PBAR = pbar
        try:
            result = searchSystem(data, pbar)
            totalTokens[0] += result[0]
            totalTokens[1] += result[1]
        except Exception as e:
            traceback.print_exc()
            return [data, totalTokens, e]
        finally:
            # Persist only if system sections produced tokens
            checkSave(data, filename, result)
    return [data, totalTokens, None]


def parseScenario(data, filename):
    totalTokens = [0, 0]
    global LOCK

    # --- Preflight: run searchCodes on each page list ---
    class _CountingBar:
        def __init__(self):
            self.n = 0
        def update(self, n=1):
            try:
                self.n += int(n) if n is not None else 1
            except Exception:
                self.n += 1
        def write(self, *args, **kwargs):
            pass
        def refresh(self):
            pass

    def _estimate_units(scenario, fname) -> int:
        # Avoid deep copy - just count commands directly
        count = 0
        try:
            for key, lst in scenario.items():
                if lst is not None and "list" in lst:
                    for cmd in lst.get("list", []):
                        if cmd and "code" in cmd:
                            code = cmd["code"]
                            if code in [401, 405, 102, 122, 408, 355, 655, 356, 357, 320, 324, 325, 111, 108, 657]:
                                count += 1
            return count if count > 0 else 1
        except Exception:
            return 1

    totalLines = _estimate_units(data, filename)
    if not isinstance(totalLines, int) or totalLines <= 0:
        totalLines = 0
        for _, lst in data.items():
            try:
                totalLines += len(lst or [])
            except Exception:
                pass
    global PBAR

    with tqdm(total=totalLines, bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE, desc=filename) as pbar:
        PBAR = pbar
        for page in data.items():
            if page[1] is not None:
                totalTokensPage = [0, 0]
                try:
                    totalTokensPage = searchCodes(page[1], pbar, [], filename)
                    totalTokens[0] += totalTokensPage[0]
                    totalTokens[1] += totalTokensPage[1]
                except Exception as e:
                    traceback.print_exc()
                    return [data, totalTokens, e]
                finally:
                    # Persist progress only if this page produced tokens
                    checkSave(data, filename, totalTokensPage)
    return [data, totalTokens, None]


def searchNames(data, pbar, context, filename):
    totalTokens = [0, 0]
    nameList = []
    nameSourceList = []
    nameIndexList = []
    profileList = []
    profileSourceList = []
    profileIndexList = []
    nicknameList = []
    nicknameSourceList = []
    nicknameIndexList = []
    descriptionList = []
    descriptionSourceList = []
    descriptionIndexList = []
    # For Skills: collect messages across all entries for batch translation
    messagesList = []  # List of tuples: (entry_idx, message_field, message_text, needs_taro)
    # Collect name mappings for vocab per run
    vocab_pairs: list[tuple[str, str]] = []
    vocab_enabled = context in ["Armors", "Weapons", "Items", "MapInfos", "Classes", "Enemies", "Skills"]
    # For batching all note types
    notesBatch = []  # List of (i, regex, match_text, note_type)
    notesBatchMap = []  # List of (i, regex, match_text, note_type, groupidx)
    i = 0  # Counter
    j = 0  # Counter 2
    filling = False
    mismatch = False
    batchFull = False

    # Set the context of what we are translating
    if "Actors" in context:
        newContext = ctx("names.npc_only")
    if "Armors" in context:
        newContext = ctx("database.armor")
    if "Classes" in context:
        newContext = ctx("database.class")
    if "MapInfos" in context:
        newContext = ctx("names.location")
    if "Enemies" in context:
        newContext = ctx("names.enemy")
    if "Weapons" in context:
        newContext = ctx("database.weapon")
    if "Items" in context:
        newContext = ctx("database.item")
    if "Skills" in context:
        newContext = ctx("database.skill")

    # Names
    with open("log/translations.txt", "a", encoding="utf-8") as file:
        file.write(f"\n#{context}\n")

    # --- Batching pass: collect all note texts for all note types ---
    note_regexes = [
        (r"<note:(.*?)>", False),
        (r"<PE拡張:(.*?)>", False),
        (r"<[Hh]int:(.*?)>", False),
        (r"<SGDescription:(.*?)>", False),
        (r"<SG説明:\n?(.*?)>", True),
        (r"<SG説明2:\n?(.*?)>", False),
        (r"<SG説明3:\n?(.*?)>", False),
        (r"<SG説明4:\n?(.*?)>", False),
        (r"<SG説明:.+?Client\s?:.+?\n\n(.*?)>", True),
        (r"<SGカテゴリ:(.*?)>", False),
        (r"<Switch Shop Description>\n(.*)\n", False),
        (r"<MapText:(.*?)>", False),
        (r"WATs:(.+?)>", False),
        (r"ADTs?:(.+?)>", False),
        (r"<detail:(.*?)>", False),
        (r"<Name:(.*?)>", False),
        (r"<sub_1:([^>]+)", True),
        (r"<sub_2:([^>]+)", True),
        (r"<sub_3:([^>]+)", True),
        (r"<infowindow:(.*?)>", True),
        (r"<ExtendDesc:(.*?)>", True),
        (r"<desc\d:(.*?)>", False),
        (r"<拡張説明:(.+?)>", False),
        (r"<STS DESC>\n(.+?)\n<", False),
        (r"text:(.+)>", False),
        (r"<Skill\d+:(?:\d+,)?([^,>\d][^,>]*)", False),
        (r"<ClassMessage>\n?(.*?)</ClassMessage>", False),
        (r"<コメント:\n?(.*?)>", True),
    ]
    # For each entry, collect all note matches
    for idx, entry in enumerate(data):
        if entry is None or "note" not in entry or not entry["note"]:
            continue
        note = entry["note"]
        for regex, wordwrap in note_regexes:
            matches = re.findall(regex, note, re.DOTALL)
            # Special filter for <SG説明:...> to skip if 'Client' is in the match
            if regex.startswith(r"<SG説明:"):
                for m in matches:
                    match_text = m if isinstance(m, str) else m[0]
                    # Skip SG説明 blocks that include a Client: section header
                    if "Client:" in match_text or "Client :" in match_text:
                        continue
                    # Skip if IGNORETLTEXT is enabled and no Japanese text
                    if IGNORETLTEXT and not re.search(LANGREGEX, match_text):
                        continue
                    # Normalize for AI (collapse intra-paragraph \n, keep headers)
                    notesBatch.append(_normalize_sg_desc(match_text))
                    notesBatchMap.append((idx, regex, match_text, wordwrap))
            else:
                for m in matches:
                    match_text = m if isinstance(m, str) else m[0]
                    # Skip if IGNORETLTEXT is enabled and no Japanese text
                    if IGNORETLTEXT and not re.search(LANGREGEX, match_text):
                        continue
                    notesBatch.append(match_text)
                    notesBatchMap.append((idx, regex, match_text, wordwrap))

    # --- Batch translate all notes ---
    translatedNotesBatch = []
    if notesBatch:
        response = translateAI(notesBatch, ctx("database.note"))
        translatedNotesBatch = response[0]
        totalTokens[0] += response[1][0]
        totalTokens[1] += response[1][1]
        # Notes don't update progress

    # --- Insert translated notes back ---
    note_insert_idx = 0
    for idx, regex, match_text, wordwrap in notesBatchMap:
        if note_insert_idx >= len(translatedNotesBatch):
            break
        translated = translatedNotesBatch[note_insert_idx]
        if wordwrap:
            if regex.startswith(r"<SG説明:"):
                translated = dazedwrap.wrapSGDesc(translated, width=NOTEWIDTH)
            else:
                translated = dazedwrap.wrapText(translated, width=NOTEWIDTH)
            translated = translated.replace('"', "")
        # Use a safe literal match for the replacement (no re.escape, just str.replace)
        data[idx]["note"] = data[idx]["note"].replace(match_text, translated, 1)
        note_insert_idx += 1

    # --- For Skills: Batch translate all messages ---
    if context in ["Skills"]:
        messages_batch = []
        messages_map = []  # List of (entry_idx, message_field, needs_taro)
        
        for idx, entry in enumerate(data):
            if entry is None:
                continue
            # Collect all message1-4 fields
            for msg_num in range(1, 5):
                msg_field = f"message{msg_num}"
                if msg_field in entry and entry[msg_field]:
                    msg_text = _entry_field_source(entry, msg_field)
                    if not _entry_field_needs_translation(entry, msg_field):
                        continue
                    needs_taro = len(msg_text) > 0 and msg_text[0] in ["は", "を", "の", "に", "が"]
                    if needs_taro:
                        messages_batch.append("Taro" + msg_text)
                    else:
                        messages_batch.append(msg_text)
                    messages_map.append((idx, msg_field, needs_taro, msg_text))
        
        # Batch translate all messages
        if messages_batch:
            response = translateAI(
                messages_batch,
                "reply with only the gender neutral " + LANGUAGE + " translation of the action log. For messages starting with Taro, always start the sentence with Taro. For example, translate 'Taroを倒した！' as 'Taro was defeated!'",
                False,
            )
            translated_messages = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            
            # Apply translations back to data
            for msg_idx, (entry_idx, msg_field, needs_taro, raw_msg) in enumerate(messages_map):
                if msg_idx < len(translated_messages):
                    translation = translated_messages[msg_idx]
                    if needs_taro:
                        translation = translation.replace("Taro", "")
                    data[entry_idx][msg_field] = translation
                    _apply_entry_field_original(data[entry_idx], msg_field, raw_msg)
            
            # Update progress for messages
            if pbar is not None:
                pbar.refresh()

    # Now continue with the rest of the batching logic for names, descriptions, etc.
    i = 0
    filling = False
    batchFull = False
    mismatch = False
    while i < len(data) or filling == True:
        if i < len(data):
            # Empty Data
            if data[i] is None or data[i]["name"] == "":
                i += 1
                continue
            # Filling up Batch
            filling = True
            if context in "Actors":
                if len(nameList) < BATCHSIZE:
                    name_src = _entry_field_source(data[i], "name")
                    if name_src != "" and _entry_field_needs_translation(data[i], "name"):
                        nameList.append(name_src)
                        nameSourceList.append(name_src)
                        nameIndexList.append(i)
                    if "nickname" in data[i]:
                        nick_src = _entry_field_source(data[i], "nickname")
                        if nick_src and _entry_field_needs_translation(data[i], "nickname"):
                            nicknameList.append(nick_src)
                            nicknameSourceList.append(nick_src)
                            nicknameIndexList.append(i)
                    if "profile" in data[i]:
                        prof_src = _entry_field_source(data[i], "profile")
                        if prof_src and _entry_field_needs_translation(data[i], "profile"):
                            profileList.append(prof_src.replace("\n", " "))
                            profileSourceList.append(prof_src)
                            profileIndexList.append(i)
                    i += 1
                else:
                    batchFull = True
            if context in ["Armors", "Weapons", "Items"]:
                if len(nameList) < BATCHSIZE:
                    name_src = _entry_field_source(data[i], "name")
                    if _entry_field_needs_translation(data[i], "name"):
                        nameList.append(name_src)
                        nameSourceList.append(name_src)
                        nameIndexList.append(i)
                    if "description" in data[i]:
                        desc_src = _entry_field_source(data[i], "description")
                        if desc_src != "":
                            if _entry_field_needs_translation(data[i], "description"):
                                descriptionList.append(desc_src.replace("\n", " "))
                                descriptionSourceList.append(desc_src)
                                descriptionIndexList.append(i)
                    i += 1
                else:
                    batchFull = True
            if context in ["Skills"]:
                if len(nameList) < BATCHSIZE:
                    name_src = _entry_field_source(data[i], "name")
                    if _entry_field_needs_translation(data[i], "name"):
                        nameList.append(name_src)
                        nameSourceList.append(name_src)
                        nameIndexList.append(i)
                    if "description" in data[i]:
                        desc_src = _entry_field_source(data[i], "description")
                        if desc_src:
                            if _entry_field_needs_translation(data[i], "description"):
                                descriptionList.append(desc_src.replace("\n", " "))
                                descriptionSourceList.append(desc_src)
                                descriptionIndexList.append(i)
                    i += 1
                else:
                    batchFull = True
            if context in ["Enemies", "Classes", "MapInfos"]:
                if len(nameList) < BATCHSIZE:
                    name_src = _entry_field_source(data[i], "name")
                    if _entry_field_needs_translation(data[i], "name"):
                        nameList.append(name_src)
                        nameSourceList.append(name_src)
                        nameIndexList.append(i)
                    i += 1
                else:
                    batchFull = True

        # Batch Full
        if batchFull == True or i >= len(data):
            k = j  # Original Index
            if context in "Actors":
                # Track tokens for this batch
                batchTokens = [0, 0]
                # Name
                translatedNameBatch = []
                if nameList:
                    response = translateAI(nameList, newContext)
                    translatedNameBatch = response[0]
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]
                    batchTokens[0] += response[1][0]
                    batchTokens[1] += response[1][1]
                    if pbar is not None:
                        pbar.refresh()

                # Nickname
                translatedNicknameBatch = []
                if nicknameList:
                    response = translateAI(nicknameList, newContext)
                    translatedNicknameBatch = response[0]
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]
                    batchTokens[0] += response[1][0]
                    batchTokens[1] += response[1][1]
                    if pbar is not None:
                        pbar.refresh()

                # Profile
                translatedProfileBatch = []
                if profileList:
                    response = translateAI(profileList, "")
                    translatedProfileBatch = response[0]
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]
                    batchTokens[0] += response[1][0]
                    batchTokens[1] += response[1][1]
                    if pbar is not None:
                        pbar.refresh()

                actor_lengths_match = (
                    len(nameList) == len(translatedNameBatch)
                    and len(nicknameList) == len(translatedNicknameBatch)
                    and len(profileList) == len(translatedProfileBatch)
                )
                if actor_lengths_match:
                    with open("log/translations.txt", "a", encoding="utf-8") as file:
                        for idx, raw_name, translated in zip(
                            nameIndexList, nameSourceList, translatedNameBatch
                        ):
                            file.write(f'{data[idx]["name"]} ({translated})\n')
                            data[idx]["name"] = translated
                            _apply_entry_field_original(data[idx], "name", raw_name)
                    for idx, raw_nick, translated in zip(
                        nicknameIndexList, nicknameSourceList, translatedNicknameBatch
                    ):
                        data[idx]["nickname"] = translated
                        _apply_entry_field_original(data[idx], "nickname", raw_nick)
                    for idx, raw_prof, translated in zip(
                        profileIndexList, profileSourceList, translatedProfileBatch
                    ):
                        data[idx]["profile"] = dazedwrap.wrapText(translated, LISTWIDTH)
                        _apply_entry_field_original(data[idx], "profile", raw_prof)

                    j = i
                    nameList.clear()
                    nameSourceList.clear()
                    nameIndexList.clear()
                    profileList.clear()
                    profileSourceList.clear()
                    profileIndexList.clear()
                    nicknameList.clear()
                    nicknameSourceList.clear()
                    nicknameIndexList.clear()
                    batchFull = False
                    filling = False
                    # Persist after applying this batch only if we actually translated something in this batch
                    checkSave(data, filename, batchTokens)
                else:
                    mismatch = True

            if context in ["Armors", "Weapons", "Items", "Skills"]:
                # Track tokens for this batch
                batchTokens = [0, 0]
                # Name
                translatedNameBatch = []
                if nameList:
                    response = translateAI(nameList, newContext)
                    translatedNameBatch = response[0]
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]
                    batchTokens[0] += response[1][0]
                    batchTokens[1] += response[1][1]
                    if pbar is not None:
                        pbar.refresh()

                # Description
                translatedDescriptionBatch = []
                if descriptionList:
                    response = translateAI(
                        descriptionList,
                        ctx("events.generic_text"),
                        True,
                    )
                    translatedDescriptionBatch = response[0]
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]
                    batchTokens[0] += response[1][0]
                    batchTokens[1] += response[1][1]
                    if pbar is not None:
                        pbar.refresh()

                db_lengths_match = (
                    len(nameList) == len(translatedNameBatch)
                    and len(descriptionList) == len(translatedDescriptionBatch)
                )
                if db_lengths_match:
                    with open("log/translations.txt", "a", encoding="utf-8") as file:
                        for idx, raw_name, translated in zip(
                            nameIndexList, nameSourceList, translatedNameBatch
                        ):
                            file.write(f"{data[idx]['name']} ({translated})\n")
                            if vocab_enabled:
                                vocab_pairs.append((raw_name, translated))
                            data[idx]["name"] = translated
                            _apply_entry_field_original(data[idx], "name", raw_name)
                    for idx, raw_desc, translated in zip(
                        descriptionIndexList,
                        descriptionSourceList,
                        translatedDescriptionBatch,
                    ):
                        data[idx]["description"] = dazedwrap.wrapText(translated, LISTWIDTH)
                        _apply_entry_field_original(data[idx], "description", raw_desc)

                    j = i
                    nameList.clear()
                    nameSourceList.clear()
                    nameIndexList.clear()
                    descriptionList.clear()
                    descriptionSourceList.clear()
                    descriptionIndexList.clear()
                    batchFull = False
                    filling = False
                    # Persist after applying this batch only if we actually translated something in this batch
                    checkSave(data, filename, batchTokens)
                else:
                    mismatch = True
            if context in ["Enemies", "Classes", "MapInfos"]:
                # Track tokens for this batch
                batchTokens = [0, 0]
                translatedNameBatch = []
                if nameList:
                    response = translateAI(nameList, newContext)
                    translatedNameBatch = response[0]
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]
                    batchTokens[0] += response[1][0]
                    batchTokens[1] += response[1][1]
                    if pbar is not None:
                        pbar.refresh()

                # Set Data
                if len(nameList) == len(translatedNameBatch):
                    with open("log/translations.txt", "a", encoding="utf-8") as file:
                        for idx, raw_name, translated in zip(
                            nameIndexList, nameSourceList, translatedNameBatch
                        ):
                            file.write(f'{data[idx]["name"]} ({translated})\n')
                            if vocab_enabled:
                                vocab_pairs.append((raw_name, translated))
                            data[idx]["name"] = translated
                            _apply_entry_field_original(data[idx], "name", raw_name)

                    j = i
                    nameList.clear()
                    nameSourceList.clear()
                    nameIndexList.clear()
                    batchFull = False
                    filling = False
                    # Persist after applying this batch only if we actually translated something in this batch
                    checkSave(data, filename, batchTokens)
                else:
                    mismatch = True

            # Mismatch
            if mismatch == True:
                MISMATCH.append(nameList)
                nameList.clear()
                nameSourceList.clear()
                nameIndexList.clear()
                profileList.clear()
                profileSourceList.clear()
                profileIndexList.clear()
                nicknameList.clear()
                nicknameSourceList.clear()
                nicknameIndexList.clear()
                descriptionList.clear()
                descriptionSourceList.clear()
                descriptionIndexList.clear()
                filling = False
                mismatch = False
                batchFull = False

                i += 1

    # Update vocab section once per context after processing all names
    if vocab_enabled and vocab_pairs:
        update_vocab_section(context, vocab_pairs)

    return totalTokens


def searchCodes(page, pbar, jobList, filename):
    if len(jobList) > 0:
        list401 = jobList[0]
        list122 = jobList[1]
        list355655 = jobList[2]
        list108 = jobList[3]
        list356 = jobList[4]
        list357 = jobList[5]
        list324 = jobList[6]
        list408 = jobList[7]
        list325 = jobList[8]
        list657 = jobList[9]
        setData = False
    else:
        list401 = []
        list122 = []
        list355655 = []
        list108 = []
        list356 = []
        list357 = []
        list324 = []
        list408 = []
        list325 = []
        list657 = []
        setData = True
    textHistory = []
    match = []
    totalTokens = [0, 0]
    translatedText = ""
    sourceQuestion = ""
    romashaCommentContext = False
    speaker = ""
    speakerID = None
    syncIndex = 0
    maxHistory = MAXHISTORY
    VNameValue = None
    reduceWidthFlag = False  # Track whether the active 101 reserves face space
    global LOCK
    global NAMESLIST
    global MISMATCH
    global PBAR
    with LOCK:
        PBAR = pbar

    # Begin Parsing File
    try:
        # Normal Format
        if "list" in page:
            codeList = page["list"]

        # Special Format (Scenario)
        else:
            codeList = page

        # Iterate through page
        i = 0
        while i < len(codeList):
            with LOCK:
                # syncIndex will keep i in sync when it gets modified
                if syncIndex > i:
                    i = syncIndex
                if len(codeList) <= i:
                    break

            # Declare Varss
            currentGroup = []
            sourceGroup = []
            currentSourceGroup = []
            nametag = ""

            # Face layout affects the following message even when code-101 name
            # translation is disabled or face-to-speaker resolution exits early.
            if "code" in codeList[i] and codeList[i]["code"] == 101:
                reduceWidthFlag = _101_has_face_graphic(codeList[i])
            elif (
                reduceWidthFlag
                and "code" in codeList[i]
                and codeList[i]["code"] not in (401, -1)
            ):
                reduceWidthFlag = False

            ## Event Code: 401 Show Text
            if "code" in codeList[i] and codeList[i]["code"] in [401, 405, -1] and ((codeList[i]["code"] in [401, -1] and CODE401) or (codeList[i]["code"] == 405 and CODE405)):
                # Save Code and starting index (j)
                code = codeList[i]["code"]
                j = i
                groupStart = j
                endtag = ""
                instantLineFlag = False

                # Grab String
                if len(codeList[i]["parameters"]) > 0:
                    previewEnd = _text_group_end(codeList, i, (401, 405, -1))
                    if not _text_needs_translation(_group_current(codeList, i, previewEnd)):
                        i = previewEnd + 1
                        continue
                    jaString = codeList[i]["parameters"][0]
                    oldjaString = _param_source(codeList[i], 0)
                    speakerWork = oldjaString
                else:
                    codeList[i]["code"] = -1
                    i += 1
                    continue

                # # For Retarded Devs
                # retardRegex = r'([\\]+[nN]\[[\\]+V\[\d*?\]\])'
                # match = re.search(retardRegex, jaString)
                # if match:
                #     if VNameValue == 1:
                #         jaString = re.sub(retardRegex, 'リッカ', jaString)
                #     if VNameValue == 2:
                #         jaString = re.sub(retardRegex, 'ミミ', jaString)
                #     if VNameValue == 3:
                #         jaString = re.sub(retardRegex, 'ヒトミ', jaString)
                #     if VNameValue == 4:
                #         jaString = re.sub(retardRegex, 'Taro', jaString)
                #     if VNameValue == 5:
                #         jaString = re.sub(retardRegex, '富士見', jaString)

                # Speaker Check
                speakerList = []

                # m and z Codes
                match = re.search(r"(.*?)[\\]+m\[\d+?\][\\]+z\[\d+?\]", speakerWork)
                if match:
                    speakerList.append(match.group(1))
                    if "\\c" in speakerList[0]:
                        speakerList = re.findall(
                            r"^[\\]+[cC]\[\d+\]【?(.+?)】?[\\]+[cC]\[\d+\](?:[\\]+[A-Za-z]+(?:\[[^\]]*\])?)*[\\]*$",
                            speakerList[0],
                        )

                # Brackets (support multiple names like 【A】【B】)
                if len(speakerList) == 0:
                    # Check for bracket at start with dialogue following (【name】dialogue...)
                    inlineBracketMatch = re.match(r"^\s*【([^】]+)】(.+)", speakerWork, re.DOTALL)
                    
                    if inlineBracketMatch:
                        # Inline bracket with dialogue on same line
                        speakerList = [inlineBracketMatch.group(1).strip()]
                    else:
                        # Only consider bracketed names when the line starts with '【' and
                        # ends with either '】' or trailing variable/control codes like \n[2], \FF[\w[3]], etc.
                        startsWithBracket = re.match(r"^\s*【", speakerWork) is not None
                        endsWithBracket = re.search(
                            r"(】\s*|(?:[\\]+[A-Za-z]+(?:\[(?:[^\[\]]|\[[^\]]*\])*\])+\s*)$)",
                            speakerWork,
                        ) is not None

                        if startsWithBracket and endsWithBracket:
                            candidates = re.findall(r"【(.*?)】", speakerWork)
                            if candidates:
                                candidates = [c.strip() for c in candidates]
                                if candidates:
                                    speakerList = candidates

                # Colors
                if len(speakerList) == 0:
                    speakerList = re.findall(
                        r"^[\\]+[cC]\[\d+\]【?(.+?)】?[\\]+[cC]\[\d+\](?:[\\]+[A-Za-z]+(?:\[[^\]]*\])?)*[\\]*$",
                        speakerWork,
                    )

                # Colons
                if len(speakerList) == 0:
                    speakerList = re.findall(
                        r"(.+)：$",
                        speakerWork,
                    )

                # [Speaker] standalone line format (written back by inline re-export)
                if len(speakerList) == 0:
                    inlineFmtMatch = re.match(rf"^\[({SPEAKER_BRACKET_INNER})\]\s*$", speakerWork, re.IGNORECASE)
                    if inlineFmtMatch:
                        speakerList = [inlineFmtMatch.group(1).strip()]

                # Inline speaker detection — Name「/Name: "/Name: (/[Name] "/[Name] (
                if len(speakerList) == 0 and INLINE401SPEAKERS:
                    inlineSpeakerMatch = re.match(
                        r'^(?:\[([^\]]{1,30})\]\s*|([^\s「」。、！？…\\\n“”"(:\[\]]{1,20})(?:[::：]?\s*)(?=[「“"(]))(.*)',
                        speakerWork, re.DOTALL
                    )
                    if inlineSpeakerMatch:
                        speakerList = [(inlineSpeakerMatch.group(1) or inlineSpeakerMatch.group(2)).strip()]
                else:
                    inlineSpeakerMatch = None

                # First Line Speakers
                if len(speakerList) == 0 and FIRSTLINESPEAKERS is True:
                    # Test Speaker
                    if (
                        len(speakerWork) < 40
                        and i + 1 < len(codeList)
                        and "code" in codeList[i + 1]
                        and codeList[i + 1]["code"] in [401, 405, -1]
                        and len(codeList[i + 1]["parameters"]) > 0
                        and len(codeList[i + 1]["parameters"][0]) > 0
                    ):
                        nextString = codeList[i + 1]["parameters"][0].strip()

                        # Remove any RPGMaker Code at start
                        ffMatchNS = re.search(
                            r"^((?:[\\]+[^cCnNiIkKvVSs{}]+?\[[\d\w\W]+?\]?\])+)",
                            nextString,
                        )
                        formatMatch = re.search(r"(^[\\]+[\W]+?)", nextString)
                        if ffMatchNS != None:
                            nextString = nextString.replace(ffMatchNS.group(1), "")
                        if formatMatch != None:
                            nextString = nextString.replace(formatMatch.group(1), "")

                        if nextString and nextString[0] in [
                            "「",
                            '"',
                            "(",
                            "（",
                            "*",
                            "[",
                        ]:
                            speakerList = re.findall(r".+", speakerWork)

                # Replace Speaker
                if len(speakerList) != 0:
                    # Check if speaker+dialogue are on same line
                    sameLineMatch = re.match(r"^\s*【([^】]+)】(.+)", speakerWork, re.DOTALL)
                    if inlineSpeakerMatch and len(speakerList) == 1:
                        # Strip speaker prefix, keep everything after as dialogue
                        response = getSpeaker(speakerList[0])
                        speaker = response[0]
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]
                        jaString = inlineSpeakerMatch.group(3)
                        if not setData:
                            nametag = f"[{speaker}]\n" + nametag
                    elif sameLineMatch and len(speakerList) == 1:
                        # Translate speaker
                        response = getSpeaker(speakerList[0])
                        speaker = response[0]
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]
                        # Remove speaker bracket from jaString, let dialogue get translated
                        jaString = sameLineMatch.group(2)
                        # Store the translated bracket to add back later
                        if not setData:
                            nametag = f"[{speaker}]\n" + nametag
                        # Don't skip to next line - continue with current line
                    elif codeList[i + 1]["code"] in [401, 405, -1]:
                        # Original behavior: speaker on its own line, dialogue on next line
                        # Single
                        if len(speakerList) == 1:
                            response = getSpeaker(speakerList[0])
                            speaker = response[0]
                            totalTokens[0] += response[1][0]
                            totalTokens[1] += response[1][1]

                        # Multiple (Brackets)
                        elif len(speakerList) > 1:
                            jaStringUpdated = jaString
                            for idx, sp in enumerate(speakerList):
                                response = getSpeaker(sp)
                                tled = response[0]
                                totalTokens[0] += response[1][0]
                                totalTokens[1] += response[1][1]
                                if not setData:
                                    pattern = r"【\s*" + re.escape(sp) + r"\s*】"
                                    jaStringUpdated = re.sub(pattern, lambda m: f"【{tled}】", jaStringUpdated)
                                # Back-compat: set 'speaker' to the first translated name
                                if idx == 0:
                                    speaker = tled

                        # Set Data
                        if not setData and len(speakerList) > 1:
                            codeList[i]["parameters"][0] = nametag + jaStringUpdated
                            _apply_original(codeList[i], oldjaString)
                        elif not setData and len(speakerList) == 1:
                            paramStr = codeList[i]["parameters"][0]
                            codeList[i]["parameters"][0] = nametag + _replace_speaker_in_param(
                                paramStr, speakerList[0], speaker
                            )
                            _apply_original(codeList[i], oldjaString)
                        nametag = ""

                        # Iterate to next string
                        i += 1
                        j = i
                        while codeList[i]["code"] in [-1]:
                            i += 1
                            j = i
                        jaString = codeList[i]["parameters"][0]
                        groupStart = i

                # Using this to keep track of 401's in a row (display text for Pass 2 formatting).
                currentGroup.append(jaString)
                anchor_has_orig = _scalar_original(codeList[groupStart]) is not None
                sourceGroup.append(_param_source(codeList[i], 0))
                currentSourceGroup.append(_param_current(codeList[i], 0))

                # Join Up 401's into single string
                if len(codeList) > i + 1:
                    while codeList[i + 1]["code"] in [401, 405, -1] and len(codeList[i]["parameters"]) > 0 and len(codeList[i + 1]["parameters"]) > 0 and not re.match(r"^(\s*[\\]+[aAbBdDeEfFgGhHjJlLmMoOpPqQrRsStTuUwWxXyYzZ]+\[[\w\d\[\]\\]+\])", codeList[i+1]["parameters"][0]):
                        if not setData:
                            codeList[i]["parameters"] = []
                            codeList[i]["code"] = -1
                        i += 1
                        j = i

                        jaString = codeList[i]["parameters"][0]
                        if jaString.strip():
                            currentGroup.append(jaString)
                            currentSourceGroup.append(_param_current(codeList[i], 0))
                            if not anchor_has_orig:
                                sourceGroup.append(_param_source(codeList[i], 0))

                        # Make sure not the end of the list.
                        if len(codeList) <= i + 1:
                            break

                # Format String
                if len(currentGroup) > 0:
                    rawSource = _group_raw_source(codeList, groupStart, sourceGroup)
                    currentSource = "\n".join(currentSourceGroup)
                    # Skip status is based on the live text, not preserved Japanese source.
                    if not rawSource.strip() or not _text_needs_translation(currentSource):
                        speaker = ""
                        i += 1
                        continue

                    finalJAString = rawSource
                    oldjaString = rawSource

                    # Set Back
                    if not setData:
                        codeList[i]["parameters"] = [finalJAString]

                    ### \\n<Speaker>
                    regex = r"([\\]+[kKnN][wWcCrRrEe]?[\[<](?:[\\]*\w\[\d+\])?(.*?)(?:[\\]*\w\[\d+\])?[>])"
                    match = re.search(regex, finalJAString)

                    # Set Name
                    if match:
                        nametag = match.group(1)
                        speaker = match.group(2)

                        # Translate Speaker
                        response = getSpeaker(speaker)
                        tledSpeaker = response[0]
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]

                        # Set Nametag and Remove from Final String
                        finalJAString = finalJAString.replace(nametag, "")
                        nametag = nametag.replace(speaker, tledSpeaker)
                        speaker = tledSpeaker

                    # Remove Extra Stuff bad for translation.
                    finalJAString = finalJAString.replace("ﾞ", "")
                    finalJAString = finalJAString.replace("　", "")
                    finalJAString = convert_corner_brackets(
                        finalJAString, TRANSLATION_CONFIG.convertQuotes
                    )
                    finalJAString = finalJAString.replace("\\,", ',')

                    ### Remove format codes
                    # Furigana: \r or \rb [base,reading] -> keep reading/base per pattern
                    finalJAString = re.sub(r"[\\]+[rR][bB]?\[(.*?),.*?\]", r"\1", finalJAString)

                    # Curly-brace furigana: {base|reading} -> keep base
                    finalJAString = re.sub(r"\{([^|{}]+)\|[^|{}]+?\}", r"\1", finalJAString)

                    # Remove any RPGMaker Code at start
                    ffMatch = re.search(
                        r"^((?:[\\]+[^cCnNiIkKvV{}]+?\[[\d\w\W]+?\]?\])+)",
                        finalJAString,
                    )
                    if ffMatch != None:
                        finalJAString = finalJAString.replace(ffMatch.group(1), "")
                        nametag = ffMatch.group(1) + nametag

                    # Remove bare escape codes at start (e.g. \\mn\\tmn, \\tmn, \\mn, \\vc)
                    bareMatch = re.match(r"^(\\mn\\tmn|\\tmn|\\mn|\\vc)", finalJAString)
                    if bareMatch is not None:
                        finalJAString = finalJAString[len(bareMatch.group(0)):]
                        nametag = bareMatch.group(0) + nametag

                    # Remove _ABL Codes
                    ffMatch = re.search(r"^(_ABL).*", finalJAString)
                    if ffMatch != None:
                        finalJAString = finalJAString.replace(ffMatch.group(1), "")
                        nametag += ffMatch.group(1)

                    # Center Lines (We Nuke These)
                    if "\\CL" in finalJAString or "\\ac" in finalJAString or "\\#" in finalJAString:
                        finalJAString = finalJAString.replace("\\CL", "")
                        finalJAString = finalJAString.replace("\\ac", "")
                        finalJAString = finalJAString.replace("\\#", "")

                    # Handle Formatting Codes
                    if "\\>" in finalJAString:
                        instantLineFlag = True
                        finalJAString = finalJAString.replace("\\>", "")

                    # Check if Empty
                    if finalJAString == "":
                        if nametag and match:
                            codeList[j]["parameters"][0] = codeList[j]["parameters"][0].replace(match.group(2), tledSpeaker)
                        i += 1
                        continue

                    # Pass 1 (Grabbing Data)
                    if setData:
                        # Remove Textwrap
                        if FIXTEXTWRAP:
                            finalJAString = finalJAString.replace("\n", " ")
                        if "\\px[200]" in finalJAString:
                            finalJAString = finalJAString.replace("\\px[200]", "")

                        # Append
                        if finalJAString != "":
                            if speaker == "" and finalJAString != "":
                                list401.append(finalJAString)
                                historyEntry = finalJAString
                            elif finalJAString != "":
                                list401.append(f"[{speaker}]: {finalJAString}")
                                historyEntry = f"[{speaker}]: {finalJAString}"
                            else:
                                list401.append(speaker)
                                historyEntry = speaker
                        speaker = ""
                        match = []
                        nametag = ""
                        currentGroup = []
                        sourceGroup = []
                        currentSourceGroup = []
                        syncIndex = i + 1

                        # Keep textHistory list at length maxHistory
                        textHistory.append('"' + historyEntry + '"')
                        if len(textHistory) > maxHistory:
                            textHistory.pop(0)

                    # Pass 2 (Setting Data)
                    else:
                        # Grab Translated String
                        if len(list401) > 0:
                            rawSource = _group_raw_source(codeList, groupStart, sourceGroup)
                            translatedText = list401[0]

                            # Remove speaker prefix if present
                            translatedText = strip_speaker_prefix(translatedText)

                            # Remove 。 that appears after ... in AI output
                            translatedText = re.sub(r'\.\.\.(。)+', '...', translatedText)

                            # Ensure a space follows sentence-ending punctuation before a capital letter.
                            # Japanese doesn't use spaces after ！/？, so the AI omits them too.
                            translatedText = re.sub(r'([!?])([A-Z])', r'\1 \2', translatedText)

                            # Ensure a single space before a run of RPGMaker pause/wait codes
                            # (\. \! \| \^) when immediately preceded by a word/punctuation char.
                            # Matches the whole code run at once so no intra-run spaces are added.
                            translatedText = re.sub(r'([^\s\\])((?:\\[.!|^])+)', r'\1 \2', translatedText)

                            # Fix '- '
                            translatedText = translatedText.replace("- ", "-")

                            # Textwrap
                            if FIXTEXTWRAP is True:
                                finalJAString = re.sub(r"\n", " ", finalJAString)
                                finalJAString = finalJAString.replace("<br>", " ")

                            # Determine width based on reduceWidthFlag
                            currentWidth = FACEWIDTH if reduceWidthFlag else WIDTH

                            if FIXTEXTWRAP is True and "_ABL" in nametag:
                                translatedText = dazedwrap.wrapText(translatedText, width=100)
                            elif FIXTEXTWRAP is True:
                                translatedText = dazedwrap.wrapText(translatedText, width=currentWidth)

                            # Reset the flag after using it
                            reduceWidthFlag = False

                            # Formatting Code
                            if instantLineFlag:
                                translatedText = translatedText.replace("\n", "\n\\>")
                                translatedText = f"\\>{translatedText}"

                            # BR Flag
                            if BRFLAG is True:
                                translatedText = translatedText.replace("\n", "<br>")

                            # px
                            if "\\px[200]" in nametag:
                                translatedText = translatedText.replace("\\px[200]", "")
                                translatedText = translatedText.replace("\n", "\n\\px[200]")

                            # Add Nametag Back In
                            translatedText = nametag + translatedText
                            nametag = ""

                            # Endtag
                            if endtag != "":
                                translatedText = translatedText + endtag
                                endtag = ""

                            # Set Code
                            codeList[j]["code"] = code

                            # Handle 405
                            if codeList[j]["code"] == 405:
                                # 1. Split translatedText by newlines
                                lines = [line for line in translatedText.split('\n') if line.strip() != ""]
                                
                                # 2. Set the first string to codeList[j]["parameters"]
                                codeList[j]["parameters"] = [lines[0]]
                                
                                # 3. Make copies for each additional line and insert them
                                for idx, line in enumerate(lines[1:]):
                                    new_item = copy.deepcopy(codeList[j])
                                    new_item.pop("_original", None)
                                    new_item["parameters"] = [line]
                                    codeList.insert(j + idx + 1, new_item)
                                
                                # 4. Update syncIndex to the last modified/added position
                                syncIndex = j + len(lines)

                            # Handle 401
                            else:
                                codeList[j]["parameters"] = [translatedText]
                                codeList[j]["code"] = code
                                syncIndex = i + 1

                            _apply_original(codeList[j], rawSource)

                            # Reset
                            speaker = ""
                            match = []
                            currentGroup = []
                            sourceGroup = []
                            list401.pop(0)

            ## Event Code: 122 [Set Variables]
            if "code" in codeList[i] and codeList[i]["code"] == 122 and CODE122 is True:
                # This is going to be the var being translated.
                # Only translate variables within the specified range.
                if codeList[i]["parameters"][0] not in list(range(CODE122_VAR_MIN, CODE122_VAR_MAX)):
                    i += 1
                    continue

                jaString = codeList[i]["parameters"][4]

                # # For Retarded Devs
                # VNameValue = jaString
                # i += 1
                # continue

                # Validate String
                if not isinstance(jaString, str):
                    i += 1
                    continue

                # Definitely don't want to mess with files
                if 'gameV' in jaString or '_' in jaString or '"[' in jaString or '＠' in jaString:
                    i += 1
                    continue

                # # Avoid anything not quoted
                # if '\"' not in jaString:
                #     i += 1
                #     continue

                # Validate Japanese Text
                # if not re.search(LANGREGEX, jaString):
                #     i += 1
                #     continue

                # Set String
                innerSource = _122_inner_source(codeList[i])
                if innerSource is not None and innerSource.strip():
                    if not _text_needs_translation(_122_inner_current(codeList[i])):
                        i += 1
                        continue

                    # Remove Textwrap
                    finalJAString = innerSource.replace("\\n", " ")

                    # Pass 1
                    if setData:
                        if finalJAString != "":
                            list122.append(finalJAString)

                    # Pass 2
                    else:
                        if len(list122) > 0:
                            rawInner = innerSource
                            hadSemicolon = ';' in jaString
                            # Grab and Replace
                            translatedText = list122[0]
                            translatedText = jaString.replace(jaString, translatedText)

                            # Remove characters that may break scripts
                            charList = ['"', "\\n"]
                            for char in charList:
                                translatedText = translatedText.replace(char, "")

                            # Force 4 Escapes
                            translatedText = re.sub(r'(?<![\\])([\\]{1})(?=\w)', r'\\\\', translatedText)

                            # Textwrap
                            translatedText = dazedwrap.wrapText(translatedText, width=LISTWIDTH)
                            translatedText = translatedText.replace("\n", "\\n")

                            # Set
                            codeList[i]["parameters"][4] = f"`{translatedText}`"
                            if hadSemicolon:
                                codeList[i]["parameters"][4] += ';'

                            _apply_original(codeList[i], rawInner)
                            list122.pop(0)

            ## Event Code: 357 [Picture Text] [Optional]
            if "code" in codeList[i] and codeList[i]["code"] == 357 and CODE357 is True:
                headerString = codeList[i]["parameters"][0]
                argVar = None

                def translatePlugins(argVar, font):
                    ### Message Text First
                    if argVar in codeList[i]["parameters"][3]:
                        acExist = False
                        jaString = codeList[i]["parameters"][3][argVar]

                        # Check ac
                        if "\\ac" in jaString:
                            acExist = True
                        else:
                            acExist = False

                        # Skip if IGNORETLTEXT is enabled and no Japanese text
                        if IGNORETLTEXT and not re.search(LANGREGEX, jaString):
                            return

                        # If there isn't any Japanese in the text just skip
                        # if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', jaString):
                        #     i += 1
                        #     continue

                        # Remove any textwrap & TL
                        jaString = jaString.replace("\n", " ")
                        if acExist:
                            jaString = jaString.replace("\\ac ", " ")
                            jaString = jaString.replace("\\ac", "")

                        # Pass 1
                        if setData:
                            list357.append(jaString)

                        # Pass 2
                        else:
                            if len(list357) > 0:
                                # Grab and Replace
                                translatedText = list357[0]
                                translatedText = jaString.replace(jaString, translatedText)

                                # Remove characters that may break scripts
                                charList = ['"', "\n"]
                                for char in charList:
                                    translatedText = translatedText.replace(char, "")

                                # Textwrap
                                # translatedText = dazedwrap.wrapText(translatedText, 80)
                                # translatedText = translatedText.replace("\n", "\\n")
                                # translatedText = re.sub(r"[\\]+c", r"\\\\c", translatedText)
                                translatedText = re.sub(r"[\\]+\*item", r"\\\\*item", translatedText)

                                # Center Text
                                if acExist:
                                    translatedText = f'\\ac {translatedText.replace('\n', '\n\\ac ')}'

                                # Check and Set Font
                                if "fontSize" in codeList[i]["parameters"][3]:
                                    if font:
                                        codeList[i]["parameters"][3]["fontSize"] = font

                                # Set
                                codeList[i]["parameters"][3][argVar] = f"{translatedText}"
                                list357.pop(0)

                # Map Plugins — use module-level registry filtered by ENABLED_PLUGINS_357
                headerMappings = {
                    k: v for k, v in HEADER_MAPPINGS_357.items()
                    if k in ENABLED_PLUGINS_357
                }

                for key, (argVars, font) in headerMappings.items():
                    if key in headerString:
                        for argVar in argVars:
                            translatePlugins(argVar, font)

                # KN_StillManager: translate parameters[2] (the display label, e.g. "ギャラリーを開く")
                # Only OPEN_GALLERY has a player-visible label in parameters[2].
                # Other commands (SHOW_BY_ID, HIDE, etc.) use parameters[2] as an internal label.
                if (headerString == "KN_StillManager" and "KN_StillManager" in ENABLED_PLUGINS_357
                        and len(codeList[i]["parameters"]) > 2
                        and len(codeList[i]["parameters"]) > 1
                        and codeList[i]["parameters"][1] == "OPEN_GALLERY"):
                    p2 = codeList[i]["parameters"][2]
                    if isinstance(p2, str) and p2.strip():
                        if not (IGNORETLTEXT and not re.search(LANGREGEX, p2)):
                            if setData:
                                list357.append(p2)
                            else:
                                if len(list357) > 0:
                                    translatedText = list357[0]
                                    list357.pop(0)
                                    translatedText = translatedText.replace('"', "")
                                    codeList[i]["parameters"][2] = translatedText

                # AdvExtention plugin support (message event)
                if headerString == "AdvExtentionllk" and len(codeList[i]["parameters"]) > 3:
                    try:
                        params_obj = codeList[i]["parameters"][3]
                    except Exception:
                        params_obj = None

                    if isinstance(params_obj, dict):
                        # 1) Speaker comes from 'name', fallback to 'altName' if missing/empty
                        speaker_name = ""
                        if isinstance(params_obj.get("altName", None), str) and params_obj["altName"].strip():
                            speaker_name = params_obj["altName"].strip()
                            if speaker_name:
                                response = getSpeaker(speaker_name)
                                params_obj["altName"] = response[0]
                                totalTokens[0] += response[1][0]
                                totalTokens[1] += response[1][1]
                                speaker = response[0]
                        if isinstance(params_obj.get("name", None), str) and params_obj["name"].strip():
                            speaker_name = params_obj["name"].strip()
                            if speaker_name:
                                response = getSpeaker(speaker_name)
                                params_obj["name"] = response[0]
                                totalTokens[0] += response[1][0]
                                totalTokens[1] += response[1][1]
                                speaker = response[0]
                        speaker = ""

                        # 2) Line comes from 'comment' if present, else 'text'
                        chosen_key = None
                        if isinstance(params_obj.get("comment", None), str) and params_obj["comment"].strip():
                            chosen_key = "comment"
                        elif isinstance(params_obj.get("text", None), str):
                            chosen_key = "text"

                        if chosen_key is not None:
                            jaString = params_obj.get(chosen_key, "")
                            if isinstance(jaString, str):
                                # Pass 1 (collect data)
                                if setData:
                                    if FIXTEXTWRAP:
                                        jaString = jaString.replace("\n", " ")
                                    # Include speaker context like 401 does
                                    if 'speaker' in locals() and isinstance(speaker, str) and speaker.strip():
                                        list357.append(f"[{speaker}]: {jaString}")
                                    else:
                                        list357.append(jaString)
                                # Pass 2 (apply translation)
                                else:
                                    if len(list357) > 0:
                                        translatedText = list357[0]
                                        list357.pop(0)

                                        # Remove speaker prefix if present (same pattern used for 401)
                                        translatedText = strip_speaker_prefix(translatedText)

                                        if FIXTEXTWRAP:
                                            translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)

                                        params_obj[chosen_key] = translatedText

                # VisuMZ_4_ProximityMessages handler
                # Text:json value is stored as a JSON-encoded string, e.g. "\"\\\\{\\\\{text\""
                # After Python JSON parsing: "\\{\\{text" (outer quotes + \\{ formatting prefix)
                if "VisuMZ_4_ProximityMessages" in headerString and len(codeList[i]["parameters"]) > 3:
                    params_obj = codeList[i]["parameters"][3]
                    if isinstance(params_obj, dict) and "Text:json" in params_obj:
                        rawValue = params_obj["Text:json"]
                        if isinstance(rawValue, str):
                            # Strip outer JSON quotes ("\"...\"" wrapper)
                            innerMatch = re.match(r'^"(.*)"$', rawValue, re.DOTALL)
                            innerText = innerMatch.group(1) if innerMatch else rawValue

                            # Preserve \\{ / \\} RPGMaker font-size codes at start and end
                            prefixMatch = re.match(r'^((?:\\\\[{}])+)', innerText)
                            prefix = prefixMatch.group(1) if prefixMatch else ""
                            remaining = innerText[len(prefix):]
                            suffixMatch = re.search(r'((?:\\\\[{}])+)$', remaining)
                            suffix = suffixMatch.group(1) if suffixMatch else ""
                            jaString = remaining[: len(remaining) - len(suffix)] if suffix else remaining

                            # Skip if IGNORETLTEXT is enabled and no Japanese text
                            skip = IGNORETLTEXT and not re.search(LANGREGEX, jaString)
                            if not skip and jaString.strip():
                                # Pass 1
                                if setData:
                                    list357.append(jaString)
                                # Pass 2
                                else:
                                    if len(list357) > 0:
                                        translatedText = list357[0]
                                        list357.pop(0)

                                        # Remove characters that would break the JSON string encoding
                                        translatedText = translatedText.replace('"', "'")

                                        # Normalize color/name codes to 4 backslashes (required for Text:json encoding)
                                        translatedText = re.sub(r'\\{1,3}([cCnNiIvV]\[\d+\])', r'\\\\\\\\\1', translatedText)

                                        # Reassemble: restore outer quotes and formatting codes
                                        params_obj["Text:json"] = f'"{prefix}{translatedText}{suffix}"'

                if headerString == "LL_GalgeChoiceWindow":
                    ### Message Text First
                    jaString = codeList[i]["parameters"][3]["messageText"]

                    # Remove any textwrap & TL
                    jaString = re.sub(r"\n", " ", jaString)
                    sourceQuestion = jaString
                    response = translateAI(jaString, "")
                    translatedText = response[0]
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]

                    # Textwrap & Set
                    translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)
                    codeList[i]["parameters"][3]["messageText"] = translatedText

                    ### Choices
                    jaString = codeList[i]["parameters"][3]["choices"]
                    matchList = re.findall(r'"label[\\]*":[\\]*"(.*?)[\\]', jaString)
                    if matchList != None:
                        # Give choices the original Japanese question, never
                        # the translated text written back above.
                        response = translateAI(
                            matchList,
                            {
                                "instructions": [ctx("events.choice")],
                                "source_items": [sourceQuestion],
                            },
                            True,
                        )
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]
                        translatedText = jaString

                        # Replace Strings
                        for j in range(len(matchList)):
                            translatedText = translatedText.replace(matchList[j], response[0][j].replace('"', ''))

                        # Set Data
                        codeList[i]["parameters"][3]["choices"] = translatedText

            ## Event Code: 657 [Picture Text] [Optional]
            if "code" in codeList[i] and codeList[i]["code"] == 657 and CODE657 is True:
                jaString = codeList[i]["parameters"][0]
                if not isinstance(jaString, str):
                    i += 1
                    continue

                # Definitely don't want to mess with files
                if "_" in jaString:
                    i += 1
                    continue

                # Only translate 'メッセージ = <value>' key/value pairs.
                # All other keys (ページ番号, イベントID, アイコンID, etc.) are internal references.
                kvMatch = re.match(r"^'?([^=]+?)\s*=\s*(.*?)'?$", jaString, re.DOTALL)
                if kvMatch:
                    kvKey = kvMatch.group(1).strip()
                    kvValue = kvMatch.group(2).strip()
                    # Strip any outer single-quotes wrapping the value
                    kvValue = re.sub(r"^'(.*)'$", r"\1", kvValue)

                    if kvKey != 'メッセージ':
                        i += 1
                        continue

                    # Skip if IGNORETLTEXT is enabled and no Japanese text
                    if IGNORETLTEXT and not re.search(LANGREGEX, kvValue):
                        i += 1
                        continue

                    if not kvValue.strip():
                        i += 1
                        continue

                    # Remove any textwrap
                    kvValue = re.sub(r"\n", " ", kvValue)

                    # Pass 1 – collect value for batch translation
                    if setData:
                        list657.append(kvValue)

                    # Pass 2 – apply translated value
                    else:
                        if len(list657) > 0:
                            translatedText = list657[0]
                            list657.pop(0)
                            for char in ['"', "'"]:
                                translatedText = translatedText.replace(char, "")
                            codeList[i]["parameters"][0] = f"'{kvKey} = {translatedText}'"

            ## Event Code: 101 [Name] [Optional]
            if "code" in codeList[i] and codeList[i]["code"] == 101 and CODE101 is True:
                isVar = False

                # Check for face name mappings first (before other processing)
                if FACENAME101:
                    matchedSpeaker = _facename101_speaker(codeList[i])
                    if matchedSpeaker is not None:
                        speaker = matchedSpeaker
                        i += 1
                        continue

                # Grab String
                jaString = ""
                if len(codeList[i]["parameters"]) > 4:
                    jaString = codeList[i]["parameters"][4]
                # Check for Var (only when parameters[0] is not a face file,
                # i.e. fewer than 4 params — standard code 101 always has 4:
                # [faceFile, faceIndex, background, position])
                elif 0 < len(codeList[i]["parameters"]) < 4:
                    jaString = codeList[i]["parameters"][0]
                    isVar = True
                if not isinstance(jaString, str):
                    i += 1
                    continue

                varActorMatch = re.match(r"^\s*(?:[\\]+[cC]\[\d+?\]\s*)?[\\]+[nN]\[(\d+)\]", jaString)
                if varActorMatch:
                    actorName = _get_actor_map().get(int(varActorMatch.group(1)))
                    speaker = actorName or varActorMatch.group(0).strip()
                    i += 1
                    continue

                # Force Speaker using var
                if "memerisu" in jaString.lower():
                    speaker = "Memerisu"
                    i += 1
                    continue
                elif "thina" in jaString.lower():
                    speaker = "Tina"
                    i += 1
                    continue
                elif "\\ap" in jaString.lower():
                    # Extract actor ID from format like \\AP[2左] or \\AP[2]仙人
                    apMatch = re.search(r"[\\]+[aA][pP]\[(\d+)[^\]]*\](.*)$", jaString, re.IGNORECASE)
                    if apMatch:
                        actorId = int(apMatch.group(1))
                        additionalText = apMatch.group(2).strip()
                        
                        # Load Actors.json to get the actor name
                        try:
                            actorsPath = Path("files/Actors.json")
                            if actorsPath.exists():
                                with open(actorsPath, 'r', encoding='utf-8') as f:
                                    actorsData = json.load(f)
                                
                                # Find the actor with matching ID
                                actorName = None
                                for actor in actorsData:
                                    if actor and isinstance(actor, dict) and actor.get("id") == actorId:
                                        actorName = actor.get("name", "")
                                        break
                                
                                if actorName:
                                    speaker = actorName
                                    
                                    # If there's additional text after \\AP[ID], translate it
                                    if additionalText:
                                        response = getSpeaker(additionalText)
                                        translatedAdditionalText = response[0]
                                        totalTokens[0] += response[1][0]
                                        totalTokens[1] += response[1][1]
                                        
                                        # Replace the text in the parameter
                                        if isVar == False and len(codeList[i]["parameters"]) > 4:
                                            codeList[i]["parameters"][4] = codeList[i]["parameters"][4].replace(additionalText, translatedAdditionalText)
                                        else:
                                            codeList[i]["parameters"][0] = codeList[i]["parameters"][0].replace(additionalText, translatedAdditionalText)
                        except Exception as e:
                            # If there's any error loading actors, just extract what's in the brackets
                            speaker = apMatch.group(1)
                    else:
                        # Fallback to old behavior
                        speaker = re.search(r"[\\]+AP\[(.*?)\]", jaString).group(1)
                    i += 1
                    continue

                # Get Speaker
                rawName = _101_name_source(codeList[i], isVar)
                sourceName = _101_speaker_name(rawName)
                currentName = _101_speaker_name(_101_name_current(codeList[i], isVar))
                if sourceName and _text_needs_translation(currentName):
                    response = getSpeaker(sourceName)
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]
                    speaker = response[0]

                    # Validate Speaker is not empty
                    if len(speaker) > 0:
                        paramIdx = 0 if isVar else 4
                        paramStr = codeList[i]["parameters"][paramIdx]
                        codeList[i]["parameters"][paramIdx] = _replace_speaker_in_param(
                            paramStr, sourceName, speaker
                        )
                        _apply_original(codeList[i], rawName)
                        isVar = False
                        i += 1
                        continue
                    else:
                        speaker = ""


            ## Event Code: 355 or 655 Scripts [Optional]
            if "code" in codeList[i] and (codeList[i]["code"] == 355 or codeList[i]["code"] == 655) and CODE355655 is True:
                jaString = codeList[i]["parameters"][0]
                
                # Patterns — use module-level registry filtered by ENABLED_PATTERNS_355655
                patterns = {
                    k: v for k, v in PATTERNS_355655.items()
                    if k in ENABLED_PATTERNS_355655
                }

                for key, (regex, multiline) in patterns.items():
                    if key in jaString:
                        # Multi-line pattern: spans 355 + subsequent 655 codes
                        # Each 655 line is translated separately (as a batch) and stays in its own line
                        if multiline and codeList[i]["code"] == 355:
                            textLines = []
                            textLineIndices = []
                            j = i + 1
                            
                            while j < len(codeList) and codeList[j]["code"] == 655:
                                param = codeList[j]["parameters"][0] if codeList[j]["parameters"] else ""
                                textMatch = re.search(regex, param)
                                if textMatch:
                                    text = _pat355655_captured_text(textMatch)
                                    if not (IGNORETLTEXT and not re.search(LANGREGEX, text)):
                                        textLines.append(text)
                                        textLineIndices.append(j)
                                j += 1
                            
                            if textLines:
                                if setData:
                                    # Store each line separately for batch translation
                                    for text in textLines:
                                        if key == "$gameMessage.show(this,":
                                            text = _decode_game_message_show_text(text)
                                        list355655.append(text)
                                else:
                                    # Apply each translated line back to its corresponding 655 code
                                    for lineIdx in textLineIndices:
                                        if len(list355655) > 0:
                                            translatedText = list355655[0]
                                            list355655.pop(0)
                                            
                                            # Replace quotes with apostrophes to avoid breaking plugin
                                            translatedText = translatedText.replace('\\"', "'")
                                            translatedText = translatedText.replace('"', "'")
                                            if key == "$gameMessage.show(this,":
                                                translatedText = _escape_single_quoted_script_text(
                                                    translatedText
                                                )
                                            
                                            origParam = codeList[lineIdx]["parameters"][0]
                                            origMatch = re.search(regex, origParam)
                                            if origMatch:
                                                codeList[lineIdx]["parameters"][0] = (
                                                    _pat355655_replace_captured(
                                                        origParam,
                                                        origMatch,
                                                        translatedText,
                                                    )
                                                )
                                
                                i = j - 1
                            break
                        
                        # Single-line pattern
                        else:
                            match = re.search(regex, jaString)
                            if match:
                                cap = _pat355655_captured_text(match)
                                if not re.search(r'[a-zA-Z一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９\uFF61-\uFF9F]', cap):
                                    continue

                                if IGNORETLTEXT and not re.search(LANGREGEX, cap):
                                    continue

                                if setData:
                                    list355655.append(cap)
                                else:
                                    translatedText = list355655[0]
                                    list355655.pop(0)

                                    if "gameVariables.setValue" in codeList[i]["parameters"][0]:
                                        translatedText = translatedText.replace('\"', "'")

                                    if "$gameVariables._data" in codeList[i]["parameters"][0]:
                                        translatedText = re.sub(r"(?<!\\)'", r"\\'", translatedText)
                                    
                                    if "BattleManager" in codeList[i]["parameters"][0]:
                                        translatedText = re.sub(r"(?<!\\)'", r"\\'", translatedText)

                                    codeList[i]["parameters"][0] = (
                                        _pat355655_replace_captured(
                                            jaString,
                                            match,
                                            translatedText,
                                        )
                                    )
                            break

                # AddCmnt handler - extract strings from array and name parameter
                if "AddCmnt(" in jaString:
                    arrayMatch = re.search(r'AddCmnt\s*\(\s*\[(.+)\]\s*,', jaString)
                    if arrayMatch:
                        arrayContent = arrayMatch.group(1)
                        strings = re.findall(r'\\?"(.+?)\\?"', arrayContent)
                        
                        # Also grab the name argument after the array: , "name")
                        nameMatch = re.search(r'AddCmnt\s*\(\s*\[.+\]\s*,\s*\\?"(.+?)\\?"\s*\)', jaString)
                        
                        translatable = []
                        for s in strings:
                            if not re.search(r'[a-zA-Z一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９\uFF61-\uFF9F]', s):
                                continue
                            if IGNORETLTEXT and not re.search(LANGREGEX, s):
                                continue
                            translatable.append(s)
                        
                        # Translate and cache the speaker name via getSpeaker
                        nameStr = None
                        translatedName = ""
                        if nameMatch:
                            n = nameMatch.group(1)
                            if re.search(r'[a-zA-Z一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９\uFF61-\uFF9F]', n):
                                if not (IGNORETLTEXT and not re.search(LANGREGEX, n)):
                                    nameStr = n
                                    response = getSpeaker(n)
                                    translatedName = response[0]
                                    totalTokens[0] += response[1][0]
                                    totalTokens[1] += response[1][1]
                        
                        if translatable or nameStr:
                            # Use the translated speaker name for context prefix
                            speakerPrefix = translatedName if translatedName else ""
                            
                            if setData:
                                romashaCommentContext = True
                                for s in translatable:
                                    if speakerPrefix:
                                        list355655.append(f"[{speakerPrefix}]: {s}")
                                    else:
                                        list355655.append(s)
                            else:
                                for s in translatable:
                                    if len(list355655) > 0:
                                        translatedText = list355655[0]
                                        list355655.pop(0)
                                        # Strip speaker prefix if present
                                        translatedText = strip_speaker_prefix(translatedText)
                                        # Replace double quotes to avoid breaking the JSON/JS syntax
                                        translatedText = translatedText.replace('\\"', "'")
                                        translatedText = translatedText.replace('"', "'")
                                        jaString = jaString.replace(s, translatedText, 1)
                                # Replace the speaker name directly (already translated via getSpeaker)
                                if nameStr and translatedName:
                                    translatedName = translatedName.replace('\\"', "'")
                                    translatedName = translatedName.replace('"', "'")
                                    jaString = jaString.replace(nameStr, translatedName, 1)
                                codeList[i]["parameters"][0] = jaString

                # AddMaill handler - translate sender name (3rd quoted arg) and title (4th quoted arg)
                # Example: this.AddMaill("M_IcoMail","liliy","リリィ","お得なクーポン配布",_MTxt,[24],193,true,504,1)
                if "AddMaill(" in jaString:
                    # Extract all quoted strings in order
                    allQuoted = re.findall(r'\\?"([^"]*?)\\?"', jaString)
                    # args: [0]=icon, [1]=id, [2]=sender, [3]=title, ...
                    translatable = []
                    translatableIndices = []
                    for idx in [2, 3]:
                        if idx < len(allQuoted):
                            s = allQuoted[idx]
                            if not s.strip():
                                continue
                            if not re.search(r'[a-zA-Z一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９\uFF61-\uFF9F]', s):
                                continue
                            if IGNORETLTEXT and not re.search(LANGREGEX, s):
                                continue
                            translatable.append(s)
                            translatableIndices.append(idx)

                    if translatable:
                        if setData:
                            for s in translatable:
                                list355655.append(s)
                        else:
                            for s in translatable:
                                if len(list355655) > 0:
                                    translatedText = list355655[0]
                                    list355655.pop(0)
                                    translatedText = translatedText.replace('\\"', "'")
                                    translatedText = translatedText.replace('"', "'")
                                    jaString = jaString.replace(s, translatedText, 1)
                            codeList[i]["parameters"][0] = jaString

                # # AddBbs handler - translate arrays of posts/replies, username, and location
                # # Example: AddBbs(["この開発したパッチを..."], "コンピューターおじいちゃん","場所:猪鹿蝶",["良きパッチが..."],"patch_npc")
                # if "AddBbs(" in jaString:
                #     translatable = []

                #     # Extract strings from the first array (topic posts)
                #     # Anchor with ],\s*\\?" after ] to skip past inner brackets like \\C[3]
                #     firstArrayMatch = re.search(r'AddBbs\s*\(\s*\[(.+?)\]\s*,\s*\\?"', jaString)
                #     firstArrayStrings = []
                #     if firstArrayMatch:
                #         firstArrayStrings = re.findall(r'\\?"([^"]+?)\\?"', firstArrayMatch.group(1))
                #         for s in firstArrayStrings:
                #             if not re.search(r'[a-zA-Z一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９\uFF61-\uFF9F]', s):
                #                 continue
                #             if IGNORETLTEXT and not re.search(LANGREGEX, s):
                #                 continue
                #             translatable.append(s)

                #     # After the first array, extract: "username","location",["replies"],"picture_id"
                #     afterFirstArray = re.search(r'AddBbs\s*\(\s*\[.+?\]\s*,\s*(.*)\)\s*;?\s*$', jaString)
                #     nameStr = None
                #     translatedName = ""
                #     locationStr = None
                #     secondArrayStrings = []

                #     if afterFirstArray:
                #         rest = afterFirstArray.group(1)

                #         # Username (first quoted string after the array)
                #         nameMatch = re.match(r'\s*\\?"([^"]+?)\\?"', rest)
                #         if nameMatch:
                #             n = nameMatch.group(1)
                #             if re.search(r'[a-zA-Z一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９\uFF61-\uFF9F]', n):
                #                 if not (IGNORETLTEXT and not re.search(LANGREGEX, n)):
                #                     nameStr = n
                #                     response = getSpeaker(n)
                #                     translatedName = response[0]
                #                     totalTokens[0] += response[1][0]
                #                     totalTokens[1] += response[1][1]

                #         # Location (second quoted string after array, before second array)
                #         locMatch = re.match(r'\s*\\?"[^"]*?\\?"\s*,\s*\\?"([^"]+?)\\?"', rest)
                #         if locMatch:
                #             loc = locMatch.group(1)
                #             if re.search(r'[a-zA-Z一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９\uFF61-\uFF9F]', loc):
                #                 if not (IGNORETLTEXT and not re.search(LANGREGEX, loc)):
                #                     locationStr = loc
                #                     translatable.append(loc)

                #         # Second array (replies)
                #         # Anchor with ],\s*\\?" after ] to skip past inner brackets like \\C[3]
                #         secondArrayMatch = re.search(r',\s*\[(.+?)\]\s*,\s*\\?"', rest)
                #         if secondArrayMatch:
                #             secondArrayStrings = re.findall(r'\\?"([^"]+?)\\?"', secondArrayMatch.group(1))
                #             for s in secondArrayStrings:
                #                 if not re.search(r'[a-zA-Z一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９\uFF61-\uFF9F]', s):
                #                     continue
                #                 if IGNORETLTEXT and not re.search(LANGREGEX, s):
                #                     continue
                #                 translatable.append(s)

                #     if translatable or nameStr:
                #         speakerPrefix = translatedName if translatedName else ""

                #         if setData:
                #             for s in translatable:
                #                 if speakerPrefix:
                #                     list355655.append(f"[{speakerPrefix}]: {s}")
                #                 else:
                #                     list355655.append(s)
                #         else:
                #             for s in translatable:
                #                 if len(list355655) > 0:
                #                     translatedText = list355655[0]
                #                     list355655.pop(0)
                #                     translatedText = re.sub(r'^\[.*?\]\s*[|:]\s*', '', translatedText)
                #                     translatedText = translatedText.replace('\\"', "'")
                #                     translatedText = translatedText.replace('"', "'")
                #                     jaString = jaString.replace(s, translatedText, 1)
                #             # Replace the username directly (already translated via getSpeaker)
                #             if nameStr and translatedName:
                #                 translatedName = translatedName.replace('\\"', "'")
                #                 translatedName = translatedName.replace('"', "'")
                #                 jaString = jaString.replace(nameStr, translatedName, 1)
                #             # Normalize \\C and \\N codes to always have exactly 4 backslashes
                #             jaString = re.sub(r'\\+([cCnN]\[\d+\])', r'\\\\\1', jaString)
                #             codeList[i]["parameters"][0] = jaString

                # _MTxt handler - translates var _MTxt = "text" + "\n"; across 355 + 655 lines
                # Code 355: var _MTxt = "text" + "\n";
                # Code 655: _MTxt += "text" + "\n";
                if "_MTxt" in jaString and codeList[i]["code"] == 355:
                    mtxtRegex = r'"(.+?)"\s*\+\s*"\\n"'
                    textLines = []
                    textLineIndices = []

                    # Extract text from the 355 line itself
                    match355 = re.search(mtxtRegex, jaString)
                    if match355:
                        text = match355.group(1)
                        if not (IGNORETLTEXT and not re.search(LANGREGEX, text)):
                            textLines.append(text)
                            textLineIndices.append(i)

                    # Extract text from subsequent 655 lines
                    j = i + 1
                    while j < len(codeList) and codeList[j]["code"] == 655:
                        param = codeList[j]["parameters"][0] if codeList[j]["parameters"] else ""
                        if "_MTxt" in param:
                            textMatch = re.search(mtxtRegex, param)
                            if textMatch:
                                text = textMatch.group(1)
                                if not (IGNORETLTEXT and not re.search(LANGREGEX, text)):
                                    textLines.append(text)
                                    textLineIndices.append(j)
                        j += 1

                    if textLines:
                        if setData:
                            for text in textLines:
                                list355655.append(text)
                        else:
                            # Collect all translated lines and re-wrap them
                            translatedLines = []
                            for _ in textLineIndices:
                                if len(list355655) > 0:
                                    tl = list355655.pop(0)
                                    tl = tl.replace('\\"', "'")
                                    tl = tl.replace('"', "'")
                                    translatedLines.append(tl)

                            if translatedLines:
                                # Join all lines and re-wrap to WIDTH
                                combined = " ".join(translatedLines)
                                wrapped = dazedwrap.wrapText(combined, width=WIDTH)
                                wrappedLines = [l for l in wrapped.split("\n") if l.strip()]

                                # Distribute wrapped lines across existing 355/655 slots
                                for idx, lineIdx in enumerate(textLineIndices):
                                    if idx < len(wrappedLines):
                                        origParam = codeList[lineIdx]["parameters"][0]
                                        origMatch = re.search(mtxtRegex, origParam)
                                        if origMatch:
                                            codeList[lineIdx]["parameters"][0] = origParam.replace(origMatch.group(1), wrappedLines[idx])
                                    else:
                                        # More slots than lines: blank out the text
                                        origParam = codeList[lineIdx]["parameters"][0]
                                        origMatch = re.search(mtxtRegex, origParam)
                                        if origMatch:
                                            codeList[lineIdx]["parameters"][0] = origParam.replace(origMatch.group(1), "")

                                # If more wrapped lines than slots, insert new 655 codes
                                if len(wrappedLines) > len(textLineIndices):
                                    lastIdx = textLineIndices[-1]
                                    indent = codeList[lastIdx].get("indent", 0)
                                    for extra in range(len(textLineIndices), len(wrappedLines)):
                                        new_item = {
                                            "code": 655,
                                            "indent": indent,
                                            "parameters": [
                                                '   _MTxt += "' + wrappedLines[extra] + '" + "\\n";'
                                            ],
                                        }
                                        insertPos = lastIdx + 1 + (extra - len(textLineIndices))
                                        codeList.insert(insertPos, new_item)
                                    # Adjust j to account for inserted items
                                    j += len(wrappedLines) - len(textLineIndices)

                        i = j - 1

                # OpeSet handler - translate speaker name (1st arg) and dialogue text (2nd arg)
                # Example: this.OpeSet(\"オペレーター\",\"今回の任務の内容は迷子になった少女を救出することです。\",\"ope\",180)
                if "OpeSet(" in jaString:
                    # Extract speaker name (1st quoted arg) and text (2nd quoted arg)
                    nameMatch = re.search(r'OpeSet\s*\(\s*\\?"(.+?)\\?"\s*,', jaString)
                    textMatch = re.search(r'OpeSet\s*\(\s*\\?"[^"]*?\\?"\s*,\s*\\?"(.+?)\\?"', jaString)

                    nameStr = None
                    translatedName = ""
                    textStr = None

                    # Process speaker name via getSpeaker
                    if nameMatch:
                        n = nameMatch.group(1)
                        if re.search(r'[a-zA-Z一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９\uFF61-\uFF9F]', n):
                            if not (IGNORETLTEXT and not re.search(LANGREGEX, n)):
                                nameStr = n
                                response = getSpeaker(n)
                                translatedName = response[0]
                                totalTokens[0] += response[1][0]
                                totalTokens[1] += response[1][1]

                    # Process text (2nd arg)
                    if textMatch:
                        t = textMatch.group(1)
                        if re.search(r'[a-zA-Z一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９\uFF61-\uFF9F]', t):
                            if not (IGNORETLTEXT and not re.search(LANGREGEX, t)):
                                textStr = t

                    if textStr or nameStr:
                        speakerPrefix = translatedName if translatedName else ""

                        if setData:
                            if textStr:
                                if speakerPrefix:
                                    list355655.append(f"[{speakerPrefix}]: {textStr}")
                                else:
                                    list355655.append(textStr)
                        else:
                            if textStr:
                                if len(list355655) > 0:
                                    translatedText = list355655[0]
                                    list355655.pop(0)
                                    # Strip speaker prefix if present
                                    translatedText = strip_speaker_prefix(translatedText)
                                    # Replace double quotes to avoid breaking JS syntax
                                    translatedText = translatedText.replace('\\"', "'")
                                    translatedText = translatedText.replace('"', "'")
                                    jaString = jaString.replace(textStr, translatedText, 1)
                            # Replace the speaker name (already translated via getSpeaker)
                            if nameStr and translatedName:
                                translatedName = translatedName.replace('\\"', "'")
                                translatedName = translatedName.replace('"', "'")
                                jaString = jaString.replace(nameStr, translatedName, 1)
                            # Normalize \\N and \\C codes to always have exactly 4 backslashes
                            jaString = re.sub(r'\\+([cCnN]\[\d+\])', r'\\\\\1', jaString)
                            codeList[i]["parameters"][0] = jaString

            ## Event Code: 408 (Script)
            if "code" in codeList[i] and (codeList[i]["code"] == 408) and CODE408 is True:
                # A 108 starts an RPG Maker comment and each following 408
                # continues it. Accept the first continuation regardless of the
                # 108 text so the entire comment block is handled consistently.
                if i > 0:
                    prevCode = codeList[i - 1].get("code", None)
                    if prevCode not in [108, 408]:
                        i += 1
                        continue

                if not codeList[i].get("parameters"):
                    i += 1
                    continue

                groupStart408 = i
                j = i
                source408Parts = []
                current408Parts = []
                rawSource = _param_source(codeList[i], 0)
                ojaString = rawSource
                anchor408HasOrig = _scalar_original(codeList[groupStart408]) is not None
                source408Parts.append(rawSource)
                current408Parts.append(_param_current(codeList[i], 0))

                if not rawSource.strip():
                    i += 1
                    continue

                # Join Up 408's into single string
                if len(codeList) > i + 1 and JOIN408 is True:
                    while codeList[i + 1]["code"] in [408] and len(codeList[i]["parameters"]) > 0 and len(codeList[i + 1]["parameters"]) > 0 and not re.match(r"^(\s*[\\]+[aAbBdDeEfFgGhHjJlLmMoOpPqQrRsStTuUwWxXyYzZ]+\[[\w\d\[\]\\]+\])", codeList[i+1]["parameters"][0]):
                        if not setData:
                            codeList[i]["parameters"] = []
                            codeList[i]["code"] = -1
                        i += 1
                        j = i

                        lineSource = _param_source(codeList[i], 0)
                        current408Parts.append(_param_current(codeList[i], 0))
                        if lineSource.strip() and not anchor408HasOrig:
                            source408Parts.append(lineSource)

                        if len(codeList) <= i + 1:
                            break

                rawSource = _group_raw_source(codeList, groupStart408, source408Parts)
                if not _text_needs_translation("\n".join(current408Parts)):
                    i += 1
                    continue
                ojaString = rawSource
                jaString = rawSource.replace("\n", " ")

                # Pass 1
                if setData:
                    list408.append(jaString)

                # Pass 2
                else:
                    if len(list408) > 0:
                        translatedText = list408[0]
                        list408.pop(0)

                        merged408 = len(source408Parts) > 1
                        if merged408:
                            codeList[i]["parameters"] = [translatedText]
                        else:
                            param0 = codeList[i]["parameters"][0]
                            if ojaString in param0:
                                codeList[i]["parameters"][0] = param0.replace(ojaString, translatedText)
                            else:
                                flatSource = ojaString.replace("\n", " ")
                                if flatSource in param0:
                                    codeList[i]["parameters"][0] = param0.replace(flatSource, translatedText)
                                else:
                                    codeList[i]["parameters"][0] = translatedText

                        _apply_original(codeList[i], rawSource)

            ## Event Code: 108 (Script)
            if "code" in codeList[i] and (codeList[i]["code"] == 108) and CODE108 is True:
                jaString = codeList[i]["parameters"][0]

                # Skip if IGNORETLTEXT is enabled and no Japanese text
                if IGNORETLTEXT and not re.search(LANGREGEX, jaString):
                    i += 1
                    continue

                # Translate
                if "info:" in jaString:
                    regex = r"info:([^,]+)"
                elif "ActiveMessage:" in jaString:
                    regex = r"<ActiveMessage:(.*)>?"
                elif "event_text" in jaString:
                    regex = r"event_text\s*:\s*(.*)"
                elif "Menu Name" in jaString:
                    regex = r"Menu\sName\s*:\s*(.*)>"
                elif "text_indicator" in jaString:
                    regex = r"text_indicator\s?:\s?(.+)"
                elif "NW名前指定" in jaString:
                    regex = r"NW名前指定\s+(.+)"
                else:
                    i += 1
                    continue

                # Need to remove outside code and put it back later
                match = re.search(regex, jaString)
                if match:
                    # Pass 1
                    if setData:
                        list108.append(match.group(1))

                        # # Grab Next
                        # j = i
                        # while codeList[j + 1]["code"] == 408:
                        #     j += 1
                        #     list108[0] = list108[0] + codeList[j]["parameters"][0].replace(">", "")
                        #     codeList[j]["parameters"][0] = ""
                        #     list108[0] = list108[0].replace("\n", " ")

                    # Pass 2
                    else:
                        # Grab and Replace
                        translatedText = list108[0]
                        list108.pop(0)

                        # Textwrap
                        # if codeList[i + 1]["code"] == 408:
                        #     translatedText = dazedwrap.wrapText(translatedText, WIDTH)

                        # Remove characters that may break scripts
                        charList = ['"']
                        for char in charList:
                            translatedText = translatedText.replace(char, "")
                        translatedText = translatedText.replace('"', '"')
                        translatedText = translatedText.replace(" ", "_")
                        translatedText = jaString.replace(match.group(1), translatedText)

                        # Add >
                        # if "ActiveMessage" in translatedText and ">" not in translatedText:
                        #     translatedText = translatedText + ">"

                        # Set Data
                        codeList[i]["parameters"][0] = translatedText

            ## Event Code: 356
            if "code" in codeList[i] and codeList[i]["code"] == 356 and CODE356 is True:
                jaString = codeList[i]["parameters"][0]
                oldjaString = jaString

                # Skip if IGNORETLTEXT is enabled and no Japanese text
                if IGNORETLTEXT and not re.search(LANGREGEX, jaString):
                    i += 1
                    continue

                # Grab Speaker
                if "Tachie showName" in jaString:
                    matchList = re.findall(r"Tachie showName (.+)", jaString)
                    if len(matchList) > 0:
                        # Translate
                        response = translateAI(
                            matchList[0],
                            ctx("names.npc"),
                            False,
                        )
                        translatedText = response[0]
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]

                        # Set Text
                        speaker = translatedText
                        speaker = speaker.replace(" ", " ")
                        codeList[i]["parameters"][0] = jaString.replace(matchList[0], speaker)
                    i += 1
                    continue

                # Want to translate this script
                if "D_TEXT " in jaString:
                    regex = r"D_TEXT\s*(.+?)(?:\s+\d+)?$"
                elif "ShowInfo" in jaString:
                    regex = r"ShowInfo\s(.*)"
                elif "PushGab" in jaString:
                    regex = r"PushGab\s(.*)"
                elif "addLog" in jaString:
                    regex = r"addLog\s(.*)"
                elif "DW_" in jaString:
                    regex = r"DW_.*\s\d+\s(.+)"
                elif "CommonPopup" in jaString:
                    regex = r"CommonPopup\sadd\stext:(.+?)(?=\s+count:|\s*$)"
                elif "AddCustomChoice" in jaString:
                    regex = r"AddCustomChoice\s\d+\s(.+)\s\d"
                else:
                    regex = r""

                # Remove any textwrap
                jaString = re.sub(r"\n", "_", jaString)

                # Capture Arguments and text
                textMatch = re.search(regex, jaString)
                if textMatch and textMatch.group(0) != "":
                    text = textMatch.group(1)

                    # Capture Speakers
                    match = re.search(r"[\\]+ow\[\d+\][\\]+c\[\d+\](.+)", text)
                    if match:
                        speakerJA = match.group(1)

                        # Translate
                        response = getSpeaker(speakerJA)
                        translatedText = response[0]
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]
                        codeList[i]["parameters"][0] = jaString.replace(speakerJA, translatedText)
                        i += 1
                        continue
                    else:
                        speaker = ""

                    # Pass 1
                    if setData:
                        text = text.replace("_", " ")                       
                        list356.append(text)

                    # Pass 2
                    else:
                        if len(list356) > 0:
                            # Grab
                            translatedText = list356[0]

                            # Remove characters that may break scripts
                            # addLog keeps dots and quotes (they're fine in log text)
                            if "addLog" not in jaString:
                                charList = [".", '"']
                                for char in charList:
                                    translatedText = translatedText.replace(char, "")

                            # Cant have spaces?
                            translatedText = translatedText.replace(" ", "_")
                            if "D_TEXT " not in jaString:
                                translatedText = translatedText.replace("__", "_")

                            # Put Args Back
                            translatedText = jaString.replace(text, translatedText)

                            # Set Data
                            codeList[i]["parameters"][0] = translatedText
                            list356.pop(0)

                if "namePop" in jaString:
                    # Support both "<namePop: text>" and "namePop [num] text" formats
                    matchList = re.findall(r"<namePop:\s*([^>]+)>", jaString)
                    if not matchList:
                        m = re.search(r"\bnamePop\b\s*(?:-?\d+)?\s*([^\r\n<>]+)", jaString)
                        if m:
                            matchList = [m.group(1).strip()]
                    if len(matchList) > 0:
                        # Translate
                        text = matchList[0]
                        response = translateAI(text, ctx("events.generic"))
                        translatedText = response[0]
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]

                        # Set Data
                        updated = jaString.replace(text, translatedText.replace(" ", "_"))
                        codeList[i]["parameters"][0] = updated

                if "LL_InfoPopupWIndowMV" in jaString:
                    matchList = re.findall(r"LL_InfoPopupWIndowMV\sshowWindow\s(.+?) .+", jaString)
                    if len(matchList) > 0:
                        text = matchList[0]

                        # Pass 1: collect into batch
                        if setData:
                            # store without underscores for cleaner translation later
                            list356.append(text.replace("_", " "))

                        # Pass 2: apply translations from list356
                        else:
                            if len(list356) > 0:
                                translatedText = list356[0]
                                list356.pop(0)

                                # Replace spaces with underscores as original format expects
                                translatedText = translatedText.replace(" ", "_")

                                # Put Args Back
                                translatedText = jaString.replace(text, translatedText)

                                # Set Data
                                codeList[i]["parameters"][0] = translatedText

                if "OriginMenuStatus SetParam" in jaString:
                    matchList = re.findall(r"OriginMenuStatus\sSetParam\sparam[\d]\s(.*)", jaString)
                    if len(matchList) > 0:
                        # Translate
                        text = matchList[0]
                        response = translateAI(text, ctx("events.generic"))
                        translatedText = response[0]
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]

                        # Set Data
                        translatedText = translatedText.replace(" ", "_")
                        translatedText = jaString.replace(text, translatedText)
                        codeList[i]["parameters"][0] = translatedText

                # LL_GalgeChoiceWindowMV Message
                if "LL_GalgeChoiceWindowMV setMessageText" in jaString:
                    ### Message Text First
                    match = re.search(r"LL_GalgeChoiceWindowMV setMessageText (.+)", jaString)
                    if match:
                        jaString = match.group(1)

                        # Remove any textwrap & TL
                        jaString = re.sub(r"\n", " ", jaString)
                        sourceQuestion = jaString
                        response = translateAI(jaString, "")
                        translatedText = response[0]
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]

                        # Textwrap & Replace Whitespace
                        translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)
                        translatedText = translatedText.replace(" ", "_")

                        # Replace and Set
                        translatedText = match.group(0).replace(match.group(1), translatedText)
                        codeList[i]["parameters"][0] = translatedText

                # LL_GalgeChoiceWindowMV Choices
                if "LL_GalgeChoiceWindowMV setChoices":
                    match = re.search(r"LL_GalgeChoiceWindowMV setChoices (.+)", jaString)
                    if match:
                        jaString = match.group(1)
                        choiceList = jaString.split(",")

                        # Keep the original Japanese message as choice context.
                        response = translateAI(
                            choiceList,
                            {
                                "instructions": [ctx("events.choice")],
                                "source_items": [sourceQuestion],
                            },
                            True,
                        )
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]
                        choiceListTL = response[0]
                        translatedText = match.group(0)

                        # Replace Strings
                        for j in range(len(choiceListTL)):
                            choiceListTL[j] = choiceListTL[j].replace(" ", "_")
                            translatedText = translatedText.replace(choiceList[j], choiceListTL[j])

                        # Set Data
                        codeList[i]["parameters"][0] = translatedText

            ### Event Code: 102 Show Choice
            if "code" in codeList[i] and codeList[i]["code"] == 102 and CODE102 is True:
                choiceList = []
                conditionList = []
                choiceIndexMap = []  # Track which original indices we're processing
                choiceSourceList = []
                
                # Process each string in the parameters list
                for choice in range(len(codeList[i]["parameters"][0])):
                    rawSource = _choice_source(codeList[i], choice)
                    currentChoice = _choice_current(codeList[i], choice)
                    jaString = rawSource.replace(" 。", ".")

                    # Avoid Empty Strings
                    if not jaString.strip():
                        continue

                    if not _text_needs_translation(currentChoice):
                        continue

                    # Preserve plugin condition clauses outside the model.
                    conditionPrefix, jaString = _split_choice_condition_prefix(jaString)
                    jaString, conditionSuffix = _split_choice_condition_suffix(jaString)
                    
                    # Store the formatting and cleaned string
                    conditionList.append((conditionPrefix, conditionSuffix))
                    choiceList.append(jaString)
                    choiceIndexMap.append(choice)
                    choiceSourceList.append(rawSource)

                # Translate the list
                if len(choiceList) > 0:
                    if len(textHistory) > 0:
                        response = translateAI(
                            choiceList,
                            {
                                "instructions": [ctx("events.choice")],
                                "source_items": textHistory,
                            },
                            True,
                        )
                    else:
                        response = translateAI(choiceList, ctx("events.choice"))
                    
                    translatedTextList = response[0]
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]

                    # Check Mismatch and set translations
                    if len(translatedTextList) == len(choiceList):
                        for idx, translatedText in enumerate(translatedTextList):
                            originalIndex = choiceIndexMap[idx]
                            
                            # Apply formatting
                            conditionPrefix, conditionSuffix = conditionList[idx]
                            if translatedText != "":
                                translatedText = (
                                    conditionPrefix
                                    + translatedText[0].upper()
                                    + translatedText[1:]
                                    + conditionSuffix
                                )
                            else:
                                translatedText = conditionPrefix + translatedText + conditionSuffix
                            
                            # Set the translation back to the original position
                            codeList[i]["parameters"][0][originalIndex] = translatedText
                            _apply_choice_original(codeList[i], originalIndex, choiceSourceList[idx])
                    else:
                        if filename not in MISMATCH:
                            MISMATCH.append(filename)

            ### Event Code: 111 Script
            if "code" in codeList[i] and codeList[i]["code"] == 111 and CODE111 is True:
                for j in range(len(codeList[i]["parameters"])):
                    jaString = codeList[i]["parameters"][j]

                    # Check if String
                    if not isinstance(jaString, str):
                        continue

                    # Only TL the Game Variable
                    if "$gameVariables" not in jaString:
                        continue

                    # Need to remove outside code and put it back later
                    matchList = re.findall(r"['\"`](.*?)['\"`]", jaString)

                    for match in matchList:
                        # Skip if IGNORETLTEXT is enabled and no Japanese text
                        if IGNORETLTEXT and not re.search(LANGREGEX, match):
                            continue

                        # Look up translation from code 122 cache (file-backed)
                        cachedTranslation = get_var_translation(match)

                        if cachedTranslation is not None:
                            jaString = jaString.replace(match, cachedTranslation)

                    # Set Data
                    codeList[i]["parameters"][j] = jaString

            ### Event Code: 320 Set Variable
            if "code" in codeList[i] and codeList[i]["code"] == 320 and CODE320 is True:
                jaString = codeList[i]["parameters"][1]
                if not isinstance(jaString, str):
                    i += 1
                    continue

                # Definitely don't want to mess with files
                if "■" in jaString or "_" in jaString:
                    i += 1
                    continue

                # Skip if IGNORETLTEXT is enabled and no Japanese text
                if IGNORETLTEXT and not re.search(LANGREGEX, jaString):
                    i += 1
                    continue

                # Translate
                response = getSpeaker(jaString)
                translatedText = response[0]
                totalTokens[0] += response[1][0]
                totalTokens[1] += response[1][1]

                # Remove characters that may break scripts
                charList = [".", '"', "'", "\\n"]
                for char in charList:
                    translatedText = translatedText.replace(char, "")

                # Set Data
                codeList[i]["parameters"][1] = translatedText

            ### Event Code: 325
            if "code" in codeList[i] and codeList[i]["code"] == 325 and CODE325 is True:
                # Expect parameters like [index, "text"] where parameters[1] is the string
                if len(codeList[i]["parameters"]) <= 1:
                    i += 1
                    continue

                jaString = codeList[i]["parameters"][1]
                if not isinstance(jaString, str):
                    i += 1
                    continue

                # Skip if IGNORETLTEXT is enabled and no Japanese text
                if IGNORETLTEXT and not re.search(LANGREGEX, jaString):
                    i += 1
                    continue

                # Remove Textwrap
                collectString = jaString.replace("\n", " ")

                # Pass 1: collect into batch
                if setData:
                    list325.append(collectString)

                # Pass 2: apply translations from batch
                else:
                    if len(list325) > 0:
                        translatedText = list325[0]
                        list325.pop(0)

                        # Textwrap
                        translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)

                        # Set translated value back into parameters[1]
                        codeList[i]["parameters"][1] = "\\}\\}" + translatedText

            ### Event Code: 324
            if "code" in codeList[i] and codeList[i]["code"] == 324 and CODE324 is True:
                # Expect parameters like [1, "text"] where index 1 is the string to translate
                if len(codeList[i]["parameters"]) <= 1:
                    i += 1
                    continue

                jaString = codeList[i]["parameters"][1]
                if not isinstance(jaString, str):
                    i += 1
                    continue

                # Skip if IGNORETLTEXT is enabled and no Japanese text
                if IGNORETLTEXT and not re.search(LANGREGEX, jaString):
                    i += 1
                    continue

                # Remove any textwrap for collection
                collectString = jaString.replace("\n", " ")

                # Pass 1: collect
                if setData:
                    list324.append(collectString)

                # Pass 2: apply translations from list324
                else:
                    if len(list324) > 0:
                        translatedText = list324[0]
                        list324.pop(0)

                        # Clean translation
                        for ch in ['"', "\\n"]:
                            translatedText = translatedText.replace(ch, "")

                        # Textwrap to reasonable width
                        translatedText = dazedwrap.wrapText(translatedText, width=LISTWIDTH)

                        # Set translated value back into parameters[1]
                        codeList[i]["parameters"][1] = translatedText

            # Iterate
            i += 1

        # EOF
        list401TL = []
        list408TL = []
        list324TL = []
        list122TL = []
        list356TL = []
        list357TL = []
        list355655TL = []
        list108TL = []
        list325TL = []
        list657TL = []
        PBAR = pbar

        # 401
        if len(list401) > 0:
            response = translateAI(list401, "")
            list401TL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            if len(list401TL) != len(list401):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)

        # 122
        if len(list122) > 0:
            response = translateAI(list122, ctx("events.code122_brief"))
            list122TL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            if len(list122TL) != len(list122):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)
            else:
                # Store each original→translated pair for code 111 consistency (file-backed)
                set_var_translations_batch(list(zip(list122, list122TL)))

        # 355/655
        if len(list355655) > 0:
            list355655_context = textHistory
            if romashaCommentContext:
                list355655_context = {
                    "instructions": [
                        "These comments are always about Romasha or her squad."
                    ],
                    "source_items": textHistory,
                }
            response = translateAI(
                list355655,
                list355655_context,
            )
            list355655TL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            if len(list355655TL) != len(list355655):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)

        # 108
        if len(list108) > 0:
            response = translateAI(list108, ctx("events.label_108"))
            list108TL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            if len(list108TL) != len(list108):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)

        # 356
        if len(list356) > 0:
            response = translateAI(list356, textHistory)
            list356TL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            if len(list356TL) != len(list356):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)

        # 357
        if len(list357) > 0:
            response = translateAI(list357, textHistory)
            list357TL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            if len(list357TL) != len(list357):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)

        # 657
        if len(list657) > 0:
            response = translateAI(list657, textHistory)
            list657TL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            if len(list657TL) != len(list657):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)

        # 408
        if len(list408) > 0:
            response = translateAI(list408, "")
            list408TL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            failed408Batch = bool(getattr(THREAD_CTX, "last_translation_had_mismatch", False))
            if failed408Batch or len(list408TL) != len(list408):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)
                # A failed internal chunk or short result would make this pass
                # partially apply or misalign later entries. Keep the entire
                # 408 batch untouched so it can be retried safely.
                list408TL = []

        # 324
        if len(list324) > 0:
            # Generic short-text translation for parameter index 1
            response = translateAI(list324, ctx("events.generic_text"))
            list324TL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            if len(list324TL) != len(list324):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)

        # 325
        if len(list325) > 0:
            # Use same short-text speaker-style translation as other name fields
            response = translateAI(list325, ctx("names.npc"))
            list325TL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            if len(list325TL) != len(list325):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)

        # Start Pass 2
        if setData:
            searchCodes(
                page,
                pbar,
                [
                    list401TL,
                    list122TL,
                    list355655TL,
                    list108TL,
                    list356TL,
                    list357TL,
                    list324TL,
                    list408TL,
                    list325TL,
                    list657TL,
                ],
                filename,
            )

        # Delete all -1 codes
        codeListFinal = []
        for i in range(len(codeList)):
            if "code" in codeList[i] and codeList[i]["code"] != -1:
                codeListFinal.append(codeList[i])

        # Normal Format
        if "list" in page:
            page["list"] = codeListFinal

        # Special Format (Scenario)
        else:
            page[:] = codeListFinal
    except IndexError as e:
        traceback.print_exc()
    except Exception as e:
        traceback.print_exc()

    return totalTokens


def searchSS(state, pbar):
    totalTokens = [0, 0]

    # --- Batch collection for basic fields and messages ---
    batch_texts = []
    batch_map = []  # [(field_type, field_name, needs_taro_prefix, raw_source), ...]
    
    # Name
    if "name" in state and state["name"]:
        name_src = _entry_field_source(state, "name")
        if _entry_field_needs_translation(state, "name"):
            batch_texts.append(name_src)
            batch_map.append(("name", "name", False, name_src))
    
    # Description
    if "description" in state and state["description"]:
        desc_src = _entry_field_source(state, "description")
        if _entry_field_needs_translation(state, "description"):
            batch_texts.append(desc_src)
            batch_map.append(("description", "description", False, desc_src))
    
    # Messages - collect all with Taro prefix handling
    for msg_field in ["message1", "message2", "message3", "message4"]:
        if msg_field in state and state[msg_field]:
            msg_text = _entry_field_source(state, msg_field)
            if not _entry_field_needs_translation(state, msg_field):
                continue
            needs_taro = len(msg_text) > 0 and msg_text[0] in ["は", "を", "の", "に", "が"]
            if needs_taro:
                batch_texts.append("Taro" + msg_text)
            else:
                batch_texts.append(msg_text)
            batch_map.append(("message", msg_field, needs_taro, msg_text))
    
    # --- Batch translate all basic fields ---
    nameResponse = ""
    descriptionResponse = ""
    message1Response = ""
    message2Response = ""
    message3Response = ""
    message4Response = ""
    
    if batch_texts:
        response = translateAI(
            batch_texts,
            "reply with only the gender neutral " + LANGUAGE + " translation. For messages starting with Taro, always start the sentence with Taro. For example, translate 'Taroを倒した！' as 'Taro was defeated!'",
            False,
        )
        translated_batch = response[0]
        totalTokens[0] += response[1][0]
        totalTokens[1] += response[1][1]
        
        # Map translations back to their fields
        for idx, (field_type, field_name, needs_taro, raw_source) in enumerate(batch_map):
            if idx < len(translated_batch):
                translation = translated_batch[idx]
                if field_type == "name":
                    nameResponse = [translation, [0, 0]]
                    _apply_entry_field_original(state, "name", raw_source)
                elif field_type == "description":
                    descriptionResponse = [translation, [0, 0]]
                    _apply_entry_field_original(state, "description", raw_source)
                elif field_type == "message":
                    response_obj = [translation, [0, 0]]
                    _apply_entry_field_original(state, field_name, raw_source)
                    if field_name == "message1":
                        message1Response = response_obj
                    elif field_name == "message2":
                        message2Response = response_obj
                    elif field_name == "message3":
                        message3Response = response_obj
                    elif field_name == "message4":
                        message4Response = response_obj

    # --- Batching pass: collect all note texts for all note types ---
    note_regexes = [
        (r"<help:([^>]*)>", False),
        (r"<STATE_HELP>\n(.*)\n", False),
        (r"<ShowHoverState:\s?(.+?)>", False),
        (r"<Detail:\s?(.+?)>", False),
        (r"<説明:([^>]*)>", False),
    ]
    notesBatch = []
    notesBatchMap = []
    if "note" in state and state["note"]:
        note = state["note"]
        for regex, wordwrap in note_regexes:
            matches = re.findall(regex, note, re.DOTALL)
            for m in matches:
                match_text = m if isinstance(m, str) else m[0]
                # Skip if IGNORETLTEXT is enabled and no Japanese text
                if IGNORETLTEXT and not re.search(LANGREGEX, match_text):
                    continue
                notesBatch.append(match_text)
                notesBatchMap.append((regex, match_text, wordwrap))

    # --- Batch translate all notes ---
    translatedNotesBatch = []
    if notesBatch:
        response = translateAI(notesBatch, ctx("database.note"))
        translatedNotesBatch = response[0]
        totalTokens[0] += response[1][0]
        totalTokens[1] += response[1][1]
        # Notes don't update progress

    # --- Insert translated notes back ---
    note_insert_idx = 0
    if "note" in state and state["note"]:
        for regex, match_text, wordwrap in notesBatchMap:
            if note_insert_idx >= len(translatedNotesBatch):
                break
            translated = translatedNotesBatch[note_insert_idx]
            if wordwrap:
                translated = dazedwrap.wrapText(translated, width=NOTEWIDTH)
                translated = translated.replace('"', "")
            # Replace only the matched text in the note using a literal replacement
            # Avoid re.sub here because replacement strings with backslashes (e.g., \I)
            # are interpreted as escapes and can raise re.PatternError.
            state["note"] = state["note"].replace(match_text, translated, 1)
            note_insert_idx += 1

    # Progress accounting for this state: name + description + messages present
    if pbar is not None:
        work_units = 0
        work_units += 1 if nameResponse != "" else 0
        work_units += 1 if descriptionResponse != "" else 0
        work_units += 1 if message1Response != "" else 0
        work_units += 1 if message2Response != "" else 0
        work_units += 1 if message3Response != "" else 0
        work_units += 1 if message4Response != "" else 0
        if work_units:
            pbar.refresh()

    # Set Data
    if "name" in state and nameResponse != "":
        state["name"] = nameResponse[0].replace('"', "")
    if "description" in state and descriptionResponse != "":
        # Textwrap
        translatedText = descriptionResponse[0]
        translatedText = dazedwrap.wrapText(translatedText, width=LISTWIDTH)
        state["description"] = translatedText.replace('"', "")
    if "message1" in state and message1Response != "":
        state["message1"] = message1Response[0].replace('"', "").replace("Taro", "")
    if "message2" in state and message2Response != "":
        state["message2"] = message2Response[0].replace('"', "").replace("Taro", "")
    if "message3" in state and message3Response != "":
        state["message3"] = message3Response[0].replace('"', "").replace("Taro", "")
    if "message4" in state and message4Response != "":
        state["message4"] = message4Response[0].replace('"', "").replace("Taro", "")

    return totalTokens


def searchSystem(data, pbar):
    totalTokens = [0, 0]
    context = ctx("database.ui_term")

    # Title - batch as a single-item list
    title_src = _system_scalar_source(data, "gameTitle")
    if _text_needs_translation(data.get("gameTitle")):
        response = translateAI(
            [title_src],
            ctx("database.game_title"),
            False,
        )
        totalTokens[0] += response[1][0]
        totalTokens[1] += response[1][1]
        data["gameTitle"] = response[0][0].strip(".")
        _apply_system_scalar_original(data, "gameTitle", title_src)
    if pbar is not None:
        pbar.refresh()

    # Terms - batch translate all term items
    for term in data["terms"]:
        if term != "messages":
            termList = data["terms"][term]
            term_values = []
            term_indices = []
            term_sources = []
            for i in range(len(termList)):
                if termList[i] is not None:
                    src = _system_terms_source(data, term, i)
                    if not _text_needs_translation(termList[i]):
                        continue
                    term_values.append(src)
                    term_indices.append(i)
                    term_sources.append(src)
            
            if term_values:
                response = translateAI(term_values, context)
                totalTokens[0] += response[1][0]
                totalTokens[1] += response[1][1]
                tl_list = response[0]
                
                for n, idx in enumerate(term_indices[: len(tl_list)]):
                    termList[idx] = tl_list[n].replace('"', "").strip()
                    _apply_system_terms_original(data, term, idx, term_sources[n])
                
                if pbar is not None:
                    pbar.refresh()

    # Armor Types - batch translate all
    armor_values = []
    armor_indices = []
    armor_sources = []
    for i in range(len(data["armorTypes"])):
        src = _system_list_source(data, "armorTypes", i)
        if not _text_needs_translation(data["armorTypes"][i]):
            continue
        armor_values.append(src)
        armor_indices.append(i)
        armor_sources.append(src)
    if armor_values:
        response = translateAI(
            armor_values,
            ctx("database.type_armor"),
            False,
        )
        totalTokens[0] += response[1][0]
        totalTokens[1] += response[1][1]
        tl_list = response[0]
        for n, idx in enumerate(armor_indices[: len(tl_list)]):
            data["armorTypes"][idx] = tl_list[n].replace('"', "").strip()
            _apply_system_list_original(data, "armorTypes", idx, armor_sources[n])
        if pbar is not None:
            pbar.refresh()

    # Skill Types - batch translate all
    skill_values = []
    skill_indices = []
    skill_sources = []
    for i in range(len(data["skillTypes"])):
        src = _system_list_source(data, "skillTypes", i)
        if not _text_needs_translation(data["skillTypes"][i]):
            continue
        skill_values.append(src)
        skill_indices.append(i)
        skill_sources.append(src)
    if skill_values:
        response = translateAI(
            skill_values,
            ctx("database.generic"),
            False,
        )
        totalTokens[0] += response[1][0]
        totalTokens[1] += response[1][1]
        tl_list = response[0]
        for n, idx in enumerate(skill_indices[: len(tl_list)]):
            data["skillTypes"][idx] = tl_list[n].replace('"', "").strip()
            _apply_system_list_original(data, "skillTypes", idx, skill_sources[n])
        if pbar is not None:
            pbar.refresh()

    # Equip Types - batch translate all (not present in RPG Maker Ace)
    equip_values = []
    equip_indices = []
    equip_sources = []
    for i in range(len(data.get("equipTypes", []) or [])):
        src = _system_list_source(data, "equipTypes", i)
        if not _text_needs_translation(data["equipTypes"][i]):
            continue
        equip_values.append(src)
        equip_indices.append(i)
        equip_sources.append(src)
    if equip_values:
        response = translateAI(
            equip_values,
            ctx("database.type_equipment"),
            False,
        )
        totalTokens[0] += response[1][0]
        totalTokens[1] += response[1][1]
        tl_list = response[0]
        for n, idx in enumerate(equip_indices[: len(tl_list)]):
            data["equipTypes"][idx] = tl_list[n].replace('"', "").strip()
            _apply_system_list_original(data, "equipTypes", idx, equip_sources[n])
        if pbar is not None:
            pbar.refresh()

    # Elements - batch translate all (skip empty)
    element_values = []
    element_indices = []
    element_sources = []
    for i in range(len(data["elements"])):
        src = _system_list_source(data, "elements", i)
        if not _text_needs_translation(data["elements"][i]):
            continue
        element_values.append(src)
        element_indices.append(i)
        element_sources.append(src)
    
    if element_values:
        response = translateAI(
            element_values,
            ctx("database.element"),
            False,
        )
        totalTokens[0] += response[1][0]
        totalTokens[1] += response[1][1]
        tl_list = response[0]
        for n, idx in enumerate(element_indices[: len(tl_list)]):
            data["elements"][idx] = tl_list[n].replace('"', "").strip()
            _apply_system_list_original(data, "elements", idx, element_sources[n])
        if pbar is not None:
            pbar.refresh()

    # Weapon Types - batch translate all (skip empty)
    weapon_values = []
    weapon_indices = []
    weapon_sources = []
    for i in range(len(data["weaponTypes"])):
        src = _system_list_source(data, "weaponTypes", i)
        if not _text_needs_translation(data["weaponTypes"][i]):
            continue
        weapon_values.append(src)
        weapon_indices.append(i)
        weapon_sources.append(src)
    
    if weapon_values:
        response = translateAI(
            weapon_values,
            ctx("database.type_weapon"),
            False,
        )
        totalTokens[0] += response[1][0]
        totalTokens[1] += response[1][1]
        tl_list = response[0]
        for n, idx in enumerate(weapon_indices[: len(tl_list)]):
            data["weaponTypes"][idx] = tl_list[n].replace('"', "").strip()
            _apply_system_list_original(data, "weaponTypes", idx, weapon_sources[n])
        if pbar is not None:
            pbar.refresh()

    # Variables (Optional usually) — batch translate to reduce calls
    if TLSYSTEMVARIABLES and "variables" in data and isinstance(data["variables"], list):
        var_indices = []
        var_values = []
        var_sources = []
        for idx, val in enumerate(data["variables"]):
            src = _system_list_source(data, "variables", idx)
            if isinstance(val, str) and src.strip():
                if not _text_needs_translation(val):
                    continue
                var_indices.append(idx)
                var_values.append(src)
                var_sources.append(src)
        if var_values:
            response = translateAI(
                var_values,
                ctx("database.actor_title"),
                True,
            )
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            tl_list = response[0]
            # Assign back translations to corresponding indices
            for n, idx in enumerate(var_indices[: len(tl_list)]):
                data["variables"][idx] = tl_list[n].replace('"', '').strip()
                _apply_system_list_original(data, "variables", idx, var_sources[n])
            if pbar is not None:
                pbar.refresh()

    # Switches (Optional) — batch translate to reduce calls
    if TLSYSTEMSWITCHES and "switches" in data and isinstance(data["switches"], list):
        switch_indices = []
        switch_values = []
        switch_sources = []
        for idx, val in enumerate(data["switches"]):
            src = _system_list_source(data, "switches", idx)
            if isinstance(val, str) and src.strip():
                if not _text_needs_translation(val):
                    continue
                switch_indices.append(idx)
                switch_values.append(src)
                switch_sources.append(src)
        if switch_values:
            response = translateAI(
                switch_values,
                ctx("database.switch"),
                True,
            )
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            tl_list = response[0]
            # Assign back translations to corresponding indices
            for n, idx in enumerate(switch_indices[: len(tl_list)]):
                data["switches"][idx] = tl_list[n].replace('"', '').strip()
                _apply_system_list_original(data, "switches", idx, switch_sources[n])
            if pbar is not None:
                pbar.refresh()

    # Messages — batch translate to reduce calls
    messages = data["terms"]["messages"]
    if messages:
        msg_keys = []
        msg_values = []
        msg_sources = []
        for key, value in messages.items():
            src = _system_terms_message_source(data, key)
            if isinstance(value, str) and src.strip():
                if not _text_needs_translation(value):
                    continue
                msg_keys.append(key)
                msg_values.append(src)
                msg_sources.append(src)
        
        if msg_values:
            response = translateAI(
                msg_values,
                ctx("database.battle_messages"),
                False,
            )
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            tl_list = response[0]
            
            # Remove characters that may break scripts
            charList = [".", '"', "\\n"]
            
            # Assign back translations to corresponding keys
            for n, key in enumerate(msg_keys[: len(tl_list)]):
                translatedText = _normalize_system_message_translation(key, tl_list[n])
                for char in charList:
                    translatedText = translatedText.replace(char, "")
                messages[key] = translatedText
                _apply_system_terms_message_original(data, key, msg_sources[n])
            
            if pbar is not None:
                pbar.refresh()

    return totalTokens

# Regex that matches one or more markup codes like \c[1], \n[2], \ow[3], etc.
_MARKUP_STRIP_RE = re.compile(r"[\\]+[a-zA-Z]+\[[\w\d]*\]")

def _is_plausible_speaker(name: str) -> bool:
    """Return True only if *name* looks like a character name rather than dialogue or junk.

    Called during SPEAKER_PARSE_MODE to filter false positives before they
    enter SPEAKER_COLLECTED.  Heuristics (applied after stripping markup):
      • 1–20 characters long
      • Contains at least one Japanese character (kana / kanji)
      • No sentence-ending / mid-sentence punctuation (。！？…、)
      • No dialogue-opening quotes (「"（)
      • No newlines, underscores, slashes, or dots
    """
    clean = _MARKUP_STRIP_RE.sub("", name).strip()
    if not clean:
        return False
    if len(clean) > 20:
        return False
    # Must have at least one Japanese character
    if not re.search(r"[\u3040-\u30FA\u31F0-\u31FF\u3400-\u4DBF\u4E00-\u9FFF\uFF61-\uFF9F]", clean):
        return False
    # Reject sentence-like strings
    if re.search(r"[。！？…、]", clean):
        return False
    # Reject dialogue openers / structural characters
    if re.search(r"[「」""\n\r_/\\.]", clean):
        return False
    return True


def _normalize_speaker_nameplate(translated: str) -> str:
    """Normalize a model TL into a short dialogue nameplate."""
    out = (translated or "").strip()
    out = re.sub(r"^(speaker:\s*)", "", out, flags=re.IGNORECASE)
    out = out.strip("'\"“”‘’「」")
    # If the model ignored instructions and wrote a sentence, keep the lead clause.
    if re.search(r"[.!?]", out):
        out = re.split(r"[.!?]", out, maxsplit=1)[0].strip()
    # Drop trailing commas / "the kind you'd..." style appositives.
    if "," in out:
        out = out.split(",", 1)[0].strip()
    out = re.sub(r"\s+", " ", out).strip()
    words = out.split()
    # Descriptive expansions often start with filler; keep the trailing role words.
    if len(words) > 3 and re.match(
        r"^(JUST|ONLY|THE|A|AN|YOUR|SOME|ANY|THIS|THAT)\b", words[0], re.I
    ):
        words = words[-2:]
    elif len(words) > 4:
        words = words[:3]
    out = " ".join(words).title().replace("'S", "'s")
    # str.title() capitalizes after apostrophes ("Ma'am" -> "Ma'Am").
    out = re.sub(r"\bMa['’]Am\b", "Ma'am", out, flags=re.IGNORECASE)
    out = re.sub(
        r"(\d)(St|Nd|Rd|Th)\b",
        lambda m: m.group(1) + m.group(2).lower(),
        out,
    )
    return out


def _is_character_vocab_category(category) -> bool:
    """True for glossary sections that define character/speaker names."""
    name = str(category or "").lstrip("#").strip().casefold()
    primary = re.split(r"\s*[·・|/]\s*", name, maxsplit=1)[0]
    return primary in {"game characters", "speakers"}


def _vocab_category_priority(category) -> int:
    """Prefer curated character entries over generated speaker entries."""
    name = str(category or "").lstrip("#").strip().casefold()
    primary = re.split(r"\s*[·・|/]\s*", name, maxsplit=1)[0]
    if primary == "game characters":
        return 3
    if primary == "speakers":
        return 2
    return 1


def _speaker_translation_valid(source: str, translated: str) -> bool:
    normalized = str(translated or "").strip()
    if not normalized:
        return False
    target = str(LANGUAGE or "").strip().casefold()
    if target == "chinese":
        return re.search(r"[ぁ-ゖァ-ヺー\uFF66-\uFF9F]", normalized) is None
    if target == "japanese":
        return True
    return (
        normalized.casefold() != str(source or "").strip().casefold()
        and re.search(LANGREGEX, normalized) is None
    )


def _speaker_vocab_indexes():
    """Return cached exact and character-only mappings from the current vocab."""
    global _speakerVocabSource, _speakerVocabExact, _speakerVocabCharacterPairs
    vocab_text = VOCAB or ""
    with _speakerVocabLock:
        if _speakerVocabSource == vocab_text:
            return _speakerVocabExact, _speakerVocabCharacterPairs

        exact = {}
        exact_priorities = {}
        characters = {}
        for term, _line, category in parseVocabWithCategories(vocab_text):
            if not isinstance(term, tuple) or len(term) != 2:
                continue
            source, translated = (str(part).strip() for part in term)
            if not source or not _speaker_translation_valid(source, translated):
                continue
            priority = _vocab_category_priority(category)
            if priority > exact_priorities.get(source, 0):
                exact[source] = translated
                exact_priorities[source] = priority
            if _is_character_vocab_category(category):
                previous = characters.get(source)
                if previous is None or priority > previous[0]:
                    characters[source] = (priority, translated)

        _speakerVocabSource = vocab_text
        _speakerVocabExact = exact
        _speakerVocabCharacterPairs = sorted(
            ((source, value[1]) for source, value in characters.items()),
            key=lambda pair: len(pair[0]),
            reverse=True,
        )
        return _speakerVocabExact, _speakerVocabCharacterPairs


def _vocab_speaker_lookup(speaker: str):
    """Resolve an exact speaker/label from vocab without asking the model."""
    exact, _characters = _speaker_vocab_indexes()
    return exact.get(speaker)


def _substitute_vocab_character_names(text: str) -> str:
    """Enforce known character spellings inside compound labels."""
    _exact, characters = _speaker_vocab_indexes()
    for source, translated in characters:
        if source in text:
            text = text.replace(source, translated)
    return text


# Save some money and enter the character before translation
def getSpeaker(speaker: str):
    """Return (and possibly collect) speaker name.

    Parse mode (SPEAKER_PARSE_MODE=True):
      - Don't translate immediately. Collect unique originals in SPEAKER_COLLECTED.
      - Return original so caller logic works; token cost is zero.

    Normal mode: translate immediately with caching.
    """
    if speaker == "":
        return ["", [0, 0]]

    # Preflight count mode: skip translation and caching entirely
    if 'PREFLIGHT_COUNT_MODE' in globals() and PREFLIGHT_COUNT_MODE:
        return [speaker, [0, 0]]

    if SPEAKER_PARSE_MODE:
        with _speakerCacheLock:
            if speaker in _speakerCache:
                return [_speakerCache[speaker], [0, 0]]
            if speaker not in SPEAKER_COLLECTED and _is_plausible_speaker(speaker):
                SPEAKER_COLLECTED.append(speaker)
        return [speaker, [0, 0]]

    # glossary.txt is authoritative. Check it before either cache so an old model
    # romanization can never override a newly curated spelling.
    vocab_hit = _vocab_speaker_lookup(speaker)
    if vocab_hit is not None:
        with _speakerCacheLock:
            _speakerCache[speaker] = vocab_hit
            for item in NAMESLIST:
                if item[0] == speaker:
                    item[1] = vocab_hit
                    break
            else:
                NAMESLIST.append([speaker, vocab_hit])
        return [vocab_hit, [0, 0]]

    # Normal/approved consume translation path
    with _speakerCacheLock:
        cached = _speakerCache.get(speaker)
        if cached is not None:
            return [cached, [0, 0]]

    # Batch collection happens before submission approval, and consume must
    # rebuild the exact same payload key to retrieve the paid batch result.
    # The GUI preflight normally resolves every name first. If a speaker is
    # still unresolved (notably when resuming a batch collected before speaker
    # glossary persistence was fixed), preserve the source name in both phases
    # instead of making a one-line live request or changing the payload key.
    if (os.getenv("BATCH_PHASE") or "").strip().lower() in {"collect", "consume"}:
        return [speaker, [0, 0]]

    # A few RPG Maker fields routed through getSpeaker are compound labels
    # (for example, "ユウイベント5"). Replace curated character names before
    # translation so the model cannot choose a different romanization. This
    # also avoids reusing a stale cache entry keyed to the all-Japanese label.
    translation_source = _substitute_vocab_character_names(speaker)

    def _translate_nameplate_once():
        try:
            THREAD_CTX.in_speaker = True
        except Exception:
            pass
        try:
            return translateAI(
                translation_source,
                ctx("names.speaker"),
                False,
            )
        finally:
            try:
                THREAD_CTX.in_speaker = False
            except Exception:
                pass

    response = _translate_nameplate_once()
    translated = _normalize_speaker_nameplate(response[0])

    # Retry once when the model echoes source or leaves the wrong script.
    # Do not cache failures: a poisoned Japanese nameplate would stick for the
    # rest of the run (common for FIRSTLINESPEAKERS short katakana names).
    if not _speaker_translation_valid(speaker, translated):
        response = _translate_nameplate_once()
        translated = _normalize_speaker_nameplate(response[0])

    if not _speaker_translation_valid(speaker, translated):
        return [speaker, response[1]]

    with _speakerCacheLock:
        if speaker not in _speakerCache:
            _speakerCache[speaker] = translated
            NAMESLIST.append([speaker, translated])
    return [translated, response[1]]

def _get_actor_map() -> dict:
    """Lazily load actor_id -> name from Actors.json, falling back to vocab actor entries."""
    global _ACTOR_MAP_CACHE
    with _ACTOR_MAP_CACHE_LOCK:
        if _ACTOR_MAP_CACHE:
            return _ACTOR_MAP_CACHE
        for candidate in (Path("translated/Actors.json"), Path("files/Actors.json")):
            if candidate.is_file():
                try:
                    data = json.loads(candidate.read_text(encoding="utf-8-sig"))
                    m: dict = {}
                    for entry in data:
                        if not entry or not isinstance(entry, dict):
                            continue
                        aid = entry.get("id")
                        name = (entry.get("name") or "").strip()
                        if aid is not None and name:
                            m[int(aid)] = name
                    if m:
                        _ACTOR_MAP_CACHE = m
                        return m
                except Exception:
                    continue
        try:
            m: dict = {}
            for line in VOCAB.splitlines():
                match = re.search(r"\(([^()]+)\)\s*-\s*.*?\bactor\s+ID\s+(\d+)\b", line, re.IGNORECASE)
                if match:
                    name = match.group(1).strip()
                    aid = int(match.group(2))
                    if name:
                        m[aid] = name
            if m:
                _ACTOR_MAP_CACHE = m
                return m
        except Exception:
            pass
        _ACTOR_MAP_CACHE = {}
        return {}


def resetActorMapCache():
    """Invalidate the cached actor map so it reloads on next use."""
    global _ACTOR_MAP_CACHE
    with _ACTOR_MAP_CACHE_LOCK:
        _ACTOR_MAP_CACHE = None


def translateAI(text, history, history_ctx=None):
    """
    Legacy wrapper function for the new shared translation utility.
    This maintains compatibility with existing code while using the new shared implementation.
    """
    global PBAR, MISMATCH, FILENAME
    
    # Update config estimate mode based on global ESTIMATE
    TRANSLATION_CONFIG.estimateMode = bool(ESTIMATE)
    # Keep batch size in sync with Settings / .env (module import can be stale).
    try:
        TRANSLATION_CONFIG.batchSize = getPricingConfig(MODEL)["batchSize"]
    except Exception:
        pass
    
    # Call the new shared translation function
    # Prefer thread-local filename for logging; fall back to global
    try:
        tl_filename = getattr(THREAD_CTX, "filename", FILENAME)
    except Exception:
        tl_filename = FILENAME

    # Speaker-parse mode: bypass all non-speaker translations to save tokens
    if SPEAKER_PARSE_MODE and not getattr(THREAD_CTX, "in_speaker", False):
        # Return original text unmodified with zero tokens
        return [text, [0, 0]]

    # Preflight count mode: don't hit API; just simulate progress units
    if 'PREFLIGHT_COUNT_MODE' in globals() and PREFLIGHT_COUNT_MODE:
        try:
            n = len(text) if isinstance(text, list) else 1
        except Exception:
            n = 1
        if PBAR is not None:
            try:
                with LOCK:
                    PBAR.update(n)
            except Exception:
                pass
        # Return original payload and zero tokens so totals aren't affected
        return [text, [0, 0]]

    # ── Actor variable substitution ──────────────────────────────────────────
    # Replace \n[X] codes with actor names before sending to AI so the model
    # sees real character names. Restore only exact-case name matches afterward;
    # this avoids lower-case words like "red" and keeps the prompt clean.
    actor_map = _get_actor_map()
    reverse: dict[str, str] = {}  # actor_name -> "\\n[X]"

    def _sub(s: str, reverse_map: dict[str, str]) -> str:
        if not isinstance(s, str) or not actor_map:
            return s

        def _display_actor_name(m: re.Match) -> str:
            name = actor_map.get(int(m.group(1)))
            return name if name else m.group(0)

        def _repl(m: re.Match) -> str:
            aid = int(m.group(1))
            name = actor_map.get(aid)
            if name:
                reverse_map[name] = m.group(0)
                return name
            return m.group(0)

        tag_match = re.match(
            rf"^(?P<open>\s*\[)(?P<speaker>{SPEAKER_BRACKET_INNER})(?P<close>\]\s*[|:：]\s*)",
            s,
            re.IGNORECASE,
        )
        if tag_match:
            speaker = _VAR_ACTOR_RE.sub(_display_actor_name, tag_match.group("speaker"))
            body = _VAR_ACTOR_RE.sub(_repl, s[tag_match.end():])
            return f"{tag_match.group('open')}{speaker}{tag_match.group('close')}{body}"

        return _VAR_ACTOR_RE.sub(_repl, s)

    if isinstance(text, list):
        item_reverses: list[dict[str, str]] = []
        subbed_text = []
        for s in text:
            item_reverse: dict[str, str] = {}
            subbed_text.append(_sub(s, item_reverse))
            item_reverses.append(item_reverse)
        text = subbed_text
    else:
        item_reverses = []
        text = _sub(text, reverse)

    result = sharedtranslateAI(
        text=text,
        history=history,
        config=TRANSLATION_CONFIG,
        filename=tl_filename,
        pbar=PBAR,
        lock=LOCK,
        mismatchList=MISMATCH,
    )
    THREAD_CTX.last_translation_had_mismatch = last_translation_had_mismatch()

    # ── Restore \n[X] codes in translated output ───────────────────────────
    def _restore(s: str, reverse_map: dict[str, str]) -> str:
        if not isinstance(s, str) or not reverse_map:
            return s
        restore_pat = re.compile(
            r"(?<!\w)(" + "|".join(re.escape(n) for n in sorted(reverse_map, key=len, reverse=True)) + r")(?!\w)",
        )
        return restore_pat.sub(lambda m: reverse_map[m.group(1)], s)

    if reverse or any(item_reverses):
        if isinstance(result[0], list):
            restored = []
            for idx, s in enumerate(result[0]):
                reverse_map = item_reverses[idx] if idx < len(item_reverses) else {}
                restored.append(_restore(s, reverse_map))
            result[0] = restored
        elif isinstance(result[0], str):
            reverse_map = item_reverses[0] if item_reverses else reverse
            result[0] = _restore(result[0], reverse_map)

    return result

def resetSpeakerState():
    """Clear all speaker-related globals so a fresh run doesn't carry over stale data."""
    global NAMESLIST, SPEAKER_COLLECTED
    NAMESLIST = []
    SPEAKER_COLLECTED = []
    with _speakerCacheLock:
        _speakerCache.clear()

def setSpeakerParseMode(flag: bool):
    """Enable/disable speaker-only parse mode."""
    global SPEAKER_PARSE_MODE
    SPEAKER_PARSE_MODE = bool(flag)

def collectedSpeakerCount() -> int:
    """Unique speaker names waiting for (or already in) the parse-mode glossary."""
    with _speakerCacheLock:
        return len(SPEAKER_COLLECTED)


def pendingSpeakerNames() -> list[str]:
    """Return collected speakers that still require a model translation."""
    _reload_vocab()
    with _speakerCacheLock:
        collected = list(SPEAKER_COLLECTED)
    pending = []
    seen = set()
    for speaker in collected:
        if not speaker or speaker in seen:
            continue
        seen.add(speaker)
        if _vocab_speaker_lookup(speaker) is None:
            pending.append(speaker)
    return pending


def _glossary_section_pattern(title: str):
    return re.compile(
        rf"^[\t ]*#+\s*{re.escape(title)}\s*(?:\r?\n|\Z).*?"
        rf"(?=^[\t ]*#|\Z)",
        re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )


def _merge_speaker_rows_into_game_characters(content: str, generated_pairs):
    """Migrate legacy speaker rows and new names into Game Characters."""
    newline = "\r\n" if "\r\n" in content else "\n"
    speaker_pattern = _glossary_section_pattern("Speakers")
    legacy_blocks = list(speaker_pattern.finditer(content))
    content_without_speakers = speaker_pattern.sub("", content)

    game_pattern = _glossary_section_pattern("Game Characters")
    game_match = game_pattern.search(content_without_speakers)
    existing_lines = []
    if game_match:
        existing_lines = game_match.group(0).splitlines()[1:]

    pair_pattern = re.compile(r"^(.+?)\s+\(([^()]*)\)(.*)$")
    existing_sources = set()
    for raw in existing_lines:
        pair = pair_pattern.match(raw.strip())
        if pair:
            existing_sources.add(pair.group(1).strip())

    candidates = []
    for block in legacy_blocks:
        candidates.extend(block.group(0).splitlines()[1:])
    candidates.extend(
        f"{source} ({translated})"
        for source, translated in generated_pairs
        if source and translated and _speaker_translation_valid(source, translated)
    )

    appended_lines = []
    seen_sources = set(existing_sources)
    seen_raw = {line.strip() for line in existing_lines if line.strip()}
    for raw in candidates:
        line = str(raw).strip()
        if not line:
            continue
        pair = pair_pattern.match(line)
        if pair:
            source = pair.group(1).strip()
            if source in seen_sources:
                continue
            seen_sources.add(source)
        elif line in seen_raw:
            continue
        seen_raw.add(line)
        appended_lines.append(line)

    if not legacy_blocks and not appended_lines:
        return content

    merged_lines = [line.rstrip() for line in existing_lines if line.strip()]
    merged_lines.extend(appended_lines)
    section = "# Game Characters" + newline
    if merged_lines:
        section += newline.join(merged_lines) + newline
    section += newline

    if game_match:
        before = content_without_speakers[:game_match.start()]
        after = content_without_speakers[game_match.end():].lstrip("\r\n")
        return before + section + after

    return section + content_without_speakers.lstrip("\r\n")


def finalizeSpeakerParse():
    """Batch translate collected speakers into # Game Characters."""
    if not SPEAKER_PARSE_MODE:
        return False
    try:
        # The grouped results must be persisted for the per-file subprocesses.
        # Without a glossary destination, translating them here would be wasted:
        # each subprocess would have to resolve the same speakers again.
        vocab_path = active_glossary_path() or VOCAB_PATH
        if vocab_path is None or not vocab_path.exists():
            return False

        # Step 1: seed curated vocab hits, then batch translate only unresolved
        # speakers. All persisted names are merged into # Game Characters;
        # legacy # Speakers rows are migrated below.
        _reload_vocab()
        pending = set(pendingSpeakerNames())
        to_translate = []
        vocab_resolved = []
        for s in SPEAKER_COLLECTED:
            if not s:
                continue
            if s in pending:
                to_translate.append(s)
                continue
            vocab_hit = _vocab_speaker_lookup(s)
            if vocab_hit is not None:
                vocab_resolved.append((s, vocab_hit))

        with _speakerCacheLock:
            for source, translated in vocab_resolved:
                _speakerCache[source] = translated
                for item in NAMESLIST:
                    if item[0] == source:
                        item[1] = translated
                        break
                else:
                    NAMESLIST.append([source, translated])
            to_translate = [s for s in to_translate if s not in _speakerCache]
        if to_translate:
            THREAD_CTX.last_translation_had_mismatch = False
            try:
                THREAD_CTX.in_speaker = True
                # Full list; translateAI chunks with the Settings batch size.
                resp = translateAI(
                    to_translate,
                    ctx("names.speaker"),
                    True,
                )
            finally:
                THREAD_CTX.in_speaker = False
            # Record token usage so it appears in the TOTAL string
            try:
                with LOCK:
                    TOKENS[0] += resp[1][0]
                    TOKENS[1] += resp[1][1]
            except Exception:
                pass
            tl_list = resp[0]
            if (
                bool(getattr(THREAD_CTX, "last_translation_had_mismatch", False))
                or not isinstance(tl_list, list)
                or len(tl_list) != len(to_translate)
            ):
                return False

            translated_pairs = []
            for orig, tl in zip(to_translate, tl_list):
                norm = _normalize_speaker_nameplate(tl)
                if not _speaker_translation_valid(orig, norm):
                    return False
                translated_pairs.append((orig, norm))

            with _speakerCacheLock:
                for orig, norm in translated_pairs:
                    if orig not in _speakerCache:
                        _speakerCache[orig] = norm
                        NAMESLIST.append([orig, norm])
            # Emit success only after every returned name passes validation.
            try:
                cost = calculateCost(resp[1][0], resp[1][1], MODEL)
                totalTokenstring = (
                    Fore.YELLOW + "[Input: " + str(resp[1][0]) + "]"
                    "[Output: "
                    + str(resp[1][1])
                    + "]" "[Cost: ${:,.4f}".format(cost)
                    + "]"
                )
                tqdm.write("Speakers: " + totalTokenstring + Fore.GREEN + " \u2713 " + Fore.RESET)
            except Exception:
                pass

        content = vocab_path.read_text(encoding="utf-8")
        new_content = _merge_speaker_rows_into_game_characters(
            content, NAMESLIST
        )

        tmp_path = vocab_path.with_suffix(vocab_path.suffix + f".{os.getpid()}.{threading.get_ident()}.tmp")
        tmp_path.write_text(new_content, encoding="utf-8")
        try:
            os.replace(tmp_path, vocab_path)
        except Exception:
            try:
                shutil.move(str(tmp_path), str(vocab_path))
            except Exception:
                return False
        _reload_vocab()
        return True
    except Exception:
        traceback.print_exc()
        return False
