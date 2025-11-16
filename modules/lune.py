# Libraries
import json
import os
import re
import util.dazedwrap as dazedwrap
import threading
import time
import traceback
import tiktoken
from pathlib import Path
from colorama import Fore
from dotenv import load_dotenv
from retry import retry
from tqdm import tqdm
from util.translation import TranslationConfig, translateAI as sharedtranslateAI, getPricingConfig, calculateCost
import tempfile

# Globals
MODEL = os.getenv("model")
TIMEOUT = int(os.getenv("timeout"))
LANGUAGE = os.getenv("language").capitalize()
PROMPT = Path("prompt.txt").read_text(encoding="utf-8")
VOCAB = Path("vocab.txt").read_text(encoding="utf-8")
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

# Regex - Need to change this if you want to translate from/to other languages. Default is Japanese Regex
LANGREGEX = r"[一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９\uFF61-\uFF9F]+"

# Get pricing configuration based on the model
PRICING_CONFIG = getPricingConfig(MODEL)
INPUTAPICOST = PRICING_CONFIG["inputAPICost"]
OUTPUTAPICOST = PRICING_CONFIG["outputAPICost"]
BATCHSIZE = PRICING_CONFIG["batchSize"]
FREQUENCY_PENALTY = PRICING_CONFIG["frequencyPenalty"]

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

def handleLune(filename, estimate):
    global FILENAME, ESTIMATE, totalTokens
    ESTIMATE = estimate
    FILENAME = filename

    if estimate:
        start = time.time()
        translatedData = openFiles(filename)

        # Print Result
        end = time.time()
        tqdm.write(getResultString(translatedData, end - start, filename))
        with LOCK:
            TOKENS[0] += translatedData[1][0]
            TOKENS[1] += translatedData[1][1]

        return getResultString(["", TOKENS, None], end - start, "TOTAL")

    else:
        try:
            with open("translated/" + filename, "w", encoding="utf-8", newline="\n") as outFile:
                start = time.time()
                translatedData = openFiles(filename)

                # Print Result
                end = time.time()
                json.dump(translatedData[0], outFile, ensure_ascii=False, indent=4)
                tqdm.write(getResultString(translatedData, end - start, filename))
                with LOCK:
                    TOKENS[0] += translatedData[1][0]
                    TOKENS[1] += translatedData[1][1]
        except Exception:
            return "Fail"

    return getResultString(["", TOKENS, None], end - start, "TOTAL")


def openFiles(filename):
    with open("files/" + filename, "r", encoding="UTF-8-sig") as f:
        data = json.load(f)

        # Map Files
        if ".json" in filename:
            translatedData = parseJSON(data, filename)

        else:
            raise NameError(filename + " Not Supported")

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


def parseJSON(data, filename):
    totalTokens = [0, 0]
    totalLines = 0
    totalLines = len(data)
    global LOCK

    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
        pbar.desc = filename
        pbar.total = totalLines
        try:
            result = translateJSON(data, pbar)
            totalTokens[0] += result[0]
            totalTokens[1] += result[1]
        except Exception as e:
            return [data, totalTokens, e]
    return [data, totalTokens, None]


def save_progress_json(data, filename):
    """Atomically save current JSON translation progress."""
    try:
        if ESTIMATE:
            return
        os.makedirs("translated", exist_ok=True)
        tmp_fd, tmp_path = tempfile.mkstemp(prefix=f"{filename}.", suffix=".tmp", dir="translated")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8", newline="\n") as tmp_file:
                json.dump(data, tmp_file, ensure_ascii=False, indent=4)
            os.replace(tmp_path, os.path.join("translated", filename))
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
    except Exception:
        traceback.print_exc()


def translateJSON(data, pbar):
    global PBAR
    PBAR = pbar
    textHistory = []
    batch = []
    maxHistory = MAXHISTORY
    tokens = [0, 0]
    speaker = "None"
    insertBool = False
    i = 0
    batchStartIndex = 0

    while i < len(data):
        item = data[i]
        # Speaker
        if "name" in item:
            if item["name"] not in [None, "-"]:
                response = getSpeaker(item["name"])
                speaker = response[0]
                tokens[0] += response[1][0]
                tokens[1] += response[1][1]
                item["name"] = speaker
                save_progress_json(data, FILENAME or "output.json")
            else:
                speaker = "None"

        # Text
        if "message" in item:
            for text in [
                "text",
                "text2",
                "help1",
                "help2",
                "help3",
                "like",
                "message",
                "me",
            ]:
                if text in item:
                    if item[text] != None:
                        jaString = item[text]

                        # Remove any textwrap
                        if FIXTEXTWRAP == True:
                            finalJAString = jaString.replace("\n", " ")

                        # [Passthrough 1] Pulling From File
                        if insertBool is False:
                            # Append to List and Clear Values
                            batch.append(finalJAString)
                            speaker = ""

                            # Translate Batch if Full
                            if len(batch) == BATCHSIZE:
                                # Translate
                                response = translateAI(batch, textHistory, True)
                                tokens[0] += response[1][0]
                                tokens[1] += response[1][1]
                                translatedBatch = response[0]
                                textHistory = translatedBatch[-10:]

                                # Set Values
                                if len(batch) == len(translatedBatch):
                                    i = batchStartIndex
                                    insertBool = True

                                # Mismatch
                                else:
                                    pbar.write(f"Mismatch: {batchStartIndex} - {i}")
                                    MISMATCH.append(batch)
                                    batchStartIndex = i
                                    batch.clear()

                            if insertBool is False:
                                i += 1

                            currentGroup = []

                        # [Passthrough 2] Setting Data
                        else:
                            # Get Text
                            translatedText = translatedBatch[0]

                            # Remove added speaker
                            translatedText = re.sub(r"^.+?:\s", "", translatedText)

                            # Textwrap
                            translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)

                            # Set Text
                            item[text] = translatedText
                            save_progress_json(data, FILENAME or "output.json")
                            translatedBatch.pop(0)
                            speaker = ""
                            currentGroup = []
                            i += 1

                            # If Batch is empty. Move on.
                            if len(translatedBatch) == 0:
                                insertBool = False
                                batchStartIndex = i
                                batch.clear()
        else:
            i += 1

        # Translate Batch if not empty and EOF
        if len(batch) != 0 and i >= len(data):
            # Translate
            response = translateAI(batch, textHistory, True)
            tokens[0] += response[1][0]
            tokens[1] += response[1][1]
            translatedBatch = response[0]
            textHistory = translatedBatch[-10:]

            # Set Values
            if len(batch) == len(translatedBatch):
                i = batchStartIndex
                insertBool = True

            # Mismatch
            else:
                pbar.write(f"Mismatch: {batchStartIndex} - {i}")
                MISMATCH.append(batch)
                batchStartIndex = i
                batch.clear()

            currentGroup = []
            # After applying a batch, persist progress
            save_progress_json(data, FILENAME or "output.json")
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
