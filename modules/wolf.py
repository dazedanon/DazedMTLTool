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
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from colorama import Fore
from dotenv import load_dotenv
from retry import retry
from tqdm import tqdm
from util.translation import TranslationConfig, translateAI as sharedtranslateAI, getPricingConfig, calculateCost, getPricingConfig, calculateCost

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
NAMESLIST = []  # Keep list for consistency
TERMSLIST = []  # Keep list for consistency
NAMES = False  # Output a list of all the character names found
BRFLAG = False  # If the game uses <br> instead
FIXTEXTWRAP = True  # Overwrites textwrap
IGNORETLTEXT = False  # Ignores all translated text.
MISMATCH = []  # Lists files that throw a mismatch error (Length of GPT list response is wrong)
FILENAME = None
BRACKETNAMES = False

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
FILENAME = None

# Dialogue / Choices
CODE101 = True
CODE102 = True

# Picture
CODE150 = False

# Set String (Fragile but necessary)
CODE122 = False

# Other
CODE210 = False
CODE300 = False
CODE250 = False

# Database
SCENARIOFLAG = False
OPTIONSFLAG = False
NPCFLAG = False
DBNAMEFLAG = False
DBVALUEFLAG = False
ITEMFLAG = False
STATEFLAG = False
ENEMYFLAG = False
ARMORFLAG = False
WEAPONFLAG = False
SKILLFLAG = False

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

def handleWOLF(filename, estimate):
    global ESTIMATE, TOKENS, FILENAME
    ESTIMATE = estimate
    FILENAME = filename

    # Translate
    start = time.time()
    translatedData = openFiles(filename)

    # Translate
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

    # Print any errors on maps
    if len(MISMATCH) > 0:
        return totalString + Fore.RED + f"\nMismatch Errors: {MISMATCH}" + Fore.RESET
    else:
        return totalString


def openFiles(filename):
    with open("files/" + filename, "r", encoding="utf-8-sig") as f:
        data = json.load(f)

        # Map Files
        if "'events':" in str(data):
            if len(data["events"]) > 0:
                translatedData = parseMap(data, filename)
            else:
                return [data, [0, 0], None]

        # Map Files
        elif "'types':" in str(data):
            translatedData = parseDB(data, filename)

        # Other Files
        elif "'commands':" in str(data):
            translatedData = parseOther(data, filename)

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


def parseOther(data, filename):
    totalTokens = [0, 0]
    totalLines = 0
    events = data["commands"]
    global LOCK

    # Thread for each page in file
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE) as pbar:
        pbar.desc = filename
        pbar.total = totalLines
        translationData = searchCodes(events, pbar, [], filename)
        try:
            totalTokens[0] += translationData[0]
            totalTokens[1] += translationData[1]
        except Exception as e:
            return [data, totalTokens, e]
    return [data, totalTokens, None]


def parseDB(data, filename):
    totalTokens = [0, 0]
    totalLines = 0
    events = data["types"]
    global LOCK

    # Thread for each page in file
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE) as pbar:
        pbar.desc = filename
        pbar.total = totalLines
        translationData = searchDB(events, pbar, [], filename)
        try:
            totalTokens[0] += translationData[0]
            totalTokens[1] += translationData[1]
        except Exception as e:
            return [data, totalTokens, e]
    return [data, totalTokens, None]


def parseMap(data, filename):
    totalTokens = [0, 0]
    totalLines = 0
    events = data["events"]
    global LOCK

    # Get total for progress bar
    for event in events:
        if event is not None:
            for page in event["pages"]:
                totalLines += len(page["list"])

    # Thread for each page in file
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
        pbar.desc = filename
        pbar.total = totalLines
        with ThreadPoolExecutor(max_workers=THREADS) as executor:
            for event in events:
                if event is not None:
                    futures = [executor.submit(searchCodes, page["list"], pbar, None, filename) for page in event["pages"] if page is not None]
                    for future in as_completed(futures):
                        try:
                            totalTokensFuture = future.result()
                            totalTokens[0] += totalTokensFuture[0]
                            totalTokens[1] += totalTokensFuture[1]
                        except Exception as e:
                            return [data, totalTokens, e]
    return [data, totalTokens, None]


def searchCodes(events, pbar, jobList, filename):
    # Lists
    if jobList:
        stringList = jobList[0]
        list210 = jobList[1]
        list300 = jobList[2]
        list150 = jobList[3]
        list250 = jobList[4]
        list122 = jobList[5]
        setData = True
    else:
        stringList = []
        list210 = []
        list300 = []
        list150 = []
        list250 = []
        list122 = []
        setData = False

    # Other
    codeList = events
    textHistory = []
    totalTokens = [0, 0]
    translatedText = ""
    speaker = ""
    nametag = ""
    initialJAString = ""
    global LOCK, NAMESLIST, MISMATCH, PBAR, FILENAME
    FILENAME = filename
    PBAR = pbar

    # Calculate Total Length
    code_flags = {102: CODE102, 122: CODE122, 300: CODE300, 250: CODE250}
    totalList = 0
    for code_item in codeList:
        if code_flags.get(code_item["code"], False):
            totalList += 1
    pbar.total = totalList
    pbar.refresh()

    # Begin Parsing File
    try:
        # Iterate through events
        i = 0
        while i < len(codeList):
            ### Event Code: 101 Message
            if codeList[i]["code"] == 101 and CODE101 == True:
                speakerRegex = r"@\d+\r?\n(.*?)：?\r?\n" # Default: r"@\d+\r?\n(.*)：?\r?\n""
                textRegex = r"@\d+\r?\n.*?：?\r?\n(.*)" # Default: r"@\d+\r?\n.*：?\r?\n(.*)"

                # Grab String
                jaString = codeList[i]["stringArgs"][0]
                speaker = ""

                # Grab Speaker
                if "\n" in jaString:
                    match = re.search(speakerRegex, jaString)
                    if match:
                        # TL Speaker
                        response = getSpeaker(match.group(1))
                        speaker = response[0]
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]

                        # Set Name
                        codeList[i]["stringArgs"][0] = codeList[i]["stringArgs"][0].replace(match.group(1), speaker)

                # Grab Only Text
                match = re.search(textRegex, jaString, flags=re.DOTALL)
                if match:
                    jaString = match.group(1)
                    initialJAString = jaString

                    # Remove Textwrap
                    jaString = jaString.replace("\r", "")
                    jaString = jaString.replace("\n", " ")

                    # 1st Pass (Save Text to List)
                    if not setData:
                        if speaker == "":
                            stringList.append(jaString)
                        else:
                            stringList.append(f"[{speaker}]: {jaString}")

                    # 2nd Pass (Set Text)
                    else:
                        # Grab Translated String
                        translatedText = stringList[0]

                        # Remove speaker
                        matchSpeakerList = re.findall(r"^(\[.+?\]\s?[|:]\s?)\s?", translatedText)
                        if len(matchSpeakerList) > 0:
                            translatedText = translatedText.replace(matchSpeakerList[0], "")

                        # Textwrap
                        if FIXTEXTWRAP is True:
                            translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)

                        # Set Data
                        codeList[i]["stringArgs"][0] = codeList[i]["stringArgs"][0].replace(initialJAString, translatedText)

                        # Reset Data and Pop Item
                        stringList.pop(0)

            ### Event Code: 102 Choices
            if codeList[i]["code"] == 102 and CODE102 == True:
                # Grab Choice List
                choiceList = []
                jaChoiceList = codeList[i]["stringArgs"]

                # Filter Empty
                for j in range(len(jaChoiceList)):
                    if jaChoiceList[j]:
                        choiceList.append(jaChoiceList[j])

                # Translate
                if 'jaString' in locals():
                    choiceString = f"Previous Line: {jaString}\n\nReply with the {LANGUAGE} translation of the dialogue choice"
                else:
                    choiceString = f"Reply with the {LANGUAGE} translation of the dialogue choice"
                response = translateAI(
                    choiceList,
                    choiceString,
                    True,
                )
                translatedChoiceList = response[0]
                totalTokens[0] += response[1][0]
                totalTokens[1] += response[1][1]

                # Validate and Set Data
                if len(translatedChoiceList) == len(choiceList):
                    for j in range(len(jaChoiceList)):
                        if jaChoiceList[j]:
                            codeList[i]["stringArgs"][j] = translatedChoiceList[0]
                            translatedChoiceList.pop(0)

            ### Event Code: 210 Common Event
            if codeList[i]["code"] == 210 and CODE210 == True:
                # Speaker Event
                if "stringArgs" in codeList[i] and codeList[i]["intArgs"][0] == None and len(codeList[i]["stringArgs"]) == 2:
                    response = getSpeaker(codeList[i]["stringArgs"][1])
                    totalTokens[1] += response[1][0]
                    totalTokens[1] += response[1][1]

                    # Set Data
                    codeList[i]["stringArgs"][1] = response[0]

                # Logs
                elif "stringArgs" in codeList[i] and codeList[i]["intArgs"][0] == 500725 and len(codeList[i]["stringArgs"]) == 2:
                    # Grab String
                    jaString = codeList[i]["stringArgs"][1]
                    initialJAString = jaString

                    # Remove Textwrap
                    jaString = jaString.replace("\r", "")
                    jaString = jaString.replace("\n", " ")

                    # 1st Pass (Save Text to List)
                    if not setData:
                        list210.append(jaString)

                    # 2nd Pass (Set Text)
                    else:
                        # Grab Translated String
                        translatedText = list210[0]

                        # Textwrap
                        if FIXTEXTWRAP is True:
                            translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)

                        # Set Data
                        codeList[i]["stringArgs"][1] = translatedText

                        # Pop Item
                        list210.pop(0)

            ### Event Code: 122 SetString
            if codeList[i]["code"] == 122 and CODE122 == True:
                if "stringArgs" in codeList[i] and len(codeList[i]["stringArgs"]) > 0:
                    # Grab String
                    jaString = re.search(r"^\n?(.*)\n?$", codeList[i]["stringArgs"][0])
                    if jaString:
                        jaString = jaString.group(1)
                    else:
                        jaString = codeList[i]["stringArgs"][0]
    
                    originalString = jaString

                    # Remove Textwrap
                    jaString = jaString.replace("\r", "")
                    jaString = jaString.replace("\n", " ")

                    # Check if this is a translatable string
                    if (
                        not re.search(r"\.[\w]+$", jaString)
                        and jaString != ""
                        and "_" not in jaString
                        and '",' not in jaString
                        and "/" not in jaString
                        and re.search(LANGREGEX, jaString)
                    ):
                        # 1st Pass (Save Text to List)
                        if not setData:
                            list122.append(jaString)

                        # 2nd Pass (Set Text)
                        else:
                            if len(list122) > 0:
                                # Grab Translated String
                                translatedText = list122[0]

                                # Textwrap
                                if FIXTEXTWRAP is True:
                                    translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)

                                # Set Data
                                codeList[i]["stringArgs"][0] = codeList[i]["stringArgs"][0].replace(originalString, translatedText)

                                # Pop Item
                                list122.pop(0)

            ### Event Code: 150 Picture String
            if codeList[i]["code"] == 150 and CODE150 == True:
                if "stringArgs" in codeList[i] and len(codeList[i]["stringArgs"]) > 0:                    
                    font150 = "\\f[8]"
                    # Grab String
                    jaString = codeList[i]["stringArgs"][0]

                    # Japanses Text Only
                    if not re.search(r"[一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９]+", jaString):
                        i += 1
                        continue

                    # Remove Textwrap
                    # jaString = jaString.replace("\n", " ")
                    # jaString = jaString.replace("\r", "")

                    # Translate Other Strings [Specific Files Only]
                    if (
                        not re.search(r"\.[\w]+$", jaString)
                        and jaString != ""
                        and "_" not in jaString
                        and '",' not in jaString
                        # and ">" not in jaString
                        # and "<" not in jaString
                    ):
                        # Pass 1 (Save Text to List)
                        if not setData:
                            list150.append(jaString)

                        # Pass 2 (Set Text)
                        else:
                            translatedText = list150[0]

                            # Textwrap
                            # translatedText = dazedwrap.wrapText(translatedText, WIDTH)

                            # Set String with font formatting
                            codeList[i]["stringArgs"][0] = re.sub(r'\\f\[(\d+)\]', lambda x: f'\\f[{int(x.group(1))-2}]', translatedText)

                            # Pop processed item
                            list150.pop(0)

            ### Event Code: 300 Common Events
            if codeList[i]["code"] == 300 and CODE300 == True and "stringArgs" in codeList[i] and len(codeList[i]["stringArgs"]) > 1:
                # Choices
                if codeList[i]["stringArgs"][0] == "[共]汎用ウィンドウ生成" or codeList[i]["stringArgs"][0] == "選択肢/確認":
                    # Grab String
                    choiceList = codeList[i]["stringArgs"][1].split(",")

                    # Translate Question
                    question = codeList[i]['stringArgs'][2]
                    response = translateAI(question, "Reply with the {LANGUAGE} translation", False)
                    translatedText = response[0]
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]

                    # Translate Question
                    jaString = translatedText
                    codeList[i]['stringArgs'][2] = translatedText

                    # Translate Choices
                    if 'jaString' in locals() and jaString:
                        response = translateAI(choiceList, jaString, True)
                    else:
                        response = translateAI(choiceList, f"Reply with the {LANGUAGE} translation of the dialogue choice", True)
                    choiceListTL = response[0]
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]

                    # Replace Commas
                    for j in range(len(choiceListTL)):
                        choiceListTL[j] = choiceListTL[j].replace(", ", "、")

                    # Convert to String and Set
                    translatedText = ",".join(choiceListTL)
                    codeList[i]["stringArgs"][1] = translatedText

                # Dialogue
                elif codeList[i]["stringArgs"][0] == "サイド通知" or codeList[i]["stringArgs"][0] == "X[移]メニュー時文章表示":
                    jaString = codeList[i]["stringArgs"][1]

                    # Pass 1
                    if not setData:
                        # Remove Textwrap
                        jaString = jaString.replace("\n", " ")
                        jaString = jaString.replace("\r", "")

                        # Append
                        list300.append(jaString)

                    # Pass 2
                    else:
                        # Add Textwrap and Font
                        translatedText = dazedwrap.wrapText(list300[0], WIDTH)
                        list300.pop(0)

                        # Write to File
                        codeList[i]["stringArgs"][1] = translatedText
                
                # Dialogue
                elif codeList[i]["stringArgs"][0] == "援護文章":
                    speakerRegex = r"@\d+\r?\n(.*)：\r?\n" # Default: r"@\d+\r?\n(.*)：\r?\n"
                    textRegex = r"@?\d*\r?\n?\u3000*([\w\W]+)\r?\n?" # Default: r"@?\d*\r?\n?\u3000*([\w\W]+)\r?\n?"

                    # Grab String
                    jaString = codeList[i]["stringArgs"][1]
                    speaker = ""

                    # Grab Speaker
                    if "：\n" in jaString or "：\r\n" in jaString:
                        match = re.search(speakerRegex, jaString)
                        if match:
                            # TL Speaker
                            response = getSpeaker(match.group(1))
                            speaker = response[0]
                            totalTokens[0] += response[1][0]
                            totalTokens[1] += response[1][1]

                            # Set nametag and remove from string
                            codeList[i]["stringArgs"][1] = codeList[i]["stringArgs"][1].replace(match.group(1), speaker)
                            jaString = jaString.replace(match.group(0), "")

                    # Grab Only Text
                    match = re.search(textRegex, jaString)
                    if match:
                        jaString = match.group(1)
                        initialJAString = jaString

                        # Remove Textwrap
                        jaString = jaString.replace("\r", "")
                        jaString = jaString.replace("\n", " ")

                        # 1st Pass (Save Text to List)
                        if not setData:
                            if speaker == "":
                                list300.append(jaString)
                            else:
                                list300.append(f"[{speaker}]: {jaString}")

                        # 2nd Pass (Set Text)
                        else:
                            # Grab Translated String
                            translatedText = list300[0]

                            # Remove speaker
                            matchSpeakerList = re.findall(r"^(\[.+?\]\s?[|:]\s?)\s?", translatedText)
                            if len(matchSpeakerList) > 0:
                                translatedText = translatedText.replace(matchSpeakerList[0], "")

                            # Textwrap
                            if FIXTEXTWRAP is True:
                                translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)

                            # Set Data
                            codeList[i]["stringArgs"][1] = codeList[i]["stringArgs"][1].replace(initialJAString, translatedText)

                            # Reset Data and Pop Item
                            list300.pop(0)

            ### Event Code: 250 DB Read/Writes
            if codeList[i]["code"] == 250 and CODE250 == True:
                # Validate size
                stringArg = 2
                if len(codeList[i]["stringArgs"]) == 4:
                    if codeList[i]["stringArgs"][1] == "unit"\
                        and codeList[i]["stringArgs"][stringArg] != "":
                        # Font Size
                        fontSize = 0

                        # Grab String
                        jaString = codeList[i]["stringArgs"][stringArg]

                        # Remove Textwrap
                        # jaString = jaString.replace("\r", "")
                        # jaString = jaString.replace("\n", " ")

                        # Pass 1 (Save Text to List)
                        if not setData:
                            list250.append(jaString)

                        # Pass 2 (Set Text)
                        else:
                            translatedText = list250[0]
                            list250.pop(0)

                            # Textwrap
                            # translatedText = dazedwrap.wrapText(translatedText, WIDTH)

                            # Add/Replace font formatting
                            # Remove existing font command if present
                            translatedText = re.sub(r'\\f\[\d+\]', '', translatedText)
                            if fontSize:
                                # Add new font command if fontSize is not 0
                                if fontSize != "0" and fontSize != 0:
                                    translatedText = f"\\f[{fontSize}]{translatedText}"

                            # Set Data
                            codeList[i]["stringArgs"][stringArg] = translatedText

            ### Iterate
            i += 1

        # EOF
        stringListTL = []
        list210TL = []
        list150TL = []
        list250TL = []
        list300TL = []
        list122TL = []
        setData = False

        # String List
        if len(stringList) > 0:
            pbar.total = len(stringList)
            pbar.refresh()
            response = translateAI(stringList, textHistory, True)
            stringListTL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            if len(stringListTL) != len(stringList):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)
            else:
                setData = True

        # 210 List
        if len(list210) > 0:
            pbar.total = len(list210)
            pbar.refresh()
            response = translateAI(list210, textHistory, True)
            list210TL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            if len(list210TL) != len(list210):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)
            else:
                setData = True

        # 250 List
        if len(list250) > 0:
            pbar.total = len(list250)
            pbar.refresh()
            response = translateAI(list250, textHistory, True)
            list250TL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            if len(list250TL) != len(list250):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)
            else:
                setData = True

        # 300 List
        if len(list300) > 0:
            pbar.total = len(list300)
            pbar.refresh()
            response = translateAI(list300, textHistory, True)
            list300TL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            if len(list300TL) != len(list300):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)
            else:
                setData = True

        # 150 List
        if len(list150) > 0:
            # Progress Bar
            pbar.total = len(list150)
            pbar.refresh()

            # Translate
            response = translateAI(
                list150,
                textHistory,
                True,
            )
            list150TL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]

            # Check Mismatch
            if len(list150TL) != len(list150):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)
            else:
                list150 = list150TL
                setData = True

        # 122 List
        if len(list122) > 0:
            pbar.total = len(list122)
            pbar.refresh()
            response = translateAI(list122, textHistory, True)
            list122TL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            if len(list122TL) != len(list122):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)
            else:
                setData = True

        # Update jobList before recursive call
        if setData == True:
            stringList = []
            jobList = [stringListTL, list210TL, list300TL, list150TL, list250TL, list122TL]  # Add list122TL
            searchCodes(events, pbar, jobList, filename)

        else:
            # Set Data
            events = codeList

    except IndexError as e:
        traceback.print_exc()
        raise Exception(str(e) + "Failed to translate: " + initialJAString) from None
    except Exception as e:
        traceback.print_exc()
        raise Exception(str(e) + "Failed to translate: " + initialJAString) from None

    return totalTokens


def formatDramon(jaString):
    imageRegex = r"(\r?\n?_[a-zA-Z_\d/.]+\r?\n?)|(@-?\d?\r\n)|(@-?\d?)([^\r]\d?-?\d?[^\r]+?)(\r\n|$)|(_PDC)|(>\r\n)|(^[#])|(\r\n@$)|(/)|(_SS_)|(\r\n[@/]\s?-?\d?\r\n)"

    jaString = jaString.replace("\u3000", " ")
    jaString = jaString.replace("#", "")
    jaString = re.sub(r"([^\r])\n", r"\1\r\n", jaString)

    # Grab and Split
    jaStringList = re.split(imageRegex, jaString)

    # Clean List
    cleanedList = [x for x in jaStringList if x is not None and x != "" and x != "\r\n" and x != "_SS_"]

    # Iterate Through List
    j = 0
    translatedText = ""
    while j < len(cleanedList):
        if (
            ("@" in cleanedList[j] or "/" in cleanedList[j])
            and j < len(cleanedList) - 1
            and re.search(r"([@/]-?\d?\r\n)", cleanedList[j]) is None
            and ".ogg" not in cleanedList[j]
        ):
            # Setup @
            if j > 0 and "@" not in cleanedList[j - 1] and "/" not in cleanedList[j - 1] and "_" not in cleanedList[j - 1]:
                cleanedList[j - 1] = cleanedList[j - 1] + cleanedList[j + 1]
            else:
                cleanedList.insert(j, cleanedList[j + 1])
                j += 1
            cleanedList[j] = f"\r\n{cleanedList[j]}\r\n"
            cleanedList.pop(j + 1)
        j += 1

    return cleanedList

def handleScenarioScript(jaString, scriptString=""):
    # Extract Speaker
    scriptRegex = r"\n?(//.*?\n|//.*|/b.*?\n|[\w]+：\d*.*?\n)"
    match = re.search(scriptRegex, jaString)
    if match:
        if "//" in match.group(1):
            scriptStringLocal = match.group(1)
            jaString = jaString.replace(scriptStringLocal, "")
            scriptString += scriptStringLocal
            match = re.search(scriptRegex, jaString)
            if not match:
                return None
            else:
                if "//" in jaString:
                    return handleScenarioScript(jaString, scriptString)
        return [jaString, match.group(1), scriptString]
    else:
        return None

# Database
def searchDB(events, pbar, jobList, filename):
    # Set Lists
    if len(jobList) > 0:
        scenarioList = jobList[0]
        npcList = jobList[1]
        itemList = jobList[2]
        stateList = jobList[3]
        armorList = jobList[4]
        enemyList = jobList[5]
        weaponsList = jobList[6]
        skillList = jobList[7]
        optionsList = jobList[8]
        dbNameList = jobList[9]
        dbValueList = jobList[10]
        setData = True
    else:
        scenarioList = [[], [], []]
        npcList = [[], [], [], []]
        itemList = [[], [], [], []]
        armorList = [[], []]
        enemyList = [[], []]
        weaponsList = [[], [], [], []]
        skillList = [[], [], [], [], []]
        stateList = [[], [], [], [], [], [], [], []]
        optionsList = [[], [], []]
        dbNameList = [[]]
        dbValueList = [[]]
        setData = False

    # Vars/Globals
    totalTokens = [0, 0]
    initialJAString = ""
    tableList = events
    font = ""
    global LOCK
    global NAMESLIST
    global MISMATCH
    global PBAR
    PBAR = pbar

    # Begin Parsing File
    try:
        for table in tableList:
            # Grab NPCs
            if table["name"] == "戦闘コマンド" and NPCFLAG == True:
                with open("translations.txt", "a", encoding="utf-8") as file:
                    if setData:
                        file.write(f"\n#Actors\n")
                    for npc in table["data"]:
                        dataList = npc["data"]

                        # Parse
                        for j in range(len(dataList)):
                            # Name
                            if dataList[j].get("name") == "コマンド名":
                                # Pass 1 (Grab Data)
                                if setData == False:
                                    if dataList[j].get("value") != "":
                                        npcList[0].append(dataList[j].get("value"))

                                # Pass 2 (Set Data)
                                else:
                                    if dataList[j].get("value") != "":
                                        # Write Name
                                        file.write(f"{dataList[j].get('value')} ({npcList[0][0]})\n")

                                        # Set Data
                                        dataList[j].update({"value": npcList[0][0]})
                                        npcList[0].pop(0)

                            # Description
                            if dataList[j].get("name") == "コマンドの説明文":
                                # Pass 1 (Grab Data)
                                if setData == False:
                                    if dataList[j].get("value") != "":
                                        # Remove Textwrap
                                        jaString = dataList[j].get("value")
                                        jaString = jaString.replace("\n", " ")
                                        jaString = jaString.replace("\r", "")
                                        jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                        # Append Data
                                        npcList[1].append(jaString)
                                # Pass 2 (Set Data)
                                else:
                                    if dataList[j].get("value") != "":
                                        # Textwrap
                                        translatedText = npcList[1][0]
                                        translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)
                                        translatedText = font + translatedText

                                        # Set Data
                                        dataList[j].update({"value": translatedText})
                                        npcList[1].pop(0)

            # Grab Scenario
            if "サブキャラ会話" in table["name"] and SCENARIOFLAG == True:
                for scenario in table["data"]:
                    dataList = scenario["data"]

                    # Parse
                    for j in range(len(dataList)):
                        # Name
                        if dataList[j].get("name") == "ルカ好感度MAX":
                            if dataList[j].get("value"):
                                jaStringList = re.split(r'\r\n\r\n|\n\n', dataList[j].get("value"))
                                for jaString in jaStringList:
                                    speakerNum = None
                                    ogString = jaString
                                    # Extract Speaker
                                    speakerList = handleScenarioScript(jaString)
                                    if not speakerList:
                                        continue
                                    if speakerList[2]:
                                        jaString = speakerList[0]
                                    speakerNumMatch = re.search(r"：(\d+)", speakerList[1])
                                    if speakerNumMatch:
                                        speakerNum = speakerNumMatch.group(1)
                                    speaker = re.sub(r"：\d*", "", speakerList[1])
                                    speaker = re.sub(r"/b", "NPC", speaker)
                                    speaker = speaker.replace("\r\n", "")
                                    
                                    # Add Speaker
                                    jaString = jaString.replace(speakerList[1], f"[{speaker}]: ")

                                    # Pass 1 (Grab Data)
                                    if setData == False:
                                        jaString = jaString.replace("\n", " ")
                                        jaString = jaString.replace("\r", "")
                                        scenarioList[0].append(jaString)

                                    # Pass 2 (Set Data)
                                    else:
                                        translatedText = scenarioList[0][0]
                                        scenarioList[0].pop(0)
                                        translatedText = dazedwrap.wrapText(translatedText, WIDTH)

                                        # Remove Speaker
                                        speakerMatch = re.search(r"\[(.+?)\]\s?[|:]\s?", translatedText)
                                        if speakerMatch:
                                            speaker = speakerMatch.group(1).strip()
                                        match = re.search(r'(^\[.+?\]\s?[|:]\s?)', translatedText)
                                        if match:
                                            translatedText = translatedText.replace(match.group(1), "") 

                                        # Redo Old Speaker Format
                                        speaker = speaker.replace("Speaker", "\b")
                                        if speakerNum:
                                            translatedText = f"{speaker}：{speakerNum}\r\n{translatedText}"
                                        elif speaker == "NPC":
                                            translatedText = f"/b\r\n{translatedText}"
                                        else:
                                            translatedText = f"{speaker}：\r\n{translatedText}"

                                        # Add Script String
                                        if speakerList[2]:
                                            translatedText = f"{speakerList[2]}{translatedText}"

                                        # Set Data
                                        dataList[j].update({"value": dataList[j].get("value").replace(ogString, translatedText)})
                        # Description
                        if dataList[j].get("name") == "NULL":
                            if dataList[j].get("value"):
                                jaStringList = re.split(r'\r\n\r\n|\n\n', dataList[j].get("value"))
                                for jaString in jaStringList:
                                    speakerNum = None
                                    ogString = jaString
                                    # Extract Speaker
                                    speakerList = handleScenarioScript(jaString)
                                    if not speakerList:
                                        continue
                                    if speakerList[2]:
                                        jaString = speakerList[0]
                                    speakerNumMatch = re.search(r"：(\d+)", speakerList[1])
                                    if speakerNumMatch:
                                        speakerNum = speakerNumMatch.group(1)
                                    speaker = re.sub(r"：\d*", "", speakerList[1])
                                    speaker = re.sub(r"/b", "NPC", speaker)
                                    speaker = speaker.replace("\r\n", "")
                                    
                                    # Add Speaker
                                    jaString = jaString.replace(speakerList[1], f"[{speaker}]: ")

                                    # Pass 1 (Grab Data)
                                    if setData == False:
                                        jaString = jaString.replace("\n", " ")
                                        jaString = jaString.replace("\r", "")
                                        scenarioList[1].append(jaString)

                                    # Pass 2 (Set Data)
                                    else:
                                        translatedText = scenarioList[1][0]
                                        scenarioList[1].pop(0)
                                        translatedText = dazedwrap.wrapText(translatedText, WIDTH)

                                        # Remove Speaker
                                        speakerMatch = re.search(r"\[(.+?)\]\s?[|:]\s?", translatedText)
                                        if speakerMatch:
                                            speaker = speakerMatch.group(1).strip()
                                        match = re.search(r'(^\[.+?\]\s?[|:]\s?)', translatedText)
                                        if match:
                                            translatedText = translatedText.replace(match.group(1), "") 

                                        # Redo Old Speaker Format
                                        speaker = speaker.replace("Speaker", "\b")
                                        if speakerNum:
                                            translatedText = f"{speaker}：{speakerNum}\r\n{translatedText}"
                                        elif speaker == "NPC":
                                            translatedText = f"/b\r\n{translatedText}"
                                        else:
                                            translatedText = f"{speaker}：\r\n{translatedText}"

                                        # Add Script String
                                        if speakerList[2]:
                                            translatedText = f"{speakerList[2]}{translatedText}"

                                        # Set Data
                                        dataList[j].update({"value": dataList[j].get("value").replace(ogString, translatedText)})

                        # Description
                        if dataList[j].get("name") == "NULL":
                            if dataList[j].get("value"):
                                jaStringList = re.split(r'\r\n\r\n|\n\n', dataList[j].get("value"))
                                for jaString in jaStringList:
                                    speakerNum = None
                                    ogString = jaString
                                    # Extract Speaker
                                    speakerList = handleScenarioScript(jaString)
                                    if not speakerList:
                                        continue
                                    if speakerList[2]:
                                        jaString = speakerList[0]
                                    speakerNumMatch = re.search(r"：(\d+)", speakerList[1])
                                    if speakerNumMatch:
                                        speakerNum = speakerNumMatch.group(1)
                                    speaker = re.sub(r"：\d*", "", speakerList[1])
                                    speaker = re.sub(r"/b", "NPC", speaker)
                                    speaker = speaker.replace("\r\n", "")
                                    
                                    # Add Speaker
                                    jaString = jaString.replace(speakerList[1], f"[{speaker}]: ")

                                    # Pass 1 (Grab Data)
                                    if setData == False:
                                        jaString = jaString.replace("\n", " ")
                                        jaString = jaString.replace("\r", "")
                                        scenarioList[2].append(jaString)

                                    # Pass 2 (Set Data)
                                    else:
                                        translatedText = scenarioList[2][0]
                                        scenarioList[2].pop(0)
                                        translatedText = dazedwrap.wrapText(translatedText, WIDTH)

                                        # Remove Speaker
                                        speakerMatch = re.search(r"\[(.+?)\]\s?[|:]\s?", translatedText)
                                        if speakerMatch:
                                            speaker = speakerMatch.group(1).strip()
                                        match = re.search(r'(^\[.+?\]\s?[|:]\s?)', translatedText)
                                        if match:
                                            translatedText = translatedText.replace(match.group(1), "") 

                                        # Redo Old Speaker Format
                                        speaker = speaker.replace("Speaker", "\b")
                                        if speakerNum:
                                            translatedText = f"{speaker}：{speakerNum}\r\n{translatedText}"
                                        elif speaker == "NPC":
                                            translatedText = f"/b\r\n{translatedText}"
                                        else:
                                            translatedText = f"{speaker}：\r\n{translatedText}"

                                        # Add Script String
                                        if speakerList[2]:
                                            translatedText = f"{speakerList[2]}{translatedText}"

                                        # Set Data
                                        dataList[j].update({"value": dataList[j].get("value").replace(ogString, translatedText)})

            # Grab Options
            if table["name"] == "用語設定" and OPTIONSFLAG == True:
                for option in table["data"]:
                    dataList = option["data"]

                    # Parse
                    for j in range(len(dataList)):
                        # Name
                        if dataList[j].get("name") == "イベント名":
                            if dataList[j].get("value"):
                                jaString = dataList[j].get("value")
                                # Pass 1 (Grab Data)
                                if setData == False:
                                    optionsList[0].append(jaString)

                                # Pass 2 (Set Data)
                                else:
                                    translatedText = optionsList[0][0]
                                    optionsList[0].pop(0)
                                    dataList[j].update({"value": dataList[j].get("value").replace(jaString, translatedText)})

                        # Description 1
                        if dataList[j].get("name") == "プロフ":
                            if dataList[j].get("value"):
                                jaString = dataList[j].get("value")
                                # Pass 1 (Grab Data)
                                if setData == False:
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    optionsList[1].append(jaString)

                                # Pass 2 (Set Data)
                                else:
                                    translatedText = optionsList[1][0]
                                    optionsList[1].pop(0)
                                    translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)
                                    dataList[j].update({"value": dataList[j].get("value").replace(jaString, translatedText)})

                        # Description 2
                        if dataList[j].get("name") == "防御破壊文言":
                            if dataList[j].get("value"):
                                jaString = dataList[j].get("value")
                                # Pass 1 (Grab Data)
                                if setData == False:
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    optionsList[2].append(jaString)

                                # Pass 2 (Set Data)
                                else:
                                    translatedText = optionsList[2][0]
                                    optionsList[2].pop(0)
                                    translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)
                                    dataList[j].update({"value": dataList[j].get("value").replace(jaString, translatedText)})

            # Grab DB Names
            if table["name"] == "マップ設定" and DBNAMEFLAG == True:
                font = None
                dbName = table["data"]
                for j in range(len(dbName)):
                    # Pass 1 (Grab Data)
                    if setData == False:
                        if dbName[j].get("name") != "":
                            dbNameList[0].append(dbName[j].get("name"))

                    # Pass 2 (Set Data)
                    else:
                        if dbName[j].get("name") != "":
                            dbName[j].update({"name": dbNameList[0][0]})
                            dbNameList[0].pop(0)

            # Grab DB Values
            if table["name"] == "近況文章" and DBVALUEFLAG == True:
                font = 16
                subject = ""
                for entry in table["data"]:
                    dbValue = entry["data"]
                    for j in range(len(dbValue)):
                        if dbValue[j].get("value"):
                            jaString = dbValue[j].get("value")

                            # Speaker
                            match = re.search(r"(^[\\]+f\[\d+\].+?\r\n).+", jaString)
                            if match:
                                subject = match.group(1)
                                jaString = jaString.replace(subject, "")

                                # Nuke Textwrap & Font
                                jaString = jaString.replace("\r", "")
                                jaString = jaString.replace("\n", " ")
                                jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                # Pass 1 (Grab Data)
                                if setData == False:
                                    # Append
                                    dbValueList[0].append(jaString)

                                # Pass 2 (Set Data)
                                else:
                                    if dbValue[j].get("value"):
                                        translatedText = dbValueList[0][0]

                                        # Textwrap
                                        translatedText = dazedwrap.wrapText(translatedText, 30)
                                        translatedText = translatedText.replace("\n", f"\r\n\\f[{font}]")

                                        # Subject
                                        if subject:
                                            translatedText = f"{subject}{translatedText}"

                                        # Set
                                        dbValue[j].update({"value": translatedText})
                                        dbValueList[0].pop(0)

            # Grab Items
            if table["name"] == "アイテム" and ITEMFLAG == True:
                # Write Category
                if setData:
                    with open("translations.txt", "a", encoding="utf-8") as file:
                        file.write(f"\n#Items\n")

                # Begin Translation
                for item in table["data"]:
                    dataList = item["data"]

                    # Parse
                    font = 20
                    for j in range(len(dataList)):
                        # Name
                        if dataList[j].get("name") == "アイテム名":
                            jaString = dataList[j].get("value")
                            if jaString != "":
                                # Pass 1 (Grab Data)
                                if setData == False:
                                    if jaString != "":
                                        itemList[0].append(jaString)

                                # Pass 2 (Set Data)
                                else:
                                    # Write to TL File
                                    with open("translations.txt", "a", encoding="utf-8") as file:
                                        file.write(f"{jaString} ({itemList[0][0]})\n")

                                    dataList[j].update({"value": itemList[0][0]})
                                    itemList[0].pop(0)

                        # Description
                        if dataList[j].get("name") == "説明文[2行まで可]":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    # Remove Textwrap & Font
                                    jaString = dataList[j].get("value")
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                    # Append Data
                                    itemList[1].append(jaString)
                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    # Textwrap
                                    translatedText = itemList[1][0]
                                    translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)

                                    # Font
                                    if font:
                                        translatedText = f"\\f[{font}]{translatedText}"

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    itemList[1].pop(0)

                        # Log
                        if dataList[j].get("name") == "使用時文章[戦](人名~":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    # Remove Textwrap
                                    jaString = dataList[j].get("value")
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                    # Skill Action
                                    if jaString[0] in [
                                        "は",
                                        "を",
                                        "の",
                                        "に",
                                        "が",
                                    ]:
                                        jaString = f"Taro{jaString}"

                                    # Append Data
                                    itemList[2].append(jaString)
                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    # Textwrap
                                    translatedText = itemList[2][0]
                                    translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)
                                    # translatedText = font + translatedText

                                    # Remove Taro
                                    translatedText = re.sub(r"\bTaro\b", "", translatedText)

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    itemList[2].pop(0)

                        # Description
                        if dataList[j].get("name") == "使用後文章[移動]":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    # Remove Textwrap
                                    jaString = dataList[j].get("value")
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                    # Append Data
                                    itemList[3].append(jaString)
                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    # Textwrap
                                    translatedText = itemList[3][0]
                                    translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)

                                    # Font
                                    if font:
                                        translatedText = f"\\f[{font}]{translatedText}"

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    itemList[3].pop(0)

            # Grab Armors
            if table["name"] == "防具" and ARMORFLAG == True:
                font = "24"
                for armor in table["data"]:
                    dataList = armor["data"]

                    # Parse
                    for j in range(len(dataList)):
                        # Name
                        if dataList[j].get("name") == "防具の名前":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    armorList[0].append(dataList[j].get("value"))

                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    dataList[j].update({"value": armorList[0][0]})
                                    armorList[0].pop(0)

                        # Description
                        if dataList[j].get("name") == "防具の説明[2行まで可]":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    # Remove Textwrap
                                    jaString = dataList[j].get("value")
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                    # Append Data
                                    armorList[1].append(jaString)
                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    # Textwrap
                                    translatedText = armorList[1][0]
                                    translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)

                                    # Font
                                    if font:
                                        translatedText = f"\\f[{font}]{translatedText}"

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    armorList[1].pop(0)

            # Grab Enemies
            if table["name"] == "敵ｷｬﾗ個体ﾃﾞｰﾀ" and ENEMYFLAG == True:
                for enemy in table["data"]:
                    dataList = enemy["data"]

                    # Parse
                    for j in range(len(dataList)):
                        # Name
                        if dataList[j].get("name") == "敵キャラ名":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    enemyList[0].append(dataList[j].get("value"))

                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    dataList[j].update({"value": enemyList[0][0]})
                                    enemyList[0].pop(0)

                        # Description
                        if dataList[j].get("name") == "NULL":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    # Remove Textwrap
                                    jaString = dataList[j].get("value")
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                    # Append Data
                                    enemyList[1].append(jaString)
                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    # Textwrap
                                    translatedText = enemyList[1][0]
                                    translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)

                                    # Font
                                    if font:
                                        translatedText = f"\\f[{font}]{translatedText}"

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    enemyList[1].pop(0)

            # Grab Weapons
            if table["name"] == "武器" and WEAPONFLAG == True:
                font = "24"
                for weapon in table["data"]:
                    dataList = weapon["data"]

                    # Parse
                    for j in range(len(dataList)):
                        # Name
                        if dataList[j].get("name") == "武器の名前":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    weaponsList[0].append(dataList[j].get("value"))

                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    dataList[j].update({"value": weaponsList[0][0]})
                                    weaponsList[0].pop(0)

                        # Description
                        if dataList[j].get("name") == "武器の説明[2行まで可]":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    # Remove Textwrap
                                    jaString = dataList[j].get("value")
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                    # Append Data
                                    weaponsList[1].append(jaString)
                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    # Textwrap
                                    translatedText = weaponsList[1][0]
                                    translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)

                                    # Font
                                    if font:
                                        translatedText = f"\\f[{font}]{translatedText}"

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    weaponsList[1].pop(0)

            # Grab Skills
            if table["name"] == "技能" and SKILLFLAG == True:
                font = "24"
                for skill in table["data"]:
                    dataList = skill["data"]

                    # Parse
                    for j in range(len(dataList)):
                        # Name
                        if dataList[j].get("name") == "技能の名前":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    skillList[0].append(dataList[j].get("value"))

                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    dataList[j].update({"value": skillList[0][0]})
                                    skillList[0].pop(0)

                        # Description
                        if dataList[j].get("name") == "説明":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    # Remove Textwrap
                                    jaString = dataList[j].get("value")
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                    # Append Data
                                    skillList[1].append(jaString)

                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    # Textwrap
                                    translatedText = skillList[1][0]
                                    translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)

                                    # Font
                                    if font:
                                        translatedText = f"\\f[{font}]{translatedText}"

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    skillList[1].pop(0)

                        # Log
                        if dataList[j].get("name") == "発動時文章":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    # Remove Textwrap
                                    jaString = dataList[j].get("value")
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                    # Skill Action
                                    if jaString[0] in [
                                        "は",
                                        "を",
                                        "の",
                                        "に",
                                        "が",
                                    ]:
                                        jaString = f"Taro{jaString}"

                                    # Append Data
                                    skillList[2].append(jaString)
                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    # Textwrap
                                    translatedText = skillList[2][0]
                                    translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)
                                    translatedText = font + translatedText

                                    # Remove Taro
                                    translatedText = re.sub(r"\bTaro\b", "", translatedText)

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    skillList[2].pop(0)

                        # Log
                        if dataList[j].get("name") == "使用時文章[戦闘](人名~":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    # Remove Textwrap
                                    jaString = dataList[j].get("value")
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                    # Skill Action
                                    if jaString[0] in [
                                        "は",
                                        "を",
                                        "の",
                                        "に",
                                        "が",
                                    ]:
                                        jaString = f"Taro{jaString}"

                                    # Append Data
                                    skillList[3].append(jaString)
                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    # Textwrap
                                    translatedText = skillList[3][0]
                                    translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)

                                    # Remove Taro
                                    translatedText = re.sub(r"\bTaro\b", "", translatedText)

                                    # Font
                                    translatedText = font + translatedText

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    skillList[3].pop(0)

                        # Log
                        if dataList[j].get("name") == "失敗時文章[(対象)～]":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    # Remove Textwrap
                                    jaString = dataList[j].get("value")
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                    # Skill Action
                                    if jaString[0] in [
                                        "は",
                                        "を",
                                        "の",
                                        "に",
                                        "が",
                                    ]:
                                        jaString = f"Taro{jaString}"

                                    # Append Data
                                    skillList[4].append(jaString)
                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    # Textwrap
                                    translatedText = skillList[4][0]
                                    translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)
                                    translatedText = font + translatedText

                                    # Remove Taro
                                    translatedText = re.sub(r"\bTaro\b", "", translatedText)

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    skillList[4].pop(0)

            # Grab States
            if table["name"] == "状態設定" and STATEFLAG == True:
                for state in table["data"]:
                    dataList = state["data"]

                    # Parse
                    for j in range(len(dataList)):
                        # Name
                        if dataList[j].get("name") == "状態名":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    stateList[0].append(dataList[j].get("value"))

                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    dataList[j].update({"value": stateList[0][0]})
                                    stateList[0].pop(0)

                        # Description
                        if dataList[j].get("name") == "表示名":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    # Remove Textwrap
                                    jaString = dataList[j].get("value")
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                    # Append Data
                                    stateList[1].append(jaString)
                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    # Textwrap
                                    translatedText = stateList[1][0]
                                    translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)
                                    translatedText = font + translatedText

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    stateList[1].pop(0)

                        # Log
                        if dataList[j].get("name") == "発生時の文章[(人名)～]":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    # Remove Textwrap
                                    jaString = dataList[j].get("value")
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                    # State Action
                                    if jaString[0] in [
                                        "は",
                                        "を",
                                        "の",
                                        "に",
                                        "が",
                                    ]:
                                        jaString = f"Taro{jaString}"

                                    # Append Data
                                    stateList[2].append(jaString)
                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    # Textwrap
                                    translatedText = stateList[2][0]
                                    translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)
                                    translatedText = font + translatedText

                                    # Remove Taro
                                    translatedText = re.sub(r"\bTaro\b", "", translatedText)

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    stateList[2].pop(0)

                        # Log
                        if dataList[j].get("name") == "行動制限時文章(空欄:ﾅｼ":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    # Remove Textwrap
                                    jaString = dataList[j].get("value")
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                    # State Action
                                    if jaString[0] in [
                                        "は",
                                        "を",
                                        "の",
                                        "に",
                                        "が",
                                    ]:
                                        jaString = f"Taro{jaString}"

                                    # Append Data
                                    stateList[3].append(jaString)
                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    # Textwrap
                                    translatedText = stateList[3][0]
                                    translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)
                                    translatedText = font + translatedText

                                    # Remove Taro
                                    translatedText = re.sub(r"\bTaro\b", "", translatedText)

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    stateList[3].pop(0)

                        # Log
                        if dataList[j].get("name") == "回復時の文章[(人名)～]":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    # Remove Textwrap
                                    jaString = dataList[j].get("value")
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                    # State Action
                                    if jaString[0] in [
                                        "は",
                                        "を",
                                        "の",
                                        "に",
                                        "が",
                                    ]:
                                        jaString = f"Taro{jaString}"

                                    # Append Data
                                    stateList[4].append(jaString)
                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    # Textwrap
                                    translatedText = stateList[4][0]
                                    translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)
                                    translatedText = font + translatedText

                                    # Remove Taro
                                    translatedText = re.sub(r"\bTaro\b", "", translatedText)

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    stateList[4].pop(0)
                        # Log
                        if dataList[j].get("name") == "┣ ｶｳﾝﾀｰ発動文[対象～":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    # Remove Textwrap
                                    jaString = dataList[j].get("value")
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                    # State Action
                                    if jaString[0] in [
                                        "は",
                                        "を",
                                        "の",
                                        "に",
                                        "が",
                                    ]:
                                        jaString = f"Taro{jaString}"

                                    # Append Data
                                    stateList[5].append(jaString)
                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    # Textwrap
                                    translatedText = stateList[5][0]
                                    translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)
                                    translatedText = font + translatedText

                                    # Remove Taro
                                    translatedText = re.sub(r"\bTaro\b", "", translatedText)

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    stateList[5].pop(0)

                        # Log
                        if dataList[j].get("name") == "尻もち　行動不能　持続3ターン":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    # Remove Textwrap
                                    jaString = dataList[j].get("value")
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                    # State Action
                                    if jaString[0] in [
                                        "は",
                                        "を",
                                        "の",
                                        "に",
                                        "が",
                                    ]:
                                        jaString = f"Taro{jaString}"

                                    # Append Data
                                    stateList[6].append(jaString)
                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    # Textwrap
                                    translatedText = stateList[6][0]
                                    translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)
                                    translatedText = font + translatedText

                                    # Remove Taro
                                    translatedText = re.sub(r"\bTaro\b", "", translatedText)

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    stateList[6].pop(0)

                        # Log
                        if dataList[j].get("name") == "状態異常の説明":
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    # Remove Textwrap
                                    jaString = dataList[j].get("value")
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                    # State Action
                                    if jaString[0] in [
                                        "は",
                                        "を",
                                        "の",
                                        "に",
                                        "が",
                                    ]:
                                        jaString = f"Taro{jaString}"

                                    # Append Data
                                    stateList[7].append(jaString)
                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    # Textwrap
                                    translatedText = stateList[7][0]
                                    translatedText = dazedwrap.wrapText(translatedText, LISTWIDTH)
                                    translatedText = font + translatedText

                                    # Remove Taro
                                    translatedText = re.sub(r"\bTaro\b", "", translatedText)

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    stateList[7].pop(0)

        # Translation
        scenarioListTL = [[], [], []]
        optionsListTL = [[], [], []]
        npcListTL = [[], [], [], []]
        itemListTL = [[], [], [], []]
        stateListTL = [[], [], [], [], [], [], [], []]
        armorListTL = [[], []]
        enemyListTL = [[], []]
        weaponsListTL = [[], [], []]
        skillListTL = [[], [], [], [], []]
        dbNameListTL = [[]]
        dbValueListTL = [[]]

        translate = False

        # NPCs
        if len(npcList[0]) > 0:
            # Progress Bar
            total = 0
            for itemArray in npcList:
                total += len(itemArray)
            pbar.total = total
            pbar.refresh()

            # Name
            response = translateAI(
                npcList[0],
                "Reply with only the " + LANGUAGE + " translation of the RPG enemy name",
                True,
            )
            nameListTL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            # Desc 1
            response = translateAI(npcList[1], "Reply with only the " + LANGUAGE + " translation", True)
            descListTL1 = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            # Desc 2
            response = translateAI(npcList[2], "Reply with only the " + LANGUAGE + " translation", True)
            descListTL2 = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            # Desc 3
            response = translateAI(npcList[3], "Reply with only the " + LANGUAGE + " translation", True)
            descListTL3 = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]

            # Check Mismatch
            if (
                len(nameListTL) != len(npcList[0])
                or len(descListTL1) != len(npcList[1])
                or len(descListTL2) != len(npcList[2])
                or len(descListTL3) != len(npcList[3])
            ):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)
            else:
                npcListTL = [nameListTL, descListTL1, descListTL2, descListTL3]
                translate = True

        # SCENARIO
        if scenarioList[0] or scenarioList[1]:
            # Progress Bar
            total = 0
            for scenarioArray in scenarioList:
                total += len(scenarioArray)
            pbar.total = total
            pbar.refresh()

            # Name
            response = translateAI(
                scenarioList[0],
                "Reply with only the " + LANGUAGE + " translation",
                True,
            )
            nameListTL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            # Desc 1
            response = translateAI(
                scenarioList[1],
                "reply with only the gender neutral " + LANGUAGE + " translation of the NPC name",
                True,
            )
            descListTL1 = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            # Desc 2
            response = translateAI(
                scenarioList[2],
                "reply with only the gender neutral " + LANGUAGE + " translation of the NPC name",
                True,
            )
            descListTL2 = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]

            # Check Mismatch
            if len(nameListTL) != len(scenarioList[0]) or len(descListTL1) != len(scenarioList[1]) or len(descListTL2) != len(scenarioList[2]):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)
            else:
                scenarioListTL = [nameListTL, descListTL1, descListTL2]
                translate = True

        # OPTIONS
        if optionsList[0] or optionsList[1]:
            # Progress Bar
            total = 0
            for optionsArray in optionsList:
                total += len(optionsArray)
            pbar.total = total
            pbar.refresh()

            # Name
            response = translateAI(
                optionsList[0],
                "Reply with only the " + LANGUAGE + " translation",
                True,
            )
            nameListTL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            # Desc 1
            response = translateAI(
                optionsList[1],
                "reply with only the gender neutral " + LANGUAGE + " translation of the NPC name",
                True,
            )
            descListTL1 = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            # Desc 2
            response = translateAI(
                optionsList[2],
                "reply with only the gender neutral " + LANGUAGE + " translation of the NPC name",
                True,
            )
            descListTL2 = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]

            # Check Mismatch
            if len(nameListTL) != len(optionsList[0]) or len(descListTL1) != len(optionsList[1]) or len(descListTL2) != len(optionsList[2]):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)
            else:
                optionsListTL = [nameListTL, descListTL1, descListTL2]
                translate = True

        # ITEMS
        if len(itemList[0]) > 0 or len(itemList[1]) > 0:
            # Progress Bar
            total = 0
            for itemArray in itemList:
                total += len(itemArray)
            pbar.total = total
            pbar.refresh()

            # Name
            response = translateAI(itemList[0], "Reply with only the " + LANGUAGE + " translation", True)
            nameListTL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            # Desc 1
            response = translateAI(itemList[1], "Reply with only the " + LANGUAGE + " translation", True)
            descListTL1 = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            # Desc 2
            response = translateAI(itemList[2], "Reply with only the " + LANGUAGE + " translation", True)
            descListTL2 = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            # Desc 3
            response = translateAI(itemList[3], "Reply with only the " + LANGUAGE + " translation", True)
            descListTL3 = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]

            # Check Mismatch
            if (
                len(nameListTL) != len(itemList[0])
                or len(descListTL1) != len(itemList[1])
                or len(descListTL2) != len(itemList[2])
                or len(descListTL3) != len(itemList[3])
            ):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)
            else:
                itemListTL = [nameListTL, descListTL1, descListTL2, descListTL3]
                translate = True

        # Armor
        if len(armorList[0]) > 0:
            # Progress Bar
            total = 0
            for armorArray in armorList:
                total += len(armorArray)
            pbar.total = total
            pbar.refresh()

            # Name
            response = translateAI(
                armorList[0],
                "Reply with only the " + LANGUAGE + " translation of the NPC name",
                True,
            )
            nameListTL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            # Desc 1
            response = translateAI(armorList[1], "Reply with only the " + LANGUAGE + " translation", True)
            descListTL1 = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]

            # Check Mismatch
            if len(nameListTL) != len(armorList[0]) or len(descListTL1) != len(armorList[1]):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)
            else:
                armorListTL = [nameListTL, descListTL1]
                translate = True

        # Enemies
        if len(enemyList[0]) > 0:
            # Progress Bar
            total = 0
            for enemyArray in enemyList:
                total += len(enemyArray)
            pbar.total = total
            pbar.refresh()

            # Name
            response = translateAI(
                enemyList[0],
                "Reply with only the " + LANGUAGE + " translation of the enemy NPC name",
                True,
            )
            nameListTL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            # Desc 1
            response = translateAI(enemyList[1], "Reply with only the " + LANGUAGE + " translation", True)
            descListTL1 = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]

            # Check Mismatch
            if len(nameListTL) != len(enemyList[0]) or len(descListTL1) != len(enemyList[1]):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)
            else:
                enemyListTL = [nameListTL, descListTL1]
                translate = True

        # Weapons
        if len(weaponsList[0]) > 0:
            # Progress Bar
            total = 0
            for weaponsArray in weaponsList:
                total += len(weaponsArray)
            pbar.total = total
            pbar.refresh()

            # Name
            response = translateAI(
                weaponsList[0],
                "Reply with only the " + LANGUAGE + " translation of the RPG weapon name",
                True,
            )
            nameListTL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            # Desc 1
            response = translateAI(weaponsList[1], "", True)
            descListTL1 = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            # Desc 2
            response = translateAI(weaponsList[2], "", True)
            descListTL2 = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]

            # Check Mismatch
            if len(nameListTL) != len(weaponsList[0]) or len(descListTL1) != len(weaponsList[1]) or len(descListTL2) != len(weaponsList[2]):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)
            else:
                weaponsListTL = [nameListTL, descListTL1, descListTL2]
                translate = True

        # Skills
        if len(skillList[0]) > 0:
            # Progress Bar
            total = 0
            for skillArray in skillList:
                total += len(skillArray)
            pbar.total = total
            pbar.refresh()

            # Name
            response = translateAI(
                skillList[0],
                "Reply with only the " + LANGUAGE + " translation of the RPG skill name",
                True,
            )
            nameListTL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]

            # Desc
            response = translateAI(
                skillList[1],
                "Reply with only the " + LANGUAGE + " translation of the RPG skill description",
                True,
            )
            descListTL1 = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]

            # Log 1
            response = translateAI(
                skillList[2],
                "reply with only the gender neutral "
                + LANGUAGE
                + " translation of the action log. Always start the sentence with Taro. For example, Translate 'Taroを倒した！' as 'Taro was defeated!'",
                True,
            )
            descListTL2 = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]

            # Log 2
            response = translateAI(
                skillList[3],
                "reply with only the gender neutral "
                + LANGUAGE
                + " translation of the action log. Always start the sentence with Taro. For example, Translate 'Taroを倒した！' as 'Taro was defeated!'",
                True,
            )
            descListTL3 = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]

            # Log 3
            response = translateAI(
                skillList[4],
                "reply with only the gender neutral "
                + LANGUAGE
                + " translation of the action log. Always start the sentence with Taro. For example, Translate 'Taroを倒した！' as 'Taro was defeated!'",
                True,
            )
            descListTL4 = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]

            # Check Mismatch
            if (
                len(nameListTL) != len(skillList[0])
                or len(descListTL1) != len(skillList[1])
                or len(descListTL2) != len(skillList[2])
                or len(descListTL3) != len(skillList[3])
                or len(descListTL4) != len(skillList[4])
            ):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)
            else:
                skillListTL = [nameListTL, descListTL1, descListTL2, descListTL3, descListTL4]
                translate = True

        # State
        for list in stateList:
            if len(list) > 0:
                # Progress Bar
                total = 0
                for stateArray in stateList:
                    total += len(stateArray)
                pbar.total = total
                pbar.refresh()

                # Name
                response = translateAI(
                    stateList[0],
                    f"Reply with the {LANGUAGE} translation of the status effect.",
                    True,
                )
                nameListTL = response[0]
                totalTokens[0] += response[1][0]
                totalTokens[1] += response[1][1]

                # Desc 1
                response = translateAI(stateList[1], "", True)
                descListTL1 = response[0]
                totalTokens[0] += response[1][0]
                totalTokens[1] += response[1][1]

                # Log 1
                response = translateAI(
                    stateList[2],
                    f"Reply with the {LANGUAGE} translation of the status effect.",
                    True,
                )
                descListTL2 = response[0]
                totalTokens[0] += response[1][0]
                totalTokens[1] += response[1][1]

                # Log 2
                response = translateAI(
                    stateList[3],
                    "reply with only the gender neutral "
                    + LANGUAGE
                    + " translation of the action log. Always start the sentence with Taro. For example, Translate 'Taroを倒した！' as 'Taro was defeated!'",
                    True,
                )
                descListTL3 = response[0]
                totalTokens[0] += response[1][0]
                totalTokens[1] += response[1][1]

                # Log 3
                response = translateAI(
                    stateList[4],
                    "reply with only the gender neutral "
                    + LANGUAGE
                    + " translation of the action log. Always start the sentence with Taro. For example, Translate 'Taroを倒した！' as 'Taro was defeated!'",
                    True,
                )
                descListTL4 = response[0]
                totalTokens[0] += response[1][0]
                totalTokens[1] += response[1][1]

                # Log 4
                response = translateAI(
                    stateList[5],
                    "reply with only the gender neutral "
                    + LANGUAGE
                    + " translation of the action log. Always start the sentence with Taro. For example, Translate 'Taroを倒した！' as 'Taro was defeated!'",
                    True,
                )
                descListTL5 = response[0]
                totalTokens[0] += response[1][0]
                totalTokens[1] += response[1][1]

                # Log 1
                response = translateAI(
                    stateList[6],
                    "reply with only the gender neutral "
                    + LANGUAGE
                    + " translation of the action log. Always start the sentence with Taro. For example, Translate 'Taroを倒した！' as 'Taro was defeated!'",
                    True,
                )
                descListTL6 = response[0]
                totalTokens[0] += response[1][0]
                totalTokens[1] += response[1][1]

                # Log 1
                response = translateAI(
                    stateList[7],
                    "reply with only the gender neutral "
                    + LANGUAGE
                    + " translation of the action log. Always start the sentence with Taro. For example, Translate 'Taroを倒した！' as 'Taro was defeated!'",
                    True,
                )
                descListTL7 = response[0]
                totalTokens[0] += response[1][0]
                totalTokens[1] += response[1][1]

                # Check Mismatch
                if (
                    len(nameListTL) != len(stateList[0])
                    or len(descListTL1) != len(stateList[1])
                    or len(descListTL2) != len(stateList[2])
                    or len(descListTL3) != len(stateList[3])
                    or len(descListTL4) != len(stateList[4])
                    or len(descListTL5) != len(stateList[5])
                    or len(descListTL6) != len(stateList[6])
                ):
                    with LOCK:
                        if filename not in MISMATCH:
                            MISMATCH.append(filename)
                else:
                    stateListTL = [
                        nameListTL,
                        descListTL1,
                        descListTL2,
                        descListTL3,
                        descListTL4,
                        descListTL5,
                        descListTL6,
                        descListTL7,
                    ]
                    translate = True

        # DB Names
        if len(dbNameList[0]) > 0:
            # Progress Bar
            total = 0
            for dbNameArray in dbNameList:
                total += len(dbNameArray)
            pbar.total = total
            pbar.refresh()

            # Name
            response = translateAI(dbNameList[0], "Reply with only the " + LANGUAGE + " translation", True)
            nameListTL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]

            # Check Mismatch
            if len(nameListTL) != len(dbNameList[0]):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)
            else:
                dbNameListTL = [nameListTL]
                translate = True

        # DB Values
        if len(dbValueList[0]) > 0:
            # Progress Bar
            total = 0
            for dbValueArray in dbValueList:
                total += len(dbValueArray)
            pbar.total = total
            pbar.refresh()

            # Name
            response = translateAI(dbValueList[0], "Reply with only the " + LANGUAGE + " translation", True)
            valueListTL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]

            # Check Mismatch
            if len(valueListTL) != len(dbValueList[0]):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)
            else:
                dbValueListTL = [valueListTL]
                translate = True

        # Start Pass 2
        if translate == True:
            jobList.append(scenarioListTL)
            jobList.append(npcListTL)
            jobList.append(itemListTL)
            jobList.append(stateListTL)
            jobList.append(armorListTL)
            jobList.append(enemyListTL)
            jobList.append(weaponsListTL)
            jobList.append(skillListTL)
            jobList.append(optionsListTL)
            jobList.append(dbNameListTL)
            jobList.append(dbValueListTL)
            searchDB(events, pbar, jobList, filename)

    except IndexError as e:
        traceback.print_exc()
        raise Exception(str(e) + "Failed to translate: " + initialJAString) from None
    except Exception as e:
        traceback.print_exc()
        raise Exception(str(e) + "Failed to translate: " + initialJAString) from None

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
