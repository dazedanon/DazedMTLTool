# Libraries
import json
import os
import re
import util.dazedwrap as dazedwrap
import threading
import time
import traceback
import tiktoken
import openai
import csv
from pathlib import Path
from colorama import Fore
from dotenv import load_dotenv
from retry import retry
from tqdm import tqdm
from util.translation import TranslationConfig, translateAI as sharedtranslateAI

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
NAMESLIST = []
NAMES = False  # Output a list of all the character names found
BRFLAG = False  # If the game uses <br> instead
FIXTEXTWRAP = True  # Overwrites textwrap
IGNORETLTEXT = True  # Ignores all translated text.
MISMATCH = []  # Lists files that thdata a mismatch error (Length of GPT list response is wrong)
FILENAME = None
BRACKETNAMES = False

# Regex - Need to change this if you want to translate from/to other languages. Default is Japanese Regex
LANGREGEX = r"[一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９\uFF61-\uFF9F]+"

# Pricing - Depends on the model https://openai.com/pricing
# Batch Size - GPT 3.5 Struggles past 15 lines per request. GPT4 struggles past 50 lines per request
# If you are getting a MISMATCH LENGTH error, lower the batch size.
if "gpt-3.5" in MODEL:
    INPUTAPICOST = 3.00
    OUTPUTAPICOST = 5.00
    BATCHSIZE = 10
    FREQUENCY_PENALTY = 0.2
elif "gpt-4" in MODEL:
    INPUTAPICOST = 1.25
    OUTPUTAPICOST = 10.00
    BATCHSIZE = 30
    FREQUENCY_PENALTY = 0.05
elif "deepseek" in MODEL:
    INPUTAPICOST = 0.27	
    OUTPUTAPICOST = 1.10
    BATCHSIZE = 30
    FREQUENCY_PENALTY = 0.05
else:
    INPUTAPICOST = float(os.getenv("input_cost"))
    OUTPUTAPICOST = float(os.getenv("output_cost"))
    BATCHSIZE = int(os.getenv("batchsize"))
    FREQUENCY_PENALTY = float(os.getenv("frequency_penalty"))

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
    totalTokenstring = (
        Fore.YELLOW + "[Input: " + str(translatedData[1][0]) + "]"
        "[Output: "
        + str(translatedData[1][1])
        + "]" "[Cost: ${:,.4f}".format(((translatedData[1][0] / 1000000) * INPUTAPICOST) + ((translatedData[1][1] / 1000000) * OUTPUTAPICOST))
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

    # Read from tmp files
    if os.path.isfile("csv.tmp"):
        with open("csv.tmp") as tmpFile:
            format = tmpFile.readline()
    else:
        format = ""

    # Choices
    while format not in ["1", "2", "3", "4"]:
        format = input("\n\nSelect the CSV Format:\n\n1. Translator++\n2. Single\n3. Multiple\n4. Speaker&Text\n")
        match format:
            case "1":
                format = "1"
            case "2":
                format = "2"
            case "3":
                format = "3"
            case "4":
                format = "4"

        # Write to file for later use
        with open("csv.tmp", "w", encoding="utf-8") as tmpFile:
            tmpFile.write(f"{format}")

    # Get total for progress bar
    totalLines = len(readFile.readlines())
    readFile.seek(0)

    reader = csv.reader(readFile, delimiter=",")
    if not ESTIMATE:
        writer = csv.writer(
            writeFile,
            delimiter=",",
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
            response = translateCSV(data, pbar, writer, filename, None, format)
            totalTokens[0] = response[0]
            totalTokens[1] = response[1]
        except Exception:
            traceback.print_exc()
    return [data, totalTokens, None]


def translateCSV(data, pbar, writer, filename, translatedList, format):
    global LOCK, ESTIMATE, PBAR
    PBAR = pbar
    translatedText = ""
    totalTokens = [0, 0]
    i = 0
    stringList = []

    try:
        # Translate
        while i < len(data):
            match format:
                # T++ Format: Source Text on column 1. TL Target on Column 2
                case "1":
                    # Get String
                    if i != 0:
                        if data[i][1] == "":
                            jaString = data[i][0]
                        else:
                            jaString = data[i][1]

                        # Remove Textwrap
                        jaString = jaString.replace("\\n", " ")

                        # Pass 1
                        if not translatedList:
                            stringList.append(jaString)

                        # Pass 2
                        else:
                            # Grab and Pop
                            translatedText = translatedList[0]
                            translatedList.pop(0)

                            # Add Wordwrap
                            translatedText = dazedwrap.wrapText(translatedText, WIDTH)
                            translatedText = translatedText.replace("\n", "\\n")

                            # Set Data
                            data[i][1] = translatedText

                    # Iterate
                    i += 1

                # Target Format
                case "2":
                    # Set Values
                    sourceColumn = 0
                    targetColumn = 1

                    # Check if Translated
                    jaString = data[i][sourceColumn]

                    # Remove Textwrap
                    jaString = jaString.replace("\\n", " ")

                    # Pass 1
                    if not translatedList:
                        stringList.append(jaString)

                    # Pass 2
                    else:
                        # Grab and Pop
                        translatedText = translatedList[0]
                        translatedList.pop(0)

                        # Add Wordwrap
                        translatedText = dazedwrap.wrapText(translatedText, WIDTH)
                        translatedText = translatedText.replace("\n", "\\n")

                        # Set Data
                        data[i][targetColumn] = translatedText

                    # Iterate
                    i += 1

                # In Place Format
                case "3":
                    # Set columns to translate. Leave empty to translate all.
                    targetColumns = [1]

                    # False - Place translation in source column
                    # True - Place translation in next column
                    targetNextRow = False

                    # Skip 1st Row
                    skipFirstRow = True

                    for j in range(len(data[i])):
                        if skipFirstRow and i == 0:
                            continue
                        if j in targetColumns and data[i][j]:
                            # Check if Translated
                            jaString = data[i][j]
                            speaker = ""
                            vo = ""

                            if ':name' in jaString:
                                match = re.search(r":name\[([^\]]+?)\]\n([\w\W]*)", jaString)
                                if match:
                                    # TL Speaker
                                    response = getSpeaker(match.group(1))
                                    speaker = response[0]
                                    totalTokens[0] += response[1][0]
                                    totalTokens[1] += response[1][1]
                                    data[i][j] = data[i][j].replace(match.group(1), speaker)

                                    # TL Text
                                    jaString = match.group(2)
                                    voMatch = re.search(r"\\[vfF]+\[.+]", jaString)
                                    if voMatch:
                                        vo = voMatch.group(0)
                                        jaString = jaString.replace(vo, "")
                                    jaString = jaString.replace(vo, "")
                            elif '\\M' in jaString:
                                match = re.search(r"\\M.+\n([\w\W]*)", jaString)
                                if match:
                                    jaString = match.group(1)
                                    voMatch = re.search(r"\\[vfF]+\[.+]", jaString)
                                    if voMatch:
                                        vo = voMatch.group(0)
                                        jaString = jaString.replace(vo, "")
                            elif 'comment' in data[i][0]:
                                # Skip comments
                                continue

                            # Remove Textwrap
                            ojaString = jaString
                            jaString = jaString.replace("\n", " ")

                            # Pass 1
                            if not translatedList:
                                if speaker:
                                    stringList.append(f"[{speaker}]: {jaString}")
                                else:
                                    stringList.append(jaString)

                            # Pass 2
                            else:
                                # Grab and Pop
                                translatedText = translatedList[0]
                                translatedList.pop(0)

                                # Remove speaker
                                if speaker:
                                    translatedText = re.sub(r"^\[?(.+?)\]?\s?[|:]\s?", "", translatedText)

                                # Add Wordwrap
                                translatedText = dazedwrap.wrapText(translatedText, WIDTH)

                                # Set Data
                                if targetNextRow:
                                    data[i][j + 1] = data[i][j + 1].replace(ojaString, f"{translatedText}")
                                else:
                                    data[i][j] = data[i][j].replace(ojaString, f"{translatedText}")

                    # Iterate
                    i += 1

                # Speaker & Text Format
                case "4":
                    # Set columns to translate. Leave empty to translate all.
                    speakerColumn = 2
                    textColumn = 9
                    speaker = ""

                    if len(data[i]) > textColumn and data[i][textColumn]:
                        # Speaker
                        if data[i][speakerColumn]:
                            speakerResponse = getSpeaker(data[i][speakerColumn])
                            totalTokens[0] += speakerResponse[1][0]
                            totalTokens[1] += speakerResponse[1][1]
                            speaker = speakerResponse[0]
                            data[i][speakerColumn] = speaker

                        # Get Text
                        jaString = data[i][textColumn]

                        # Remove Textwrap
                        jaString = jaString.replace("\\n", " ")

                        # Remove Furigana
                        jaString = re.sub(r"＜(.*)＝.*＞", r"\1", jaString)

                        # Pass 1
                        if not translatedList:
                            # Append Speaker
                            if speaker:
                                jaString = f"[{speaker}]: {jaString}"

                            # Append to List
                            stringList.append(jaString)

                        # Pass 2
                        else:
                            # Grab and Pop
                            translatedText = translatedList[0]
                            translatedList.pop(0)

                            # Add Wordwrap
                            translatedText = dazedwrap.wrapText(translatedText, WIDTH)
                            translatedText = translatedText.replace("\n", "\\n")

                            # Check for more than 3 newlines (Shoujo Ramune)
                            newline_count = translatedText.count("\\n")
                            if newline_count >= 3:
                                parts = translatedText.split("\\n", 3)
                                data[i][textColumn] = parts[0] + "\\n" + parts[1] + "\\n" + parts[2]
                                new_row = data[i].copy()
                                new_row[textColumn] = parts[3]
                                new_row[0] = str(int(new_row[0]) + 1)  # Add 1 to the line number
                                data.insert(i + 1, new_row)
                                i += 1
                            else:
                                data[i][textColumn] = translatedText

                    # Iterate
                    i += 1

        # EOF
        if len(stringList) > 0:
            # Set Progress
            pbar.total = len(stringList)
            pbar.refresh()

            # Translate
            response = translateAI(stringList, "", True)
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            translatedList = response[0]

            # Set Strings
            if len(stringList) == len(translatedList):
                translateCSV(data, pbar, writer, filename, translatedList, format)

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

    except Exception:
        traceback.print_exc()

        # Write all Data
        with LOCK:
            if not ESTIMATE:
                for row in data:
                    writer.writerow(row)
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

def translateAI(text, history, fullPromptFlag):
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
        fullPromptFlag=fullPromptFlag,
        config=TRANSLATION_CONFIG,
        filename=FILENAME,
        pbar=PBAR,
        lock=LOCK,
        mismatchList=MISMATCH
    )
