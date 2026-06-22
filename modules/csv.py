# Libraries
import json
import os
import re
import util.dazedwrap as dazedwrap
import threading
import time
import traceback
import tiktoken
import csv
from pathlib import Path
from colorama import Fore
from dotenv import load_dotenv
from retry import retry
from tqdm import tqdm
from util.translation import TranslationConfig, translateAI as sharedtranslateAI, getPricingConfig, calculateCost
from util.speaker_prefix import strip_speaker_prefix
import tempfile

# Globals
MODEL = os.getenv("model")
TIMEOUT = int(os.getenv("timeout"))
LANGUAGE = os.getenv("language").capitalize()
from util.paths import PROMPT_PATH, VOCAB_PATH

PROMPT = PROMPT_PATH.read_text(encoding="utf-8")
VOCAB = VOCAB_PATH.read_text(encoding="utf-8")
LOCK = threading.Lock()
WIDTH = int(os.getenv("width"))
LISTWIDTH = int(os.getenv("listWidth"))
NOTEWIDTH = int(os.getenv("noteWidth"))
MAXHISTORY = 10
ESTIMATE = ""
TOKENS = [0, 0]
NAMESLIST = []
NAMES = False  # Output a list of all the character names found
BRFLAG = False  # If the game uses <br> instead
FIXTEXTWRAP = True  # Overwrites textwrap
IGNORETLTEXT = True  # Ignores all translated text.
MISMATCH = []  # Lists files that thdata a mismatch error (Length of GPT list response is wrong)
FILENAME = None
BRACKETNAMES = False

# CSV Configuration Settings (configurable via GUI)
CSV_DELIMITER = "	"  # CSV delimiter character (comma, semicolon, tab)
SOURCE_COLUMN = 2  # Which column has the source text to translate (0-indexed)
TARGET_COLUMN = 3  # Which column to write translations to
SPEAKER_COLUMN = 1  # Which column has speaker names (-1 = none)
SKIP_HEADER_ROW = False  # Skip the first row (header)
USE_TARGET_IF_NOT_EMPTY = False  # Use target column text if not empty (T++ style)
WRITE_TO_NEXT_COLUMN = False  # Write to column after target instead of overwriting
PARSE_NAME_TAGS = False  # Parse :name[] tags in text
PARSE_M_MARKERS = False  # Parse \M markers in text
REMOVE_FURIGANA = True  # Remove furigana annotations ＜＝＞
SKIP_COMMENT_ROWS = False  # Skip rows starting with 'comment'

# Regex - Need to change this if you want to translate from/to other languages. Default is Japanese Regex
LANGREGEX = r"[一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９\uFF61-\uFF9F]+"

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
PBAR = None
ENCODING = "utf8"

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

def handleCSV(filename, estimate):
    global ESTIMATE, TOKENS, FILENAME
    ESTIMATE = estimate
    FILENAME = filename

    if not ESTIMATE:
        with open("translated/" + filename, "w+t", newline="", encoding=ENCODING, errors="xmlcharrefreplace") as writeFile:
            # Translate
            start = time.time()
            translatedData = openFiles(filename, writeFile)

            # Print Result
            end = time.time()
            tqdm.write(getResultString(translatedData, end - start, filename))
            with LOCK:
                TOKENS[0] += translatedData[1][0]
                TOKENS[1] += translatedData[1][1]
    else:
        # Translate
        start = time.time()
        translatedData = openFilesEstimate(filename)

        # Print Result
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


def openFiles(filename, writeFile):
    with open("files/" + filename, "r", encoding=ENCODING) as readFile, writeFile:
        translatedData = parseCSV(readFile, writeFile, filename)

    return translatedData


def openFilesEstimate(filename):
    with open("files/" + filename, "r", encoding="utf8") as readFile:
        translatedData = parseCSV(readFile, "", filename)

    return translatedData


def getResultString(translatedData, translationTime, filename):
    # File Print String
    cost = calculateCost(translatedData[1][0], translatedData[1][1], MODEL)
    totalTokenstring = (
        Fore.YELLOW + "[Input: " + str(translatedData[1][0]) + "]"
        "[Output: "
        + str(translatedData[1][1])
        + "]" "[Cost: ${:,.4f}".format(cost)
        + "]"
    )
    timeString = Fore.BLUE + "[" + str(round(translationTime, 1)) + "s]"

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


def parseCSV(readFile, writeFile, filename):
    totalTokens = [0, 0]
    totalLines = 0
    global LOCK

    # Get total for progress bar
    totalLines = len(readFile.readlines())
    readFile.seek(0)

    reader = csv.reader(readFile, delimiter=CSV_DELIMITER)
    if not ESTIMATE:
        writer = csv.writer(
            writeFile,
            delimiter=CSV_DELIMITER,
        )
    else:
        writer = ""

    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
        pbar.desc = filename
        pbar.total = totalLines

        # Grab All Rows
        data = []
        for row in reader:
            data.append(row)

        try:
            response = translateCSV(data, pbar, writeFile, writer, filename, None)
            totalTokens[0] = response[0]
            totalTokens[1] = response[1]
        except Exception:
            traceback.print_exc()
    return [data, totalTokens, None]


def flush_progress_csv(writeFile, writer, rows):
    """Flush current CSV progress to the already-open output file (Windows-safe)."""
    try:
        if ESTIMATE or writeFile is None:
            return
        with LOCK:
            writeFile.seek(0)
            # Recreate writer at current position to avoid state issues
            tmp_writer = csv.writer(writeFile, delimiter=CSV_DELIMITER)
            tmp_writer.writerows(rows)
            writeFile.truncate()
            writeFile.flush()
            os.fsync(writeFile.fileno())
    except Exception:
        traceback.print_exc()


def translateCSV(data, pbar, writeFile, writer, filename, translatedList):
    """
    Unified CSV translation function using configurable settings.
    
    Uses global settings:
    - SOURCE_COLUMN: column index for source text
    - TARGET_COLUMN: column index to write translations
    - SPEAKER_COLUMN: column index for speaker names (-1 = none)
    - SKIP_HEADER_ROW: whether to skip first row
    - USE_TARGET_IF_NOT_EMPTY: use existing target text if present (T++ style)
    - WRITE_TO_NEXT_COLUMN: write to column after target
    - PARSE_NAME_TAGS: parse :name[] tags
    - PARSE_M_MARKERS: parse \\M markers
    - REMOVE_FURIGANA: remove furigana
    - SKIP_COMMENT_ROWS: skip rows with 'comment' in first column
    """
    global LOCK, ESTIMATE, PBAR
    PBAR = pbar
    translatedText = ""
    totalTokens = [0, 0]
    i = 0
    stringList = []

    try:
        # Translate
        while i < len(data):
            # Skip header row if configured
            if SKIP_HEADER_ROW and i == 0:
                i += 1
                continue
            
            # Skip comment rows if configured
            if SKIP_COMMENT_ROWS and len(data[i]) > 0 and 'comment' in str(data[i][0]).lower():
                i += 1
                continue
            
            # Check if row has enough columns
            if len(data[i]) <= SOURCE_COLUMN:
                i += 1
                continue
            
            # Get source text
            jaString = ""
            speaker = ""
            
            # If USE_TARGET_IF_NOT_EMPTY is enabled (T++ style), check target column first
            if USE_TARGET_IF_NOT_EMPTY and len(data[i]) > TARGET_COLUMN and data[i][TARGET_COLUMN]:
                jaString = data[i][TARGET_COLUMN]
            else:
                jaString = data[i][SOURCE_COLUMN] if data[i][SOURCE_COLUMN] else ""
            
            # Skip empty strings
            if not jaString:
                i += 1
                continue
            
            # Handle speaker column if configured
            if SPEAKER_COLUMN >= 0 and len(data[i]) > SPEAKER_COLUMN and data[i][SPEAKER_COLUMN]:
                speakerResponse = getSpeaker(data[i][SPEAKER_COLUMN])
                totalTokens[0] += speakerResponse[1][0]
                totalTokens[1] += speakerResponse[1][1]
                speaker = speakerResponse[0]
                data[i][SPEAKER_COLUMN] = speaker
            
            # Parse :name[] tags if configured
            if PARSE_NAME_TAGS and ':name' in jaString:
                match = re.search(r":name\[([^\]]+?)\]\n([\w\W]*)", jaString)
                if match:
                    # Translate speaker name
                    response = getSpeaker(match.group(1))
                    speaker = response[0]
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]
                    data[i][SOURCE_COLUMN] = data[i][SOURCE_COLUMN].replace(match.group(1), speaker)
                    
                    # Extract text portion
                    jaString = match.group(2)
                    # Remove voice markers
                    voMatch = re.search(r"\\[vfF]+\[.+]", jaString)
                    if voMatch:
                        jaString = jaString.replace(voMatch.group(0), "")
            
            # Parse \M markers if configured
            if PARSE_M_MARKERS and '\\M' in jaString:
                match = re.search(r"\\M.+\n([\w\W]*)", jaString)
                if match:
                    jaString = match.group(1)
                    voMatch = re.search(r"\\[vfF]+\[.+]", jaString)
                    if voMatch:
                        jaString = jaString.replace(voMatch.group(0), "")
            
            # Remove furigana if configured
            if REMOVE_FURIGANA:
                jaString = re.sub(r"＜(.*)＝.*＞", r"\1", jaString)
            
            # Store original for replacement
            ojaString = jaString
            
            # Remove textwrap
            jaString = jaString.replace("\\n", " ")
            jaString = jaString.replace("\n", " ")
            
            # Pass 1: Collect strings
            if not translatedList:
                if speaker:
                    stringList.append(f"[{speaker}]: {jaString}")
                else:
                    stringList.append(jaString)
            
            # Pass 2: Apply translations
            else:
                # Grab and pop translation
                translatedText = translatedList[0]
                translatedList.pop(0)
                
                # Remove speaker prefix from translation if present
                translatedText = strip_speaker_prefix(translatedText)
                
                # Add wordwrap
                translatedText = dazedwrap.wrapText(translatedText, WIDTH)
                translatedText = translatedText.replace("\n", "\\n")
                
                # Determine target column
                actual_target = TARGET_COLUMN + 1 if WRITE_TO_NEXT_COLUMN else TARGET_COLUMN
                
                # Ensure row has enough columns
                while len(data[i]) <= actual_target:
                    data[i].append("")
                
                # Set data
                if PARSE_NAME_TAGS or PARSE_M_MARKERS:
                    # Replace original text portion
                    data[i][actual_target] = data[i][actual_target].replace(ojaString, translatedText) if data[i][actual_target] else translatedText
                else:
                    data[i][actual_target] = translatedText
                
                flush_progress_csv(writeFile, writer, data)
            
            # Iterate
            i += 1

        # EOF - Process collected strings
        if len(stringList) > 0:
            # Set Progress
            pbar.total = len(stringList)
            pbar.refresh()

            # Translate
            response = translateAI(stringList, "")
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            translatedList = response[0]

            # Set Strings
            if len(stringList) == len(translatedList):
                translateCSV(data, pbar, writeFile, writer, filename, translatedList)
            # Mismatch
            else:
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)

            # Write all Data
            with LOCK:
                if not ESTIMATE:
                    for row in data:
                        writer.writerow(row)
            flush_progress_csv(writeFile, writer, data)

    except Exception:
        traceback.print_exc()

        # Write all Data
        with LOCK:
            if not ESTIMATE:
                for row in data:
                    writer.writerow(row)
        flush_progress_csv(writeFile, writer, data)
        return totalTokens

    return totalTokens

# Save some money and enter the character before translation
def getSpeaker(speaker):
    match speaker:
        case "ファイン":
            return ["Fine", [0, 0]]
        case "":
            return ["", [0, 0]]
        case _:
            # Find Speaker
            for i in range(len(NAMESLIST)):
                if speaker == NAMESLIST[i][0]:
                    return [NAMESLIST[i][1], [0, 0]]
                
            if speaker == "？？？":
                return ["???", [0, 0]]

            # Translate and Store Speaker
            response = translateAI(
                f"{speaker}",
                "Reply with the " + LANGUAGE + " translation of the NPC name.",
                False,
            )
            response[0] = response[0].title()
            response[0] = response[0].replace("'S", "'s")
            response[0] = response[0].replace("Speaker: ", "")

            # Retry if name doesn't translate for some reason
            if re.search(r"([a-zA-Z？?])", response[0]) == None:
                response = translateAI(
                    f"{speaker}",
                    "Reply with the " + LANGUAGE + " translation of the NPC name.",
                    False,
                )
                response[0] = response[0].title()
                response[0] = response[0].replace("'S", "'s")

            speakerList = [speaker, response[0]]
            NAMESLIST.append(speakerList)
            return response
    return [speaker, [0, 0]]

def translateAI(text, history, history_ctx=None):
    """
    Legacy wrapper function for the new shared translation utility.
    This maintains compatibility with existing code while using the new shared implementation.
    """
    global PBAR, MISMATCH, FILENAME
    
    # Update config estimate mode based on global ESTIMATE
    TRANSLATION_CONFIG.estimateMode = bool(ESTIMATE)
    
    # Call the new shared translation function
    return sharedtranslateAI(
        text=text,
        history=history,
        config=TRANSLATION_CONFIG,
        filename=FILENAME,
        pbar=PBAR,
        lock=LOCK,
        mismatchList=MISMATCH
    )
