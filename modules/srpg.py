# Libraries
import json
import os
import re
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

        # Quests File
        if "quests" in filename.lower():
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
        # Count work units (name and desc fields that need translation)
        total_units = 0
        for entry in data:
            if entry and "name" in entry and entry["name"] and re.search(LANGREGEX, entry["name"]):
                total_units += 1
            if entry and "desc" in entry and entry["desc"] and re.search(LANGREGEX, entry["desc"]):
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
    Translates generic SRPG Studio data with id, name, desc structure.
    Uses two-pass approach via recursion:
    - Pass 1 (translatedDataList=None): Collect strings and batch translate
    - Pass 2 (translatedDataList set): Apply translations back to the data
    
    Args:
        data: List of objects with id, name, desc keys
        filename: Name of the file being translated
        translatedDataList: List containing [nameList, descList] 
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
    else:
        # PASS 2: Use provided translated lists
        nameList = translatedDataList[0]
        descList = translatedDataList[1]
    
    # Single loop - behavior depends on which pass we're in
    for entry in data:
        if not entry:
            continue
        
        # Handle name field
        if "name" in entry and entry["name"] and re.search(LANGREGEX, entry["name"]):
            # PASS 1: Collect original
            if translatedDataList is None:
                nameList.append(entry["name"])
            # PASS 2: Apply translation
            else:
                if nameList:
                    entry["name"] = nameList[0]
                    nameList.pop(0)
        
        # Handle desc field
        if "desc" in entry and entry["desc"] and re.search(LANGREGEX, entry["desc"]):
            # PASS 1: Collect original
            if translatedDataList is None:
                descList.append(entry["desc"])
            # PASS 2: Apply translation
            else:
                if descList:
                    entry["desc"] = descList[0]
                    descList.pop(0)
    
    # If this was Pass 1, do the translation and recurse for Pass 2
    if translatedDataList is None:
        # Store original counts for mismatch checking
        originalNameCount = len(nameList)
        originalDescCount = len(descList)
        
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
        
        # Check for mismatch errors
        if len(nameList) != originalNameCount:
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)
        
        if len(descList) != originalDescCount:
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)
        
        # PASS 2: Recursively call to apply translations
        translateGeneric(data, filename, [nameList, descList])
    
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

