# Libraries
import json
import os
import re
import util.dazedwrap as dazedwrap
import threading
import time
import traceback
import openai
import copy
from pathlib import Path
import shutil
from colorama import Fore
from dotenv import load_dotenv
from retry import retry
from tqdm import tqdm
from util.translation import TranslationConfig, translateAI as sharedtranslateAI, getPricingConfig, calculateCost, getPricingConfig, calculateCost

# Open AI
load_dotenv()
if os.getenv("api").replace(" ", "") != "":
    openai.base_url = os.getenv("api")
openai.organization = os.getenv("org")
openai.api_key = os.getenv("key")

# Globals
MODEL = os.getenv("model")
TIMEOUT = int(os.getenv("timeout"))
LANGUAGE = os.getenv("language").capitalize()
PROMPT = Path("prompt.txt").read_text(encoding="utf-8")
VOCAB = Path("vocab.txt").read_text(encoding="utf-8")
THREADS = int(os.getenv("threads"))
LOCK = threading.Lock()
THREAD_CTX = threading.local()
WIDTH = int(os.getenv("width"))
LISTWIDTH = int(os.getenv("listWidth"))
NOTEWIDTH = int(os.getenv("noteWidth"))
MAXHISTORY = 10
ESTIMATE = ""
TOKENS = [0, 0]
MISMATCH = []  # Lists files that throw a mismatch error (Length of GPT list response is wrong)
PBAR = None
FILENAME = None
TIMETOTAL = 0  # Total Time Taken for all translations
VOCAB_LOCK = threading.Lock()

# Speakers
NAMESLIST = []
SPEAKER_PARSE_MODE = False
_speakerCache = {}
_speakerCacheLock = threading.Lock()
SPEAKER_COLLECTED = []  # Original speaker names collected during parse mode (untranslated)

# Regex - Need to change this if you want to translate from/to other languages. Default is Japanese Regex
LANGREGEX = r"[\u3000-\u303F\u3040-\u309F\u30A0-\u30FF\u31F0-\u31FF\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\uFF00-\uFF5D\uFF5F-\uFFEF]+"

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

# Config (Default)
# FIRSTLINESPEAKERS: Guess speaker from first line.
FIRSTLINESPEAKERS = False
# FACENAME101: Map face name -> speaker.
FACENAME101 = False
# BRFLAG: Newlines -> <br>.
BRFLAG = False
# FIXTEXTWRAP: Rewrap text to WIDTH/NOTEWIDTH.
FIXTEXTWRAP = True
# IGNORETLTEXT: Skip Translated Text.
IGNORETLTEXT = False
# TLSYSTEMVARIABLES: Translate System Variables. (Optional but sometimes necessary. Can break stuff.)
TLSYSTEMVARIABLES = False

# Dialogue / Scroll / Choices (Main Codes)
CODE101 = True
CODE401 = True
CODE405 = True
CODE102 = True

# Optional
CODE408 = False

# Variables
CODE122 = False

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


def handleMVMZ(filename, estimate):
    global ESTIMATE, TOKENS, FILENAME
    ESTIMATE = estimate
    FILENAME = filename
    # Also record per-thread filename to avoid cross-thread interference
    try:
        THREAD_CTX.filename = filename
    except Exception:
        pass

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
        if "Map" in filename and filename != "MapInfos.json":
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
    """Update or insert a section in vocab.txt for the given category with provided pairs.
    Only writes when there's an actual translation (dst is non-empty and differs from src after normalization).
    - category: e.g., "Items", "Weapons", etc. Section header will be "# {category}".
    - pairs: list of (source, translated) strings. Duplicates by source are deduped (last wins).
    The existing section is replaced entirely; other sections are preserved.
    """
    try:
        vocab_path = Path("vocab.txt")

        # Helper: normalized comparison to detect no-op translations
        def _norm(s: str) -> str:
            if s is None:
                return ""
            # Collapse whitespace and case-fold; leave punctuation to avoid over-matching
            return re.sub(r"\s+", " ", str(s)).strip().casefold()

        # Filter and deduplicate by source term (last mapping wins)
        dedup: dict[str, str] = {}
        for src, dst in pairs:
            if not src:
                continue
            # Skip when no destination or no actual change
            if dst is None or _norm(dst) == "" or _norm(dst) == _norm(src):
                continue
            dedup[src] = dst

        # If nothing to add after filtering, skip touching the file
        if not dedup:
            return

        # Guard the read-modify-write with a dedicated lock to avoid races
        with VOCAB_LOCK:
            existing = vocab_path.read_text(encoding="utf-8") if vocab_path.exists() else ""

            lines = [f"{src} ({dst})" for src, dst in dedup.items()]
            # Always terminate a section with a blank line to separate from next header
            new_block = f"# {category}\n" + "\n".join(lines)
            if not new_block.endswith("\n\n"):
                if not new_block.endswith("\n"):
                    new_block += "\n"
                new_block += "\n"

            # Regex to find the specific section starting at the header for this category
            # and ending right before the next header (any number of '#') or EOF.
            # - Handles headers like '#Category', '# Category', '## Category', etc.
            # - Uses non-greedy matching for the body to avoid spanning multiple sections.
            pattern = re.compile(
                rf"^[\t ]*#+\s*{re.escape(category)}\s*$\r?\n.*?(?=^[\t ]*#|\Z)",
                re.MULTILINE | re.DOTALL,
            )
            if pattern.search(existing):
                # Replace only the first matching section for this category.
                updated = pattern.sub(lambda m: new_block, existing, count=1)
            else:
                updated = existing
                if updated and not updated.endswith("\n\n"):
                    # Ensure a blank line before appending new section if file not empty
                    if not updated.endswith("\n"):
                        updated += "\n"
                    updated += "\n"
                updated += new_block

            # Avoid writing if nothing changed
            if updated == existing:
                return
            # Atomic write: write to unique temp and replace with retries on Windows
            tmp_path = vocab_path.with_suffix(vocab_path.suffix + f".{os.getpid()}.{threading.get_ident()}.tmp")
            tmp_path.write_text(updated, encoding="utf-8")

            attempts = 6
            delay = 0.1
            last_err = None
            for attempt in range(attempts):
                try:
                    os.replace(tmp_path, vocab_path)
                    last_err = None
                    break
                except PermissionError as e:
                    last_err = e
                    # Try relaxing permissions then retry
                    try:
                        if vocab_path.exists():
                            os.chmod(vocab_path, 0o666)
                    except Exception:
                        pass
                    time.sleep(delay)
                    delay = min(1.0, delay * 2)
                except Exception as e:
                    last_err = e
                    break
            if last_err is not None:
                try:
                    shutil.move(str(tmp_path), str(vocab_path))
                except Exception:
                    try:
                        if tmp_path.exists():
                            tmp_path.unlink(missing_ok=True)
                    except Exception:
                        pass
                    raise last_err
    except Exception:
        traceback.print_exc()


def parseMap(data, filename):
    totalTokens = [0, 0]
    totalLines = 0
    events = data["events"]
    global LOCK

    # Translate displayName for Map files
    if "Map" in filename:
        response = translateAI(
            data["displayName"],
            "Reply with only the " + LANGUAGE + " translation of the RPG location name",
            False,
        )
        totalTokens[0] += response[1][0]
        totalTokens[1] += response[1][1]
        data["displayName"] = response[0].replace('"', "")

    # Get total for progress bar (sum of all command list lengths across pages)
    for event in events:
        if event:
            note_val = event.get("note") or ""
            if not isinstance(note_val, str):
                note_val = str(note_val) if note_val is not None else ""
            if "<LB>" in note_val:
                # Translate event name when flagged with <LB>
                name_val = event.get("name") or ""
                if isinstance(name_val, str) and name_val:
                    response = translateAI(
                        name_val,
                        "Reply with only the " + LANGUAGE + " translation of the RPG location name",
                        False,
                    )
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]
                    event["name"] = response[0].replace('"', "")
            if "<msgText:" in note_val:
                tokensResponse = translateNote(event, r"<msgText:\"(.*?)\">", False)
                totalTokens[0] += tokensResponse[0]
                totalTokens[1] += tokensResponse[1]
            for page in event["pages"]:
                totalLines += len(page["list"])
    global PBAR

    # Process each page synchronously with progress updates
    with tqdm(total=totalLines, bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE, desc=filename) as pbar:
        PBAR = pbar
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


def translateNote(event, regex, wordwrap=False):
    # Regex String
    jaString = event.get("note") or ""
    if not isinstance(jaString, str):
        jaString = str(jaString) if jaString is not None else ""
    match = re.findall(regex, jaString, re.DOTALL)
    if match:
        tokens = [0, 0]
        i = 0
        while i < len(match):
            initialJAString = match[i]
            modifiedJAString = initialJAString
            # Remove any textwrap
            if wordwrap:
                modifiedJAString = modifiedJAString.replace("\n", " ")

            # Translate
            response = translateAI(
                modifiedJAString,
                "Reply with only the " + LANGUAGE + " translation.",
                False,
            )
            translatedText = response[0]
            tokens[0] += response[1][0]
            tokens[1] += response[1][1]

            # Textwrap
            if wordwrap:
                translatedText = dazedwrap.wrapText(translatedText, width=NOTEWIDTH)
                translatedText = translatedText.replace('"', "")

            jaString = jaString.replace(initialJAString, translatedText)
            event["note"] = jaString
            i += 1
        return tokens
    return [0, 0]


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
            "Reply with the " + LANGUAGE + " translation of the location name.",
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


def parseCommonEvents(data, filename):
    totalTokens = [0, 0]
    totalLines = 0
    global LOCK

    # Get total for progress bar
    for page in data:
        if page is not None:
            totalLines += len(page["list"])
    global PBAR

    with tqdm(total=totalLines, bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE, desc=filename) as pbar:
        PBAR = pbar
        for page in data:
            if page is not None:
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
    totalLines = 0
    global LOCK

    # Get total for progress bar
    for troop in data:
        if troop is not None:
            for page in troop["pages"]:
                # Progress measured by number of commands in each page's list
                totalLines += len(page["list"])
    global PBAR

    with tqdm(total=totalLines, bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE, desc=filename) as pbar:
        PBAR = pbar
        for troop in data:
            if troop is not None:
                for page in troop["pages"]:
                    if page is not None:
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

    # Precompute total work units for progress bar
    def count_work_units(data, context):
        total = 0

        for entry in data:
            if not entry:
                continue

            # Names and associated fields
            name = entry.get("name", "")
            desc = entry.get("description", "")
            nickname = entry.get("nickname", "")
            profile = entry.get("profile", "")

            if context == "Actors":
                if name:
                    total += 1
                if nickname:
                    total += 1
                if profile:
                    total += 1
            elif context in ["Armors", "Weapons", "Items"]:
                if name:
                    total += 1
                if desc:
                    total += 1
            elif context == "Skills":
                if name:
                    total += 1
                if desc:
                    total += 1
                # Messages translated individually in searchNames
                for n in range(1, 5):
                    msg = entry.get(f"message{n}")
                    if msg:
                        total += 1
            elif context in ["Enemies", "Classes", "MapInfos"]:
                if name:
                    total += 1

        return total

    total_units = count_work_units(data, context)
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

    # Precompute total units (ignore notes): name, description, message1..4 presence
    def count_work_units(states):
        total = 0
        for st in states:
            if not st:
                continue
            if st.get("name"):
                total += 1
            if st.get("description"):
                total += 1
            for n in range(1, 5):
                if st.get(f"message{n}"):
                    total += 1
        return total

    total_units = count_work_units(data)
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

    # Precompute total units across system sections (exclude notes; count strings)
    def count_work_units(sys):
        total = 0
        # Title
        if sys.get("gameTitle"):
            total += 1
        # Terms (excluding 'messages' object)
        terms = sys.get("terms", {})
        for term_key, term_list in terms.items():
            if term_key == "messages":
                continue
            if isinstance(term_list, list):
                total += sum(1 for x in term_list if x is not None)
        # Armor, Skill, Equip types
        total += len(sys.get("armorTypes", []) or [])
        total += len(sys.get("skillTypes", []) or [])
        total += len(sys.get("equipTypes", []) or [])
        # Messages
        messages = terms.get("messages", {}) or {}
        total += len(messages)
        return total

    total_units = count_work_units(data)
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
    totalLines = 0
    global LOCK

    # Get total for progress bar
    for page in data.items():
        totalLines += len(page[1])
    global PBAR

    with tqdm(total=totalLines, bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE, desc=filename) as pbar:
        PBAR = pbar
        for page in data.items():
            if page[1] is not None:
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
    profileList = []
    nicknameList = []
    descriptionList = []
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
        newContext = "Reply with only the " + LANGUAGE + " translation of the NPC name"
    if "Armors" in context:
        newContext = "Reply with only the " + LANGUAGE + " translation of the RPG equipment name"
    if "Classes" in context:
        newContext = "Reply with only the " + LANGUAGE + " translation of the RPG class name"
    if "MapInfos" in context:
        newContext = "Reply with only the " + LANGUAGE + " translation of the location name"
    if "Enemies" in context:
        newContext = "Reply with only the " + LANGUAGE + " translation of the enemy NPC name"
    if "Weapons" in context:
        newContext = "Reply with only the " + LANGUAGE + " translation of the RPG weapon name"
    if "Items" in context:
        newContext = "Reply with only the " + LANGUAGE + " translation of the RPG item name"
    if "Skills" in context:
        newContext = "Reply with only the " + LANGUAGE + " translation of the RPG skill name"

    # Names
    with open("log/translations.txt", "a", encoding="utf-8") as file:
        file.write(f"\n#{context}\n")

    # --- Batching pass: collect all note texts for all note types ---
    note_regexes = [
        (r"<note:(.*?)>", False),
        (r"<PE拡張:(.*?)>", False),
        (r"<hint:(.*?)>", False),
        (r"<SGDescription:(.*?)>", False),
        (r"<SG説明:\n?(.*?)>", False),
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
                    notesBatch.append(match_text)
                    notesBatchMap.append((idx, regex, match_text, wordwrap))
            else:
                for m in matches:
                    match_text = m if isinstance(m, str) else m[0]
                    notesBatch.append(match_text)
                    notesBatchMap.append((idx, regex, match_text, wordwrap))

    # --- Batch translate all notes ---
    translatedNotesBatch = []
    if notesBatch:
        response = translateAI(notesBatch, f"Reply with only the {LANGUAGE} translation of the note text.", True)
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
                    msg_text = entry[msg_field]
                    needs_taro = len(msg_text) > 0 and msg_text[0] in ["は", "を", "の", "に", "が"]
                    if needs_taro:
                        messages_batch.append("Taro" + msg_text)
                    else:
                        messages_batch.append(msg_text)
                    messages_map.append((idx, msg_field, needs_taro))
        
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
            for msg_idx, (entry_idx, msg_field, needs_taro) in enumerate(messages_map):
                if msg_idx < len(translated_messages):
                    translation = translated_messages[msg_idx]
                    if needs_taro:
                        translation = translation.replace("Taro", "")
                    data[entry_idx][msg_field] = translation
            
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
                    if data[i]["name"] != "":
                        nameList.append(data[i]["name"])
                    if "nickname" in data[i] and data[i]["nickname"]:
                        nicknameList.append(data[i]["nickname"])
                    if "profile" in data[i] and data[i]["profile"]:
                        profileList.append(data[i]["profile"].replace("\n", " "))
                    i += 1
                else:
                    batchFull = True
            if context in ["Armors", "Weapons", "Items"]:
                if len(nameList) < BATCHSIZE:
                    nameList.append(data[i]["name"])
                    if "description" in data[i] and data[i]["description"] != "":
                        description = data[i]["description"]
                        description = description.replace("\n", " ")
                        descriptionList.append(description)
                    i += 1
                else:
                    batchFull = True
            if context in ["Skills"]:
                if len(nameList) < BATCHSIZE:
                    nameList.append(data[i]["name"])
                    if "description" in data[i] and data[i]["description"]:
                        descriptionList.append(data[i]["description"].replace("\n", " "))
                    i += 1
                else:
                    batchFull = True
            if context in ["Enemies", "Classes", "MapInfos"]:
                if len(nameList) < BATCHSIZE:
                    nameList.append(data[i]["name"])
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
                response = translateAI(nameList, newContext, True)
                translatedNameBatch = response[0]
                totalTokens[0] += response[1][0]
                totalTokens[1] += response[1][1]
                batchTokens[0] += response[1][0]
                batchTokens[1] += response[1][1]
                if pbar is not None and nameList:
                    pbar.refresh()

                # Nickname
                if nicknameList:
                    response = translateAI(nicknameList, newContext, True)
                    translatedNicknameBatch = response[0]
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]
                    batchTokens[0] += response[1][0]
                    batchTokens[1] += response[1][1]
                    if pbar is not None:
                        pbar.refresh()

                # Profile
                if profileList:
                    response = translateAI(profileList, "", True)
                    translatedProfileBatch = response[0]
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]
                    batchTokens[0] += response[1][0]
                    batchTokens[1] += response[1][1]
                    if pbar is not None:
                        pbar.refresh()

                # Set Data
                if len(nameList) == len(translatedNameBatch):
                    j = k
                    while j < i:
                        # Empty Data
                        if data[j] is None or data[j]["name"] == "":
                            j += 1
                            continue
                        else:
                            # Get Text
                            if data[j]["name"] != "":
                                with open("log/translations.txt", "a", encoding="utf-8") as file:
                                    file.write(f'{data[j]["name"]} ({translatedNameBatch[0]})\n')
                                # Actors are excluded from vocab updates
                                    data[j]["name"] = translatedNameBatch[0]
                                translatedNameBatch.pop(0)
                            if "nickname" in data[j] and data[j]["nickname"]:
                                data[j]["nickname"] = translatedNicknameBatch[0]
                                translatedNicknameBatch.pop(0)
                            if "profile" in data[j] and data[j]["profile"]:
                                data[j]["profile"] = dazedwrap.wrapText(translatedProfileBatch[0], LISTWIDTH)
                                translatedProfileBatch.pop(0)

                            # If Batch is empty. Move on.
                            if len(translatedNameBatch) == 0:
                                nameList.clear()
                                profileList.clear()
                                nicknameList.clear()
                                batchFull = False
                                filling = False
                            j += 1
                    # Persist after applying this batch only if we actually translated something in this batch
                    checkSave(data, filename, batchTokens)
                else:
                    mismatch = True

            if context in ["Armors", "Weapons", "Items", "Skills"]:
                # Track tokens for this batch
                batchTokens = [0, 0]
                # Name
                response = translateAI(nameList, newContext, True)
                translatedNameBatch = response[0]
                totalTokens[0] += response[1][0]
                totalTokens[1] += response[1][1]
                batchTokens[0] += response[1][0]
                batchTokens[1] += response[1][1]
                if pbar is not None and nameList:
                    pbar.refresh()

                # Description
                if descriptionList:
                    response = translateAI(
                        descriptionList,
                        f"Reply with only the {LANGUAGE} translation of the text.",
                        True,
                    )
                    translatedDescriptionBatch = response[0]
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]
                    batchTokens[0] += response[1][0]
                    batchTokens[1] += response[1][1]
                    if pbar is not None:
                        pbar.refresh()

                # Set Data
                if len(nameList) == len(translatedNameBatch):
                    j = k
                    with open("log/translations.txt", "a", encoding="utf-8") as file:
                        while j < i:
                            # Empty Data
                            if data[j] is None or data[j]["name"] == "":
                                j += 1
                                continue
                            else:
                                # Get Text
                                file.write(f"{data[j]['name']} ({translatedNameBatch[0]})\n")
                                if vocab_enabled:
                                    try:
                                        vocab_pairs.append((data[j]['name'], translatedNameBatch[0]))
                                    except Exception:
                                        pass
                                data[j]["name"] = translatedNameBatch[0]
                                translatedNameBatch.pop(0)
                                if "description" in data[j] and data[j]["description"] != "":
                                    translatedDescriptionBatch[0] = dazedwrap.wrapText(translatedDescriptionBatch[0], LISTWIDTH)
                                    data[j]["description"] = translatedDescriptionBatch[0]
                                    translatedDescriptionBatch.pop(0)

                            # If Batch is empty. Move on.
                            if len(translatedNameBatch) == 0:
                                nameList.clear()
                                descriptionList.clear()
                                batchFull = False
                                filling = False
                            j += 1
                    # Persist after applying this batch only if we actually translated something in this batch
                    checkSave(data, filename, batchTokens)
                else:
                    mismatch = True
            if context in ["Enemies", "Classes", "MapInfos"]:
                # Track tokens for this batch
                batchTokens = [0, 0]
                response = translateAI(nameList, newContext, True)
                translatedNameBatch = response[0]
                totalTokens[0] += response[1][0]
                totalTokens[1] += response[1][1]
                batchTokens[0] += response[1][0]
                batchTokens[1] += response[1][1]
                if pbar is not None and nameList:
                    pbar.refresh()

                # Set Data
                if len(nameList) == len(translatedNameBatch):
                    j = k
                    while j < i:
                        # Empty Data
                        if data[j] is None or data[j]["name"] == "":
                            j += 1
                            continue
                        else:
                            with open("log/translations.txt", "a", encoding="utf-8") as file:
                                file.write(f'{data[j]["name"]} ({translatedNameBatch[0]})\n')
                            # Get Text
                            if vocab_enabled:
                                try:
                                    vocab_pairs.append((data[j]["name"], translatedNameBatch[0]))
                                except Exception:
                                    pass
                            data[j]["name"] = translatedNameBatch[0]
                            translatedNameBatch.pop(0)

                            # If Batch is empty. Move on.
                            if len(translatedNameBatch) == 0:
                                nameList.clear()
                                batchFull = False
                                filling = False
                            j += 1
                    # Persist after applying this batch only if we actually translated something in this batch
                    checkSave(data, filename, batchTokens)
                else:
                    mismatch = True

            # Mismatch
            if mismatch == True:
                MISMATCH.append(nameList)
                nameList.clear()
                profileList.clear()
                descriptionList.clear()
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
        setData = True
    textHistory = []
    match = []
    totalTokens = [0, 0]
    translatedText = ""
    speaker = ""
    speakerID = None
    syncIndex = 0
    maxHistory = MAXHISTORY
    VNameValue = None
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
            nametag = ""

            ## Event Code: 401 Show Text
            if "code" in codeList[i] and codeList[i]["code"] in [401, 405, -1] and (CODE401 or CODE405):
                # Save Code and starting index (j)
                code = codeList[i]["code"]
                j = i
                endtag = ""
                instantLineFlag = False

                # Grab String
                if len(codeList[i]["parameters"]) > 0:
                    jaString = codeList[i]["parameters"][0]
                    oldjaString = jaString
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

                # Remove any RPGMaker Code at start
                ffMatch = re.search(
                    r"^((?:[\\]+[^cCnNiIkKvV]+\[[\d\w]+\])+)",
                    jaString,
                )
                if ffMatch != None:
                    jaString = jaString.replace(ffMatch.group(0), "")
                    nametag += ffMatch.group(0)

                # m and z Codes
                match = re.search(r"(.*?)[\\]+m\[\d+?\][\\]+z\[\d+?\]", jaString)
                if match:
                    speakerList.append(match.group(1))
                    if "\\c" in speakerList[0]:
                        speakerList = re.findall(
                            r"^[\\]+[cC]\[\d+\]【?(.+?)】?[\\]+[cC]\[\d+\](?:[\\]+[A-Za-z]+(?:\[[^\]]*\])?)*[\\]*$",
                            speakerList[0],
                        )

                # Brackets (support multiple names like 【A】【B】)
                if len(speakerList) == 0:
                    # Only consider bracketed names when the line starts with '【' and
                    # ends with either '】' or trailing variable/control codes like \n[2], \FF[\w[3]], etc.
                    startsWithBracket = re.match(r"^\s*【", jaString) is not None
                    endsWithBracket = re.search(
                        r"(】\s*|(?:[\\]+[A-Za-z]+(?:\[(?:[^\[\]]|\[[^\]]*\])*\])+\s*)$)",
                        jaString,
                    ) is not None

                    if startsWithBracket and endsWithBracket:
                        candidates = re.findall(r"【(.*?)】", jaString)
                        if candidates:
                            candidates = [c.strip() for c in candidates]
                            if candidates:
                                speakerList = candidates

                # Colors
                if len(speakerList) == 0:
                    speakerList = re.findall(
                        r"^[\\]+[cC]\[\d+\]【?(.+?)】?[\\]+[cC]\[\d+\](?:[\\]+[A-Za-z]+(?:\[[^\]]*\])?)*[\\]*$",
                        jaString,
                    )

                # Colons
                if len(speakerList) == 0:
                    speakerList = re.findall(
                        r"[\\]*[cC]?\[?\d*\]?(.+)：$",
                        jaString,
                    )

                # First Line Speakers
                if len(speakerList) == 0 and FIRSTLINESPEAKERS is True:
                    # Test Speaker
                    if (
                        len(jaString) < 40
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
                            speakerList = re.findall(r".+", jaString)

                # Replace Speaker
                if len(speakerList) != 0 and codeList[i + 1]["code"] in [401, 405, -1]:
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
                    elif not setData and len(speakerList) == 1:
                        codeList[i]["parameters"][0] = nametag + jaString.replace(speakerList[0], speaker)
                    nametag = ""

                    # Iterate to next string
                    i += 1
                    j = i
                    while codeList[i]["code"] in [-1]:
                        i += 1
                        j = i
                    jaString = codeList[i]["parameters"][0]

                # Check if there is text to translate
                if not re.search(r"\w+", jaString):
                    i += 1
                    continue

                # Validate Japanese Text
                if not re.search(LANGREGEX, jaString) and IGNORETLTEXT:
                    i += 1
                    continue

                # Using this to keep track of 401's in a row.
                currentGroup.append(jaString)

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

                        # Make sure not the end of the list.
                        if len(codeList) <= i + 1:
                            break

                # Format String
                if len(currentGroup) > 0:
                    finalJAString = "\n".join(currentGroup)
                    oldjaString = finalJAString

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
                    finalJAString = finalJAString.replace("…", "...")
                    finalJAString = finalJAString.replace("。", ".")
                    finalJAString = re.sub(r"(\.{3}\.+)", "...", finalJAString)
                    finalJAString = finalJAString.replace("　", "")
                    finalJAString = finalJAString.replace("「", '"')
                    finalJAString = finalJAString.replace("」", '"')
                    finalJAString = finalJAString.replace("\\,", ',')

                    ### Remove format codes
                    # Furigana: \r or \rb [base,reading] -> keep reading/base per pattern
                    finalJAString = re.sub(r"[\\]+[r][b]?\[(.*?),.*?\]", r"\1", finalJAString)

                    # Curly-brace furigana: {base|reading} -> keep base
                    finalJAString = re.sub(r"\{([^|{}]+)\|[^|{}]+?\}", r"\1", finalJAString)

                    # Remove any RPGMaker Code at start
                    ffMatch = re.search(
                        r"^((?:[\\]+[^cCnNiIkKvVSs{}]+?\[[\d\w\W]+?\]?\])+)",
                        finalJAString,
                    )
                    if ffMatch != None:
                        finalJAString = finalJAString.replace(ffMatch.group(1), "")
                        nametag = ffMatch.group(1) + nametag

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
                            elif finalJAString != "":
                                list401.append(f"[{speaker}]: {finalJAString}")
                            else:
                                list401.append(speaker)
                        speaker = ""
                        match = []
                        nametag = ""
                        currentGroup = []
                        syncIndex = i + 1

                        # Keep textHistory list at length maxHistory
                        textHistory.append('"' + finalJAString + '"')
                        if len(textHistory) > maxHistory:
                            textHistory.pop(0)

                    # Pass 2 (Setting Data)
                    else:
                        # Grab Translated String
                        if len(list401) > 0:
                            translatedText = list401[0]

                            # Remove speaker
                            match = re.search(r'(^\[.+?\]\s?[|:]\s?)', translatedText)
                            if match:
                                translatedText = translatedText.replace(match.group(1), "") 

                            # Fix '- '
                            translatedText = translatedText.replace("- ", "-")

                            # Textwrap
                            if FIXTEXTWRAP is True:
                                finalJAString = re.sub(r"\n", " ", finalJAString)
                                finalJAString = finalJAString.replace("<br>", " ")

                            if FIXTEXTWRAP is True and "_ABL" in nametag:
                                translatedText = dazedwrap.wrapText(translatedText, width=100)
                            elif FIXTEXTWRAP is True:
                                translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)

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
                                    new_item["parameters"] = [line]
                                    codeList.insert(j + idx + 1, new_item)
                                
                                # 4. Update syncIndex to the last modified/added position
                                syncIndex = j + len(lines)

                            # Handle 401
                            else:
                                codeList[j]["parameters"] = [translatedText]
                                codeList[j]["code"] = code
                                syncIndex = i + 1

                            # Reset
                            speaker = ""
                            match = []
                            currentGroup = []
                            list401.pop(0)

            ## Event Code: 122 [Set Variables]
            if "code" in codeList[i] and codeList[i]["code"] == 122 and CODE122 is True:
                # This is going to be the var being set. (IMPORTANT)
                if codeList[i]["parameters"][0] not in list(range(0, 2000)):
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
                if 'gameV' in jaString or '_' in jaString or '"[' in jaString:
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
                matchedText = None
                if len(re.findall(r"([\'\"\`])", jaString)) >= 2:
                    matchedText = re.search(r"[\'\"\`](.*)[\'\"\`]", jaString)
                    if matchedText and matchedText.group(1).strip():
                        # Remove Textwrap
                        finalJAString = matchedText.group(1).replace("\\n", " ")

                        # Pass 1
                        if setData:
                            if finalJAString != "":
                                list122.append(finalJAString)

                        # Pass 2
                        else:
                            if len(list122) > 0:
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

                        # If there isn't any Japanese in the text just skip
                        # if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', jaString):
                        #     i += 1
                        #     continue

                        # Remove any textwrap & TL
                        jaString = jaString.replace("\\n", " ")
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
                                charList = ['"', "\\n"]
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

                # Map Plugins
                headerMappings = {
                    "LL_InfoPopupWIndow": ("messageText", None),
                    "QuestSystem": ("DetailNote", None),
                    "BalloonInBattle": ("text", None),
                    "MNKR_CommonPopupCoreMZ": ("text", None),
                    "DestinationWindow": ("destination", None),
                    "_TMLogWindowMZ": ("text", None),
                    "TorigoyaMZ_NotifyMessage": ("message", None),
                    "SoR_GabWindow": ("arg1", None),
                    "DarkPlasma_CharacterText": ("text", None),
                    "DTextPicture": ("text", None),
                    "TextPicture": ("text", None),
                    "TRP_SkitMZ": ("name", None),
                    "LogWindow": ("text", None),
                    "BattleLogOutput": ("message", None),
                    "TorigoyaMZ_NotifyMessage_CommandMessage": ("message", None),
                    "NUUN_SaveScreen": ("AnyName", None),
                }

                for key, (argVar, font) in headerMappings.items():
                    if key in headerString:
                        translatePlugins(argVar, font)

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
                                        m = re.search(r'(^\[.+?\]\s?[|:]\s?)', translatedText)
                                        if m:
                                            translatedText = translatedText.replace(m.group(1), "")

                                        if FIXTEXTWRAP:
                                            translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)

                                        params_obj[chosen_key] = translatedText

                if headerString == "LL_GalgeChoiceWindow":
                    ### Message Text First
                    jaString = codeList[i]["parameters"][3]["messageText"]

                    # Remove any textwrap & TL
                    jaString = re.sub(r"\n", " ", jaString)
                    response = translateAI(jaString, "", False)
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
                        # Translate
                        question = codeList[i]["parameters"][3]["messageText"]
                        response = translateAI(
                            matchList,
                            f"Previous text for context: {question}\n",
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
                if "text" in codeList[i]["parameters"][0]:
                    jaString = codeList[i]["parameters"][0]
                    if not isinstance(jaString, str):
                        i += 1
                        continue

                    # Definitely don't want to mess with files
                    if "_" in jaString:
                        i += 1
                        continue

                    # If there isn't any Japanese in the text just skip
                    if not re.search(LANGREGEX, jaString):
                        i += 1
                        continue

                    # Remove outside text
                    startString = re.search(r"^[^一-龠ぁ-ゔァ-ヴー\<\>【】\\]+", jaString)
                    jaString = re.sub(r"^[^一-龠ぁ-ゔァ-ヴー\<\>【】\\]+", "", jaString)
                    endString = re.search(r"[^一-龠ぁ-ゔァ-ヴー\<\>【】。！？\\]+$", jaString)
                    jaString = re.sub(r"[^一-龠ぁ-ゔァ-ヴー\<\>【】。！？\\]+$", "", jaString)
                    if startString is None:
                        startString = ""
                    else:
                        startString = startString.group()
                    if endString is None:
                        endString = ""
                    else:
                        endString = endString.group()

                    # Remove any textwrap
                    jaString = re.sub(r"\n", " ", jaString)

                    # Translate
                    response = translateAI(jaString, "", True)
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]
                    translatedText = response[0]

                    # Remove characters that may break scripts
                    charList = [".", '"', "'"]
                    for char in charList:
                        translatedText = translatedText.replace(char, "")

                    # Textwrap
                    translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)
                    translatedText = startString + translatedText + endString

                    # Set Data
                    codeList[i]["parameters"][0] = translatedText

            ## Event Code: 101 [Name] [Optional]
            if "code" in codeList[i] and codeList[i]["code"] == 101 and CODE101 is True:
                isVar = False

                # Grab String
                jaString = ""
                if len(codeList[i]["parameters"]) > 4:
                    jaString = codeList[i]["parameters"][4]
                # Check for Var
                elif len(codeList[i]["parameters"]) > 0:
                    jaString = codeList[i]["parameters"][0]
                    isVar = True
                if not isinstance(jaString, str):
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
                elif "\\ap" in jaString:
                    speaker = re.search(r"[\\]+AP\[(.*?)\]", jaString).group(1)
                    i += 1
                    continue

                # Get Speaker
                match = re.search(r"^(?:[\\]+[cC]\[\d+?\])?([\w\s]+)", jaString)
                if match:
                    jaString = match.group(1)
                    response = getSpeaker(jaString)
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]
                    speaker = response[0]

                    # Validate Speaker is not empty
                    if len(speaker) > 0:
                        if isVar == False:
                            codeList[i]["parameters"][4] = codeList[i]["parameters"][4].replace(jaString, speaker)
                            i += 1
                            continue
                        else:
                            codeList[i]["parameters"][0] = codeList[i]["parameters"][0].replace(jaString, speaker)
                            isVar = False
                            i += 1
                            continue
                    else:
                        speaker = ""
                elif FACENAME101:
                    faceName = codeList[i]["parameters"][0]
                    if faceName == "Actor1_1":
                        speaker = "Sakura"
                    if faceName == "Actor2_1":
                        speaker = "Suzune"
                    if faceName == "Actor3_1":
                        speaker = "Kaji"
                    if faceName == "Actor4_1":
                        speaker = "Kirari"
                    if faceName == "Actor5_1":
                        speaker = "Onsen"
                    if faceName == "Actor6_1":
                        speaker = "Gufu"
                    if faceName == "Actor7_1":
                        speaker = "Kahimeru"
                    if faceName == "Actor10_1":
                        speaker = "Miuma"
                    if faceName == "Actor11_1":
                        speaker = "Nurari"
                    if faceName == "Actor12_1":
                        speaker = "Kokotsuzumi"

            ## Event Code: 355 or 655 Scripts [Optional]
            if "code" in codeList[i] and (codeList[i]["code"] == 355 or codeList[i]["code"] == 655) and CODE355655 is True:
                jaString = codeList[i]["parameters"][0]
                
                patterns = {
                    # "テキスト-": (r"テキスト-(.+)")
                    # "=": (r'=\s?(.*)",'),
                    # "var text": (r"var\stext\d+\s=\s\"(.+)\""),
                    # "logtxt = ": (r"logtxt\s=\s'(.+)'" 
                    # ".setNickname": (r'.setNickname\(\\?"(.+?)\\?"\)'
                    # "_subject=": (r'_subject=(.+?)_'
                    # "text =": (r"text\s*=\s*'(.+[^\\])'"),
                    # "const text": (r'(const\stext\s?=\s?"(.+)";?)'),
                    # "ex_a_name": (r'ex_a_name\(\d+,"(.+)"\)'),
                    # "gameVariables.setValue": (r"\$gameVariables.setValue\(\d+,\s?'(.+)'\)"),
                    # "BattleManager._logWindow.push('addText'": (r"BattleManager._logWindow.push\('addText',\s'(.+)'\)"),
                    # "BattleManager._logWindow.addText": (r"BattleManager._logWindow.addText\('(.+)'\)"),
                }

                for key, (regex) in patterns.items():
                    if key in jaString:
                        match = re.search(regex, jaString)
                        if match:
                            # Check if the match contains actual text (not just numbers/special chars)
                            if not re.search(r'[a-zA-Z一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９\uFF61-\uFF9F]', match.group(1)):
                                continue

                            # Pass 1
                            if setData:
                                list355655.append(match.group(1))

                            # Pass 2
                            else:
                                # Grab and Replace
                                translatedText = list355655[0]
                                list355655.pop(0)

                                # Only escape if not already escaped 
                                matchList = re.findall(r"(.+)'\s*[$+].+?'(.+)", translatedText)
                                if matchList:
                                    for string in matchList[0]:
                                        escapedMatch = re.sub(r"(?<!\\)'", r"\\'", string)
                                        translatedText = translatedText.replace(string, escapedMatch)
                                else:
                                    translatedText = re.sub(r"(?<!\\)'", r"\\'", translatedText)
                                translatedText = re.sub(r'(?<!\\)"', r'"', translatedText)
                                # Double backslashes before control codes
                                translatedText = re.sub(r'(?<![\\])([\\]{1})(?=\w)', r'\\\\', translatedText)

                                # Set
                                codeList[i]["parameters"][0] = jaString.replace(match.group(1), translatedText)
                        break

            ## Event Code: 408 (Script)
            if "code" in codeList[i] and (codeList[i]["code"] == 408) and CODE408 is True:
                jaString = codeList[i]["parameters"][0]
                match = re.search(r"(.+)", jaString)
                if match:
                    # Remove Textwrap
                    jaString = codeList[i]["parameters"][0]
                    ojaString = jaString
                    jaString = jaString.replace("\n", " ")

                    # If there isn't any Japanese in the text just skip
                    if not re.search(LANGREGEX, jaString):
                        i += 1
                        continue

                    # Pass 1
                    if setData:
                        list408.append(jaString)
                    
                    # Pass 2
                    else:
                        translatedText = list408[0]
                        list408.pop(0)

                        # Textwrap
                        translatedText = dazedwrap.wrapText(translatedText, width=LISTWIDTH)

                        # Set Data
                        codeList[i]["parameters"][0] = codeList[i]["parameters"][0].replace(ojaString, translatedText)

            ## Event Code: 108 (Script)
            if "code" in codeList[i] and (codeList[i]["code"] == 108) and CODE108 is True:
                jaString = codeList[i]["parameters"][0]

                # If there isn't any Japanese in the text just skip
                if not re.search(LANGREGEX, jaString):
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
                        if "ActiveMessage" in translatedText and ">" not in translatedText:
                            translatedText = translatedText + ">"

                        # Set Data
                        codeList[i]["parameters"][0] = translatedText

            ## Event Code: 356
            if "code" in codeList[i] and codeList[i]["code"] == 356 and CODE356 is True:
                jaString = codeList[i]["parameters"][0]
                oldjaString = jaString

                # Grab Speaker
                if "Tachie showName" in jaString:
                    matchList = re.findall(r"Tachie showName (.+)", jaString)
                    if len(matchList) > 0:
                        # Translate
                        response = translateAI(
                            matchList[0],
                            "Reply with the " + LANGUAGE + " translation of the NPC name.",
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
                    regex = r"D_TEXT\s*([^\s]+)\s?\d*"
                elif "ShowInfo" in jaString:
                    regex = r"ShowInfo\s(.*)"
                elif "PushGab" in jaString:
                    regex = r"PushGab\s(.*)"
                elif "addLog" in jaString:
                    regex = r"addLog\s(.*)"
                elif "DW_" in jaString:
                    regex = r"DW_.*\s\d+\s(.+)"
                elif "CommonPopup" in jaString:
                    regex = r"CommonPopup\sadd\stext:(.*?)[\\]+}"
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
                            charList = [".", '"']
                            for char in charList:
                                translatedText = translatedText.replace(char, "")

                            # Cant have spaces?
                            translatedText = translatedText.replace(" ", "_")
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
                        response = translateAI(text, "Reply with the " + LANGUAGE + " Translation", False)
                        translatedText = response[0]
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]

                        # Set Data
                        updated = jaString.replace(text, translatedText.replace(" ", "_"))
                        codeList[i]["parameters"][0] = updated

                if "LL_InfoPopupWIndowMV" in jaString:
                    matchList = re.findall(r"LL_InfoPopupWIndowMV\sshowWindow\s(.+?) .+", jaString)
                    if len(matchList) > 0:
                        # Translate
                        text = matchList[0]
                        response = translateAI(text, "Reply with the " + LANGUAGE + " Translation", False)
                        translatedText = response[0]
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]

                        # Set Data
                        translatedText = translatedText.replace(" ", "_")
                        translatedText = jaString.replace(text, translatedText)
                        codeList[i]["parameters"][0] = translatedText

                if "OriginMenuStatus SetParam" in jaString:
                    matchList = re.findall(r"OriginMenuStatus\sSetParam\sparam[\d]\s(.*)", jaString)
                    if len(matchList) > 0:
                        # Translate
                        text = matchList[0]
                        response = translateAI(text, "Reply with the " + LANGUAGE + " Translation", False)
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
                        response = translateAI(jaString, "", False)
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

                        # Translate
                        question = translatedText
                        response = translateAI(
                            choiceList,
                            f"Previous text for context: {question}\n",
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
                varList = []
                choiceIndexMap = []  # Track which original indices we're processing
                
                # Process each string in the parameters list
                for choice in range(len(codeList[i]["parameters"][0])):
                    jaString = codeList[i]["parameters"][0][choice]
                    jaString = jaString.replace(" 。", ".")

                    # Avoid Empty Strings
                    if not jaString.strip():
                        continue

                    # If and En Statements
                    ifVar = ""
                    ifList = re.findall(r"([ei][nf]\(.+?\)\)?\)?)", jaString)
                    if len(ifList) != 0:
                        for var in ifList:
                            jaString = jaString.replace(var, "")
                            ifVar += var
                    
                    # Store the formatting and cleaned string
                    varList.append(ifVar)
                    choiceList.append(jaString)
                    choiceIndexMap.append(choice)

                # Translate the list
                if len(choiceList) > 0:
                    if len(textHistory) > 0:
                        response = translateAI(
                            choiceList,
                            f"Reply with the English translation of the dialogue choice.\n\nPrevious text for context: {str(textHistory)}\n",
                            True,
                        )
                    else:
                        response = translateAI(choiceList, "Reply with the English translation of the dialogue choice.", True)
                    
                    translatedTextList = response[0]
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]

                    # Check Mismatch and set translations
                    if len(translatedTextList) == len(choiceList):
                        for idx, translatedText in enumerate(translatedTextList):
                            originalIndex = choiceIndexMap[idx]
                            
                            # Apply formatting
                            if translatedText != "":
                                translatedText = varList[idx] + translatedText[0].upper() + translatedText[1:]
                            else:
                                translatedText = varList[idx] + translatedText
                            
                            # Set the translation back to the original position
                            codeList[i]["parameters"][0][originalIndex] = translatedText
                    else:
                        if filename not in MISMATCH:
                            MISMATCH.append(filename)

            ### Event Code: 111 Script
            if "code" in codeList[i] and codeList[i]["code"] == 111 and CODE111 is True:
                for j in range(len(codeList[i]["parameters"])):
                    jaString = codeList[i]["parameters"][j]

                    # Check if String
                    if not isinstance(jaString, str):
                        i += 1
                        continue

                    # Only TL the Game Variable
                    if "$gameVariables" not in jaString:
                        i += 1
                        continue

                    # This is going to be the var being set. (IMPORTANT)
                    if "1045" not in jaString:
                        i += 1
                        continue

                    # Need to remove outside code and put it back later
                    matchList = re.findall(r"'(.*?)'", jaString)

                    for match in matchList:
                        response = translateAI(match, "", False)
                        translatedText = response[0]
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]

                        # Remove characters that may break scripts
                        charList = [".", '"', "'", "\\n"]
                        for char in charList:
                            translatedText = translatedText.replace(char, "")

                        jaString = jaString.replace(match, translatedText)

                    # Set Data
                    translatedText = jaString
                    codeList[i]["parameters"][j] = translatedText

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

                # If there isn't any Japanese in the text just skip
                if not re.search(LANGREGEX, jaString):
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

                # Remove any textwrap for collection
                collectString = jaString.replace("\n", " ")

                # Pass 1: collect
                if setData:
                    list324.append(collectString)
                    i += 1

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
        PBAR = pbar

        # 401
        if len(list401) > 0:
            response = translateAI(list401, "", True)
            list401TL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            if len(list401TL) != len(list401):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)

        # 122
        if len(list122) > 0:
            response = translateAI(list122, "Keep your translation as brief as possible", True)
            list122TL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            if len(list122TL) != len(list122):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)

        # 355/655
        if len(list355655) > 0:
            response = translateAI(list355655, textHistory, True)
            list355655TL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            if len(list355655TL) != len(list355655):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)

        # 108
        if len(list108) > 0:
            response = translateAI(list108, "This text is a label. Use title capitalization and keep it brief.", True)
            list108TL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            if len(list108TL) != len(list108):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)

        # 356
        if len(list356) > 0:
            response = translateAI(list356, textHistory, True)
            list356TL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            if len(list356TL) != len(list356):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)

        # 357
        if len(list357) > 0:
            response = translateAI(list357, textHistory, True)
            list357TL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            if len(list357TL) != len(list357):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)

        # 408
        if len(list408) > 0:
            response = translateAI(list408, "", True)
            list408TL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            if len(list408TL) != len(list408):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)

        # 324
        if len(list324) > 0:
            # Generic short-text translation for parameter index 1
            response = translateAI(list324, "Reply with only the " + LANGUAGE + " translation of the text.", True)
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
            response = translateAI(list325, "Reply with the " + LANGUAGE + " translation of the NPC name.", True)
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
    batch_map = []  # [(field_type, field_name, needs_taro_prefix), ...]
    
    # Name
    if "name" in state and state["name"]:
        batch_texts.append(state["name"])
        batch_map.append(("name", "name", False))
    
    # Description
    if "description" in state and state["description"]:
        batch_texts.append(state["description"])
        batch_map.append(("description", "description", False))
    
    # Messages - collect all with Taro prefix handling
    for msg_field in ["message1", "message2", "message3", "message4"]:
        if msg_field in state and state[msg_field]:
            msg_text = state[msg_field]
            needs_taro = len(msg_text) > 0 and msg_text[0] in ["は", "を", "の", "に", "が"]
            if needs_taro:
                batch_texts.append("Taro" + msg_text)
            else:
                batch_texts.append(msg_text)
            batch_map.append(("message", msg_field, needs_taro))
    
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
        for idx, (field_type, field_name, needs_taro) in enumerate(batch_map):
            if idx < len(translated_batch):
                translation = translated_batch[idx]
                if field_type == "name":
                    nameResponse = [translation, [0, 0]]
                elif field_type == "description":
                    descriptionResponse = [translation, [0, 0]]
                elif field_type == "message":
                    response_obj = [translation, [0, 0]]
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
        (r"(.+)", True),
    ]
    notesBatch = []
    notesBatchMap = []
    if "note" in state and state["note"]:
        note = state["note"]
        for regex, wordwrap in note_regexes:
            matches = re.findall(regex, note, re.DOTALL)
            for m in matches:
                match_text = m if isinstance(m, str) else m[0]
                notesBatch.append(match_text)
                notesBatchMap.append((regex, match_text, wordwrap))

    # --- Batch translate all notes ---
    translatedNotesBatch = []
    if notesBatch:
        response = translateAI(notesBatch, f"Reply with only the {LANGUAGE} translation of the note text.", True)
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
    context = "Reply with only the " + LANGUAGE + ' translation of the UI textbox."'

    # Title - batch as a single-item list
    response = translateAI(
        [data["gameTitle"]],
        " Reply with the " + LANGUAGE + " translation of the game title name",
        False,
    )
    totalTokens[0] += response[1][0]
    totalTokens[1] += response[1][1]
    data["gameTitle"] = response[0][0].strip(".")
    if pbar is not None:
        pbar.refresh()

    # Terms - batch translate all term items
    for term in data["terms"]:
        if term != "messages":
            termList = data["terms"][term]
            term_values = []
            term_indices = []
            for i in range(len(termList)):
                if termList[i] is not None:
                    term_values.append(termList[i])
                    term_indices.append(i)
            
            if term_values:
                response = translateAI(term_values, context, False)
                totalTokens[0] += response[1][0]
                totalTokens[1] += response[1][1]
                tl_list = response[0]
                
                for n, idx in enumerate(term_indices[: len(tl_list)]):
                    termList[idx] = tl_list[n].replace('"', "").strip()
                
                if pbar is not None:
                    pbar.refresh()

    # Armor Types - batch translate all
    armor_values = [data["armorTypes"][i] for i in range(len(data["armorTypes"]))]
    if armor_values:
        response = translateAI(
            armor_values,
            "Reply with only the " + LANGUAGE + " translation of the armor type",
            False,
        )
        totalTokens[0] += response[1][0]
        totalTokens[1] += response[1][1]
        tl_list = response[0]
        for i in range(min(len(tl_list), len(data["armorTypes"]))):
            data["armorTypes"][i] = tl_list[i].replace('"', "").strip()
        if pbar is not None:
            pbar.refresh()

    # Skill Types - batch translate all
    skill_values = [data["skillTypes"][i] for i in range(len(data["skillTypes"]))]
    if skill_values:
        response = translateAI(
            skill_values,
            "Reply with only the " + LANGUAGE + " translation",
            False,
        )
        totalTokens[0] += response[1][0]
        totalTokens[1] += response[1][1]
        tl_list = response[0]
        for i in range(min(len(tl_list), len(data["skillTypes"]))):
            data["skillTypes"][i] = tl_list[i].replace('"', "").strip()
        if pbar is not None:
            pbar.refresh()

    # Equip Types - batch translate all
    equip_values = [data["equipTypes"][i] for i in range(len(data["equipTypes"]))]
    if equip_values:
        response = translateAI(
            equip_values,
            "Reply with only the " + LANGUAGE + " translation of the equipment type. No disclaimers.",
            False,
        )
        totalTokens[0] += response[1][0]
        totalTokens[1] += response[1][1]
        tl_list = response[0]
        for i in range(min(len(tl_list), len(data["equipTypes"]))):
            data["equipTypes"][i] = tl_list[i].replace('"', "").strip()
        if pbar is not None:
            pbar.refresh()

    # Elements - batch translate all (skip empty)
    element_values = []
    element_indices = []
    for i in range(len(data["elements"])):
        if data["elements"][i]:  # Skip empty strings
            element_values.append(data["elements"][i])
            element_indices.append(i)
    
    if element_values:
        response = translateAI(
            element_values,
            "Reply with only the " + LANGUAGE + " translation of the element type",
            False,
        )
        totalTokens[0] += response[1][0]
        totalTokens[1] += response[1][1]
        tl_list = response[0]
        for n, idx in enumerate(element_indices[: len(tl_list)]):
            data["elements"][idx] = tl_list[n].replace('"', "").strip()
        if pbar is not None:
            pbar.refresh()

    # Weapon Types - batch translate all (skip empty)
    weapon_values = []
    weapon_indices = []
    for i in range(len(data["weaponTypes"])):
        if data["weaponTypes"][i]:  # Skip empty strings
            weapon_values.append(data["weaponTypes"][i])
            weapon_indices.append(i)
    
    if weapon_values:
        response = translateAI(
            weapon_values,
            "Reply with only the " + LANGUAGE + " translation of the weapon type",
            False,
        )
        totalTokens[0] += response[1][0]
        totalTokens[1] += response[1][1]
        tl_list = response[0]
        for n, idx in enumerate(weapon_indices[: len(tl_list)]):
            data["weaponTypes"][idx] = tl_list[n].replace('"', "").strip()
        if pbar is not None:
            pbar.refresh()

    # Variables (Optional usually) — batch translate to reduce calls
    if TLSYSTEMVARIABLES and "variables" in data and isinstance(data["variables"], list):
        var_indices = []
        var_values = []
        for idx, val in enumerate(data["variables"]):
            if isinstance(val, str) and val.strip():
                var_indices.append(idx)
                var_values.append(val)
        if var_values:
            response = translateAI(
                var_values,
                'Reply with only the ' + LANGUAGE + ' translation of the title',
                True,
            )
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            tl_list = response[0]
            # Assign back translations to corresponding indices
            for n, idx in enumerate(var_indices[: len(tl_list)]):
                data["variables"][idx] = tl_list[n].replace('"', '').strip()
            if pbar is not None:
                pbar.refresh()

    # Messages — batch translate to reduce calls
    messages = data["terms"]["messages"]
    if messages:
        msg_keys = []
        msg_values = []
        for key, value in messages.items():
            if isinstance(value, str) and value.strip():
                msg_keys.append(key)
                msg_values.append(value)
        
        if msg_values:
            response = translateAI(
                msg_values,
                "Reply with only the "
                + LANGUAGE
                + ' translation of the battle text.\nTranslate "常時ダッシュ" as "Always Dash"\nTranslate "次の%1まで" as Next %1.',
                False,
            )
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            tl_list = response[0]
            
            # Remove characters that may break scripts
            charList = [".", '"', "\\n"]
            
            # Assign back translations to corresponding keys
            for n, key in enumerate(msg_keys[: len(tl_list)]):
                translatedText = tl_list[n]
                for char in charList:
                    translatedText = translatedText.replace(char, "")
                messages[key] = translatedText
            
            if pbar is not None:
                pbar.refresh()

    return totalTokens

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

    if SPEAKER_PARSE_MODE:
        with _speakerCacheLock:
            if speaker in _speakerCache:
                return [_speakerCache[speaker], [0, 0]]
            if speaker not in SPEAKER_COLLECTED:
                SPEAKER_COLLECTED.append(speaker)
        return [speaker, [0, 0]]

    # Normal mode translation path
    with _speakerCacheLock:
        cached = _speakerCache.get(speaker)
        if cached is not None:
            return [cached, [0, 0]]

    try:
        THREAD_CTX.in_speaker = True
    except Exception:
        pass
    response = translateAI(
        speaker,
        "Reply with the " + LANGUAGE + " translation of the NPC name.",
        False,
    )
    try:
        THREAD_CTX.in_speaker = False
    except Exception:
        pass
    translated = response[0].title().replace("'S", "'s").replace("Speaker: ", "")

    if re.search(r"([a-zA-Z？?])", translated) is None:
        try:
            THREAD_CTX.in_speaker = True
        except Exception:
            pass
        response = translateAI(
            speaker,
            "Reply with the " + LANGUAGE + " translation of the NPC name.",
            False,
        )
        try:
            THREAD_CTX.in_speaker = False
        except Exception:
            pass
        translated = response[0].title().replace("'S", "'s")

    with _speakerCacheLock:
        if speaker not in _speakerCache:
            _speakerCache[speaker] = translated
            NAMESLIST.append([speaker, translated])
    return [translated, response[1]]

def translateAI(text, history, fullPromptFlag):
    """
    Legacy wrapper function for the new shared translation utility.
    This maintains compatibility with existing code while using the new shared implementation.
    """
    global PBAR, MISMATCH, FILENAME
    
    # Update config estimate mode based on global ESTIMATE
    TRANSLATION_CONFIG.estimateMode = bool(ESTIMATE)
    
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

    return sharedtranslateAI(
        text=text,
        history=history,
        fullPromptFlag=fullPromptFlag,
        config=TRANSLATION_CONFIG,
        filename=tl_filename,
        pbar=PBAR,
        lock=LOCK,
        mismatchList=MISMATCH
    )

def setSpeakerParseMode(flag: bool):
    """Enable/disable speaker-only parse mode."""
    global SPEAKER_PARSE_MODE
    SPEAKER_PARSE_MODE = bool(flag)

def finalizeSpeakerParse():
    """Batch translate collected speakers and write fresh # Speakers section."""
    if not SPEAKER_PARSE_MODE:
        return
    try:
        # Step 1: batch translate any collected speakers not already translated
        to_translate = []
        with _speakerCacheLock:
            for s in SPEAKER_COLLECTED:
                if s not in _speakerCache and s != "":
                    to_translate.append(s)
        if to_translate:
            try:
                THREAD_CTX.in_speaker = True
            except Exception:
                pass
            resp = translateAI(
                to_translate,
                "Reply with the " + LANGUAGE + " translation of the NPC name.",
                True,
            )
            try:
                THREAD_CTX.in_speaker = False
            except Exception:
                pass
            # Record token usage so it appears in the TOTAL string
            try:
                with LOCK:
                    TOKENS[0] += resp[1][0]
                    TOKENS[1] += resp[1][1]
            except Exception:
                pass
            # Emit a one-time summary line for speaker translation using the same format
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
            tl_list = resp[0]
            with _speakerCacheLock:
                for orig, tl in zip(to_translate, tl_list):
                    norm = tl.title().replace("'S", "'s").replace("Speaker: ", "")
                    if re.search(r"([a-zA-Z？?])", norm) is None:
                        norm = tl  # keep raw if heuristic fails
                    if orig not in _speakerCache:
                        _speakerCache[orig] = norm
                        NAMESLIST.append([orig, norm])

        vocab_path = Path("vocab.txt")
        if not vocab_path.exists():
            return
        content = vocab_path.read_text(encoding="utf-8")

        seen = set()
        lines = []
        for orig, tl in NAMESLIST:
            if not orig or not tl:
                continue
            if orig in seen:
                continue
            seen.add(orig)
            lines.append(f"{orig} ({tl})")
        if not lines:
            return
        section_block = "# Speakers\n" + "\n".join(lines) + "\n\n"

        speakers_pattern = re.compile(r"^[\t ]*#+\s*Speakers\s*$\r?\n.*?(?=^[\t ]*#|\Z)", re.MULTILINE | re.DOTALL)
        content = speakers_pattern.sub("", content)

        game_char_header = re.compile(r"^[\t ]*#\s*Game Characters\s*$", re.MULTILINE)
        match_gc = game_char_header.search(content)
        if match_gc:
            subsequent_headers = list(re.finditer(r"^[\t ]*#\s+.*$", content[match_gc.end():], re.MULTILINE))
            if subsequent_headers:
                insert_index = match_gc.end() + subsequent_headers[0].start()
            else:
                insert_index = len(content)
        else:
            insert_index = 0

        before = content[:insert_index]
        after = content[insert_index:]
        if not before.endswith("\n\n"):
            if not before.endswith("\n"):
                before += "\n"
            before += "\n"
        new_content = before + section_block + after.lstrip("\n")

        tmp_path = vocab_path.with_suffix(vocab_path.suffix + f".{os.getpid()}.{threading.get_ident()}.tmp")
        tmp_path.write_text(new_content, encoding="utf-8")
        try:
            os.replace(tmp_path, vocab_path)
        except Exception:
            try:
                shutil.move(str(tmp_path), str(vocab_path))
            except Exception:
                pass
    except Exception:
        traceback.print_exc()
