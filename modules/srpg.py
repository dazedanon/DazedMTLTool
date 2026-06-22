# Libraries
import json
import os
import re
import shutil
import util.dazedwrap as dazedwrap
import threading
import time
import traceback
from dotenv import load_dotenv
from pathlib import Path
from colorama import Fore
from dotenv import load_dotenv
from retry import retry
from tqdm import tqdm
from util.translation import TranslationConfig, translateAI as sharedtranslateAI, getPricingConfig, calculateCost
from util.speaker_prefix import strip_speaker_prefix

# Globals
MODEL = os.getenv("model")
TIMEOUT = int(os.getenv("timeout"))
LANGUAGE = os.getenv("language").capitalize()
from util.paths import PROMPT_PATH, VOCAB_PATH

PROMPT = PROMPT_PATH.read_text(encoding="utf-8")
VOCAB = VOCAB_PATH.read_text(encoding="utf-8")
LOCK = threading.Lock()
VOCAB_LOCK = threading.Lock()  # Dedicated lock for vocab.txt updates
WIDTH = int(os.getenv("width"))
LISTWIDTH = int(os.getenv("listWidth"))
NOTEWIDTH = int(os.getenv("noteWidth"))
MAXHISTORY = 10
ESTIMATE = ""
TOKENS = [0, 0]
MISMATCH = []  # Lists files that throw a mismatch error (Length of GPT list response is wrong)
NAMESLIST = []  # List of speaker names and their translations
PBAR = None
FILENAME = None
TIMETOTAL = 0  # Total Time Taken for all translations

# Regex - Need to change this if you want to translate from/to other languages. Default is Japanese Regex
LANGREGEX = r"[\u3000-\u303F\u3040-\u309F\u30A0-\u30FF\u31F0-\u31FF\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\uFF61-\uFF9F]+"

# Get pricing configuration based on the model
PRICING_CONFIG = getPricingConfig(MODEL)
INPUTAPICOST = PRICING_CONFIG["inputAPICost"]
OUTPUTAPICOST = PRICING_CONFIG["outputAPICost"]
BATCHSIZE = PRICING_CONFIG["batchSize"]
FREQUENCY_PENALTY = PRICING_CONFIG["frequencyPenalty"]

# tqdm Globals
BAR_FORMAT = "{l_bar}{bar:10}{r_bar}{bar:-10b}"
POSITION = 0
LEAVE = False

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

# Config (Default)
FIXTEXTWRAP = True  # Rewrap text to WIDTH
IGNORETLTEXT = False  # Skip Translated Text

# List of file patterns that use parseGeneric
# Add more patterns here as needed
GENERIC_FILES = [
    "quests",
    "shops",
    "shoplayout",
    "bonuses",
    "base",
    "battleprep",
    "manage",
    "mapcommands",
    "title",
    "classes",
    "classesgroups",
    "classtypes",
    "races",
    "skills",
    "weapons",
    "states",
    "difficulties",
    "fonts",
    "fusionsettings",
    "transformations",
    "characters",
    "glossary",
    "npc",
    "screens",
    "strings",
    "originalterrains",
    "runtimeterrains",
    "archers",
    "fighters",
    "mages",
    "items",
]

# List of file patterns that use parseMap
# Be specific to avoid catching non-map files like CommandLayout/mapcommands.json
# SRPG Studio map files in this project follow the pattern Maps/map_XXX.json
MAP_FILES = [
    "map_",  # e.g., Maps/map_000.json
]


def update_vocab_section(category: str, pairs: list[tuple[str, str]]):
    """Update or insert a section in vocab.txt for the given category with provided pairs.
    Only writes when there's an actual translation (dst is non-empty and differs from src after normalization).
    - category: e.g., "Items", "Weapons", "Speakers", etc. Section header will be "# {category}".
    - pairs: list of (source, translated) strings. Duplicates by source are deduped (last wins).
    The existing section is replaced entirely; other sections are preserved.
    """
    try:
        vocab_path = VOCAB_PATH

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


def handleSRPG(filename, estimate):
    """
    Main handler function for SRPG Studio files.
    
    Args:
        filename: Name of the file to translate
        estimate: Boolean indicating if this is an estimate run
    
    Returns:
        String with translation results or error message
    """
    global ESTIMATE, TOKENS, FILENAME, TIMETOTAL
    ESTIMATE = estimate
    FILENAME = filename

    # Translate
    start = time.time()
    translatedData = openFiles(filename)

    # Write output file if not in estimate mode
    if not estimate:
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

    # Print any errors
    if len(MISMATCH) > 0:
        return totalString + Fore.RED + f"\nMismatch Errors: {MISMATCH}" + Fore.RESET
    else:
        return totalString


def openFiles(filename):
    """
    Opens and routes SRPG Studio files to appropriate parsing functions.
    
    Args:
        filename: Name of the file to open and parse
    
    Returns:
        Tuple of (translated data, token counts, error)
    """
    with open("files/" + filename, "r", encoding="utf-8-sig") as f:
        data = json.load(f)

        # Check if filename matches recollection pattern
        if "recollection" in filename.lower():
            translatedData = parseRecollection(data, filename)
        # mapcommonevents is a list of events like recollection
        elif "mapcommonevents" in filename.lower():
            translatedData = parseRecollection(data, filename)
        # Bookmark events use the same structure as recollection (list of events with pages/commands)
        elif "bookmarkevents" in filename.lower():
            translatedData = parseRecollection(data, filename)
        # Event files (autoevents, placeevents, talkevents, communicationevents, openingevents, endingevents)
        # all have name, desc, and pages->commands structure like recollection
        elif any(event_type in filename.lower() for event_type in ["autoevents", "placeevents", "talkevents", "communicationevents", "openingevents", "endingevents"]):
            translatedData = parseRecollection(data, filename)
        # Check if filename matches bookmark pattern (top-level entries with name/desc + events)
        elif "bookmark" in filename.lower():
            translatedData = parseBookmark(data, filename)
        # Players have the same shape as bookmark entries
        elif "players" in filename.lower():
            translatedData = parseBookmark(data, filename)
        # Titles.json is a small dict of title strings
        elif os.path.basename(filename).lower() == "titles.json":
            translatedData = parseTitles(data, filename)
        # Check if filename matches map pattern
        elif any(pattern in filename.lower() for pattern in MAP_FILES):
            translatedData = parseMap(data, filename)
        # Check if filename matches any pattern in GENERIC_FILES
        elif any(pattern in filename.lower() for pattern in GENERIC_FILES):
            translatedData = parseGeneric(data, filename)
        
        # TODO: Add other SRPG Studio file types here
        else:
            raise NameError(filename + " Not Supported")

    return translatedData


def parseBookmark(data, filename):
    """
    Parser for SRPG Studio bookmark.json files.
    Structure: List of entries, each with id, name, desc, and events containing pages -> commands
               where commands have data (array of strings) and optional speaker.

    Args:
        data: Parsed JSON data (list of bookmark entries)
        filename: Name of the file being parsed

    Returns:
        Tuple of (translated data, token counts, error)
    """
    global PBAR
    totalTokens = [0, 0]

    pbar = None
    try:
        # Count work units: names, descs, dialogue lines, and speakers
        total_units = 0

        for entry in data:
            if not entry:
                continue

            # name and desc
            for field in ["name", "desc"]:
                if field in entry and entry[field]:
                    total_units += 1

            # events -> pages -> commands
            if "events" in entry and isinstance(entry["events"], list):
                for event in entry["events"]:
                    if not event:
                        continue
                    
                    # Count event-level name and desc fields
                    for field in ["name", "desc"]:
                        if field in event and event[field]:
                            total_units += 1
                    
                    if "pages" not in event or not isinstance(event["pages"], list):
                        continue
                        
                    for page in event["pages"]:
                        if not page or "commands" not in page or not isinstance(page["commands"], list):
                            continue
                        for command in page["commands"]:
                            if not command:
                                continue
                            if "data" in command and isinstance(command["data"], list):
                                for text in command["data"]:
                                    if text:
                                        total_units += 1
                            if "speaker" in command and command["speaker"]:
                                total_units += 1

        # Setup progress bar
        with LOCK:
            pbar = tqdm(
                desc=filename,
                total=total_units,
                bar_format=BAR_FORMAT,
                position=POSITION,
                leave=LEAVE,
            )
            PBAR = pbar

        # Translate using two-pass approach
        result = translateBookmark(data, filename, pbar=pbar)
        totalTokens[0] += result[0]
        totalTokens[1] += result[1]

        return (data, totalTokens, None)

    except Exception as e:
        traceback.print_exc()
        return (data, totalTokens, e)
    finally:
        try:
            if pbar is not None:
                pbar.close()
        except Exception:
            pass
        PBAR = None


def translateBookmark(data, filename, translatedDataList=None, pbar=None):
    """
    Translates bookmark.json data structure.
    Two-pass approach via recursion:
    - Pass 1: Collect strings (names, descs, dialogue data with speaker prefix, speakers)
    - Pass 2: Apply translations back into data

    Returns:
        [input tokens, output tokens]
    """
    totalTokens = [0, 0]

    # Initialize or extract lists
    if translatedDataList is None:
        nameList = []
        descList = []
        dataList = []
        speakerList = []
    else:
        nameList = translatedDataList[0]
        descList = translatedDataList[1]
        dataList = translatedDataList[2]
        speakerList = translatedDataList[3]

    for entry in data:
        if not entry:
            continue

        # name
        if "name" in entry and entry["name"]:
            if translatedDataList is None:
                nameList.append(entry["name"])
            else:
                if nameList:
                    entry["name"] = nameList[0]
                    nameList.pop(0)

        # desc
        if "desc" in entry and entry["desc"]:
            if translatedDataList is None:
                # Remove newlines for translation
                descList.append(entry["desc"].replace("\n", " "))
            else:
                if descList:
                    translatedText = descList[0]
                    # Apply text wrapping
                    translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)
                    entry["desc"] = translatedText
                    descList.pop(0)

        # events -> pages -> commands
        if "events" in entry and isinstance(entry["events"], list):
            for event in entry["events"]:
                if not event:
                    continue
                
                # Handle event-level name field
                if "name" in event and event["name"]:
                    if translatedDataList is None:
                        nameList.append(event["name"])
                    else:
                        if nameList:
                            event["name"] = nameList[0]
                            nameList.pop(0)
                
                # Handle event-level desc field
                if "desc" in event and event["desc"]:
                    if translatedDataList is None:
                        # Remove newlines for translation
                        descList.append(event["desc"].replace("\n", " "))
                    else:
                        if descList:
                            translatedText = descList[0]
                            # Apply text wrapping
                            translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)
                            event["desc"] = translatedText
                            descList.pop(0)
                
                if "pages" not in event or not isinstance(event["pages"], list):
                    continue
                    
                for page in event["pages"]:
                    if not page or "commands" not in page or not isinstance(page["commands"], list):
                        continue
                    for command in page["commands"]:
                        if not command:
                            continue

                        speaker = command.get("speaker", "")

                        # data array
                        if "data" in command and isinstance(command["data"], list):
                            for i, text in enumerate(command["data"]):
                                if text:
                                    if translatedDataList is None:
                                        text = text.replace("\n", " ")
                                        if speaker:
                                            dataList.append(f"[{speaker}]: {text}")
                                        else:
                                            dataList.append(text)
                                    else:
                                        if dataList:
                                            translated = dataList[0]
                                            translated = strip_speaker_prefix(translated)
                                            translated = dazedwrap.wrapText(translated, width=WIDTH)
                                            command["data"][i] = translated
                                            dataList.pop(0)

                        # speaker field
                        if "speaker" in command and command["speaker"]:
                            if translatedDataList is None:
                                speakerList.append(command["speaker"])
                            else:
                                if speakerList:
                                    command["speaker"] = speakerList[0]
                                    speakerList.pop(0)

    # If this was Pass 1, perform translations and recurse
    if translatedDataList is None:
        originalNameCount = len(nameList)
        originalDescCount = len(descList)
        originalDataCount = len(dataList)
        originalSpeakerCount = len(speakerList)

        if nameList:
            response = translateAI(
                nameList,
                "Reply with only the " + LANGUAGE + " translation of the bookmark name.",
                True,
                filename,
                pbar,
            )
            nameList = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]

        if descList:
            response = translateAI(
                descList,
                "Reply with only the " + LANGUAGE + " translation of the bookmark description.",
                True,
                filename,
                pbar,
            )
            descList = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]

        if dataList:
            response = translateAI(
                dataList,
                "Reply with only the " + LANGUAGE + " translation of the dialogue text.",
                True,
                filename,
                pbar,
            )
            dataList = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]

        if speakerList:
            response = translateAI(
                speakerList,
                "Reply with only the " + LANGUAGE + " translation of the speaker name.",
                True,
                filename,
                pbar,
            )
            speakerList = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]

        # Mismatch checks
        if len(nameList) != originalNameCount:
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)
        if len(descList) != originalDescCount:
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)
        if len(dataList) != originalDataCount:
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)
        if len(speakerList) != originalSpeakerCount:
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)

        # PASS 2
        translateBookmark(data, filename, [nameList, descList, dataList, speakerList], pbar)

    return totalTokens


def parseGeneric(data, filename):
    """
    Generic parser for SRPG Studio files with id, name, desc structure.
    Handles files like quests.json.
    Uses a two-pass approach: first pass collects all strings to translate,
    then batch translates them, then second pass applies translations.
    
    Args:
        data: Parsed JSON data (list of objects with id, name, desc)
        filename: Name of the file being parsed
    
    Returns:
        Tuple of (data, token counts, error)
    """
    global PBAR
    
    totalTokens = [0, 0]
    
    pbar = None
    try:
        # Count work units (all translatable fields that need translation)
        total_units = 0
        translatable_fields = ["name", "desc", "commandName", "command"]
        
        for entry in data:
            if entry:
                for field in translatable_fields:
                    if field in entry and entry[field]:
                        # If command is a list (e.g., fusionsettings), count per element
                        if field == "command" and isinstance(entry[field], list):
                            total_units += sum(1 for x in entry[field] if x)
                        # Otherwise simple increment
                        elif not isinstance(entry[field], list):
                            total_units += 1
                
                # Handle pages array separately
                if "pages" in entry and entry["pages"] and isinstance(entry["pages"], list):
                    for page in entry["pages"]:
                        if page:
                            total_units += 1

                # Handle msg arrays (e.g., shoplayout)
                if "msg" in entry and isinstance(entry["msg"], list):
                    total_units += sum(1 for m in entry["msg"] if m)
                
                # Handle rewardData arrays (e.g., quests)
                if "rewardData" in entry and isinstance(entry["rewardData"], list):
                    total_units += sum(1 for r in entry["rewardData"] if r)
                
                # Handle customParameters name field (e.g., {name:'シャルロット強制売春'})
                if "customParameters" in entry and entry["customParameters"]:
                    match = re.search(r"name:\s*['\"]([^'\"]+)['\"]", entry["customParameters"])
                    if match:
                        total_units += 1
                
                # Handle terrains array (nested structure)
                if "terrains" in entry and entry["terrains"] and isinstance(entry["terrains"], list):
                    for terrain in entry["terrains"]:
                        if terrain:
                            for field in ["name", "desc"]:
                                if field in terrain and terrain[field]:
                                    total_units += 1
        
        # Setup progress bar (use a per-file instance to avoid cross-thread clashes)
        with LOCK:
            pbar = tqdm(
                desc=filename,
                total=total_units,
                bar_format=BAR_FORMAT,
                position=POSITION,
                leave=LEAVE,
            )
            PBAR = pbar
        
        # Translate the data using two-pass approach
        result = translateGeneric(data, filename, pbar=pbar)
        totalTokens[0] += result[0]
        totalTokens[1] += result[1]
        
        return (data, totalTokens, None)
    
    except Exception as e:
        traceback.print_exc()
        return (data, totalTokens, e)
    finally:
        # Ensure progress bar is closed
        try:
            if pbar is not None:
                pbar.close()
        except Exception:
            pass
        PBAR = None


def translateGeneric(data, filename, translatedDataList=None, pbar=None):
    """
    Translates generic SRPG Studio data with id, name, desc, commandName, command, pages structure.
    Uses two-pass approach via recursion:
    - Pass 1 (translatedDataList=None): Collect strings and batch translate
    - Pass 2 (translatedDataList set): Apply translations back to the data
    
    Args:
        data: List of objects with id, name, desc, commandName, command, pages keys
        filename: Name of the file being translated
        translatedDataList: List containing [nameList, descList, commandNameList, commandList, pagesList] 
                           - Pass 1: Empty lists to collect originals
                           - Pass 2: Filled lists with translations
    
    Returns:
        Tuple of [input tokens, output tokens]
    """
    global PBAR
    
    totalTokens = [0, 0]
    
    # Initialize or extract lists
    if translatedDataList is None:
        # PASS 1: Create empty lists to collect strings
        nameList = []
        descList = []
        commandNameList = []
        commandList = []
        pagesList = []
        msgList = []
        commandArrayList = []
        rewardDataList = []
        customParametersNameList = []
    else:
        # PASS 2: Use provided translated lists
        nameList = translatedDataList[0]
        descList = translatedDataList[1]
        commandNameList = translatedDataList[2]
        commandList = translatedDataList[3]
        pagesList = translatedDataList[4]
        msgList = translatedDataList[5]
        commandArrayList = translatedDataList[6]
        rewardDataList = translatedDataList[7]
        customParametersNameList = translatedDataList[8]
    
    # Single loop - behavior depends on which pass we're in
    for entry in data:
        if not entry:
            continue
        
        # Handle name field
        if "name" in entry and entry["name"]:
            # PASS 1: Collect original
            if translatedDataList is None:
                nameList.append(entry["name"])
            # PASS 2: Apply translation
            else:
                if nameList:
                    entry["name"] = nameList[0]
                    nameList.pop(0)
        
        # Handle desc field
        if "desc" in entry and entry["desc"]:
            # PASS 1: Collect original
            if translatedDataList is None:
                # Nuke Wordwrap
                descList.append(entry["desc"].replace("\n", " "))
            # PASS 2: Apply translation
            else:
                if descList:
                    translatedText = descList[0]
                    # Wordwrap
                    translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)

                    # Set Data
                    entry["desc"] = translatedText
                    descList.pop(0)
        
        # Handle commandName field
        if "commandName" in entry and entry["commandName"]:
            # PASS 1: Collect original
            if translatedDataList is None:
                commandNameList.append(entry["commandName"])
            # PASS 2: Apply translation
            else:
                if commandNameList:
                    entry["commandName"] = commandNameList[0]
                    commandNameList.pop(0)
        
        # Handle command field (string or list)
        if "command" in entry and entry["command"] is not None:
            # If list of strings
            if isinstance(entry["command"], list):
                for i, val in enumerate(entry["command"]):
                    if val:
                        if translatedDataList is None:
                            # Nuke Wrap
                            commandArrayList.append(val.replace("\n", " "))
                        else:
                            if commandArrayList:
                                translatedText = dazedwrap.wrapText(commandArrayList[0], width=WIDTH)
                                entry["command"][i] = translatedText
                                commandArrayList.pop(0)
            # If simple string
            elif isinstance(entry["command"], str):
                if translatedDataList is None:
                    commandList.append(entry["command"])
                else:
                    if commandList:
                        entry["command"] = commandList[0]
                        commandList.pop(0)
        
        # Handle pages field (array of strings)
        if "pages" in entry and entry["pages"] and isinstance(entry["pages"], list):
            for i, page in enumerate(entry["pages"]):
                if page:
                    # PASS 1: Collect original
                    if translatedDataList is None:
                        # Nuke Wordwrap
                        page = page.replace("\n", " ")
                        pagesList.append(page)
                    # PASS 2: Apply translation
                    else:
                        if pagesList:
                            translatedText = pagesList[0]

                            # Wordwrap
                            translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)

                            # Set Data
                            entry["pages"][i] = translatedText
                            pagesList.pop(0)

        # Handle msg field (array of strings)
        if "msg" in entry and isinstance(entry["msg"], list):
            for i, val in enumerate(entry["msg"]):
                if val is not None:
                    if translatedDataList is None:
                        msgList.append(str(val).replace("\n", " "))
                    else:
                        if msgList:
                            translatedText = dazedwrap.wrapText(msgList[0], width=WIDTH)
                            entry["msg"][i] = translatedText
                            msgList.pop(0)
        
        # Handle rewardData field (array of strings)
        if "rewardData" in entry and isinstance(entry["rewardData"], list):
            for i, val in enumerate(entry["rewardData"]):
                if val:
                    # PASS 1: Collect original
                    if translatedDataList is None:
                        rewardDataList.append(str(val).replace("\n", " "))
                    # PASS 2: Apply translation
                    else:
                        if rewardDataList:
                            translatedText = rewardDataList[0]
                            # Set Data (no wordwrap for reward data)
                            entry["rewardData"][i] = translatedText
                            rewardDataList.pop(0)
        
        # Handle customParameters name field (e.g., {name:'シャルロット強制売春'})
        if "customParameters" in entry and entry["customParameters"]:
            match = re.search(r"name:\s*['\"]([^'\"]+)['\"]", entry["customParameters"])
            if match:
                # PASS 1: Collect original
                if translatedDataList is None:
                    customParametersNameList.append(match.group(1))
                # PASS 2: Apply translation
                else:
                    if customParametersNameList:
                        translatedName = customParametersNameList[0]
                        # Replace the name value in customParameters
                        entry["customParameters"] = re.sub(
                            r"(name:\s*['\"])([^'\"]+)(['\"])",
                            r"\1" + translatedName.replace("\\", "\\\\") + r"\3",
                            entry["customParameters"]
                        )
                        customParametersNameList.pop(0)
        
        # Handle terrains field (nested array with name and desc)
        if "terrains" in entry and entry["terrains"] and isinstance(entry["terrains"], list):
            for terrain in entry["terrains"]:
                if not terrain:
                    continue
                
                # Handle terrain name
                if "name" in terrain and terrain["name"]:
                    # PASS 1: Collect original
                    if translatedDataList is None:
                        nameList.append(terrain["name"])
                    # PASS 2: Apply translation
                    else:
                        if nameList:
                            terrain["name"] = nameList[0]
                            nameList.pop(0)
                
                # Handle terrain desc
                if "desc" in terrain and terrain["desc"]:
                    # PASS 1: Collect original
                    if translatedDataList is None:
                        descList.append(terrain["desc"]).replace("\n", " ")
                    # PASS 2: Apply translation
                    else:
                        if descList:
                            translatedText = descList[0]
                            # Wordwrap
                            translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)
                            
                            # Set Data
                            terrain["desc"] = translatedText
                            descList.pop(0)
    
    # If this was Pass 1, do the translation and recurse for Pass 2
    if translatedDataList is None:
        # Store original counts for mismatch checking
        originalNameCount = len(nameList)
        originalDescCount = len(descList)
        originalCommandNameCount = len(commandNameList)
        originalCommandCount = len(commandList)
        originalPagesCount = len(pagesList)
        originalMsgCount = len(msgList)
        originalCommandArrayCount = len(commandArrayList)
        originalRewardDataCount = len(rewardDataList)
        originalCustomParametersNameCount = len(customParametersNameList)
        
        # Keep a copy of original names for vocab update (for characters/items/skills/classes/weapons)
        vocab_name_files = ["characters", "items", "skills", "classes", "weapons"]
        originalNameList = nameList.copy() if any(tag in filename.lower() for tag in vocab_name_files) else []
        
        # Batch translate names
        if nameList:
            response = translateAI(
                nameList,
                "Reply with only the " + LANGUAGE + " translation of the quest name.",
                True,
                filename,
                pbar
            )
            nameList = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
        
        # Update vocab.txt for name-bearing files
        if originalNameList and nameList:
            try:
                file_lower = filename.lower()
                section = None
                if "characters" in file_lower:
                    section = "Speakers"
                elif "items" in file_lower:
                    section = "Items"
                elif "skills" in file_lower:
                    section = "Skills"
                elif "classes" in file_lower:
                    section = "Classes"
                elif "weapons" in file_lower:
                    section = "Weapons"

                if section:
                    vocab_pairs = list(zip(originalNameList, nameList))
                    update_vocab_section(section, vocab_pairs)
            except Exception:
                traceback.print_exc()
        
        # Batch translate descriptions
        if descList:
            response = translateAI(
                descList,
                "Reply with only the " + LANGUAGE + " translation of the quest description.",
                True,
                filename,
                pbar
            )
            descList = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
        
        # Batch translate command names
        if commandNameList:
            response = translateAI(
                commandNameList,
                "Reply with only the " + LANGUAGE + " translation of the command name.",
                True,
                filename,
                pbar
            )
            commandNameList = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
        
        # Batch translate commands
        if commandList:
            response = translateAI(
                commandList,
                "Reply with only the " + LANGUAGE + " translation of the command.",
                True,
                filename,
                pbar
            )
            commandList = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
        
        # Batch translate pages
        if pagesList:
            response = translateAI(
                pagesList,
                "Reply with only the " + LANGUAGE + " translation of the page content.",
                True,
                filename,
                pbar
            )
            pagesList = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]

        # Batch translate msg arrays
        if msgList:
            response = translateAI(
                msgList,
                "Reply with only the " + LANGUAGE + " translation of the message text.",
                True,
                filename,
                pbar
            )
            msgList = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]

        # Batch translate command arrays
        if commandArrayList:
            response = translateAI(
                commandArrayList,
                "Reply with only the " + LANGUAGE + " translation of the command text.",
                True,
                filename,
                pbar
            )
            commandArrayList = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]

        # Batch translate rewardData arrays
        if rewardDataList:
            response = translateAI(
                rewardDataList,
                "Reply with only the " + LANGUAGE + " translation of the reward data text.",
                True,
                filename,
                pbar
            )
            rewardDataList = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]

        # Batch translate customParameters name fields
        if customParametersNameList:
            response = translateAI(
                customParametersNameList,
                "Reply with only the " + LANGUAGE + " translation of the custom parameter name.",
                True,
                filename,
                pbar
            )
            customParametersNameList = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
        
        # Check for mismatch errors
        if len(nameList) != originalNameCount:
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)
        
        if len(descList) != originalDescCount:
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)
        
        if len(commandNameList) != originalCommandNameCount:
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)
        
        if len(commandList) != originalCommandCount:
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)
        
        if len(pagesList) != originalPagesCount:
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)
        if len(msgList) != originalMsgCount:
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)
        if len(commandArrayList) != originalCommandArrayCount:
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)
        if len(rewardDataList) != originalRewardDataCount:
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)
        if len(customParametersNameList) != originalCustomParametersNameCount:
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)
        
        # PASS 2: Recursively call to apply translations
        translateGeneric(
            data,
            filename,
            [nameList, descList, commandNameList, commandList, pagesList, msgList, commandArrayList, rewardDataList, customParametersNameList],
            pbar,
        )
    
    return totalTokens


def parseTitles(data, filename):
    """Parser for titles.json (small dict of title strings)."""
    global PBAR
    totalTokens = [0, 0]
    pbar = None
    try:
        # Collect fields to translate
        keys = [k for k in ["windowTitle", "gameTitle", "saveFileTitle"] if k in data and data[k]]
        values = [data[k] for k in keys]

        with LOCK:
            pbar = tqdm(
                desc=filename,
                total=len(values),
                bar_format=BAR_FORMAT,
                position=POSITION,
                leave=LEAVE,
            )
            PBAR = pbar

        if values:
            response = translateAI(
                values,
                "Reply with only the " + LANGUAGE + " translation of the title text.",
                True,
                filename,
                pbar,
            )
            translations = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]

            # Apply
            for i, k in enumerate(keys):
                data[k] = translations[i]

        return (data, totalTokens, None)
    except Exception as e:
        traceback.print_exc()
        return (data, totalTokens, e)
    finally:
        try:
            if pbar is not None:
                pbar.close()
        except Exception:
            pass
        PBAR = None


def parseRecollection(data, filename):
    """
    Parser for SRPG Studio recollection.json files.
    Structure: List of entries, each with pages containing commands with data arrays and speakers.
    
    Args:
        data: Parsed JSON data (list of objects with id, pages structure)
        filename: Name of the file being parsed
    
    Returns:
        Tuple of (data, token counts, error)
    """
    global PBAR
    
    totalTokens = [0, 0]
    
    pbar = None
    try:
        # Count work units (data entries and speakers that need translation)
        total_units = 0
        
        # Iterate through structure and count
        for entry in data:
            if not entry:
                continue
            
            # Count name and desc fields at entry level
            for field in ["name", "desc"]:
                if field in entry and entry[field]:
                    total_units += 1
            
            # Count customParameters hints
            if "customParameters" in entry and entry["customParameters"]:
                match = re.search(r'hint:"((?:[^"\\]|\\.)*)"', entry["customParameters"])
                if match:
                    total_units += 1
            
            if "pages" not in entry or not isinstance(entry["pages"], list):
                continue
            
            for page in entry["pages"]:
                if not page or "commands" not in page or not isinstance(page["commands"], list):
                    continue
                
                for command in page["commands"]:
                    if not command:
                        continue
                    
                    # Count data array items (count any non-empty text; do not gate on LANGREGEX)
                    if "data" in command and isinstance(command["data"], list):
                        for text in command["data"]:
                            if text:
                                total_units += 1

                    # Count speaker field (count any non-empty speaker; do not gate on LANGREGEX)
                    if "speaker" in command and command["speaker"]:
                        total_units += 1
        
        # Setup progress bar (per-file instance)
        with LOCK:
            pbar = tqdm(
                desc=filename,
                total=total_units,
                bar_format=BAR_FORMAT,
                position=POSITION,
                leave=LEAVE,
            )
            PBAR = pbar
        
        # Translate the data using two-pass approach
        result = translateRecollection(data, filename, pbar=pbar)
        totalTokens[0] += result[0]
        totalTokens[1] += result[1]
        
        return (data, totalTokens, None)
    
    except Exception as e:
        traceback.print_exc()
        return (data, totalTokens, e)
    finally:
        try:
            if pbar is not None:
                pbar.close()
        except Exception:
            pass
        PBAR = None


def translateRecollection(data, filename, translatedDataList=None, pbar=None):
    """
    Translates recollection.json data structure.
    Uses two-pass approach via recursion:
    - Pass 1 (translatedDataList=None): Collect strings and batch translate
    - Pass 2 (translatedDataList set): Apply translations back to the data
    
    Args:
        data: List of objects with name, desc, customParameters, and pages->commands->data structure
        filename: Name of the file being translated
        translatedDataList: List containing [nameList, descList, dataList, speakerList, customParamsList] 
                           - Pass 1: Empty lists to collect originals
                           - Pass 2: Filled lists with translations
    
    Returns:
        Tuple of [input tokens, output tokens]
    """
    global PBAR
    
    totalTokens = [0, 0]
    
    # Initialize or extract lists
    if translatedDataList is None:
        # PASS 1: Create empty lists to collect strings
        nameList = []
        descList = []
        dataList = []
        speakerList = []
        customParamsList = []
        originalSpeakerList = []  # For vocab update
    else:
        # PASS 2: Use provided translated lists
        nameList = translatedDataList[0]
        descList = translatedDataList[1]
        dataList = translatedDataList[2]
        speakerList = translatedDataList[3]
        customParamsList = translatedDataList[4]
    
    # Single loop - behavior depends on which pass we're in
    for entry in data:
        if not entry:
            continue
        
        # Handle name field
        if "name" in entry and entry["name"]:
            # PASS 1: Collect original
            if translatedDataList is None:
                nameList.append(entry["name"])
            # PASS 2: Apply translation
            else:
                if nameList:
                    entry["name"] = nameList[0]
                    nameList.pop(0)
        
        # Handle desc field
        if "desc" in entry and entry["desc"]:
            # PASS 1: Collect original
            if translatedDataList is None:
                # Remove newlines for translation
                descList.append(entry["desc"].replace("\n", " "))
            # PASS 2: Apply translation
            else:
                if descList:
                    translatedText = descList[0]
                    # Apply text wrapping
                    translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)
                    entry["desc"] = translatedText
                    descList.pop(0)
        
        # Handle customParameters at entry level
        if "customParameters" in entry and entry["customParameters"]:
            # PASS 1: Collect hint text
            if translatedDataList is None:
                # Extract hint value using regex (captures content between hint:" and ")
                match = re.search(r'hint:"((?:[^"\\]|\\.)*)"', entry["customParameters"])
                if match:
                    hintText = match.group(1)
                    hintText = hintText.replace("\\n", " ")
                    customParamsList.append(hintText)
                else:
                    # No hint found, add empty string as placeholder
                    customParamsList.append("")
            # PASS 2: Apply translation
            else:
                if customParamsList:
                    translatedHint = customParamsList[0]
                    customParamsList.pop(0)
                    
                    if translatedHint:  # Only replace if we translated something
                        # Replace double quotes with single quotes since \" is used as delimiter
                        translatedHint = translatedHint.replace('"', "'")
                        # Wrap text using dazedwrap with WIDTH and replace newlines with \\n
                        translatedHint = dazedwrap.wrapText(translatedHint, width=WIDTH)
                        translatedHint = translatedHint.replace("\n", "\\\\n")
                        # Replace the hint value in customParameters
                        entry["customParameters"] = re.sub(
                            r'(hint:")((?:[^"\\]|\\.)*)"',
                            r'\1' + translatedHint + '"',
                            entry["customParameters"]
                        )
        
        # Check if pages exists before processing
        if "pages" not in entry or not isinstance(entry["pages"], list):
            continue
            
        for page in entry["pages"]:
            if not page or "commands" not in page:
                continue
            
            if not isinstance(page["commands"], list):
                continue
                
            for command in page["commands"]:
                if not command:
                    continue
                
                # Get the speaker for this command (if available)
                speaker = command.get("speaker", "")
                
                # Handle data array
                if "data" in command and isinstance(command["data"], list):
                    for i, text in enumerate(command["data"]):
                        if text:
                            # PASS 1: Collect original with speaker prefix
                            if translatedDataList is None:
                                # Remove Wrap
                                text = text.replace("\n", " ")

                                # Attach speaker to data for translation
                                if speaker:
                                    dataList.append(f"[{speaker}]: {text}")
                                else:
                                    dataList.append(text)

                            # PASS 2: Apply translation and strip speaker prefix
                            else:
                                if dataList:
                                    translated = dataList[0]

                                    # Remove speaker
                                    translated = strip_speaker_prefix(translated)
                                    
                                    # Textwrap
                                    translated = dazedwrap.wrapText(translated, width=WIDTH)

                                    # Set Data
                                    command["data"][i] = translated
                                    dataList.pop(0)
                
                # Handle speaker field
                if "speaker" in command and command["speaker"]:
                    # PASS 1: Collect original
                    if translatedDataList is None:
                        originalSpeakerList.append(command["speaker"])
                        speakerList.append(command["speaker"])
                    # PASS 2: Apply translation
                    else:
                        if speakerList:
                            command["speaker"] = speakerList[0]
                            speakerList.pop(0)
    
    # If this was Pass 1, do the translation and recurse for Pass 2
    if translatedDataList is None:
        # Store original counts for mismatch checking
        originalNameCount = len(nameList)
        originalDescCount = len(descList)
        originalDataCount = len(dataList)
        originalSpeakerCount = len(speakerList)
        originalCustomParamsCount = len(customParamsList)
        
        # Batch translate names
        if nameList:
            response = translateAI(
                nameList,
                "Reply with only the " + LANGUAGE + " translation of the name.",
                True,
                filename,
                pbar
            )
            nameList = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
        
        # Batch translate descriptions
        if descList:
            response = translateAI(
                descList,
                "Reply with only the " + LANGUAGE + " translation of the description.",
                True,
                filename,
                pbar
            )
            descList = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
        
        # Batch translate data text
        if dataList:
            response = translateAI(
                dataList,
                "Reply with only the " + LANGUAGE + " translation of the dialogue text.",
                True,
                filename,
                pbar
            )
            dataList = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
        
        # Batch translate speakers
        if speakerList:
            response = translateAI(
                speakerList,
                "Reply with only the " + LANGUAGE + " translation of the speaker name.",
                True,
                filename,
                pbar
            )
            speakerList = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
        
        # Batch translate customParameters hints (only non-empty ones)
        if customParamsList:
            # Filter out empty strings for translation
            hintsToTranslate = [h for h in customParamsList if h]
            if hintsToTranslate:
                response = translateAI(
                    hintsToTranslate,
                    "Reply with only the " + LANGUAGE + " translation of the hint text.",
                    True,
                    filename,
                    pbar
                )
                translatedHints = response[0]
                totalTokens[0] += response[1][0]
                totalTokens[1] += response[1][1]
                
                # Reconstruct customParamsList with translations in place
                translatedIndex = 0
                for i, hint in enumerate(customParamsList):
                    if hint:  # If it was non-empty, use the translation
                        customParamsList[i] = translatedHints[translatedIndex]
                        translatedIndex += 1
        
        # Check for mismatch errors
        if len(nameList) != originalNameCount:
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)
        
        if len(descList) != originalDescCount:
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)
        
        if len(dataList) != originalDataCount:
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)
        
        if len(speakerList) != originalSpeakerCount:
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)
        
        if len(customParamsList) != originalCustomParamsCount:
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)
        
        # PASS 2: Recursively call to apply translations
        translateRecollection(data, filename, [nameList, descList, dataList, speakerList, customParamsList], pbar)
    
    return totalTokens


def parseMap(data, filename):
    """
    Parser for SRPG Studio map.json files.
    Structure: Single object with:
      - id, name, desc, mapName
      - victoryConds (array of strings)
      - defeatConds (array of strings)
      - EnemyUnits (array of objects with id, name, desc, events structure similar to recollection)
    
    Args:
        data: Parsed JSON data (single map object)
        filename: Name of the file being parsed
    
    Returns:
        Tuple of (data, token counts, error)
    """
    global PBAR
    
    totalTokens = [0, 0]
    
    pbar = None
    try:
        # Count work units (all translatable fields)
        total_units = 0
        
        # Count top-level fields: desc, mapName (name is an identifier and should not be translated)
        for field in ["desc", "mapName"]:
            if field in data and data[field]:
                total_units += 1
        
        # Count victoryConds array items
        if "victoryConds" in data and isinstance(data["victoryConds"], list):
            for cond in data["victoryConds"]:
                if cond:
                    total_units += 1
        
        # Count defeatConds array items
        if "defeatConds" in data and isinstance(data["defeatConds"], list):
            for cond in data["defeatConds"]:
                if cond:
                    total_units += 1
        
        # Count units with events (EnemyUnits, EvEnemyUnits)
        for unitsKey in ["EnemyUnits", "EvEnemyUnits"]:
            if unitsKey in data and isinstance(data[unitsKey], list):
                for unit in data[unitsKey]:
                    if not unit:
                        continue
                    
                    # Count unit name and desc
                    for field in ["name", "desc"]:
                        if field in unit and unit[field]:
                            total_units += 1
                    
                    # Count events->pages->commands->data and speaker
                    if "events" in unit and isinstance(unit["events"], list):
                        for event in unit["events"]:
                            if not event or "pages" not in event:
                                continue
                            
                            if not isinstance(event["pages"], list):
                                continue
                            
                            for page in event["pages"]:
                                if not page or "commands" not in page:
                                    continue
                                
                                if not isinstance(page["commands"], list):
                                    continue
                                
                                for command in page["commands"]:
                                    if not command:
                                        continue
                                    
                                    # Count data array items
                                    if "data" in command and isinstance(command["data"], list):
                                        for text in command["data"]:
                                            if text:
                                                total_units += 1
                                    
                                    # Count speaker field
                                    if "speaker" in command and command["speaker"]:
                                        total_units += 1
        
        # Count events (placeEvents, autoEvents, openingEvents, communicationEvents)
        for eventsKey in ["placeEvents", "autoEvents", "openingEvents", "communicationEvents"]:
            if eventsKey in data and isinstance(data[eventsKey], list):
                for event in data[eventsKey]:
                    if not event:
                        continue
                    
                    # Count event-level name and desc fields
                    for field in ["name", "desc"]:
                        if field in event and event[field]:
                            total_units += 1
                    
                    if "pages" not in event or not isinstance(event["pages"], list):
                        continue
                    
                    for page in event["pages"]:
                        if not page or "commands" not in page:
                            continue
                        
                        if not isinstance(page["commands"], list):
                            continue
                        
                        for command in page["commands"]:
                            if not command:
                                continue
                            
                            # Count data array items
                            if "data" in command and isinstance(command["data"], list):
                                for text in command["data"]:
                                    if text:
                                        total_units += 1
                            
                            # Count speaker field
                            if "speaker" in command and command["speaker"]:
                                total_units += 1
        
        # Setup progress bar (per-file instance)
        with LOCK:
            pbar = tqdm(
                desc=filename,
                total=total_units,
                bar_format=BAR_FORMAT,
                position=POSITION,
                leave=LEAVE,
            )
            PBAR = pbar
        
        # Translate the data using two-pass approach
        result = translateMap(data, filename, pbar=pbar)
        totalTokens[0] += result[0]
        totalTokens[1] += result[1]
        
        return (data, totalTokens, None)
    
    except Exception as e:
        traceback.print_exc()
        return (data, totalTokens, e)
    finally:
        try:
            if pbar is not None:
                pbar.close()
        except Exception:
            pass
        PBAR = None


def translateMap(data, filename, translatedDataList=None, pbar=None):
    """
    Translates map.json data structure.
    Uses two-pass approach via recursion:
    - Pass 1 (translatedDataList=None): Collect strings and batch translate
    - Pass 2 (translatedDataList set): Apply translations back to the data
    
    Args:
        data: Single map object with name, desc, mapName, victoryConds, defeatConds, and EnemyUnits
        filename: Name of the file being translated
        translatedDataList: List containing translation lists
                           - Pass 1: Empty lists to collect originals
                           - Pass 2: Filled lists with translations
    
    Returns:
        Tuple of [input tokens, output tokens]
    """
    global PBAR
    
    totalTokens = [0, 0]
    
    # Initialize or extract lists
    if translatedDataList is None:
        # PASS 1: Create empty lists to collect strings
        descList = []
        mapNameList = []
        victoryCondsList = []
        defeatCondsList = []
        unitNameList = []
        unitDescList = []
        eventNameList = []
        eventDescList = []
        dataList = []
        speakerList = []
        originalSpeakerList = []  # For vocab update
    else:
        # PASS 2: Use provided translated lists
        descList = translatedDataList[0]
        mapNameList = translatedDataList[1]
        victoryCondsList = translatedDataList[2]
        defeatCondsList = translatedDataList[3]
        unitNameList = translatedDataList[4]
        unitDescList = translatedDataList[5]
        eventNameList = translatedDataList[6]
        eventDescList = translatedDataList[7]
        dataList = translatedDataList[8]
        speakerList = translatedDataList[9]
    
    # Note: name field is not translated as it's an identifier (e.g., "ch3_瘴気の森")
    
    # Handle desc field
    if "desc" in data and data["desc"]:
        # PASS 1: Collect original
        if translatedDataList is None:
            descList.append(data["desc"].replace("\n", " "))
        # PASS 2: Apply translation
        else:
            if descList:
                translatedText = descList[0]
                # Wordwrap
                translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)
                data["desc"] = translatedText
                descList.pop(0)
    
    # Handle mapName field
    if "mapName" in data and data["mapName"]:
        # PASS 1: Collect original
        if translatedDataList is None:
            mapNameList.append(data["mapName"])
        # PASS 2: Apply translation
        else:
            if mapNameList:
                data["mapName"] = mapNameList[0]
                mapNameList.pop(0)
    
    # Handle victoryConds array
    if "victoryConds" in data and isinstance(data["victoryConds"], list):
        for i, cond in enumerate(data["victoryConds"]):
            if cond:
                # PASS 1: Collect original
                if translatedDataList is None:
                    victoryCondsList.append(cond)
                # PASS 2: Apply translation
                else:
                    if victoryCondsList:
                        data["victoryConds"][i] = victoryCondsList[0]
                        victoryCondsList.pop(0)
    
    # Handle defeatConds array
    if "defeatConds" in data and isinstance(data["defeatConds"], list):
        for i, cond in enumerate(data["defeatConds"]):
            if cond:
                # PASS 1: Collect original
                if translatedDataList is None:
                    defeatCondsList.append(cond)
                # PASS 2: Apply translation
                else:
                    if defeatCondsList:
                        data["defeatConds"][i] = defeatCondsList[0]
                        defeatCondsList.pop(0)
    
    # Process all unit arrays (EnemyUnits, EvEnemyUnits)
    for unitsKey in ["EnemyUnits", "EvEnemyUnits"]:
        if unitsKey in data and isinstance(data[unitsKey], list):
            for unit in data[unitsKey]:
                if not unit:
                    continue
                
                # Handle unit name
                if "name" in unit and unit["name"]:
                    if translatedDataList is None:
                        unitNameList.append(unit["name"])
                    else:
                        if unitNameList:
                            unit["name"] = unitNameList[0]
                            unitNameList.pop(0)
                
                # Handle unit desc
                if "desc" in unit and unit["desc"]:
                    if translatedDataList is None:
                        unitDescList.append(unit["desc"].replace("\n", " "))
                    else:
                        if unitDescList:
                            translatedText = unitDescList[0]
                            # Wordwrap
                            translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)
                            unit["desc"] = translatedText
                            unitDescList.pop(0)
                
                # Process events within units
                if "events" in unit and isinstance(unit["events"], list):
                    for event in unit["events"]:
                        if not event or "pages" not in event:
                            continue
                        
                        if not isinstance(event["pages"], list):
                            continue
                        
                        for page in event["pages"]:
                            if not page or "commands" not in page:
                                continue
                            
                            if not isinstance(page["commands"], list):
                                continue
                            
                            for command in page["commands"]:
                                if not command:
                                    continue
                                
                                speaker = command.get("speaker", "")
                                
                                # Handle data array
                                if "data" in command and isinstance(command["data"], list):
                                    for i, text in enumerate(command["data"]):
                                        if text:
                                            if translatedDataList is None:
                                                text = text.replace("\n", " ")
                                                if speaker:
                                                    dataList.append(f"[{speaker}]: {text}")
                                                else:
                                                    dataList.append(text)
                                            else:
                                                if dataList:
                                                    translated = dataList[0]
                                                    translated = strip_speaker_prefix(translated)
                                                    translated = dazedwrap.wrapText(translated, width=WIDTH)
                                                    command["data"][i] = translated
                                                    dataList.pop(0)
                                
                                # Handle speaker field
                                if "speaker" in command and command["speaker"]:
                                    if translatedDataList is None:
                                        originalSpeakerList.append(command["speaker"])
                                        speakerList.append(command["speaker"])
                                    else:
                                        if speakerList:
                                            command["speaker"] = speakerList[0]
                                            speakerList.pop(0)
    
    # Process all event arrays (placeEvents, autoEvents, openingEvents, communicationEvents)
    for eventsKey in ["placeEvents", "autoEvents", "openingEvents", "communicationEvents"]:
        if eventsKey in data and isinstance(data[eventsKey], list):
            for event in data[eventsKey]:
                if not event:
                    continue
                
                # Handle event-level name field
                if "name" in event and event["name"]:
                    if translatedDataList is None:
                        eventNameList.append(event["name"])
                    else:
                        if eventNameList:
                            event["name"] = eventNameList[0]
                            eventNameList.pop(0)
                
                # Handle event-level desc field
                if "desc" in event and event["desc"]:
                    if translatedDataList is None:
                        # Remove newlines for translation
                        eventDescList.append(event["desc"].replace("\n", " "))
                    else:
                        if eventDescList:
                            translatedText = eventDescList[0]
                            # Apply text wrapping
                            translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)
                            event["desc"] = translatedText
                            eventDescList.pop(0)
                
                if "pages" not in event or not isinstance(event["pages"], list):
                    continue
                
                for page in event["pages"]:
                    if not page or "commands" not in page:
                        continue
                    
                    if not isinstance(page["commands"], list):
                        continue
                    
                    for command in page["commands"]:
                        if not command:
                            continue
                        
                        speaker = command.get("speaker", "")
                        
                        # Handle data array
                        if "data" in command and isinstance(command["data"], list):
                            for i, text in enumerate(command["data"]):
                                if text:
                                    if translatedDataList is None:
                                        text = text.replace("\n", " ")
                                        if speaker:
                                            dataList.append(f"[{speaker}]: {text}")
                                        else:
                                            dataList.append(text)
                                    else:
                                        if dataList:
                                            translated = dataList[0]
                                            translated = strip_speaker_prefix(translated)
                                            translated = dazedwrap.wrapText(translated, width=WIDTH)
                                            command["data"][i] = translated
                                            dataList.pop(0)
                        
                        # Handle speaker field
                        if "speaker" in command and command["speaker"]:
                            if translatedDataList is None:
                                originalSpeakerList.append(command["speaker"])
                                speakerList.append(command["speaker"])
                            else:
                                if speakerList:
                                    command["speaker"] = speakerList[0]
                                    speakerList.pop(0)
    
    # If this was Pass 1, do the translation and recurse for Pass 2
    if translatedDataList is None:
        # Store original counts for mismatch checking
        originalDescCount = len(descList)
        originalMapNameCount = len(mapNameList)
        originalVictoryCondsCount = len(victoryCondsList)
        originalDefeatCondsCount = len(defeatCondsList)
        originalUnitNameCount = len(unitNameList)
        originalUnitDescCount = len(unitDescList)
        originalEventNameCount = len(eventNameList)
        originalEventDescCount = len(eventDescList)
        originalDataCount = len(dataList)
        originalSpeakerCount = len(speakerList)
        
        # Batch translate map descriptions
        if descList:
            response = translateAI(
                descList,
                "Reply with only the " + LANGUAGE + " translation of the map description.",
                True,
                filename,
                pbar
            )
            descList = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
        
        # Batch translate map display names
        if mapNameList:
            response = translateAI(
                mapNameList,
                "Reply with only the " + LANGUAGE + " translation of the map display name.",
                True,
                filename,
                pbar
            )
            mapNameList = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
        
        # Batch translate victory conditions
        if victoryCondsList:
            response = translateAI(
                victoryCondsList,
                "Reply with only the " + LANGUAGE + " translation of the victory condition.",
                True,
                filename,
                pbar
            )
            victoryCondsList = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
        
        # Batch translate defeat conditions
        if defeatCondsList:
            response = translateAI(
                defeatCondsList,
                "Reply with only the " + LANGUAGE + " translation of the defeat condition.",
                True,
                filename,
                pbar
            )
            defeatCondsList = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
        
        # Batch translate unit names
        if unitNameList:
            response = translateAI(
                unitNameList,
                "Reply with only the " + LANGUAGE + " translation of the enemy unit name.",
                True,
                filename,
                pbar
            )
            unitNameList = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
        
        # Batch translate unit descriptions
        if unitDescList:
            response = translateAI(
                unitDescList,
                "Reply with only the " + LANGUAGE + " translation of the enemy unit description.",
                True,
                filename,
                pbar
            )
            unitDescList = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
        
        # Batch translate event names
        if eventNameList:
            response = translateAI(
                eventNameList,
                "Reply with only the " + LANGUAGE + " translation of the event name.",
                True,
                filename,
                pbar
            )
            eventNameList = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
        
        # Batch translate event descriptions
        if eventDescList:
            response = translateAI(
                eventDescList,
                "Reply with only the " + LANGUAGE + " translation of the event description.",
                True,
                filename,
                pbar
            )
            eventDescList = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
        
        # Batch translate dialogue data
        if dataList:
            response = translateAI(
                dataList,
                "Reply with only the " + LANGUAGE + " translation of the dialogue text.",
                True,
                filename,
                pbar
            )
            dataList = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
        
        # Batch translate speakers
        if speakerList:
            response = translateAI(
                speakerList,
                "Reply with only the " + LANGUAGE + " translation of the speaker name.",
                True,
                filename,
                pbar
            )
            speakerList = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
        
        # Check for mismatch errors
        if len(descList) != originalDescCount:
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)
        
        if len(mapNameList) != originalMapNameCount:
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)
        
        if len(victoryCondsList) != originalVictoryCondsCount:
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)
        
        if len(defeatCondsList) != originalDefeatCondsCount:
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)
        
        if len(unitNameList) != originalUnitNameCount:
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)
        
        if len(unitDescList) != originalUnitDescCount:
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)
        
        if len(eventNameList) != originalEventNameCount:
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)
        
        if len(eventDescList) != originalEventDescCount:
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)
        
        if len(dataList) != originalDataCount:
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)
        
        if len(speakerList) != originalSpeakerCount:
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)
        
        # PASS 2: Recursively call to apply translations
        translateMap(data, filename, [descList, mapNameList, victoryCondsList, defeatCondsList, unitNameList, unitDescList, eventNameList, eventDescList, dataList, speakerList], pbar)
    
    return totalTokens


def getResultString(translatedData, translationTime, filename):
    """
    Formats the translation result string with token counts, cost, and time.
    
    Args:
        translatedData: Tuple of (data, tokens, error)
        translationTime: Time taken for translation
        filename: Name of the file
    
    Returns:
        Formatted result string
    """
    global TIMETOTAL
    
    # Calculate cost
    cost = calculateCost(translatedData[1][0], translatedData[1][1], MODEL)
    totalTokenstring = (
        Fore.YELLOW + "[Input: " + str(translatedData[1][0]) + "]"
        "[Output: "
        + str(translatedData[1][1])
        + "]" "[Cost: ${:,.4f}".format(cost)
        + "]"
    )
    
    # Format time string
    if filename != "TOTAL":
        timeString = Fore.BLUE + "[" + str(round(translationTime, 1)) + "s]"
        TIMETOTAL += round(translationTime, 1)
    else:
        timeString = Fore.BLUE + "[" + str(round(TIMETOTAL, 1)) + "s]"

    # Return success or failure string
    if translatedData[2] is None:
        # Success
        return filename + ": " + totalTokenstring + timeString + Fore.GREEN + " \u2713 " + Fore.RESET
    else:
        # Fail
        try:
            raise translatedData[2]
        except Exception as e:
            traceback.print_exc()
            return (
                filename
                + ": "
                + totalTokenstring
                + timeString
                + Fore.RED
                + " \u2717 "
                + Fore.RESET
            )


def getSpeaker(speaker):
    """
    Translates speaker/character names with caching to avoid redundant translations.
    
    Args:
        speaker: The original speaker name to translate
    
    Returns:
        List containing [translated name, [input tokens, output tokens]]
    """
    if speaker == "":
        return ["", [0, 0]]
    
    # Check if speaker has already been translated
    for i in range(len(NAMESLIST)):
        if speaker == NAMESLIST[i][0]:
            return [NAMESLIST[i][1], [0, 0]]
    
    # Translate and Store Speaker
    response = translateAI(
        speaker,
        "Reply with the " + LANGUAGE + " translation of the NPC name.",
        False,
    )
    response[0] = response[0].title()
    response[0] = response[0].replace("'S", "'s")
    response[0] = response[0].replace("Speaker: ", "")
    
    # Retry if name doesn't translate for some reason
    if re.search(r"([a-zA-Z？?])", response[0]) is None:
        response = translateAI(
            speaker,
            "Reply with the " + LANGUAGE + " translation of the NPC name.",
            False,
        )
        response[0] = response[0].title()
        response[0] = response[0].replace("'S", "'s")
    
    speakerList = [speaker, response[0]]
    NAMESLIST.append(speakerList)
    return response


def translateAI(text, history, history_ctx=None, filename=None, pbar=None):
    """
    Legacy wrapper function for the new shared translation utility.
    This maintains compatibility with existing code while using the new shared implementation.
    
    Args:
        text: Text to translate (can be string or list)
        history: History/context for the translation
    
    Returns:
        List containing [translated text, [input tokens, output tokens]]
    """
    global PBAR, MISMATCH, FILENAME
    
    # Update config estimate mode based on global ESTIMATE
    TRANSLATION_CONFIG.estimateMode = bool(ESTIMATE)
    
    # Call the new shared translation function
    return sharedtranslateAI(
        text=text,
        history=history,
        config=TRANSLATION_CONFIG,
        filename=filename if filename is not None else FILENAME,
        pbar=pbar if pbar is not None else PBAR,
        lock=LOCK,
        mismatchList=MISMATCH
    )

