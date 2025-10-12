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

        # TODO: Add specific file type detection and parsing
        # For now, return a basic structure
        # This will be expanded based on SRPG Studio file formats
        
        # Placeholder - you'll need to implement specific parsers
        # based on SRPG Studio's actual file structure
        translatedData = parseGeneric(data, filename)

    return translatedData


def parseGeneric(data, filename):
    """
    Generic parser for SRPG Studio files.
    This is a placeholder that should be replaced with specific parsers.
    
    Args:
        data: Parsed JSON data
        filename: Name of the file being parsed
    
    Returns:
        Tuple of (data, token counts, error)
    """
    global ESTIMATE, TOKENS
    
    totalTokens = [0, 0]
    totalLines = 0
    
    try:
        # TODO: Implement actual parsing logic based on SRPG Studio format
        # This is a placeholder structure
        tqdm.write(f"Parsing {filename}...")
        
        # For now, just return the data unchanged
        return (data, totalTokens, None)
        
    except Exception as e:
        traceback.print_exc()
        return (data, totalTokens, e)


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

