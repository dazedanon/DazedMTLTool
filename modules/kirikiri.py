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
PBAR = None
FILENAME = None

# tqdm Globals
BAR_FORMAT = "{l_bar}{bar:10}{r_bar}{bar:-10b}"
POSITION = 0
LEAVE = False

# Flags
SPEAKERS = True
CHOICES = True
DIALOGUE = True

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
    INPUTAPICOST = 2.0
    OUTPUTAPICOST = 8.00
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

def handleKirikiri(filename, estimate):
    global ESTIMATE, FILENAME
    ESTIMATE = estimate
    FILENAME = filename

    if ESTIMATE:
        start = time.time()
        translatedData = openFiles(filename)

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

    else:
        try:
            with open("translated/" + filename, "w", encoding="cp932", errors="ignore") as outFile:
                start = time.time()
                translatedData = openFiles(filename)

                # Print Result
                end = time.time()
                if translatedData[0] != []:
                    outFile.writelines(translatedData[0])
                else:
                    PBAR.write(f"{FILENAME} Failed to write")
                    os.remove(f"translated/{filename}")
                tqdm.write(getResultString(translatedData, end - start, filename))
                with LOCK:
                    TOKENS[0] += translatedData[1][0]
                    TOKENS[1] += translatedData[1][1]
        except Exception:
            traceback.print_exc()
            os.remove(f"translated/{filename}")
            return "Fail"

    return getResultString(["", TOKENS, None], end - start, "TOTAL")


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
    with open("files/" + filename, "r", encoding="cp932") as readFile:
        translatedData = parseKiriKiri(readFile, filename)
    return translatedData


def parseKiriKiri(readFile, filename):
    global PBAR
    totalTokens = [0, 0]

    # Read File into data
    data = readFile.readlines()

    # Create Progress Bar
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE) as PBAR:
        PBAR.desc = filename

        try:
            result = translateKiriKiri(data, PBAR, filename, [])
            totalTokens[0] += result[0]
            totalTokens[1] += result[1]
        except Exception as e:
            traceback.print_exc()
            return [data, totalTokens, e]
    return [data, totalTokens, None]


def translateKiriKiri(data, pbar, filename, jobList):
    # Check Job Data
    if len(jobList) > 0:
        stringList = jobList[0]
        choiceList = jobList[1]
        setData = True
    else:
        stringList = []
        choiceList = []
        setData = False
    tokens = [0, 0]
    speaker = ""
    global LOCK, ESTIMATE
    i = 0

    # Regex
    speakerRegex = r"【(.*)】\[CR\]"
    dialogueRegex = r"^\[text\](.*).*\[KeyWait\]|\[\w+\](.*)\[\/\w+\].*\[KeyWait\]"
    furiganaRegex = r'(\[eruby\sstr="(.*?)"\stext.*?\])'
    choicesRegex = r"^\s*\[button\d\sclickse=sys_decide.*text='(.*?)'.*"

    while i < len(data):
        speaker = ""
        # Speaker
        match = re.search(speakerRegex, data[i])
        if match and SPEAKERS:
            speakerJA = match.group(1)
            response = getSpeaker(speakerJA)
            speaker = response[0]
            tokens[0] += response[1][0]
            tokens[1] += response[1][1]
            data[i] = data[i].replace(speakerJA, speaker)
            i += 1

        # Choices
        match = re.search(choicesRegex, data[i])
        if match and CHOICES:
            jaString = match.group(1)

            # Pass 1
            if not setData:
                choiceList.append(jaString)

            # Pass 2
            else:
                # Grab and Pop and Set
                translatedText = choiceList[0]
                choiceList.pop(0)

                # Replace Quotes
                data[i] = data[i].replace("'", '"')
                translatedText = translatedText.replace('"', "'")
                data[i] = data[i].replace(jaString, translatedText)

        # Dialogue
        match = re.search(dialogueRegex, data[i])
        if match and DIALOGUE:
            jaString = match.group(1)
            if not jaString:
                jaString = match.group(2)

            # Pass 1
            if not setData:
                # Remove any textwrap
                jaString = jaString.replace("[r]", " ")

                # Remove Furigana
                matchList = re.findall(furiganaRegex, jaString)
                if matchList:
                    for match in matchList:
                        jaString = jaString.replace(match[0], match[1])

                # Add String
                if speaker:
                    stringList.append(f"[{speaker}]: {jaString.strip()}")
                else:
                    stringList.append(f"{jaString.strip()}")

            # Pass 2
            else:
                if len(stringList) > 0:
                    # Grab and Pop
                    translatedText = stringList[0]
                    stringList.pop(0)

                    # Remove Speaker
                    translatedText = re.sub(r"\[.*?\]:\s", "", translatedText)

                    # Textwrap
                    translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)
                    translatedText = translatedText.replace("\n", "[r]")

                    # Replace Quotes
                    data[i] = data[i].replace("'", '"')
                    translatedText = translatedText.replace('"', "'")
                    data[i] = data[i].replace(jaString, translatedText)

        # Next Line
        i += 1

    # EOF
    stringListTL = []
    choiceListTL = []

    # Dialogue
    if len(stringList) > 0:
        # Set Progress
        pbar.total = len(stringList)
        pbar.refresh()

        # Translate
        response = translateAI(
            stringList,
            "",
            True,
        )
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        stringListTL = response[0]

        # Validate
        if len(stringList) != len(stringListTL):
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)
                    stringListTL = stringList

    # Choices
    if len(choiceList) > 0:
        # Set Progress
        pbar.total = len(choiceList)
        pbar.refresh()

        # Translate
        response = translateAI(
            choiceList,
            "",
            True,
        )
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        choiceListTL = response[0]

        # Validate
        if len(choiceList) != len(choiceListTL):
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)
                    choiceListTL = choiceList

    # Proceed to Pass 2
    if not setData:
        translateKiriKiri(data, pbar, filename, [stringListTL, choiceListTL])

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
