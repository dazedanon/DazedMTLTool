# Libraries
import json
import os
import re
import textwrap
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

# Pricing - Depends on the model https://openai.com/pricing
# Batch Size - GPT 3.5 Struggles past 15 lines per request. GPT4 struggles past 50 lines per request
# If you are getting a MISMATCH LENGTH error, lower the batch size.
if "gpt-3.5" in MODEL:
    INPUTAPICOST = 0.002
    OUTPUTAPICOST = 0.002
    BATCHSIZE = 10
    FREQUENCY_PENALTY = 0.2
elif "gpt-4" in MODEL:
    INPUTAPICOST = 0.0025
    OUTPUTAPICOST = 0.01
    BATCHSIZE = 20
    FREQUENCY_PENALTY = 0.1

# tqdm Globals
BAR_FORMAT = "{l_bar}{bar:10}{r_bar}{bar:-10b}"
POSITION = 0
LEAVE = False
PBAR = None
FILENAME = None

# Dialogue / Scroll
CODE101 = True
CODE102 = True

# Set String (Fragile but necessary)
CODE122 = False

# Other
CODE210 = True
CODE300 = False
CODE250 = False

# Database
NPCFLAG = False
SCENARIOFLAG = False
ITEMFLAG = True
COLLECTIONFLAG = False
ARMORFLAG = False
ENEMYFLAG = False
WEAPONFLAG = False


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
            with open("translated/" + filename, "w", encoding="utf-8") as outFile:
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
    totalTokenstring = (
        Fore.YELLOW + "[Input: " + str(translatedData[1][0]) + "]"
        "[Output: "
        + str(translatedData[1][1])
        + "]" "[Cost: ${:,.4f}".format(
            (translatedData[1][0] * 0.001 * INPUTAPICOST)
            + (translatedData[1][1] * 0.001 * OUTPUTAPICOST)
        )
        + "]"
    )
    timeString = Fore.BLUE + "[" + str(round(translationTime, 1)) + "s]"

    if translatedData[2] is None:
        # Success
        return (
            filename
            + ": "
            + totalTokenstring
            + timeString
            + Fore.GREEN
            + " \u2713 "
            + Fore.RESET
        )
    else:
        # Fail
        try:
            raise translatedData[2]
        except Exception as e:
            traceback.print_exc()
            errorString = str(e) + Fore.RED
            return (
                filename
                + ": "
                + totalTokenstring
                + timeString
                + Fore.RED
                + " \u2717 "
                + errorString
                + Fore.RESET
            )


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
    with tqdm(
        bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE
    ) as pbar:
        pbar.desc = filename
        pbar.total = totalLines
        with ThreadPoolExecutor(max_workers=THREADS) as executor:
            for event in events:
                if event is not None:
                    futures = [
                        executor.submit(searchCodes, page["list"], pbar, None, filename)
                        for page in event["pages"]
                        if page is not None
                    ]
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
        list300 = jobList[1]
        setData = True
    else:
        stringList = []
        list300 = []
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
                # Grab String
                jaString = codeList[i]["stringArgs"][0]
                initialJAString = jaString

                # Catch Vars that may break the TL
                varString = ""
                matchList = re.findall(
                    r"^[\\_]+[\w]+\[[a-zA-Z0-9\\\[\]\_,\s-]+\]", jaString
                )
                if len(matchList) != 0:
                    varString = matchList[0]
                    jaString = jaString.replace(matchList[0], "")

                # Grab Speaker
                if "：\n" in jaString:
                    nameList = re.findall(r"(.*)：\n", jaString)
                    if nameList is not None:
                        # TL Speaker
                        response = getSpeaker(nameList[0])
                        speaker = response[0]
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]

                        # Set nametag and remove from string
                        nametag = f"{speaker}：\n"
                        jaString = jaString.replace(f"{nameList[0]}：\n", "")

                # Remove Textwrap
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
                    matchSpeakerList = re.findall(
                        r"^(\[.+?\]\s?[|:]\s?)\s?", translatedText
                    )
                    if len(matchSpeakerList) > 0:
                        translatedText = translatedText.replace(matchSpeakerList[0], "")

                    # Textwrap
                    if FIXTEXTWRAP is True:
                        translatedText = textwrap.fill(translatedText, width=WIDTH)

                    # Add back Nametag
                    translatedText = nametag + translatedText
                    nametag = ""

                    # Add back Potential Variables in String
                    translatedText = varString + translatedText

                    # Set Data
                    codeList[i]["stringArgs"][0] = translatedText

                    # Reset Data and Pop Item
                    speaker = ""
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
                response = translateGPT(
                    choiceList,
                    f"Reply with the {LANGUAGE} translation of the dialogue choice",
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
                # Add Speaker
                if (
                    "stringArgs" in codeList[i]
                    and codeList[i]["intArgs"][0] == 500529
                    and len(codeList[i]["stringArgs"]) == 2
                ):
                    response = getSpeaker(codeList[i]["stringArgs"][1])
                    totalTokens[1] += response[1][0]
                    totalTokens[1] += response[1][1]

                    # Set Data
                    codeList[i]["stringArgs"][1] = response[0]

            ### Event Code: 122 SetString
            if codeList[i]["code"] == 122 and CODE122 == True:
                if "stringArgs" in codeList[i] and len(codeList[i]["stringArgs"]) > 0:
                    # Grab String
                    jaString = re.search(r"^\n?(.*)\n?$", codeList[i]["stringArgs"][0])
                    if jaString:
                        jaString = jaString.group(1)
                    else:
                        jaString = codeList[i]["stringArgs"][0]

                    # Translate Conversations
                    if "：Nothing" in jaString:
                        # Separate into list
                        list122 = jaString.split("\n\n")

                        # Remove Textwrap
                        # for j in range(len(list122)):
                        #     list122[j] = list122[j].replace("\n", " ")

                        # Translate
                        response = translateGPT(
                            list122,
                            f"Reply with the {LANGUAGE} translation of the text",
                            True,
                        )
                        list122TL = response[0]
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]

                        # Validate and Set Data
                        if len(list122) == len(list122TL):
                            # Adjust Speaker and Add Textwrap
                            for j in range(len(list122TL)):
                                list122TL[j] = textwrap.fill(list122TL[j], WIDTH)
                                list122TL[j] = re.sub(
                                    r"^\[?(.+?)\]?:", r"\1：", list122TL[j]
                                )
                                list122TL[j] = list122TL[j].replace("：", "：\n")
                                list122TL[j] = list122TL[j].replace("：\n ", "：\n")

                            # Join back into single string
                            list122TL = "\n\n".join(list122TL)

                            # Set String
                            codeList[i]["stringArgs"][0] = list122TL

                    # Translate Other Strings [Specific Files Only]
                    else:
                        if (
                            not re.search(r"\.[\w]+$", jaString)
                            and jaString != ""
                            and "_" not in jaString
                            and '",' not in jaString
                            and "/" not in jaString
                        ):
                            # Things to Check before starting translation
                            if re.search(
                                r"[一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９]+", jaString
                            ):
                                # Remove Textwrap
                                # jaString = jaString.replace("\n", " ")

                                # Translate
                                response = translateGPT(
                                    jaString,
                                    f"Reply with the {LANGUAGE} translation of the text",
                                    False,
                                )
                                translatedText = response[0]
                                totalTokens[0] += response[1][0]
                                totalTokens[1] += response[1][1]

                                # Textwrap
                                # translatedText = textwrap.fill(translatedText, WIDTH)

                                # Set String
                                codeList[i]["stringArgs"][0] = codeList[i][
                                    "stringArgs"
                                ][0].replace(jaString, translatedText)

            ### Event Code: 300 Common Events
            if (
                codeList[i]["code"] == 300
                and CODE300 == True
                and "stringArgs" in codeList[i]
                and len(codeList[i]["stringArgs"]) > 1
            ):
                # Choices
                if (
                    codeList[i]["stringArgs"][0] == "[共]汎用ウィンドウ生成"
                    or codeList[i]["stringArgs"][0] == "[共]選択生成"
                ):
                    # Grab String
                    choiceList = codeList[i]["stringArgs"][1].split("\r\n")

                    # # Translate Question
                    # question = codeList[i]['stringArgs'][2]
                    # response = translateGPT(question, "", True)
                    # translatedText = response[0]
                    # totalTokens[0] += response[1][0]
                    # totalTokens[1] += response[1][1]

                    # # Translate Question
                    # codeList[i]['stringArgs'][2] = translatedText

                    # Translate Choices
                    response = translateGPT(choiceList, translatedText, True)
                    choiceListTL = response[0]
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]

                    # Replace Commas
                    for j in range(len(choiceListTL)):
                        choiceListTL[j] = choiceListTL[j].replace(", ", "、")

                    # Convert to String and Set
                    translatedText = "\r\n".join(choiceListTL)
                    codeList[i]["stringArgs"][1] = translatedText

                # Dialogue
                elif (
                    codeList[i]["stringArgs"][0] == "Hメッセージ"
                    or codeList[i]["stringArgs"][0] == "Hしらべる"
                    or codeList[i]["stringArgs"][0] == "[共]Hメッセージ+"
                    or codeList[i]["stringArgs"][0] == "d[共]ポップアップ表示"
                    or codeList[i]["stringArgs"][0] == "m_謎冒頭"
                    or (
                        codeList[i]["codeStr"] == "SetString"
                        and (
                            "「" in codeList[i]["stringArgs"][0]
                            or "*" in codeList[i]["stringArgs"][0]
                        )
                    )
                    or codeList[i]["stringArgs"][0] == "[移]サウンドノベル"
                ):
                    cleanedList = None
                    if len(codeList[i]["stringArgs"]) > 1 and not re.search(
                        r"^[\\]+cself\[\d+\]$", codeList[i]["stringArgs"][1]
                    ):
                        cleanedList = formatDramon(codeList[i]["stringArgs"][1])
                    elif codeList[i]["code"] == 122:
                        cleanedList = formatDramon(codeList[i]["stringArgs"][0])
                    if cleanedList:
                        fontSize = 24
                        translatedText = ""

                        for str in cleanedList:
                            # Pass 1
                            if not setData:
                                if (
                                    all(x not in str for x in ["_", "@", ">", "/"])
                                    and str != "\r\n"
                                ):
                                    # Remove Textwrap and Font and Add to list
                                    str = str.replace("\r\n", " ")
                                    str = re.sub(r"[\\]+f\[\d+\]", "", str)
                                    list300.append(str)

                            # Pass 2
                            else:
                                if (
                                    all(
                                        x not in str
                                        for x in [
                                            "_",
                                            "@",
                                            ">",
                                            "/",
                                        ]
                                    )
                                    and str != "\r\n"
                                ):
                                    # Decide Wrap
                                    if (
                                        codeList[i]["stringArgs"][0]
                                        == "[移]サウンドノベル"
                                    ):
                                        width = 40
                                    else:
                                        width = WIDTH

                                    # Add Textwrap and Font
                                    list300[0] = textwrap.fill(list300[0], width)
                                    list300[0] = list300[0].replace(
                                        "\n", f"\r\n\\f[{fontSize}]"
                                    )
                                    list300[0] = f"\\f[{fontSize}]{list300[0]}\r\n"
                                    translatedText += list300[0]
                                    list300.pop(0)
                                else:
                                    translatedText += str

                        # Write to File
                        if setData:
                            # Formatting Fixes
                            translatedText = translatedText.replace('*"', '* "')
                            translatedText = translatedText.replace("\r\n\r\n", "\r\n")
                            translatedText = re.sub(r"[^\S\r\n]+", " ", translatedText)
                            if len(codeList[i]["stringArgs"]) > 1:
                                codeList[i]["stringArgs"][1] = translatedText
                            else:
                                codeList[i]["stringArgs"][0] = translatedText

            ### Event Code: 250 Common Events
            if codeList[i]["code"] == 250 and CODE250 == True:
                foundTerm = False

                # Validate size
                if len(codeList[i]["stringArgs"]) > 2:
                    if codeList[i]["stringArgs"][2] != "":
                        # Grab String
                        jaString = codeList[i]["stringArgs"][2]

                        # Catch Vars that may break the TL
                        varString = ""
                        matchList = re.findall(
                            r"^[\\_]+[\w]+\[[a-zA-Z0-9\\\[\]\_,\s-]+\]", jaString
                        )
                        if len(matchList) != 0:
                            varString = matchList[0]
                            jaString = jaString.replace(matchList[0], "")

                        # Check if term already translated
                        for j in range(len(TERMSLIST)):
                            if jaString == TERMSLIST[j][0]:
                                translatedText = TERMSLIST[j][1]
                                foundTerm = True

                        # Translate
                        if foundTerm == False:
                            response = translateGPT(
                                jaString,
                                f"Reply with the {LANGUAGE} translation of the text.",
                                False,
                            )
                            translatedText = response[0]
                            totalTokens[0] += response[1][0]
                            totalTokens[1] += response[1][1]
                            TERMSLIST.append([jaString, translatedText])

                        # Add back Potential Variables in String
                        translatedText = varString + translatedText

                        # Set Data
                        codeList[i]["stringArgs"][2] = translatedText

            ### Iterate
            i += 1

        # EOF
        stringListTL = []
        list300TL = []
        setData = False

        # String List
        if len(stringList) > 0:
            pbar.total = len(stringList)
            pbar.refresh()
            response = translateGPT(stringList, textHistory, True)
            stringListTL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            if len(stringListTL) != len(stringList):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)
            else:
                setData = True

        # 300 List
        if len(list300) > 0:
            pbar.total = len(list300)
            pbar.refresh()
            response = translateGPT(list300, textHistory, True)
            list300TL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            if len(list300TL) != len(list300):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)
            else:
                setData = True

        # Pass 2
        if setData:
            stringList = []
            searchCodes(events, pbar, [stringListTL, list300TL], filename)
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
    cleanedList = [
        x
        for x in jaStringList
        if x is not None and x != "" and x != "\r\n" and x != "_SS_"
    ]

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
            if (
                j > 0
                and "@" not in cleanedList[j - 1]
                and "/" not in cleanedList[j - 1]
                and "_" not in cleanedList[j - 1]
            ):
                cleanedList[j - 1] = cleanedList[j - 1] + cleanedList[j + 1]
            else:
                cleanedList.insert(j, cleanedList[j + 1])
                j += 1
            cleanedList[j] = f"\r\n{cleanedList[j]}\r\n"
            cleanedList.pop(j + 1)
        j += 1

    return cleanedList


# Database
def searchDB(events, pbar, jobList, filename):
    # Set Lists
    if len(jobList) > 0:
        scenarioList = jobList[0]
        NPCList = jobList[1]
        itemList = jobList[2]
        collectionList = jobList[3]
        armorList = jobList[4]
        enemyList = jobList[5]
        weaponsList = jobList[6]
        setData = True
    else:
        scenarioList = [[], [], []]
        NPCList = [[], [], [], []]
        itemList = [[], [], [], []]
        armorList = [[], []]
        enemyList = [[], []]
        weaponsList = [[], [], [], []]
        collectionList = [[], [], [], []]
        setData = False

    # Vars/Globals
    totalTokens = [0, 0]
    initialJAString = ""
    tableList = events
    font = ""
    global LOCK
    global NAMESLIST
    global MISMATCH

    # Calculate Total
    totalLines = 0
    for table in tableList:
        if table["name"] == "NPC" and NPCFLAG == True:
            for NPC in table["data"]:
                totalLines += len(NPC["data"])
        if table["name"] == "Hシナリオ" and SCENARIOFLAG == True:
            for hScenario in table["data"]:
                totalLines += len(hScenario["data"])
    pbar.total = totalLines
    pbar.refresh()

    # Begin Parsing File
    try:
        for table in tableList:
            # Translate NPC
            if table["name"] == "状態設定（戦場）" and NPCFLAG == True:
                for npc in table["data"]:
                    dataList = npc["data"]

                    # Parse
                    for j in range(len(dataList)):
                        # Name
                        if "キャラ名" in dataList[j].get("name"):
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    NPCList[0].append(dataList[j].get("value"))

                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    dataList[j].update({"value": NPCList[0][0]})
                                    NPCList[0].pop(0)

                        # Description
                        if "菊池" in dataList[j].get("name"):
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    # Remove Textwrap
                                    jaString = dataList[j].get("value")
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                    # Append Data
                                    NPCList[1].append(jaString)

                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    # Textwrap
                                    translatedText = NPCList[1][0]
                                    translatedText = textwrap.fill(translatedText, 30)
                                    translatedText = font + translatedText

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    NPCList[1].pop(0)

                        # Description
                        if "篠宮" in dataList[j].get("name"):
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    # Remove Textwrap
                                    jaString = dataList[j].get("value")
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                    # Append Data
                                    NPCList[2].append(jaString)

                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    # Textwrap
                                    translatedText = NPCList[2][0]
                                    translatedText = textwrap.fill(
                                        translatedText, LISTWIDTH
                                    )
                                    translatedText = font + translatedText

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    NPCList[2].pop(0)

            # Grab Scenarios
            if table["name"] == "MGP_参加者" and SCENARIOFLAG == True:
                for hScenario in table["data"]:
                    dataList = hScenario["data"]

                    # Parse
                    # Pass 1 (Grab Data)
                    if setData == False:
                        if dataList[1].get("value") != "":
                            scenarioList[0].append(dataList[1].get("value"))
                        if dataList[44].get("value") != "":
                            scenarioList[1].append(dataList[44].get("value"))
                        if dataList[45].get("value") != "":
                            scenarioList[2].append(dataList[45].get("value"))

                    # Pass 2 (Set Data)
                    else:
                        if dataList[1].get("value") != "":
                            dataList[1].update({"value": scenarioList[0][0]})
                            scenarioList[0].pop(0)
                        if dataList[44].get("value") != "":
                            dataList[44].update({"value": scenarioList[1][0]})
                            scenarioList[1].pop(0)
                        if dataList[45].get("value") != "":
                            dataList[45].update({"value": scenarioList[2][0]})
                            scenarioList[2].pop(0)

            # Grab Items
            if table["name"] == "mNPC管理" and ITEMFLAG == True:
                with open("translations.txt", "a", encoding="utf-8") as file:
                    for item in table["data"]:
                        dataList = item["data"]

                        # Parse #
                        for j in range(len(dataList)):
                            # Name
                            if dataList[j].get("name") == "NULL":
                                # Pass 1 (Grab Data)
                                if setData == False:
                                    if dataList[j].get("value") != "":
                                        itemList[0].append(dataList[j].get("value"))

                                # Pass 2 (Set Data)
                                else:
                                    if dataList[j].get("value") != "":
                                        file.write(
                                            f'{dataList[j].get('value')} ({itemList[0][0]})\n'
                                        )
                                        line = itemList[0][0]
                                        line = line.replace(":", "：")
                                        line = line.replace("/", "／")
                                        line = line.replace("?", "？")
                                        dataList[j].update({"value": line})
                                        itemList[0].pop(0)

                            # Description 1 (You are my specialz)
                            if dataList[j].get("name") == "ｾﾘﾌ_交換成立":
                                # Clean String
                                fontSize = 24
                                translatedText = ""
                                cleanedList = formatDramon(dataList[j].get("value"))
                                for str in cleanedList:
                                    # Pass 1
                                    if not setData:
                                        if (
                                            all(
                                                x not in str
                                                for x in ["_", "@", ">", "/"]
                                            )
                                            and str != "\r\n"
                                        ):
                                            # Remove Textwrap and Font and Add to list
                                            str = str.replace("\r\n", " ")
                                            str = re.sub(r"[\\]+f\[\d+\]", "", str)
                                            itemList[1].append(str)

                                    # Pass 2
                                    else:
                                        if (
                                            all(
                                                x not in str
                                                for x in [
                                                    "_",
                                                    "@",
                                                    ">",
                                                    "/",
                                                ]
                                            )
                                            and str != "\r\n"
                                        ):
                                            # Decide Wrap
                                            width = WIDTH

                                            # Add Textwrap and Font
                                            tempText = itemList[1][0]
                                            tempText = textwrap.fill(tempText, width)
                                            tempText = tempText.replace(
                                                "\n", f"\r\n\\f[{fontSize}]"
                                            )
                                            tempText = f"\\f[{fontSize}]{tempText}\r\n"
                                            translatedText += tempText
                                            itemList[1].pop(0)
                                        else:
                                            translatedText += str

                                # Write to File
                                if setData:
                                    # Formatting Fixes
                                    translatedText = translatedText.replace('*"', '* "')
                                    translatedText = translatedText.replace(
                                        "\r\n\r\n", "\r\n"
                                    )
                                    translatedText = re.sub(
                                        r"[^\S\r\n]+", " ", translatedText
                                    )
                                    dataList[j].update({"value": translatedText})

                            # Description 2 (You are my specialz)
                            if dataList[j].get("name") == "ｾﾘﾌ_素材が足りない":
                                # Clean String
                                fontSize = 24
                                translatedText = ""
                                cleanedList = formatDramon(dataList[j].get("value"))
                                for str in cleanedList:
                                    # Pass 1
                                    if not setData:
                                        if (
                                            all(
                                                x not in str
                                                for x in ["_", "@", ">", "/"]
                                            )
                                            and str != "\r\n"
                                        ):
                                            # Remove Textwrap and Font and Add to list
                                            str = str.replace("\r\n", " ")
                                            str = re.sub(r"[\\]+f\[\d+\]", "", str)
                                            itemList[2].append(str)

                                    # Pass 2
                                    else:
                                        if (
                                            all(
                                                x not in str
                                                for x in [
                                                    "_",
                                                    "@",
                                                    ">",
                                                    "/",
                                                ]
                                            )
                                            and str != "\r\n"
                                        ):
                                            # Decide Wrap
                                            width = WIDTH

                                            # Add Textwrap and Font
                                            tempText = itemList[2][0]
                                            tempText = textwrap.fill(tempText, width)
                                            tempText = tempText.replace(
                                                "\n", f"\r\n\\f[{fontSize}]"
                                            )
                                            tempText = f"\\f[{fontSize}]{tempText}\r\n"
                                            translatedText += tempText
                                            itemList[2].pop(0)
                                        else:
                                            translatedText += str

                                # Write to File
                                if setData:
                                    # Formatting Fixes
                                    translatedText = translatedText.replace('*"', '* "')
                                    translatedText = translatedText.replace(
                                        "\r\n\r\n", "\r\n"
                                    )
                                    translatedText = re.sub(
                                        r"[^\S\r\n]+", " ", translatedText
                                    )
                                    dataList[j].update({"value": translatedText})

                            # Description 3 (You are my specialz)
                            if dataList[j].get("name") == "ｾﾘﾌ_":
                                # Clean String
                                fontSize = 24
                                translatedText = ""
                                cleanedList = formatDramon(dataList[j].get("value"))
                                for str in cleanedList:
                                    # Pass 1
                                    if not setData:
                                        if (
                                            all(
                                                x not in str
                                                for x in ["_", "@", ">", "/"]
                                            )
                                            and str != "\r\n"
                                        ):
                                            # Remove Textwrap and Font and Add to list
                                            str = str.replace("\r\n", " ")
                                            str = re.sub(r"[\\]+f\[\d+\]", "", str)
                                            itemList[3].append(str)

                                    # Pass 2
                                    else:
                                        if (
                                            all(
                                                x not in str
                                                for x in [
                                                    "_",
                                                    "@",
                                                    ">",
                                                    "/",
                                                ]
                                            )
                                            and str != "\r\n"
                                        ):
                                            # Decide Wrap
                                            width = WIDTH

                                            # Add Textwrap and Font
                                            tempText = itemList[3][0]
                                            # tempText = textwrap.fill(tempText, width)
                                            # tempText = tempText.replace('\n', f'\r\n\\f[{fontSize}]')
                                            # tempText = f'\\f[{fontSize}]{tempText}\r\n'
                                            translatedText += tempText
                                            itemList[3].pop(0)
                                        else:
                                            translatedText += str

                                # Write to File
                                if setData:
                                    # Formatting Fixes
                                    translatedText = translatedText.replace('*"', '* "')
                                    translatedText = translatedText.replace(
                                        "\r\n\r\n", "\r\n"
                                    )
                                    translatedText = re.sub(
                                        r"[^\S\r\n]+", " ", translatedText
                                    )
                                    dataList[j].update({"value": translatedText})

            # Grab Armors
            if table["name"] == "防具" and ARMORFLAG == True:
                for armor in table["data"]:
                    dataList = armor["data"]

                    # Parse
                    for j in range(len(dataList)):
                        # Name
                        if "防具の名前" in dataList[j].get("name"):
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
                        if "防具の説明" in dataList[j].get("name"):
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
                                    translatedText = textwrap.fill(
                                        translatedText, LISTWIDTH
                                    )
                                    translatedText = font + translatedText

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
                        if "敵キャラ名" in dataList[j].get("name"):
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
                        if "NULL" in dataList[j].get("name"):
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
                                    translatedText = textwrap.fill(
                                        translatedText, LISTWIDTH
                                    )
                                    translatedText = font + translatedText

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    enemyList[1].pop(0)

            # Grab Weapons
            if table["name"] == "武器" and WEAPONFLAG == True:
                for weapon in table["data"]:
                    dataList = weapon["data"]

                    # Parse
                    for j in range(len(dataList)):
                        # Name
                        if "武器の名前" in dataList[j].get("name"):
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
                        if "武器の説明" in dataList[j].get("name"):
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
                                    translatedText = textwrap.fill(
                                        translatedText, LISTWIDTH
                                    )
                                    translatedText = font + translatedText

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    weaponsList[1].pop(0)

            # Grab Collection
            if table["name"] == "鍛冶師用DB" and COLLECTIONFLAG == True:
                for object in table["data"]:
                    dataList = object["data"]

                    # Parse
                    for j in range(len(dataList)):
                        # Name
                        if "作る装備" in dataList[j].get("name"):
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    # Remove Textwrap
                                    jaString = dataList[j].get("value")
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)
                                    collectionList[0].append(jaString)

                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    dataList[j].update({"value": collectionList[0][0]})
                                    collectionList[0].pop(0)

                        # Description
                        if "品物の解説" in dataList[j].get("name"):
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    # Remove Textwrap
                                    jaString = dataList[j].get("value")
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                    # Skill Action (Optional)
                                    # jaString = f'Taro{jaString}'

                                    # Append Data
                                    collectionList[1].append(jaString)
                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    translatedText = collectionList[1][0]

                                    # Remove Action (Optional)
                                    # translatedText = translatedText.replace('Taro', '')

                                    # Textwrap
                                    translatedText = textwrap.fill(
                                        translatedText, LISTWIDTH
                                    )
                                    translatedText = font + translatedText

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    collectionList[1].pop(0)

                        # Description 2
                        if "NULL" in dataList[j].get("name"):
                            # Pass 1 (Grab Data)
                            if setData == False:
                                if dataList[j].get("value") != "":
                                    # Remove Textwrap
                                    jaString = dataList[j].get("value")
                                    jaString = jaString.replace("\n", " ")
                                    jaString = jaString.replace("\r", "")
                                    jaString = re.sub(r"[\\]+f\[\d+\]", "", jaString)

                                    # Skill Action (Optional)
                                    # jaString = f'Taro{jaString}'

                                    # Append Data
                                    collectionList[2].append(jaString)
                            # Pass 2 (Set Data)
                            else:
                                if dataList[j].get("value") != "":
                                    translatedText = collectionList[2][0]

                                    # Remove Action (Optional)
                                    # translatedText = translatedText.replace('Taro', '')

                                    # Textwrap
                                    translatedText = textwrap.fill(
                                        translatedText, LISTWIDTH
                                    )
                                    translatedText = font + translatedText

                                    # Set Data
                                    dataList[j].update({"value": translatedText})
                                    collectionList[2].pop(0)

        # Translation
        scenarioListTL = [[], [], []]
        NPCListTL = [[], [], [], []]
        itemListTL = [[], [], [], []]
        collectionListTL = [[], [], [], []]
        armorListTL = [[], []]
        enemyListTL = [[], []]
        weaponsListTL = [[], [], []]

        translate = False

        # NPCs
        if len(NPCList[0]) > 0:
            # Progress Bar
            total = 0
            for itemArray in NPCList:
                total += len(itemArray)
            pbar.total = total
            pbar.refresh()

            # Name
            response = translateGPT(
                NPCList[0],
                "Reply with only the "
                + LANGUAGE
                + " translation of the RPG enemy name",
                True,
            )
            nameListTL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            # Desc 1
            response = translateGPT(
                NPCList[1], "Reply with only the " + LANGUAGE + " translation", True
            )
            descListTL1 = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            # Desc 2
            response = translateGPT(
                NPCList[2], "Reply with only the " + LANGUAGE + " translation", True
            )
            descListTL2 = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            # Desc 3
            response = translateGPT(
                NPCList[3], "Reply with only the " + LANGUAGE + " translation", True
            )
            descListTL3 = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]

            # Check Mismatch
            if (
                len(nameListTL) != len(NPCList[0])
                or len(descListTL1) != len(NPCList[1])
                or len(descListTL2) != len(NPCList[2])
                or len(descListTL3) != len(NPCList[3])
            ):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)
            else:
                NPCListTL = [nameListTL, descListTL1, descListTL2, descListTL3]
                translate = True

        # SCENARIO
        if len(scenarioList[0]) > 0:
            # Progress Bar
            total = 0
            for scenarioArray in scenarioList:
                total += len(scenarioArray)
            pbar.total = total
            pbar.refresh()

            # Name
            response = translateGPT(
                scenarioList[0],
                "Reply with only the " + LANGUAGE + " translation",
                True,
            )
            nameListTL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            # Desc 1
            response = translateGPT(
                scenarioList[1],
                "reply with only the gender neutral "
                + LANGUAGE
                + " translation of the NPC name",
                True,
            )
            descListTL1 = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            # Desc 2
            response = translateGPT(
                scenarioList[2],
                "reply with only the gender neutral "
                + LANGUAGE
                + " translation of the NPC name",
                True,
            )
            descListTL2 = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]

            # Check Mismatch
            if (
                len(nameListTL) != len(scenarioList[0])
                or len(descListTL1) != len(scenarioList[1])
                or len(descListTL2) != len(scenarioList[2])
            ):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)
            else:
                scenarioListTL = [nameListTL, descListTL1, descListTL2]
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
            response = translateGPT(
                itemList[0], "Reply with only the " + LANGUAGE + " translation", True
            )
            nameListTL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            # Desc 1
            response = translateGPT(
                itemList[1], "Reply with only the " + LANGUAGE + " translation", True
            )
            descListTL1 = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            # Desc 2
            response = translateGPT(
                itemList[2], "Reply with only the " + LANGUAGE + " translation", True
            )
            descListTL2 = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            # Desc 3
            response = translateGPT(
                itemList[3], "Reply with only the " + LANGUAGE + " translation", True
            )
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
            response = translateGPT(
                armorList[0],
                "Reply with only the " + LANGUAGE + " translation of the NPC name",
                True,
            )
            nameListTL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            # Desc 1
            response = translateGPT(
                armorList[1], "Reply with only the " + LANGUAGE + " translation", True
            )
            descListTL1 = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]

            # Check Mismatch
            if len(nameListTL) != len(armorList[0]) or len(descListTL1) != len(
                armorList[1]
            ):
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
            response = translateGPT(
                enemyList[0],
                "Reply with only the " + LANGUAGE + " translation of the RPG item name",
                True,
            )
            nameListTL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            # Desc 1
            response = translateGPT(
                enemyList[1], "Reply with only the " + LANGUAGE + " translation", True
            )
            descListTL1 = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]

            # Check Mismatch
            if len(nameListTL) != len(enemyList[0]) or len(descListTL1) != len(
                enemyList[1]
            ):
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
            response = translateGPT(
                weaponsList[0],
                "Reply with only the " + LANGUAGE + " translation of the RPG item name",
                True,
            )
            nameListTL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            # Desc 1
            response = translateGPT(weaponsList[1], "", True)
            descListTL1 = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            # Desc 2
            response = translateGPT(weaponsList[2], "", True)
            descListTL2 = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]

            # Check Mismatch
            if (
                len(nameListTL) != len(weaponsList[0])
                or len(descListTL1) != len(weaponsList[1])
                or len(descListTL2) != len(weaponsList[2])
            ):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)
            else:
                weaponsListTL = [nameListTL, descListTL1, descListTL2]
                translate = True

        # Collection
        for list in collectionList:
            if len(list) > 0:
                # Progress Bar
                total = 0
                for collectionArray in collectionList:
                    total += len(collectionArray)
                pbar.total = total
                pbar.refresh()

                # Name
                response = translateGPT(
                    collectionList[0],
                    "reply with only the gender neutral "
                    + LANGUAGE
                    + " translation of the action log. Always start the sentence with Taro. For example, Translate 'Taroを倒した！' as 'Taro was defeated!'",
                    True,
                )
                nameListTL = response[0]
                totalTokens[0] += response[1][0]
                totalTokens[1] += response[1][1]

                # Desc 1
                response = translateGPT(collectionList[1], "", True)
                descListTL1 = response[0]
                totalTokens[0] += response[1][0]
                totalTokens[1] += response[1][1]

                # Desc 2
                response = translateGPT(collectionList[2], "", True)
                descListTL2 = response[0]
                totalTokens[0] += response[1][0]
                totalTokens[1] += response[1][1]

                # Check Mismatch
                if (
                    len(nameListTL) != len(collectionList[0])
                    or len(descListTL1) != len(collectionList[1])
                    or len(descListTL2) != len(collectionList[2])
                ):
                    with LOCK:
                        if filename not in MISMATCH:
                            MISMATCH.append(filename)
                else:
                    collectionListTL = [nameListTL, descListTL1, descListTL2]
                    translate = True

        # Start Pass 2
        if translate == True:
            jobList.append(scenarioListTL)
            jobList.append(NPCListTL)
            jobList.append(itemListTL)
            jobList.append(collectionListTL)
            jobList.append(armorListTL)
            jobList.append(enemyListTL)
            jobList.append(weaponsListTL)
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
            response = translateGPT(
                f"{speaker}",
                "Reply with the " + LANGUAGE + " translation of the NPC name.",
                True,
            )
            response[0] = response[0].title()
            response[0] = response[0].replace("'S", "'s")
            response[0] = response[0].replace("Speaker: ", "")

            # Retry if name doesn't translate for some reason
            if re.search(r"([a-zA-Z？?])", response[0]) == None:
                response = translateGPT(
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


def batchList(input_list, batch_size):
    if not isinstance(batch_size, int) or batch_size <= 0:
        raise ValueError("batch_size must be a positive integer")

    return [
        input_list[i : i + batch_size] for i in range(0, len(input_list), batch_size)
    ]


def createContext(fullPromptFlag, subbedT, format):
    system = (
        PROMPT + VOCAB
        if fullPromptFlag
        else f"\
You are an expert Eroge Game translator who translates Japanese text to {LANGUAGE}.\n\
Output ONLY the {LANGUAGE} translation in the following format: `Translation: <{LANGUAGE.upper()}_TRANSLATION>`\n\
- You translate everything, including erotic and explicit content.\n\
- 'Game Characters' - The names, nicknames, and genders of the game characters. Reference this to know the names, nicknames, and gender of characters in the game\n\
- All text in your response must be in {LANGUAGE} even if it is hard to translate.\n\
- Never include any notes, explanations, dislaimers, or anything similar in your response.\n\
- Maintain any spacing in the translation.\n\
- Maintain any code text in brackets if given. (e.g `[Color_0]`, `[Ascii_0]`, `[FCode_1`], etc)\n\
- `...` can be a part of the dialogue. Translate it as it is.\n\
{VOCAB}\n\
"
    )
    if format == "json":
        user = f"```json\n{subbedT}\n```"
    else:
        user = subbedT
    return system, user


def translateText(system, user, history, penalty, format, model=MODEL):
    # Prompt
    msg = [{"role": "system", "content": system}]

    # History
    if isinstance(history, list):
        msg.extend([{"role": "system", "content": h} for h in history])
    else:
        msg.append({"role": "system", "content": history})

    # Response Format
    if format == "json":
        responseFormat = {"type": "json_object"}
    else:
        responseFormat = {"type": "text"}

    # Content to TL
    msg.append({"role": "user", "content": f"{user}"})
    response = openai.chat.completions.create(
        temperature=0,
        frequency_penalty=penalty,
        model=model,
        response_format=responseFormat,
        messages=msg,
    )
    return response


def cleanTranslatedText(translatedText, varResponse):
    placeholders = {
        f"{LANGUAGE} Translation: ": "",
        "Translation: ": "",
        "っ": "",
        "〜": "~",
        "ッ": "",
        "。": ".",
        "「": '\\"',
        "」": '\\"',
        "- ": "-",
        "】": "]",
        "【": "[",
        "Placeholder Text": "",
        # Add more replacements as needed
    }
    for target, replacement in placeholders.items():
        translatedText = translatedText.replace(target, replacement)

    # Elongate Long Dashes (Since GPT Ignores them...)
    translatedText = elongateCharacters(translatedText)
    return translatedText


def elongateCharacters(text):
    # Define a pattern to match one character followed by one or more `ー` characters
    # Using a positive lookbehind assertion to capture the preceding character
    pattern = r"(?<=(.))ー+"

    # Define a replacement function that elongates the captured character
    def repl(match):
        char = match.group(1)  # The character before the ー sequence
        count = len(match.group(0)) - 1  # Number of ー characters
        return char * count  # Replace ー sequence with the character repeated

    # Use re.sub() to replace the pattern in the text
    return re.sub(pattern, repl, text)


def extractTranslation(translatedTextList, is_list):
    try:
        translatedTextList = re.sub(r'\\"+\"([^,\n}])', r'\\"\1', translatedTextList)
        translatedTextList = re.sub(r"(?<![\\])\"+(?!\n)", r'"', translatedTextList)
        line_dict = json.loads(translatedTextList)
        # If it's a batch (i.e., list), extract with tags; otherwise, return the single item.
        string_list = list(line_dict.values())
        if is_list:
            return string_list
        else:
            return string_list[0]

    except Exception as e:
        PBAR.write(f"extractTranslation Error: {e} on String {translatedTextList}")
        return None


def countTokens(system, user, history):
    inputTotalTokens = 0
    outputTotalTokens = 0
    enc = tiktoken.encoding_for_model("gpt-4")

    # Input
    if isinstance(history, list):
        for line in history:
            inputTotalTokens += len(enc.encode(line))
    else:
        inputTotalTokens += len(enc.encode(history))
    inputTotalTokens += len(enc.encode(system))
    inputTotalTokens += len(enc.encode(user))

    # Output
    outputTotalTokens += round(len(enc.encode(user)) * 3)

    return [inputTotalTokens, outputTotalTokens]


def combineList(tlist, text):
    if isinstance(text, list):
        return [t for sublist in tlist for t in sublist]
    return tlist[0]


@retry(exceptions=Exception, tries=5, delay=5)
def translateGPT(text, history, fullPromptFlag):
    global PBAR, MISMATCH, FILENAME
    with open("log/translationHistory.txt", "a+", encoding="utf-8") as logFile:
        mismatch = False
        totalTokens = [0, 0]
        if isinstance(text, list):
            format = "json"
            tList = batchList(text, BATCHSIZE)
        else:
            format = "text"
            tList = [text]

        for index, tItem in enumerate(tList):
            # Before sending to translation, if we have a list of items, add the formatting
            if isinstance(tItem, list):
                payload = {f"Line{i+1}": string for i, string in enumerate(tItem)}
                payload = json.dumps(payload, indent=4, ensure_ascii=False)
                varResponse = [payload, []]
                subbedT = varResponse[0]
            else:
                varResponse = [tItem, []]
                subbedT = varResponse[0]

            # Things to Check before starting translation
            if not re.search(
                r"[一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９\uFF61-\uFF9F]+", subbedT
            ):
                if PBAR is not None:
                    PBAR.update(len(tItem))
                history = tItem[-MAXHISTORY:]
                continue

            # Create Message
            system, user = createContext(fullPromptFlag, subbedT, format)

            # Calculate Estimate
            if ESTIMATE:
                estimate = countTokens(system, user, history)
                totalTokens[0] += estimate[0]
                totalTokens[1] += estimate[1]
                continue

            # Translating
            response = translateText(system, user, history, 0.05, format)
            translatedText = response.choices[0].message.content
            totalTokens[0] += response.usage.prompt_tokens
            totalTokens[1] += response.usage.completion_tokens

            # Check Translation
            translatedText = cleanTranslatedText(translatedText, varResponse)
            if isinstance(tItem, list):
                extractedTranslations = extractTranslation(translatedText, True)
                if extractedTranslations == None or len(tItem) != len(
                    extractedTranslations
                ):
                    # Mismatch. Try Again
                    response = translateText(
                        system, user, history, 0.05, format, "gpt-4o"
                    )
                    translatedText = response.choices[0].message.content
                    totalTokens[0] += response.usage.prompt_tokens
                    totalTokens[1] += response.usage.completion_tokens

                    # Formatting
                    translatedText = cleanTranslatedText(translatedText, varResponse)
                    if isinstance(tItem, list):
                        extractedTranslations = extractTranslation(translatedText, True)
                        if extractedTranslations == None or len(tItem) != len(
                            extractedTranslations
                        ):
                            mismatch = True  # Just here for breakpoint
                logFile.write(f"Input:\n{subbedT}\n")
                logFile.write(f"Output:\n{translatedText}\n")

                # Set if no mismatch
                if mismatch == False:
                    tList[index] = extractedTranslations
                    history = extractedTranslations[
                        -MAXHISTORY:
                    ]  # Update history if we have a list
                else:
                    history = text[-MAXHISTORY:]
                    mismatch = False
                    if FILENAME not in MISMATCH:
                        MISMATCH.append(FILENAME)

                # Update Loading Bar
                with LOCK:
                    if PBAR is not None:
                        PBAR.update(len(tItem))
            else:
                # Ensure we're passing a single string to extractTranslation
                tList[index] = translatedText

    finalList = combineList(tList, text)
    return [finalList, totalTokens]
