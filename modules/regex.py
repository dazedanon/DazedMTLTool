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
NOTEWIDTH = 70
MAXHISTORY = 10
ESTIMATE = ""
TOKENS = [0, 0]
NAMESLIST = []
NAMES = False  # Output a list of all the character names found
BRFLAG = False  # If the game uses <br> instead
FIXTEXTWRAP = True  # Overwrites textwrap
IGNORETLTEXT = False  # Ignores all translated text.
MISMATCH = []  # Lists files that throw a mismatch error (Length of GPT list response is wrong)
FILENAME = None
TIMETOTAL = 0  # Total Time Taken for all translations
TIMETOTAL = 0  # Total Time Taken for all translations

# tqdm Globals
BAR_FORMAT = "{l_bar}{bar:10}{r_bar}{bar:-10b}"
POSITION = 0
LEAVE = False
PBAR = None

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
elif "gpt-5" in MODEL:
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

def handleRegex(filename, estimate):
    global ESTIMATE, TOKENS, FILENAME
    ESTIMATE = estimate
    FILENAME = filename

    # Translate
    start = time.time()
    translatedData = openFiles(filename)

    # Translate
    if not estimate:
        try:
            with open("translated/" + filename, "w", encoding="utf-8-sig") as outFile:
                outFile.writelines(translatedData[0])
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


def getResultString(translatedData, translationTime, filename):
    global TIMETOTAL
    # File Print String
    totalTokenstring = (
        Fore.YELLOW + "[Input: " + str(translatedData[1][0]) + "]"
        "[Output: "
        + str(translatedData[1][1])
        + "]" "[Cost: ${:,.4f}".format(((translatedData[1][0] / 1000000) * INPUTAPICOST) + ((translatedData[1][1] / 1000000) * OUTPUTAPICOST))
        + "]"
    )
    if filename != "TOTAL":
        timeString = Fore.BLUE + "[" + str(round(translationTime, 1)) + "s]"
        TIMETOTAL += round(translationTime, 1)
    else:
        timeString = Fore.BLUE + "[" + str(round(TIMETOTAL, 1)) + "s]"

    if translatedData[2] == None:
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


def openFiles(filename):
    with open("files/" + filename, "r", encoding="utf-8-sig") as readFile:
        translatedData = parseRegex(readFile, filename)

        # Delete lines marked for deletion
        finalData = []
        for line in translatedData[0]:
            if line != "\\d\n":
                finalData.append(line)
        translatedData[0] = finalData

    return translatedData


def parseRegex(readFile, filename):
    global PBAR
    totalTokens = [0, 0]

    # Read File into data
    data = readFile.readlines()

    # Create Progress Bar
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE) as pbar:
        pbar.desc = filename
        PBAR = pbar

        try:
            result = translateRegex(data, [])
            totalTokens[0] += result[0]
            totalTokens[1] += result[1]
        except Exception as e:
            traceback.print_exc()
            return [data, totalTokens, e]
    return [data, totalTokens, None]


def translateRegex(data, translatedList):
    if translatedList:
        stringList = translatedList[0]
        choiceList = translatedList[1]
    else:
        stringList = []
        choiceList = []
    tokens = [0, 0]
    speaker = ""
    global LOCK, ESTIMATE, FILENAME, PBAR, MISMATCH
    i = 0

    while i < len(data):
        voice = False
        lineRegexText = r'"profile": "(.*)"'
        lineRegexSpeaker = r"◆A.+?◆(.+)"
        choiceRegex = r"\$menu_item.+?,(.*?),"
        titleRegex = r"title\s'(.*)'$"
        speaker = ""

        # Title
        match = re.search(titleRegex, data[i])
        if match:
            response = translateAI(
                match.group(1),
                f"Reply with the {LANGUAGE} translation of the chapter title",
                True,
            )
            tokens[0] += response[1][0]
            tokens[1] += response[1][1]
            title = response[0]

            # Set
            if not translatedList:
                title = re.sub(r"(?<!\\)'", r"\\'", title)
                data[i] = data[i].replace(match.group(1), title)

        # Speaker
        match = re.search(lineRegexSpeaker, data[i])
        if match:
            if match.group(1):
                if match.group(1) == "主人公":
                    speaker = "Protagonist"
                else:
                    response = getSpeaker(match.group(1))
                    speaker = response[0]
                    tokens[0] += response[1][0]
                    tokens[1] += response[1][1]
                if translatedList:
                    data[i] = data[i].replace(match.group(1), speaker)
                i += 3
            else:
                speaker = None
        elif data[i] == "Protagonist\n":
            speaker = "Protagonist"
            i += 1

        # Dialogue
        match = re.search(lineRegexText, data[i])
        jaString = None
        if match and match.group(0).replace("\u3000", "") != '\n':
            # Set String
            jaString = match.group(1)

            # Save Original String
            originalString = jaString

            # Pass 1
            if not translatedList:
                # Strip Spaces
                jaString = jaString.strip()

                # Remove Textwrap
                jaString = jaString.replace('\\n', ' ')

                if jaString:
                    if speaker:
                        stringList.append(f"[{speaker}]: {jaString}")
                    else:
                        stringList.append(jaString)

            # Pass 2
            else:
                # Get Text
                if stringList:
                    # Grab and Pop
                    translatedText = stringList[0]
                    stringList.pop(0)

                    # Set to None if empty list
                    if len(stringList) <= 0:
                        stringList = None

                    # Remove speaker
                    translatedText = re.sub(r"^\[?(.+?)\]?\s?[|:]\s?", "", translatedText)

                    # Escape Quotes
                    translatedText = re.sub(r'(?<!\\)"', r"", translatedText)

                    # Remove characters that may break scripts
                    translatedText = translatedText.replace("<", "(")
                    translatedText = translatedText.replace(">", ")")

                    # Textwrap
                    translatedText = dazedwrap.wrapText(translatedText, width=WIDTH).replace("\n", "\\n")   
                    
                    # Set Data
                    if "「" in data[i-1] and "」" not in translatedText:
                        data[i] = data[i].replace(originalString, f"「{translatedText}」")
                    else:
                        data[i] = data[i].replace(originalString, f"{translatedText}")            

        # Choices
        match = re.search(choiceRegex, data[i])
        if match:
            # Pass 1
            if not translatedList:
                choiceList.append(match.group(1))

            # Pass 2
            else:
                # Grab and Pop
                translatedText = choiceList[0]
                choiceList.pop(0)

                # Replace Spaces
                translatedText = translatedText.replace("\u3000", " ")

                # Escape Quotes
                translatedText = re.sub(r'(?<!\\)"', r'\\"', translatedText)
                translatedText = re.sub(r"(?<!\\)'", r"\\'", translatedText)

                # Set
                data[i] = data[i].replace(match.group(1), translatedText)

            i += 1
        else:
            i += 1

    # EOF
    if not translatedList:
        stringListTL = []
        choiceListTL = []

        # String List
        if stringList:
            PBAR.total = len(stringList)
            PBAR.refresh()
            response = translateAI(stringList, "Reply with the English Translation", True)
            tokens[0] += response[1][0]
            tokens[1] += response[1][1]
            stringListTL = response[0]

            if len(stringList) != len(stringListTL):
                # Mismatch
                with LOCK:
                    if FILENAME not in MISMATCH:
                        MISMATCH.append(FILENAME)

        # Choice List
        if choiceList:
            response = translateAI(choiceList, "Reply with the English TL of the Dialogue Choice", True)
            tokens[0] += response[1][0]
            tokens[1] += response[1][1]
            choiceListTL = response[0]

            if len(choiceList) != len(choiceListTL):
                # Mismatch
                with LOCK:
                    if FILENAME not in MISMATCH:
                        MISMATCH.append(FILENAME)

        # Set Strings
        translateRegex(data, [stringListTL, choiceListTL])
    return tokens

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
