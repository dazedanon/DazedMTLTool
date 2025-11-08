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
from util.translation import TranslationConfig, translateAI as sharedtranslateAI, getPricingConfig, calculateCost, getPricingConfig, calculateCost
import tempfile

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
FILENAME = None
NAMES = False  # Output a list of all the character names found
BRFLAG = False  # If the game uses <br> instead
FIXTEXTWRAP = True  # Overwrites textwrap
IGNORETLTEXT = False  # Ignores all translated text.
MISMATCH = []  # Lists files that throw a mismatch error (Length of GPT list response is wrong)
PBAR = None

# tqdm Globals
BAR_FORMAT = "{l_bar}{bar:10}{r_bar}{bar:-10b}"
POSITION = 0
LEAVE = False
PBAR = None

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

def handleJSON(filename, estimate):
    global ESTIMATE, totalTokens, FILENAME
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
            start = time.time()
            translatedData = openFiles(filename)

            # Write final result after translation is complete
            with open("translated/" + filename, "w", encoding="utf-8", newline="\n") as outFile:
                json.dump(translatedData[0], outFile, ensure_ascii=False, indent=4)
            
            # Print Result
            end = time.time()
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
    global LOCK, PBAR

    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
        pbar.desc = filename
        PBAR = pbar
        try:
            result = translateJSON(data, filename, [])
            totalTokens[0] += result[0]
            totalTokens[1] += result[1]
        except Exception as e:
            traceback.print_exc()
            return [data, totalTokens, e]
    return [data, totalTokens, None]


def save_progress_json(data, filename):
    """Save current JSON translation progress."""
    try:
        if ESTIMATE:
            return
        os.makedirs("translated", exist_ok=True)
        tmp_path = os.path.join("translated", f"{filename}.tmp")
        final_path = os.path.join("translated", filename)
        with open(tmp_path, "w", encoding="utf-8", newline="\n") as outFile:
            json.dump(data, outFile, ensure_ascii=False, indent=4)
        os.replace(tmp_path, final_path)
    except Exception:
        traceback.print_exc()


def translateJSON(data, filename, translatedList):
    global LOCK, ESTIMATE, FILENAME, PBAR, MISMATCH
    if translatedList:
        stringList = translatedList[0]
        eventList = translatedList[1]
    else:
        stringList = []
        eventList = [[], [], [], [], [], [], []]  # [title, process, text, key, target, job, place]
    tokens = [0, 0]
    speaker = ""
    i = 0
    stringListTL = []
    eventListTL = [[], [], [], [], [], [], []]

    while i < len(data):
        speakerKey = "character_nameText"
        messageKey = "m_text"

        # Event List Format - Key
        if "key" in data[i] and data[i]["key"]:
            jaString = data[i]["key"]
            
            # Pass 1
            if not translatedList:
                eventList[3].append(jaString.strip())
            
            # Pass 2
            else:
                if eventList[3]:
                    translatedText = eventList[3][0]
                    eventList[3].pop(0)
                    
                    # Set Data
                    data[i]["key"] = translatedText
                    save_progress_json(data, filename)

        # Event List Format - Title
        if "title" in data[i] and data[i]["title"]:
            jaString = data[i]["title"]
            
            # Pass 1
            if not translatedList:
                eventList[0].append(jaString.strip())
            
            # Pass 2
            else:
                if eventList[0]:
                    translatedText = eventList[0][0]
                    eventList[0].pop(0)
                    
                    # Set Data
                    data[i]["title"] = translatedText
                    save_progress_json(data, filename)

        # Event List Format - Target
        if "target" in data[i] and data[i]["target"]:
            jaString = data[i]["target"]
            
            # Pass 1
            if not translatedList:
                eventList[4].append(jaString.strip())
            
            # Pass 2
            else:
                if eventList[4]:
                    translatedText = eventList[4][0]
                    eventList[4].pop(0)
                    
                    # Set Data
                    data[i]["target"] = translatedText
                    save_progress_json(data, filename)

        # Event List Format - Job
        if "job" in data[i] and data[i]["job"]:
            jaString = data[i]["job"]
            
            # Pass 1
            if not translatedList:
                eventList[5].append(jaString.strip())
            
            # Pass 2
            else:
                if eventList[5]:
                    translatedText = eventList[5][0]
                    eventList[5].pop(0)
                    
                    # Set Data
                    data[i]["job"] = translatedText
                    save_progress_json(data, filename)

        # Event List Format - Place
        if "place" in data[i] and data[i]["place"]:
            jaString = data[i]["place"]
            
            # Pass 1
            if not translatedList:
                eventList[6].append(jaString.strip())
            
            # Pass 2
            else:
                if eventList[6]:
                    translatedText = eventList[6][0]
                    eventList[6].pop(0)
                    
                    # Set Data
                    data[i]["place"] = translatedText
                    save_progress_json(data, filename)

        # Event List Format - Process
        if "process" in data[i] and data[i]["process"]:
            jaString = data[i]["process"]
            
            # Pass 1
            if not translatedList:
                eventList[1].append(jaString.strip())
            
            # Pass 2
            else:
                if eventList[1]:
                    translatedText = eventList[1][0]
                    eventList[1].pop(0)
                    
                    # Set Data
                    data[i]["process"] = translatedText
                    save_progress_json(data, filename)

        # Event List Format - Text
        if "text" in data[i] and data[i]["text"]:
            jaString = data[i]["text"]
            # Pass 1
            if not translatedList:
                # Replace \n with space for translation
                jaStringClean = jaString.replace("\n", " ")
                eventList[2].append(jaStringClean.strip())
            
            # Pass 2
            else:
                if eventList[2]:
                    translatedText = eventList[2][0]
                    eventList[2].pop(0)
                    
                    # Apply text wrapping and restore linebreaks
                    translatedText = dazedwrap.wrapText(translatedText, 70)
                    
                    # Set Data
                    data[i]["text"] = translatedText
                    save_progress_json(data, filename)

        # Speaker
        if speakerKey in data[i] and data[i][speakerKey]:
            # Grab and TL
            speaker = data[i][speakerKey]
            response = getSpeaker(speaker)
            speaker = response[0]
            tokens[0] += response[1][0]
            tokens[1] += response[1][1]

            # Set Speaker
            data[i][speakerKey] = speaker

        # Dialogue
        if messageKey in data[i]\
            and data[i][messageKey].strip()\
            and data[i][messageKey] != "a"\
            and data[i][messageKey].replace("\u3000", "").strip() != "":
            jaString = data[i][messageKey]

            # Save Original String
            originalString = jaString

            # If there isn't any Japanese in the text just skip
            if not re.search(LANGREGEX, jaString):
                i += 1
                continue

            # Pass 1
            if not translatedList:
                # Strip Spaces
                jaString = jaString.strip()

                # Remove Textwrap
                # jaString = jaString.replace('\n', ' ')

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
                    match = re.search(r'(^\[.+?\]\s?[|:]\s?)', translatedText)
                    if match:
                        translatedText = translatedText.replace(match.group(1), "") 

                    # Escape Quotes
                    translatedText = re.sub(r'(?<!\\)"', r"", translatedText)

                    # Remove characters that may break scripts
                    # translatedText = translatedText.replace("<", "(")
                    # translatedText = translatedText.replace(">", ")")
                    translatedText = translatedText.replace("『", "")
                    translatedText = translatedText.replace("』", "")

                    # Remove GPT ' Quotes
                    if translatedText:
                        if translatedText[0] == "'":
                            translatedText = translatedText[1:]
                        if translatedText[-1] == "'":
                            translatedText = translatedText[:-1]
                    else:
                        print("Warning: Empty Translation for", originalString)

                    # Textwrap
                    # translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)  
                    
                    # Set Data
                    if "『" in data[i][messageKey] and "』" not in translatedText:
                        data[i][messageKey] = data[i][messageKey].replace(originalString, f"『{translatedText}』")
                    else:
                        data[i][messageKey] = data[i][messageKey].replace(originalString, f"{translatedText}")

                    # Save progress after each message replacement
                    save_progress_json(data, filename)
        # Next Value
        i += 1       

    # EOF - Only do translation if this is Pass 1 (collecting strings)
    if not translatedList:
        # Event List
        if any(eventList):
            PBAR.total = sum(len(event) for event in eventList)
            PBAR.refresh()
            
            # Event Title
            if eventList[0]:
                response = translateAI(eventList[0], "Event Title", True)
                tokens[0] += response[1][0]
                tokens[1] += response[1][1]
                eventListTL[0] = response[0]
                
                if len(eventList[0]) != len(eventListTL[0]):
                    with LOCK:
                        if FILENAME not in MISMATCH:
                            MISMATCH.append(FILENAME)

            # Event Process
            if eventList[1]:
                response = translateAI(eventList[1], "Event Process", True)
                tokens[0] += response[1][0]
                tokens[1] += response[1][1]
                eventListTL[1] = response[0]
                
                if len(eventList[1]) != len(eventListTL[1]):
                    with LOCK:
                        if FILENAME not in MISMATCH:
                            MISMATCH.append(FILENAME)

            # Event Text
            if eventList[2]:
                response = translateAI(eventList[2], "Event Description", True)
                tokens[0] += response[1][0]
                tokens[1] += response[1][1]
                eventListTL[2] = response[0]
                
                if len(eventList[2]) != len(eventListTL[2]):
                    with LOCK:
                        if FILENAME not in MISMATCH:
                            MISMATCH.append(FILENAME)

            # Event Key
            if eventList[3]:
                response = translateAI(eventList[3], "Event Key", True)
                tokens[0] += response[1][0]
                tokens[1] += response[1][1]
                eventListTL[3] = response[0]
                
                if len(eventList[3]) != len(eventListTL[3]):
                    with LOCK:
                        if FILENAME not in MISMATCH:
                            MISMATCH.append(FILENAME)

            # Event Target
            if eventList[4]:
                response = translateAI(eventList[4], "Character Name", True)
                tokens[0] += response[1][0]
                tokens[1] += response[1][1]
                eventListTL[4] = response[0]
                
                if len(eventList[4]) != len(eventListTL[4]):
                    with LOCK:
                        if FILENAME not in MISMATCH:
                            MISMATCH.append(FILENAME)

            # Event Job
            if eventList[5]:
                response = translateAI(eventList[5], "Job/Occupation", True)
                tokens[0] += response[1][0]
                tokens[1] += response[1][1]
                eventListTL[5] = response[0]
                
                if len(eventList[5]) != len(eventListTL[5]):
                    with LOCK:
                        if FILENAME not in MISMATCH:
                            MISMATCH.append(FILENAME)

            # Event Place
            if eventList[6]:
                response = translateAI(eventList[6], "Location Name", True)
                tokens[0] += response[1][0]
                tokens[1] += response[1][1]
                eventListTL[6] = response[0]
                
                if len(eventList[6]) != len(eventListTL[6]):
                    with LOCK:
                        if FILENAME not in MISMATCH:
                            MISMATCH.append(FILENAME)

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

        # Pass 2: Set Strings (recursive call)
        translateJSON(data, filename, [stringListTL, eventListTL])
    
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
