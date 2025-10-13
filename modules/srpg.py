# Libraries
import json
import os
import re
import shutil
import util.dazedwrap as dazedwrap
import threading
import time
import traceback
import openai
from pathlib import Path
from colorama import Fore
from dotenv import load_dotenv
from retry import retry
from tqdm import tqdm
from util.translation import TranslationConfig, translateAI as sharedtranslateAI, getPricingConfig, calculateCost

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
LANGREGEX = r"[\u3000-\u303F\u3040-\u309F\u30A0-\u30FF\u31F0-\u31FF\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\uFF00-\uFF5D\uFF5F-\uFFEF]+"

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
    "bonuses",
    "base",
    "battleprep",
    "manage",
    "mapcommands",
    "title",
    "placeevents",
    "talkevents",
    "characters",
    "glossary",
    
    # Add more file patterns here, e.g.:
    # "items",
    # "skills",
    # "classes",
]


def update_vocab_section(category: str, pairs: list[tuple[str, str]]):
    """Update or insert a section in vocab.txt for the given category with provided pairs.
    Only writes when there's an actual translation (dst is non-empty and differs from src after normalization).
    - category: e.g., "Items", "Weapons", "Speakers", etc. Section header will be "# {category}".
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
        # Check if filename matches any pattern in GENERIC_FILES
        elif any(pattern in filename.lower() for pattern in GENERIC_FILES):
            translatedData = parseGeneric(data, filename)
        
        # TODO: Add other SRPG Studio file types here
        else:
            raise NameError(filename + " Not Supported")

    return translatedData


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
    
    try:
        # Count work units (all translatable fields that need translation)
        total_units = 0
        translatable_fields = ["name", "desc", "commandName", "command"]
        
        for entry in data:
            if entry:
                for field in translatable_fields:
                    if field in entry and entry[field]:
                        total_units += 1
                
                # Handle pages array separately
                if "pages" in entry and entry["pages"] and isinstance(entry["pages"], list):
                    for page in entry["pages"]:
                        if page:
                            total_units += 1
        
        # Setup progress bar
        with LOCK:
            PBAR = tqdm(
                desc=filename,
                total=total_units,
                bar_format=BAR_FORMAT,
                position=POSITION,
                leave=LEAVE,
            )
        
        # Translate the data using two-pass approach
        result = translateGeneric(data, filename)
        totalTokens[0] += result[0]
        totalTokens[1] += result[1]
        
        # Close progress bar
        with LOCK:
            if PBAR:
                PBAR.close()
                PBAR = None
        
        return (data, totalTokens, None)
        
    except Exception as e:
        traceback.print_exc()
        if PBAR:
            with LOCK:
                PBAR.close()
                PBAR = None
        return (data, totalTokens, e)


def translateGeneric(data, filename, translatedDataList=None):
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
    else:
        # PASS 2: Use provided translated lists
        nameList = translatedDataList[0]
        descList = translatedDataList[1]
        commandNameList = translatedDataList[2]
        commandList = translatedDataList[3]
        pagesList = translatedDataList[4]
    
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
                descList.append(entry["desc"])
            # PASS 2: Apply translation
            else:
                if descList:
                    entry["desc"] = descList[0]
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
        
        # Handle command field
        if "command" in entry and entry["command"]:
            # PASS 1: Collect original
            if translatedDataList is None:
                commandList.append(entry["command"])
            # PASS 2: Apply translation
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
    
    # If this was Pass 1, do the translation and recurse for Pass 2
    if translatedDataList is None:
        # Store original counts for mismatch checking
        originalNameCount = len(nameList)
        originalDescCount = len(descList)
        originalCommandNameCount = len(commandNameList)
        originalCommandCount = len(commandList)
        originalPagesCount = len(pagesList)
        
        # Keep a copy of original names for vocab update (for characters.json)
        originalNameList = nameList.copy() if "characters" in filename.lower() else []
        
        # Batch translate names
        if nameList:
            response = translateAI(
                nameList,
                "Reply with only the " + LANGUAGE + " translation of the quest name.",
                True
            )
            nameList = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
        
        # Update vocab.txt for characters.json
        if "characters" in filename.lower() and originalNameList and nameList:
            try:
                # Create pairs of (original, translated) for vocab
                vocab_pairs = list(zip(originalNameList, nameList))
                update_vocab_section("Speakers", vocab_pairs)
            except Exception:
                traceback.print_exc()
        
        # Batch translate descriptions
        if descList:
            response = translateAI(
                descList,
                "Reply with only the " + LANGUAGE + " translation of the quest description.",
                True
            )
            descList = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
        
        # Batch translate command names
        if commandNameList:
            response = translateAI(
                commandNameList,
                "Reply with only the " + LANGUAGE + " translation of the command name.",
                True
            )
            commandNameList = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
        
        # Batch translate commands
        if commandList:
            response = translateAI(
                commandList,
                "Reply with only the " + LANGUAGE + " translation of the command.",
                True
            )
            commandList = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
        
        # Batch translate pages
        if pagesList:
            response = translateAI(
                pagesList,
                "Reply with only the " + LANGUAGE + " translation of the page content.",
                True
            )
            pagesList = response[0]
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
        
        # PASS 2: Recursively call to apply translations
        translateGeneric(data, filename, [nameList, descList, commandNameList, commandList, pagesList])
    
    return totalTokens


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
    
    try:
        # Count work units (data entries and speakers that need translation)
        total_units = 0
        
        # Iterate through structure and count
        for entry in data:
            if not entry or "pages" not in entry or not isinstance(entry["pages"], list):
                continue
            
            for page in entry["pages"]:
                if not page or "commands" not in page or not isinstance(page["commands"], list):
                    continue
                
                for command in page["commands"]:
                    if not command:
                        continue
                    
                    # Count data array items
                    if "data" in command and isinstance(command["data"], list):
                        for text in command["data"]:
                            if text and re.search(LANGREGEX, text):
                                total_units += 1
                    
                    # Count speaker field
                    if "speaker" in command and command["speaker"]:
                        if re.search(LANGREGEX, command["speaker"]):
                            total_units += 1
        
        # Setup progress bar
        with LOCK:
            PBAR = tqdm(
                desc=filename,
                total=total_units,
                bar_format=BAR_FORMAT,
                position=POSITION,
                leave=LEAVE,
            )
        
        # Translate the data using two-pass approach
        result = translateRecollection(data, filename)
        totalTokens[0] += result[0]
        totalTokens[1] += result[1]
        
        # Close progress bar
        with LOCK:
            if PBAR:
                PBAR.close()
                PBAR = None
        
        return (data, totalTokens, None)
        
    except Exception as e:
        traceback.print_exc()
        if PBAR:
            with LOCK:
                PBAR.close()
                PBAR = None
        return (data, totalTokens, e)


def translateRecollection(data, filename, translatedDataList=None):
    """
    Translates recollection.json data structure.
    Uses two-pass approach via recursion:
    - Pass 1 (translatedDataList=None): Collect strings and batch translate
    - Pass 2 (translatedDataList set): Apply translations back to the data
    
    Args:
        data: List of objects with pages->commands->data structure
        filename: Name of the file being translated
        translatedDataList: List containing [dataList, speakerList] 
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
        dataList = []
        speakerList = []
        originalSpeakerList = []  # For vocab update
    else:
        # PASS 2: Use provided translated lists
        dataList = translatedDataList[0]
        speakerList = translatedDataList[1]
    
    # Single loop - behavior depends on which pass we're in
    for entry in data:
        if not entry or "pages" not in entry:
            continue
        
        if not isinstance(entry["pages"], list):
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
                                    if speaker:
                                        match = re.search(r'(^\[.+?\]\s?[|:]\s?)', translated)
                                        if match:
                                            translated = translated.replace(match.group(1), "")
                                    
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
        originalDataCount = len(dataList)
        originalSpeakerCount = len(speakerList)
        
        # Batch translate data text
        if dataList:
            response = translateAI(
                dataList,
                "Reply with only the " + LANGUAGE + " translation of the dialogue text.",
                True
            )
            dataList = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
        
        # Batch translate speakers
        if speakerList:
            response = translateAI(
                speakerList,
                "Reply with only the " + LANGUAGE + " translation of the speaker name.",
                True
            )
            speakerList = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
        
        # Check for mismatch errors
        if len(dataList) != originalDataCount:
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)
        
        if len(speakerList) != originalSpeakerCount:
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)
        
        # PASS 2: Recursively call to apply translations
        translateRecollection(data, filename, [dataList, speakerList])
    
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


def translateAI(text, history, fullPromptFlag):
    """
    Legacy wrapper function for the new shared translation utility.
    This maintains compatibility with existing code while using the new shared implementation.
    
    Args:
        text: Text to translate (can be string or list)
        history: History/context for the translation
        fullPromptFlag: Whether to use the full prompt with vocab
    
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
        fullPromptFlag=fullPromptFlag,
        config=TRANSLATION_CONFIG,
        filename=FILENAME,
        pbar=PBAR,
        lock=LOCK,
        mismatchList=MISMATCH
    )

