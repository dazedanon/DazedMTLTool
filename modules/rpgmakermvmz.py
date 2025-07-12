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
import copy
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
NAMESLIST = []
MISMATCH = []  # Lists files that throw a mismatch error (Length of GPT list response is wrong)
PBAR = None
FILENAME = None
TIMETOTAL = 0  # Total Time Taken for all translations

# Regex - Need to change this if you want to translate from/to other languages. Default is Japanese Regex
LANGREGEX = r"[一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９\uFF61-\uFF9F]+"

# Pricing - Depends on the model https://openai.com/pricing ($ Price Per 1M)
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

# tqdm Globals
BAR_FORMAT = "{l_bar}{bar:10}{r_bar}{bar:-10b}"
POSITION = 0
LEAVE = False

# Config (Default)
FIRSTLINESPEAKERS = False  # If 1st line of 401 is a speaker, set to True (False)
FACENAME101 = False  # Find Speakers in 101 Codes based on Face Name (False)
NAMES = False  # Output a list of all the character names found (False)
BRFLAG = False  # If the game uses <br> instead (False)
FIXTEXTWRAP = True  # Overwrites textwrap (True)
IGNORETLTEXT = False  # Ignores all translated text. (False)

# Dialogue / Scroll / Choices (Main Codes)
CODE401 = True
CODE405 = True
CODE102 = True

# Optional
CODE101 = False  # Turn this one on when names exist in 101
CODE408 = False  # Warning, translates comments and can inflate costs.

# Variables
CODE122 = False

# Other
CODE355655 = False
CODE357 = False
CODE657 = False
CODE356 = False
CODE320 = False
CODE324 = False
CODE111 = False
CODE108 = False


def handleMVMZ(filename, estimate):
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
        if "Map" in filename and filename != "MapInfos.json":
            translatedData = parseMap(data, filename)

        # CommonEvents Files
        elif "CommonEvents" in filename:
            translatedData = parseCommonEvents(data, filename)

        # Actor File
        elif "Actors" in filename:
            translatedData = parseNames(data, filename, "Actors")

        # Armor File
        elif "Armors" in filename:
            translatedData = parseNames(data, filename, "Armors")

        # Weapons File
        elif "Weapons" in filename:
            translatedData = parseNames(data, filename, "Weapons")

        # Classes File
        elif "Classes" in filename:
            translatedData = parseNames(data, filename, "Classes")

        # Enemies File
        elif "Enemies" in filename:
            translatedData = parseNames(data, filename, "Enemies")

        # Items File
        elif "Items" in filename:
            translatedData = parseNames(data, filename, "Items")

        # MapInfo File
        elif "MapInfos" in filename:
            translatedData = parseNames(data, filename, "MapInfos")

        # Skills File
        elif "Skills" in filename:
            translatedData = parseNames(data, filename, "Skills")

        # Troops File
        elif "Troops" in filename:
            translatedData = parseTroops(data, filename)

        # States File
        elif "States" in filename:
            translatedData = parseSS(data, filename)

        # System File
        elif "System" in filename:
            translatedData = parseSystem(data, filename)

        # Scenario File
        elif "Scenario" in filename:
            translatedData = parseScenario(data, filename)

        else:
            raise NameError(filename + " Not Supported")

    return translatedData


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


def parseMap(data, filename):
    totalTokens = [0, 0]
    totalLines = 0
    events = data["events"]
    global LOCK

    # Translate displayName for Map files
    if "Map" in filename:
        response = translateGPT(
            data["displayName"],
            "Reply with only the " + LANGUAGE + " translation of the RPG location name",
            False,
        )
        totalTokens[0] += response[1][0]
        totalTokens[1] += response[1][1]
        data["displayName"] = response[0].replace('"', "")

    # Get total for progress bar
    for event in events:
        if event:
            if "<LB>" in event["note"]:
                response = translateGPT(
                    event["name"],
                    "Reply with only the " + LANGUAGE + " translation of the RPG location name",
                    False,
                )
                totalTokens[0] += response[1][0]
                totalTokens[1] += response[1][1]
                event["name"] = response[0].replace('"', "")
            if "<msgText:" in event["note"]:
                tokensResponse = translateNote(event, r"<msgText:\"(.*?)\">", False)
                totalTokens[0] += tokensResponse[0]
                totalTokens[1] += tokensResponse[1]
            for page in event["pages"]:
                totalLines += len(page["list"])

    # Thread for each page in file
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE) as pbar:
        pbar.desc = filename
        with ThreadPoolExecutor(max_workers=THREADS) as executor:
            for event in events:
                if event is not None:
                    # This translates ID of events. (May break the game)
                    if "<namePop:" in event["note"]:
                        response = translateNoteOmitSpace(event, r"<namePop:(.*?)\s?[\d-]+?")
                        totalTokens[0] += response[0]
                        totalTokens[1] += response[1]
                    if "<LB:" in event["note"]:
                        response = translateNoteOmitSpace(event, r"<LB:(.*?)\s?>.*")
                        totalTokens[0] += response[0]
                        totalTokens[1] += response[1]
                    if "<dn:" in event["note"]:
                        response = translateNoteOmitSpace(event, r"<dn:\s*(.*)>.*")
                        totalTokens[0] += response[0]
                        totalTokens[1] += response[1]

                    futures = [executor.submit(searchCodes, page, pbar, [], filename) for page in event["pages"] if page is not None]
                    for future in as_completed(futures):
                        try:
                            totalTokensFuture = future.result()
                            totalTokens[0] += totalTokensFuture[0]
                            totalTokens[1] += totalTokensFuture[1]
                        except Exception as e:
                            traceback.print_exc()
                            return [data, totalTokens, e]
    return [data, totalTokens, None]


def translateNote(event, regex, wordwrap=False):
    # Regex String
    jaString = event["note"]
    match = re.findall(regex, jaString, re.DOTALL)
    if match:
        tokens = [0, 0]
        i = 0
        while i < len(match):
            initialJAString = match[i]
            modifiedJAString = initialJAString
            # Remove any textwrap
            if wordwrap:
                modifiedJAString = modifiedJAString.replace("\n", " ")

            # Translate
            response = translateGPT(
                modifiedJAString,
                "Reply with only the " + LANGUAGE + " translation.",
                False,
            )
            translatedText = response[0]
            tokens[0] += response[1][0]
            tokens[1] += response[1][1]

            # Textwrap
            if wordwrap:
                translatedText = dazedwrap.wrapText(translatedText, width=NOTEWIDTH)
                translatedText = translatedText.replace('"', "")

            jaString = jaString.replace(initialJAString, translatedText)
            event["note"] = jaString
            i += 1
        return tokens
    return [0, 0]


# For notes that can't have spaces.
def translateNoteOmitSpace(event, regex):
    # Regex that only matches text inside LB.
    jaString = event["note"]

    match = re.findall(regex, jaString, re.DOTALL)
    if match:
        oldJAString = match[0]
        # Remove any textwrap
        jaString = re.sub(r"\n", " ", oldJAString)

        # Translate
        response = translateGPT(
            jaString,
            "Reply with the " + LANGUAGE + " translation of the location name.",
            False,
        )
        translatedText = response[0]

        translatedText = translatedText.replace('"', "")
        translatedText = translatedText.replace(" ", "_")
        event["note"] = event["note"].replace(oldJAString, translatedText)
        return response[1]
    return [0, 0]


def parseCommonEvents(data, filename):
    totalTokens = [0, 0]
    totalLines = 0
    global LOCK

    # Get total for progress bar
    for page in data:
        if page is not None:
            totalLines += len(page["list"])

    with tqdm(bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE) as pbar:
        pbar.desc = filename
        with ThreadPoolExecutor(max_workers=THREADS) as executor:
            futures = [executor.submit(searchCodes, page, pbar, [], filename) for page in data if page is not None]
            for future in as_completed(futures):
                try:
                    totalTokensFuture = future.result()
                    totalTokens[0] += totalTokensFuture[0]
                    totalTokens[1] += totalTokensFuture[1]
                except Exception as e:
                    traceback.print_exc()
                    return [data, totalTokens, e]
    return [data, totalTokens, None]


def parseTroops(data, filename):
    totalTokens = [0, 0]
    totalLines = 0
    global LOCK

    # Get total for progress bar
    for troop in data:
        if troop is not None:
            for page in troop["pages"]:
                totalLines += len(page["list"]) + 1  # The +1 is because each page has a name.

    with tqdm(bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE) as pbar:
        pbar.desc = filename
        for troop in data:
            if troop is not None:
                with ThreadPoolExecutor(max_workers=THREADS) as executor:
                    futures = [executor.submit(searchCodes, page, pbar, [], filename) for page in troop["pages"] if page is not None]
                    for future in as_completed(futures):
                        try:
                            totalTokensFuture = future.result()
                            totalTokens[0] += totalTokensFuture[0]
                            totalTokens[1] += totalTokensFuture[1]
                        except Exception as e:
                            traceback.print_exc()
                            return [data, totalTokens, e]
    return [data, totalTokens, None]


def parseNames(data, filename, context):
    totalTokens = [0, 0]
    totalLines = 0
    totalLines += len(data)

    with tqdm(bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE) as pbar:
        pbar.desc = filename
        try:
            result = searchNames(data, pbar, context)
            totalTokens[0] += result[0]
            totalTokens[1] += result[1]
        except Exception as e:
            traceback.print_exc()
            return [data, totalTokens, e]
    return [data, totalTokens, None]


def parseSS(data, filename):
    totalTokens = [0, 0]
    totalLines = 0
    totalLines += len(data)

    with tqdm(bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE) as pbar:
        pbar.desc = filename
        for ss in data:
            if ss is not None:
                try:
                    result = searchSS(ss, pbar)
                    totalTokens[0] += result[0]
                    totalTokens[1] += result[1]
                except Exception as e:
                    traceback.print_exc()
                    return [data, totalTokens, e]
    return [data, totalTokens, None]


def parseSystem(data, filename):
    totalTokens = [0, 0]
    totalLines = 0

    # Calculate Total Lines
    for term in data["terms"]:
        termList = data["terms"][term]
        totalLines += len(termList)
    totalLines += len(data["gameTitle"])
    totalLines += len(data["terms"]["messages"])
    totalLines += len(data["variables"])
    totalLines += len(data["equipTypes"])
    totalLines += len(data["armorTypes"])
    totalLines += len(data["skillTypes"])

    with tqdm(bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE) as pbar:
        pbar.desc = filename
        try:
            result = searchSystem(data, pbar)
            totalTokens[0] += result[0]
            totalTokens[1] += result[1]
        except Exception as e:
            traceback.print_exc()
            return [data, totalTokens, e]
    return [data, totalTokens, None]


def parseScenario(data, filename):
    totalTokens = [0, 0]
    totalLines = 0
    global LOCK

    # Get total for progress bar
    for page in data.items():
        totalLines += len(page[1])

    with tqdm(bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE) as pbar:
        pbar.desc = filename
        with ThreadPoolExecutor(max_workers=THREADS) as executor:
            futures = [executor.submit(searchCodes, page[1], pbar, [], filename) for page in data.items() if page[1] is not None]
            for future in as_completed(futures):
                try:
                    totalTokensFuture = future.result()
                    totalTokens[0] += totalTokensFuture[0]
                    totalTokens[1] += totalTokensFuture[1]
                except Exception as e:
                    traceback.print_exc()
                    return [data, totalTokens, e]
    return [data, totalTokens, None]


def searchNames(data, pbar, context):
    totalTokens = [0, 0]
    nameList = []
    profileList = []
    nicknameList = []
    descriptionList = []
    # For batching all note types
    notesBatch = []  # List of (i, regex, match_text, note_type)
    notesBatchMap = []  # List of (i, regex, match_text, note_type, groupidx)
    i = 0  # Counter
    j = 0  # Counter 2
    filling = False
    mismatch = False
    batchFull = False

    # Set the context of what we are translating
    if "Actors" in context:
        newContext = "Reply with only the " + LANGUAGE + " translation of the NPC name"
    if "Armors" in context:
        newContext = "Reply with only the " + LANGUAGE + " translation of the RPG equipment name"
    if "Classes" in context:
        newContext = "Reply with only the " + LANGUAGE + " translation of the RPG class name"
    if "MapInfos" in context:
        newContext = "Reply with only the " + LANGUAGE + " translation of the location name"
    if "Enemies" in context:
        newContext = "Reply with only the " + LANGUAGE + " translation of the enemy NPC name"
    if "Weapons" in context:
        newContext = "Reply with only the " + LANGUAGE + " translation of the RPG weapon name"
    if "Items" in context:
        newContext = "Reply with only the " + LANGUAGE + " translation of the RPG item name"
    if "Skills" in context:
        newContext = "Reply with only the " + LANGUAGE + " translation of the RPG skill name"

    # Names
    with open("translations.txt", "a", encoding="utf-8") as file:
        file.write(f"\n#{context}\n")

    # --- Batching pass: collect all note texts for all note types ---
    note_regexes = [
        (r"<note:(.*?)>", False),
        (r"<PE拡張:(.*?)>", False),
        (r"<hint:(.*?)>", False),
        (r"<SGDescription:(.*?)>", False),
        (r"<SG説明:\n?(.*?)>", False),
        (r"<SG説明2:\n?(.*?)>", False),
        (r"<SG説明3:\n?(.*?)>", False),
        (r"<SG説明4:\n?(.*?)>", False),
        (r"<SGカテゴリ:(.*?)>", False),
        (r"<Switch Shop Description>\n(.*)\n", False),
        (r"<MapText:(.*?)>", False),
        (r"WATs:(.+?)>", False),
        (r"ADTs?:(.+?)>", False),
        (r"<detail:(.*?)>", False),
        (r"<Name:(.*?)>", False),
        (r"<sub_1:([^>]+)", True),
        (r"<sub_2:([^>]+)", True),
        (r"<sub_3:([^>]+)", True),
        (r"<infowindow:(.*?)>", True),
        (r"<ExtendDesc:(.*?)>", True),
        (r"<desc\d:(.*?)>", False),
        (r"<拡張説明:(.+?)>", False),
        (r"<STS DESC>\n(.+?)\n<", False),
    ]
    # For each entry, collect all note matches
    for idx, entry in enumerate(data):
        if entry is None or "note" not in entry or not entry["note"]:
            continue
        note = entry["note"]
        for regex, wordwrap in note_regexes:
            matches = re.findall(regex, note, re.DOTALL)
            for m in matches:
                match_text = m if isinstance(m, str) else m[0]
                notesBatch.append(match_text)
                notesBatchMap.append((idx, regex, match_text, wordwrap))

    # --- Batch translate all notes ---
    translatedNotesBatch = []
    if notesBatch:
        response = translateGPT(notesBatch, f"Reply with only the {LANGUAGE} translation of the note text.", True)
        translatedNotesBatch = response[0]
        totalTokens[0] += response[1][0]
        totalTokens[1] += response[1][1]

    # --- Insert translated notes back ---
    note_insert_idx = 0
    for idx, regex, match_text, wordwrap in notesBatchMap:
        if note_insert_idx >= len(translatedNotesBatch):
            break
        translated = translatedNotesBatch[note_insert_idx]
        if wordwrap:
            translated = dazedwrap.wrapText(translated, width=NOTEWIDTH)
            translated = translated.replace('"', "")
        # Use a safe literal match for the replacement (no re.escape, just str.replace)
        data[idx]["note"] = data[idx]["note"].replace(match_text, translated, 1)
        note_insert_idx += 1

    # Now continue with the rest of the batching logic for names, descriptions, etc.
    i = 0
    filling = False
    batchFull = False
    mismatch = False
    while i < len(data) or filling == True:
        if i < len(data):
            # Empty Data
            if data[i] is None or data[i]["name"] == "":
                i += 1
                continue
            # Filling up Batch
            filling = True
            if context in "Actors":
                if len(nameList) < BATCHSIZE:
                    if data[i]["name"] != "":
                        nameList.append(data[i]["name"])
                    if "nickname" in data[i] and data[i]["nickname"]:
                        nicknameList.append(data[i]["nickname"])
                    if "profile" in data[i] and data[i]["profile"]:
                        profileList.append(data[i]["profile"].replace("\n", " "))
                    i += 1
                else:
                    batchFull = True
            if context in ["Armors", "Weapons", "Items"]:
                if len(nameList) < BATCHSIZE:
                    nameList.append(data[i]["name"])
                    if "description" in data[i] and data[i]["description"] != "":
                        description = data[i]["description"]
                        description = description.replace("\n", " ")
                        descriptionList.append(description)
                    i += 1
                else:
                    batchFull = True
            if context in ["Skills"]:
                if len(nameList) < BATCHSIZE:
                    nameList.append(data[i]["name"])
                    if "description" in data[i] and data[i]["description"]:
                        descriptionList.append(data[i]["description"].replace("\n", " "))
                    # Messages (unchanged)
                    number = 1
                    while number < 5:
                        if f"message{number}" in data[i] and data[i][f"message{number}"]:
                            if data[i][f"message{number}"][0] in ["は", "を", "の", "に", "が"]:
                                msgResponse = translateGPT(
                                    "Taro" + data[i][f"message{number}"],
                                    "reply with only the gender neutral "
                                    + LANGUAGE
                                    + " translation of the action log. Always start the sentence with Taro. For example, Translate 'Taroを倒した！' as 'Taro was defeated!'",
                                    False,
                                )
                                data[i][f"message{number}"] = msgResponse[0].replace("Taro", "")
                                totalTokens[0] += msgResponse[1][0]
                                totalTokens[1] += msgResponse[1][1]
                                number += 1
                            else:
                                msgResponse = translateGPT(
                                    data[i][f"message{number}"],
                                    "reply with only the gender neutral " + LANGUAGE + " translation",
                                    False,
                                )
                                data[i][f"message{number}"] = msgResponse[0]
                                totalTokens[0] += msgResponse[1][0]
                                totalTokens[1] += msgResponse[1][1]
                                number += 1
                        else:
                            number += 1
                    i += 1
                else:
                    batchFull = True
            if context in ["Enemies", "Classes", "MapInfos"]:
                if len(nameList) < BATCHSIZE:
                    nameList.append(data[i]["name"])
                    i += 1
                else:
                    batchFull = True

        # Batch Full
        if batchFull == True or i >= len(data):
            k = j  # Original Index
            if context in "Actors":
                # Name
                response = translateGPT(nameList, newContext, True)
                translatedNameBatch = response[0]
                totalTokens[0] += response[1][0]
                totalTokens[1] += response[1][1]

                # Nickname
                if nicknameList:
                    response = translateGPT(nicknameList, newContext, True)
                    translatedNicknameBatch = response[0]
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]

                # Profile
                if profileList:
                    response = translateGPT(profileList, "", True)
                    translatedProfileBatch = response[0]
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]

                # Set Data
                if len(nameList) == len(translatedNameBatch):
                    j = k
                    while j < i:
                        # Empty Data
                        if data[j] is None or data[j]["name"] == "":
                            j += 1
                            continue
                        else:
                            # Get Text
                            if data[j]["name"] != "":
                                with open("translations.txt", "a", encoding="utf-8") as file:
                                    file.write(f'{data[j]["name"]} ({translatedNameBatch[0]})\n')
                                    data[j]["name"] = translatedNameBatch[0]
                                translatedNameBatch.pop(0)
                            if "nickname" in data[j] and data[j]["nickname"]:
                                data[j]["nickname"] = translatedNicknameBatch[0]
                                translatedNicknameBatch.pop(0)
                            if "profile" in data[j] and data[j]["profile"]:
                                data[j]["profile"] = dazedwrap.wrapText(translatedProfileBatch[0], LISTWIDTH)
                                translatedProfileBatch.pop(0)

                            # If Batch is empty. Move on.
                            if len(translatedNameBatch) == 0:
                                nameList.clear()
                                profileList.clear()
                                nicknameList.clear()
                                batchFull = False
                                filling = False
                            j += 1
                else:
                    mismatch = True

            if context in ["Armors", "Weapons", "Items", "Skills"]:
                # Name
                response = translateGPT(nameList, newContext, True)
                translatedNameBatch = response[0]
                totalTokens[0] += response[1][0]
                totalTokens[1] += response[1][1]

                # Description
                if descriptionList:
                    response = translateGPT(
                        descriptionList,
                        f"Reply with only the {LANGUAGE} translation of the text.",
                        True,
                    )
                    translatedDescriptionBatch = response[0]
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]

                # Set Data
                if len(nameList) == len(translatedNameBatch):
                    j = k
                    with open("translations.txt", "a", encoding="utf-8") as file:
                        while j < i:
                            # Empty Data
                            if data[j] is None or data[j]["name"] == "":
                                j += 1
                                continue
                            else:
                                # Get Text
                                file.write(f'{data[j]['name']} ({translatedNameBatch[0]})\n')
                                data[j]["name"] = translatedNameBatch[0]
                                translatedNameBatch.pop(0)
                                if "description" in data[j] and data[j]["description"] != "":
                                    translatedDescriptionBatch[0] = dazedwrap.wrapText(translatedDescriptionBatch[0], LISTWIDTH)
                                    data[j]["description"] = translatedDescriptionBatch[0]
                                    translatedDescriptionBatch.pop(0)

                            # If Batch is empty. Move on.
                            if len(translatedNameBatch) == 0:
                                nameList.clear()
                                descriptionList.clear()
                                batchFull = False
                                filling = False
                            j += 1
                else:
                    mismatch = True
            if context in ["Enemies", "Classes", "MapInfos"]:
                response = translateGPT(nameList, newContext, True)
                translatedNameBatch = response[0]
                totalTokens[0] += response[1][0]
                totalTokens[1] += response[1][1]

                # Set Data
                if len(nameList) == len(translatedNameBatch):
                    j = k
                    while j < i:
                        # Empty Data
                        if data[j] is None or data[j]["name"] == "":
                            j += 1
                            continue
                        else:
                            with open("translations.txt", "a", encoding="utf-8") as file:
                                file.write(f'{data[j]["name"]} ({translatedNameBatch[0]})\n')
                            # Get Text
                            data[j]["name"] = translatedNameBatch[0]
                            translatedNameBatch.pop(0)

                            # If Batch is empty. Move on.
                            if len(translatedNameBatch) == 0:
                                nameList.clear()
                                batchFull = False
                                filling = False
                            j += 1
                else:
                    mismatch = True

            # Mismatch
            if mismatch == True:
                MISMATCH.append(nameList)
                nameList.clear()
                profileList.clear()
                descriptionList.clear()
                filling = False
                mismatch = False
                batchFull = False

                i += 1

    return totalTokens


def searchCodes(page, pbar, jobList, filename):
    if len(jobList) > 0:
        list401 = jobList[0]
        list122 = jobList[1]
        list355655 = jobList[2]
        list108 = jobList[3]
        list356 = jobList[4]
        list357 = jobList[5]
        list408 = jobList[6]
        setData = False
    else:
        list401 = []
        list122 = []
        list355655 = []
        list108 = []
        list356 = []
        list357 = []
        list408 = []
        setData = True
    textHistory = []
    match = []
    totalTokens = [0, 0]
    translatedText = ""
    speaker = ""
    speakerID = None
    syncIndex = 0
    CLFlag = False
    maxHistory = MAXHISTORY
    VNameValue = None
    global LOCK
    global NAMESLIST
    global MISMATCH
    global PBAR
    with LOCK:
        PBAR = pbar

    # Begin Parsing File
    try:
        # Normal Format
        if "list" in page:
            codeList = page["list"]

        # Special Format (Scenario)
        else:
            codeList = page

        # Iterate through page
        i = 0
        while i < len(codeList):
            with LOCK:
                # syncIndex will keep i in sync when it gets modified
                if syncIndex > i:
                    i = syncIndex
                if len(codeList) <= i:
                    break

            # Declare Varss
            currentGroup = []
            nametag = ""

            ## Event Code: 401 Show Text
            if "code" in codeList[i] and codeList[i]["code"] in [401, 405, -1] and (CODE401 or CODE405):
                # Save Code and starting index (j)
                code = codeList[i]["code"]
                j = i
                endtag = ""
                instantLineFlag = False

                # Grab String
                if len(codeList[i]["parameters"]) > 0:
                    jaString = codeList[i]["parameters"][0]
                    oldjaString = jaString
                else:
                    codeList[i]["code"] = -1
                    i += 1
                    continue

                # # For Retarded Devs
                # retardRegex = r'([\\]+[nN]\[[\\]+V\[\d*?\]\])'
                # match = re.search(retardRegex, jaString)
                # if match:
                #     if VNameValue == 1:
                #         jaString = re.sub(retardRegex, 'リッカ', jaString)
                #     if VNameValue == 2:
                #         jaString = re.sub(retardRegex, 'ミミ', jaString)
                #     if VNameValue == 3:
                #         jaString = re.sub(retardRegex, 'ヒトミ', jaString)
                #     if VNameValue == 4:
                #         jaString = re.sub(retardRegex, 'Taro', jaString)
                #     if VNameValue == 5:
                #         jaString = re.sub(retardRegex, '富士見', jaString)

                # Speaker Check
                speakerList = []

                # m and z Codes
                match = re.search(r"(.*?)[\\]+m\[\d+?\][\\]+z\[\d+?\]", jaString)
                if match:
                    speakerList.append(match.group(1))
                    if "\\c" in speakerList[0]:
                        speakerList = re.findall(
                            r"^[\\]+[cC]\[[\d]+\]【?(.+?)】?[\\]+[Cc]\[[\d]\]\\?\\?$",
                            speakerList[0],
                        )

                # Brackets
                if len(speakerList) == 0:
                    speakerList = re.findall(r"^【(.*?)】$|^【(.*?)】[\\]*[a-zA-Z]*\[.*\]$", jaString)
                    if speakerList:
                        if speakerList[0][0]:
                            speakerList = [speakerList[0][0]]
                        else:
                            speakerList = [speakerList[0][1]]

                # Colors
                if len(speakerList) == 0:
                    speakerList = re.findall(
                        r"^[\\]+[cC]\[[\d]+\]【?(.+?)】?[\\]+[Cc]\[?[\d]?\]?\\?\\?$",
                        jaString,
                    )

                # Colons
                if len(speakerList) == 0:
                    speakerList = re.findall(
                        r"[\\]*[cC]?\[?\d*\]?(.+)：$",
                        jaString,
                    )

                # First Line Speakers
                if len(speakerList) == 0 and FIRSTLINESPEAKERS is True:
                    # Remove any RPGMaker Code at start
                    ffMatch = re.search(
                        r"^((?:[\\]+[^cCnNiIkKvV]+\[[\d\w]+\])+)",
                        jaString,
                    )
                    if ffMatch != None:
                        jaString = jaString.replace(ffMatch.group(0), "")
                        nametag += ffMatch.group(0)

                    # Test Speaker
                    if (
                        len(jaString) < 40
                        and "code" in codeList[i + 1]
                        and codeList[i + 1]["code"] in [401, 405, -1]
                        and len(codeList[i + 1]["parameters"]) > 0
                        and len(codeList[i + 1]["parameters"][0]) > 0
                    ):
                        nextString = codeList[i + 1]["parameters"][0].strip()

                        # Remove any RPGMaker Code at start
                        ffMatchNS = re.search(
                            r"^((?:[\\]+[^cCnNiIkKvV{}]+\[[\d\w\W]+\])+)",
                            nextString,
                        )
                        if ffMatchNS != None:
                            nextString = nextString.replace(ffMatchNS.group(1), "")

                        if nextString and nextString[0] in [
                            "「",
                            '"',
                            "(",
                            "（",
                            "*",
                            "[",
                        ]:
                            speakerList = re.findall(r".+", jaString)

                # Replace Speaker
                if len(speakerList) != 0 and codeList[i + 1]["code"] in [401, 405, -1]:
                    # Get Speaker
                    response = getSpeaker(speakerList[0])
                    speaker = response[0]
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]

                    # Set Data
                    if not setData:
                        codeList[i]["parameters"][0] = nametag + jaString.replace(speakerList[0], speaker)
                    nametag = ""

                    # Iterate to next string
                    i += 1
                    j = i
                    while codeList[i]["code"] in [-1]:
                        i += 1
                        j = i
                    jaString = codeList[i]["parameters"][0]

                # Replace Symbols
                jaString = jaString.replace("…", "...")
                jaString = jaString.replace("。", ".")
                jaString = jaString.replace("･", ".")
                jaString = jaString.replace("「", '"')
                jaString = jaString.replace("」", '"')

                # Check if there is text to translate
                if not re.search(r"\w+", jaString):
                    i += 1
                    continue

                # Validate Japanese Text
                if not re.search(LANGREGEX, jaString) and IGNORETLTEXT:
                    i += 1
                    continue

                # Using this to keep track of 401's in a row.
                currentGroup.append(jaString)

                # Join Up 401's into single string
                if len(codeList) > i + 1:
                    while codeList[i + 1]["code"] in [401, 405, -1] and len(codeList[i]["parameters"]) > 0 and not re.match(r"^(\s*[\\]+[aAbBdDeEfFgGhHjJlLmMoOpPqQrRsStTuUwWxXyYzZ]+\[[\w\d\[\]\\]+\])", codeList[i+1]["parameters"][0]):
                        if not setData:
                            codeList[i]["parameters"] = []
                            codeList[i]["code"] = -1
                        i += 1
                        j = i

                        jaString = codeList[i]["parameters"][0]
                        if jaString.strip():
                            currentGroup.append(jaString)

                        # Make sure not the end of the list.
                        if len(codeList) <= i + 1:
                            break

                # Format String
                if len(currentGroup) > 0:
                    finalJAString = "\n".join(currentGroup)
                    oldjaString = finalJAString

                    # Set Back
                    if not setData:
                        codeList[i]["parameters"] = [finalJAString]

                    ### \\n<Speaker>
                    regex = r"([\\]+[kKnN][wWcCrRrEe]?[\[<](.*?)[>])"
                    match = re.search(regex, finalJAString)

                    # Set Name
                    if match:
                        nametag = match.group(1)
                        speaker = match.group(2)

                        # Translate Speaker
                        response = getSpeaker(speaker)
                        tledSpeaker = response[0]
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]

                        # Set Nametag and Remove from Final String
                        finalJAString = finalJAString.replace(nametag, "")
                        nametag = nametag.replace(speaker, tledSpeaker)
                        speaker = tledSpeaker

                    # Remove Extra Stuff bad for translation.
                    finalJAString = finalJAString.replace("ﾞ", "")
                    finalJAString = finalJAString.replace("…", "...")
                    finalJAString = finalJAString.replace("。", ".")
                    finalJAString = re.sub(r"(\.{3}\.+)", "...", finalJAString)
                    finalJAString = finalJAString.replace("　", "")
                    finalJAString = finalJAString.replace("「", '"')
                    finalJAString = finalJAString.replace("」", '"')
                    finalJAString = finalJAString.replace("\\,", ',')

                    ### Remove format codes
                    # Furigana
                    rcodeMatch = re.findall(r"([\\]+[r][b]?\[.*?,(.*?)\])", finalJAString)
                    if len(rcodeMatch) > 0:
                        for match in rcodeMatch:
                            finalJAString = finalJAString.replace(match[0], match[1])

                    # Remove any RPGMaker Code at start
                    ffMatch = re.search(
                        r"^((?:[\\]+[^cCnNiIkKvV{}]+\[[\d\w\W]+\])+)",
                        finalJAString,
                    )
                    if ffMatch != None:
                        finalJAString = finalJAString.replace(ffMatch.group(1), "")
                        nametag = ffMatch.group(1) + nametag

                    # Remove _ABL Codes
                    ffMatch = re.search(r"^(_ABL).*", finalJAString)
                    if ffMatch != None:
                        finalJAString = finalJAString.replace(ffMatch.group(1), "")
                        nametag += ffMatch.group(1)

                    # Center Lines
                    if "\\CL" in finalJAString or "\\ac" in finalJAString:
                        finalJAString = finalJAString.replace("\\CL ", "")
                        finalJAString = finalJAString.replace("\\CL", "")
                        finalJAString = finalJAString.replace("\\ac ", "")
                        finalJAString = finalJAString.replace("\\ac", "")
                        CLFlag = True

                    # Handle Formatting Codes
                    if "\\>" in finalJAString:
                        instantLineFlag = True
                        finalJAString = finalJAString.replace("\\>", "")

                    # Check if Empty
                    if finalJAString == "":
                        if nametag:
                            codeList[j]["parameters"][0] = codeList[j]["parameters"][0].replace(match.group(2), tledSpeaker)
                        i += 1
                        continue

                    # Pass 1 (Grabbing Data)
                    if setData:
                        # Remove Textwrap
                        if FIXTEXTWRAP:
                            finalJAString = finalJAString.replace("\n", " ")
                        if "\\px[200]" in finalJAString:
                            finalJAString = finalJAString.replace("\\px[200]", "")

                        # Append
                        if finalJAString != "":
                            if speaker == "" and finalJAString != "":
                                list401.append(finalJAString)
                            elif finalJAString != "":
                                list401.append(f"[{speaker}]: {finalJAString}")
                            else:
                                list401.append(speaker)
                        speaker = ""
                        match = []
                        nametag = ""
                        currentGroup = []
                        syncIndex = i + 1

                        # Keep textHistory list at length maxHistory
                        textHistory.append('"' + finalJAString + '"')
                        if len(textHistory) > maxHistory:
                            textHistory.pop(0)

                    # Pass 2 (Setting Data)
                    else:
                        # Grab Translated String
                        if len(list401) > 0:
                            translatedText = list401[0]

                            # Remove speaker
                            match = re.search(r'(^\[.+?\]\s?[|:]\s?)', translatedText)
                            if match:
                                translatedText = translatedText.replace(match.group(1), "") 

                            # Fix '- '
                            translatedText = translatedText.replace("- ", "-")

                            # Textwrap
                            if FIXTEXTWRAP is True:
                                finalJAString = re.sub(r"\n", " ", finalJAString)
                                finalJAString = finalJAString.replace("<br>", " ")

                            if FIXTEXTWRAP is True and "_ABL" in nametag:
                                translatedText = dazedwrap.wrapText(translatedText, width=100)
                            elif FIXTEXTWRAP is True:
                                translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)

                            # Formatting Code
                            if instantLineFlag:
                                translatedText = translatedText.replace("\n", "\n\\>")
                                translatedText = f"\\>{translatedText}"

                            # BR Flag
                            if BRFLAG is True:
                                translatedText = translatedText.replace("\n", "<br>")

                            # px
                            if "\\px[200]" in nametag:
                                translatedText = translatedText.replace("\\px[200]", "")
                                translatedText = translatedText.replace("\n", "\n\\px[200]")

                            ### Add Var Strings
                            # CL Flag
                            if CLFlag:
                                translatedText = "\\ac " + translatedText
                                translatedText = translatedText.replace("\n", "\n\\ac ")
                                translatedText = re.sub(r"[\\]+?ac\s+", r"\\ac ", translatedText)
                                CLFlag = False

                            # Add Nametag Back In
                            translatedText = nametag + translatedText
                            nametag = ""

                            # Endtag
                            if endtag != "":
                                translatedText = translatedText + endtag
                                endtag = ""

                            # Set Code
                            codeList[j]["code"] = code

                            # Handle 405
                            if codeList[j]["code"] == 405:
                                # 1. Split translatedText by newlines
                                lines = [line for line in translatedText.split('\n') if line.strip() != ""]
                                
                                # 2. Set the first string to codeList[j]["parameters"]
                                codeList[j]["parameters"] = [lines[0]]
                                
                                # 3. Make copies for each additional line and insert them
                                for idx, line in enumerate(lines[1:]):
                                    new_item = copy.deepcopy(codeList[j])
                                    new_item["parameters"] = [line]
                                    codeList.insert(j + idx + 1, new_item)
                                
                                # 4. Update syncIndex to the last modified/added position
                                syncIndex = j + len(lines)

                            # Handle 401
                            else:
                                codeList[j]["parameters"] = [translatedText]
                                codeList[j]["code"] = code
                                syncIndex = i + 1

                            # Reset
                            speaker = ""
                            match = []
                            currentGroup = []
                            list401.pop(0)

            ## Event Code: 122 [Set Variables]
            if "code" in codeList[i] and codeList[i]["code"] == 122 and CODE122 is True:
                # This is going to be the var being set. (IMPORTANT)
                if codeList[i]["parameters"][0] not in list(range(0, 2000)):
                    i += 1
                    continue

                jaString = codeList[i]["parameters"][4]

                # # For Retarded Devs
                # VNameValue = jaString
                # i += 1
                # continue

                # Validate String
                if not isinstance(jaString, str):
                    i += 1
                    continue

                # Definitely don't want to mess with files
                if 'gameV' in jaString or '_' in jaString or '"[' in jaString:
                    i += 1
                    continue

                # # Avoid anything not quoted
                # if '\"' not in jaString:
                #     i += 1
                #     continue

                # Validate Japanese Text
                # if not re.search(LANGREGEX, jaString):
                #     i += 1
                #     continue

                # Set String
                matchedText = None
                if len(re.findall(r"([\'\"\`])", jaString)) >= 2:
                    matchedText = re.search(r"[\'\"\`](.*)[\'\"\`]", jaString)
                    if matchedText and matchedText.group(1).strip():
                        # Remove Textwrap
                        finalJAString = matchedText.group(1).replace("\\n", " ")

                        # Pass 1
                        if setData:
                            if finalJAString != "":
                                list122.append(finalJAString)

                        # Pass 2
                        else:
                            if len(list122) > 0:
                                # Grab and Replace
                                translatedText = list122[0]
                                translatedText = jaString.replace(jaString, translatedText)

                                # Remove characters that may break scripts
                                charList = ['"', "\\n"]
                                for char in charList:
                                    translatedText = translatedText.replace(char, "")

                                # Force 4 Escapes
                                translatedText = re.sub(r'(?<![\\])([\\]{1})(?=\w)', r'\\\\', translatedText)

                                # Textwrap
                                translatedText = dazedwrap.wrapText(translatedText, width=LISTWIDTH)
                                translatedText = translatedText.replace("\n", "\\n")

                                # Set
                                codeList[i]["parameters"][4] = f"`{translatedText}`"
                                list122.pop(0)

            ## Event Code: 357 [Picture Text] [Optional]
            if "code" in codeList[i] and codeList[i]["code"] == 357 and CODE357 is True:
                headerString = codeList[i]["parameters"][0]
                argVar = None

                def translatePlugins(argVar, font):
                    ### Message Text First
                    if argVar in codeList[i]["parameters"][3]:
                        acExist = False
                        jaString = codeList[i]["parameters"][3][argVar]

                        # Check ac
                        if "\\ac" in jaString:
                            acExist = True
                        else:
                            acExist = False

                        # If there isn't any Japanese in the text just skip
                        # if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', jaString):
                        #     i += 1
                        #     continue

                        # Remove any textwrap & TL
                        jaString = jaString.replace("\\n", " ")
                        if acExist:
                            jaString = jaString.replace("\\ac ", " ")
                            jaString = jaString.replace("\\ac", "")

                        # Pass 1
                        if setData:
                            list357.append(jaString)

                        # Pass 2
                        else:
                            if len(list357) > 0:
                                # Grab and Replace
                                translatedText = list357[0]
                                translatedText = jaString.replace(jaString, translatedText)

                                # Remove characters that may break scripts
                                charList = ['"', "\\n"]
                                for char in charList:
                                    translatedText = translatedText.replace(char, "")

                                # Textwrap
                                # translatedText = dazedwrap.wrapText(translatedText, 80)
                                # translatedText = translatedText.replace("\n", "\\n")
                                # translatedText = re.sub(r"[\\]+c", r"\\\\c", translatedText)
                                translatedText = re.sub(r"[\\]+\*item", r"\\\\*item", translatedText)

                                # Center Text
                                if acExist:
                                    translatedText = f'\\ac {translatedText.replace('\n', '\n\\ac ')}'

                                # Check and Set Font
                                if "fontSize" in codeList[i]["parameters"][3]:
                                    if font:
                                        codeList[i]["parameters"][3]["fontSize"] = font

                                # Set
                                codeList[i]["parameters"][3][argVar] = f"{translatedText}"
                                list357.pop(0)

                # Map Plugins
                headerMappings = {
                    "LL_InfoPopupWIndow": ("messageText", None),
                    "QuestSystem": ("DetailNote", None),
                    "BalloonInBattle": ("text", None),
                    "MNKR_CommonPopupCoreMZ": ("text", None),
                    "DestinationWindow": ("destination", None),
                    "_TMLogWindowMZ": ("text", None),
                    "TorigoyaMZ_NotifyMessage": ("message", None),
                    "SoR_GabWindow": ("arg1", None),
                    "DarkPlasma_CharacterText": ("text", None),
                    "DTextPicture": ("text", None),
                    "TextPicture": ("text", None),
                    "TRP_SkitMZ": ("name", None),
                }

                for key, (argVar, font) in headerMappings.items():
                    if key in headerString:
                        translatePlugins(argVar, font)

                if headerString == "LL_GalgeChoiceWindow":
                    ### Message Text First
                    jaString = codeList[i]["parameters"][3]["messageText"]

                    # Remove any textwrap & TL
                    jaString = re.sub(r"\n", " ", jaString)
                    response = translateGPT(jaString, "", False)
                    translatedText = response[0]
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]

                    # Textwrap & Set
                    translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)
                    codeList[i]["parameters"][3]["messageText"] = translatedText

                    ### Choices
                    jaString = codeList[i]["parameters"][3]["choices"]
                    matchList = re.findall(r'"label[\\]*":[\\]*"(.*?)[\\]', jaString)
                    if matchList != None:
                        # Translate
                        question = codeList[i]["parameters"][3]["messageText"]
                        response = translateGPT(
                            matchList,
                            f"Previous text for context: {question}\n",
                            True,
                        )
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]
                        translatedText = jaString

                        # Replace Strings
                        for j in range(len(matchList)):
                            translatedText = translatedText.replace(matchList[j], response[0][j].replace('"', ''))

                        # Set Data
                        codeList[i]["parameters"][3]["choices"] = translatedText

            ## Event Code: 657 [Picture Text] [Optional]
            if "code" in codeList[i] and codeList[i]["code"] == 657 and CODE657 is True:
                if "text" in codeList[i]["parameters"][0]:
                    jaString = codeList[i]["parameters"][0]
                    if not isinstance(jaString, str):
                        i += 1
                        continue

                    # Definitely don't want to mess with files
                    if "_" in jaString:
                        i += 1
                        continue

                    # If there isn't any Japanese in the text just skip
                    if not re.search(LANGREGEX, jaString):
                        i += 1
                        continue

                    # Remove outside text
                    startString = re.search(r"^[^一-龠ぁ-ゔァ-ヴー\<\>【】\\]+", jaString)
                    jaString = re.sub(r"^[^一-龠ぁ-ゔァ-ヴー\<\>【】\\]+", "", jaString)
                    endString = re.search(r"[^一-龠ぁ-ゔァ-ヴー\<\>【】。！？\\]+$", jaString)
                    jaString = re.sub(r"[^一-龠ぁ-ゔァ-ヴー\<\>【】。！？\\]+$", "", jaString)
                    if startString is None:
                        startString = ""
                    else:
                        startString = startString.group()
                    if endString is None:
                        endString = ""
                    else:
                        endString = endString.group()

                    # Remove any textwrap
                    jaString = re.sub(r"\n", " ", jaString)

                    # Translate
                    response = translateGPT(jaString, "", True)
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]
                    translatedText = response[0]

                    # Remove characters that may break scripts
                    charList = [".", '"', "'"]
                    for char in charList:
                        translatedText = translatedText.replace(char, "")

                    # Textwrap
                    translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)
                    translatedText = startString + translatedText + endString

                    # Set Data
                    codeList[i]["parameters"][0] = translatedText

            ## Event Code: 101 [Name] [Optional]
            if "code" in codeList[i] and codeList[i]["code"] == 101 and CODE101 is True:
                isVar = False

                # Grab String
                jaString = ""
                if len(codeList[i]["parameters"]) > 4:
                    jaString = codeList[i]["parameters"][4]
                # Check for Var
                elif len(codeList[i]["parameters"]) > 0:
                    jaString = codeList[i]["parameters"][0]
                    isVar = True
                if not isinstance(jaString, str):
                    i += 1
                    continue

                # Force Speaker using var
                if "memerisu" in jaString.lower():
                    speaker = "Memerisu"
                    i += 1
                    continue
                elif "thina" in jaString.lower():
                    speaker = "Tina"
                    i += 1
                    continue
                elif "\\ap" in jaString:
                    speaker = re.search(r"[\\]+AP\[(.*?)\]", jaString).group(1)
                    i += 1
                    continue

                # Get Speaker
                match = re.search(r"^(?:[\\]+[cC]\[\d+?\])?([\w\s]+)", jaString)
                if match:
                    jaString = match.group(1)
                    response = getSpeaker(jaString)
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]
                    speaker = response[0]

                    # Validate Speaker is not empty
                    if len(speaker) > 0:
                        if isVar == False:
                            codeList[i]["parameters"][4] = codeList[i]["parameters"][4].replace(jaString, speaker)
                            i += 1
                            continue
                        else:
                            codeList[i]["parameters"][0] = codeList[i]["parameters"][0].replace(jaString, speaker)
                            isVar = False
                            i += 1
                            continue
                    else:
                        speaker = ""
                elif FACENAME101:
                    faceName = codeList[i]["parameters"][0]
                    if faceName == "Actor1_1":
                        speaker = "Sakura"
                    if faceName == "Actor2_1":
                        speaker = "Suzune"
                    if faceName == "Actor3_1":
                        speaker = "Kaji"
                    if faceName == "Actor4_1":
                        speaker = "Kirari"
                    if faceName == "Actor5_1":
                        speaker = "Onsen"
                    if faceName == "Actor6_1":
                        speaker = "Gufu"
                    if faceName == "Actor7_1":
                        speaker = "Kahimeru"
                    if faceName == "Actor10_1":
                        speaker = "Miuma"
                    if faceName == "Actor11_1":
                        speaker = "Nurari"
                    if faceName == "Actor12_1":
                        speaker = "Kokotsuzumi"

            ## Event Code: 355 or 655 Scripts [Optional]
            if "code" in codeList[i] and (codeList[i]["code"] == 355 or codeList[i]["code"] == 655) and CODE355655 is True:
                jaString = codeList[i]["parameters"][0]
                
                patterns = {
                    "テキスト-": (r"テキスト-(.+)")
                    # "var text": (r"var\stext\d+\s=\s\"(.+)\""),
                    # "logtxt = ": (r"logtxt\s=\s'(.+)'" 
                    # ".setNickname": (r'.setNickname\(\\?"(.+?)\\?"\)'
                    # "_subject=": (r'_subject=(.+?)_'
                    # "text =": (r"text\s*=\s*'(.+[^\\])'"),
                    # "ex_a_name": (r'ex_a_name\(\d+,"(.+)"\)'),
                    # "gameVariables.setValue": (r":\$gameVariables.setValue\(\d+,'(.+)'\)"),
                    # "BattleManager._logWindow.push('addText'": (r"BattleManager._logWindow.push\('addText',\s'(.+)'\)"),
                }

                for key, (regex) in patterns.items():
                    if key in jaString:
                        match = re.search(regex, jaString)
                        if match:
                            # Pass 1
                            if setData:
                                list355655.append(match.group(1))

                            # Pass 2
                            else:
                                # Grab and Replace
                                translatedText = list355655[0]
                                list355655.pop(0)

                                # Only escape if not already escaped 
                                matchList = re.findall(r"(.+)'\s*[$+].+?'(.+)", translatedText)
                                if matchList:
                                    for string in matchList[0]:
                                        escapedMatch = re.sub(r"(?<!\\)'", r"\\'", string)
                                        translatedText = translatedText.replace(string, escapedMatch)
                                else:
                                    translatedText = re.sub(r"(?<!\\)'", r"\\'", translatedText)
                                translatedText = re.sub(r'(?<!\\)"', r'"', translatedText)
                                # Double backslashes before control codes
                                translatedText = re.sub(r'(?<![\\])([\\]{1})(?=\w)', r'\\\\', translatedText)

                                # Set
                                codeList[i]["parameters"][0] = jaString.replace(match.group(1), translatedText)
                        break

            ## Event Code: 408 (Script)
            if "code" in codeList[i] and (codeList[i]["code"] == 408) and CODE408 is True:
                # Remove Textwrap
                jaString = codeList[i]["parameters"][0]
                # jaString = jaString.replace("\n", " ")

                # Pass 1
                if setData:
                    list408.append(jaString)
                
                # Pass 2
                else:
                    translatedText = list408[0]
                    list408.pop(0)

                    # Textwrap
                    translatedText = dazedwrap.wrapText(translatedText, width=1000)

                    # Set Data
                    codeList[i]["parameters"][0] = f"{translatedText}"

            ## Event Code: 108 (Script)
            if "code" in codeList[i] and (codeList[i]["code"] == 108) and CODE108 is True:
                jaString = codeList[i]["parameters"][0]

                # If there isn't any Japanese in the text just skip
                if not re.search(LANGREGEX, jaString):
                    i += 1
                    continue

                # Translate
                if "info:" in jaString:
                    regex = r"info:(.*)"
                elif "ActiveMessage:" in jaString:
                    regex = r"<ActiveMessage:(.*)>?"
                elif "event_text" in jaString:
                    regex = r"event_text\s*:\s*(.*)"
                elif "Menu Name" in jaString:
                    regex = r"Menu\sName\s*:\s*(.*)>"
                else:
                    i += 1
                    continue

                # Need to remove outside code and put it back later
                match = re.search(regex, jaString)
                if match:
                    # Pass 1
                    if setData:
                        list108.append(match.group(1))

                        # # Grab Next
                        # j = i
                        # while codeList[j + 1]["code"] == 408:
                        #     j += 1
                        #     list108[0] = list108[0] + codeList[j]["parameters"][0].replace(">", "")
                        #     codeList[j]["parameters"][0] = ""
                        #     list108[0] = list108[0].replace("\n", " ")

                    # Pass 2
                    else:
                        # Grab and Replace
                        translatedText = list108[0]
                        list108.pop(0)

                        # Textwrap
                        # if codeList[i + 1]["code"] == 408:
                        #     translatedText = dazedwrap.wrapText(translatedText, WIDTH)

                        # Remove characters that may break scripts
                        charList = ['"']
                        for char in charList:
                            translatedText = translatedText.replace(char, "")
                        translatedText = translatedText.replace('"', '"')
                        translatedText = translatedText.replace(" ", "_")
                        translatedText = jaString.replace(match.group(1), translatedText)

                        # Add >
                        if "ActiveMessage" in translatedText and ">" not in translatedText:
                            translatedText = translatedText + ">"

                        # Set Data
                        codeList[i]["parameters"][0] = translatedText

            ## Event Code: 356
            if "code" in codeList[i] and codeList[i]["code"] == 356 and CODE356 is True:
                jaString = codeList[i]["parameters"][0]
                oldjaString = jaString

                # Grab Speaker
                if "Tachie showName" in jaString:
                    matchList = re.findall(r"Tachie showName (.+)", jaString)
                    if len(matchList) > 0:
                        # Translate
                        response = translateGPT(
                            matchList[0],
                            "Reply with the " + LANGUAGE + " translation of the NPC name.",
                            False,
                        )
                        translatedText = response[0]
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]

                        # Set Text
                        speaker = translatedText
                        speaker = speaker.replace(" ", " ")
                        codeList[i]["parameters"][0] = jaString.replace(matchList[0], speaker)
                    i += 1
                    continue

                # Want to translate this script
                if "D_TEXT " in jaString:
                    regex = r"D_TEXT\s([^\s]+)\s?\d*"
                elif "ShowInfo" in jaString:
                    regex = r"ShowInfo\s(.*)"
                elif "PushGab" in jaString:
                    regex = r"PushGab\s(.*)"
                elif "addLog" in jaString:
                    regex = r"addLog\s(.*)"
                elif "DW_" in jaString:
                    regex = r"DW_.*?\s(.*)"
                elif "CommonPopup" in jaString:
                    regex = r"CommonPopup\sadd\stext:(.*?)[\\]+}"
                elif "AddCustomChoice" in jaString:
                    regex = r"AddCustomChoice\s\d+\s(.+)\s\d"
                else:
                    regex = r""

                # Remove any textwrap
                jaString = re.sub(r"\n", "_", jaString)

                # Capture Arguments and text
                textMatch = re.search(regex, jaString)
                if textMatch and textMatch.group(0) != "":
                    text = textMatch.group(1)

                    # Capture Speakers
                    match = re.search(r"[\\]+ow\[\d+\][\\]+c\[\d+\](.+)", text)
                    if match:
                        speakerJA = match.group(1)

                        # Translate
                        response = getSpeaker(speakerJA)
                        translatedText = response[0]
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]
                        codeList[i]["parameters"][0] = jaString.replace(speakerJA, translatedText)
                        i += 1
                        continue
                    else:
                        speaker = ""

                    # Pass 1
                    if setData:
                        text = text.replace("_", " ")                       
                        list356.append(text)

                    # Pass 2
                    else:
                        if len(list356) > 0:
                            # Grab
                            translatedText = list356[0]

                            # Remove characters that may break scripts
                            charList = [".", '"']
                            for char in charList:
                                translatedText = translatedText.replace(char, "")

                            # Cant have spaces?
                            translatedText = translatedText.replace(" ", "_")
                            translatedText = translatedText.replace("__", "_")

                            # Put Args Back
                            translatedText = jaString.replace(text, translatedText)

                            # Set Data
                            codeList[i]["parameters"][0] = translatedText
                            list356.pop(0)

                if "namePop" in jaString:
                    matchList = re.findall(r"<namePop:(.*?)\s?[\d-]+?", jaString)
                    if len(matchList) > 0:
                        # Translate
                        text = matchList[0]
                        response = translateGPT(text, "Reply with the " + LANGUAGE + " Translation", False)
                        translatedText = response[0]
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]

                        # Set Data
                        translatedText = jaString.replace(text, translatedText)
                        codeList[i]["parameters"][0] = translatedText

                if "LL_InfoPopupWIndowMV" in jaString:
                    matchList = re.findall(r"LL_InfoPopupWIndowMV\sshowWindow\s(.+?) .+", jaString)
                    if len(matchList) > 0:
                        # Translate
                        text = matchList[0]
                        response = translateGPT(text, "Reply with the " + LANGUAGE + " Translation", False)
                        translatedText = response[0]
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]

                        # Set Data
                        translatedText = translatedText.replace(" ", "_")
                        translatedText = jaString.replace(text, translatedText)
                        codeList[i]["parameters"][0] = translatedText

                if "OriginMenuStatus SetParam" in jaString:
                    matchList = re.findall(r"OriginMenuStatus\sSetParam\sparam[\d]\s(.*)", jaString)
                    if len(matchList) > 0:
                        # Translate
                        text = matchList[0]
                        response = translateGPT(text, "Reply with the " + LANGUAGE + " Translation", False)
                        translatedText = response[0]
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]

                        # Set Data
                        translatedText = translatedText.replace(" ", "_")
                        translatedText = jaString.replace(text, translatedText)
                        codeList[i]["parameters"][0] = translatedText

                # LL_GalgeChoiceWindowMV Message
                if "LL_GalgeChoiceWindowMV setMessageText" in jaString:
                    ### Message Text First
                    match = re.search(r"LL_GalgeChoiceWindowMV setMessageText (.+)", jaString)
                    if match:
                        jaString = match.group(1)

                        # Remove any textwrap & TL
                        jaString = re.sub(r"\n", " ", jaString)
                        response = translateGPT(jaString, "", False)
                        translatedText = response[0]
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]

                        # Textwrap & Replace Whitespace
                        translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)
                        translatedText = translatedText.replace(" ", "_")

                        # Replace and Set
                        translatedText = match.group(0).replace(match.group(1), translatedText)
                        codeList[i]["parameters"][0] = translatedText

                # LL_GalgeChoiceWindowMV Choices
                if "LL_GalgeChoiceWindowMV setChoices":
                    match = re.search(r"LL_GalgeChoiceWindowMV setChoices (.+)", jaString)
                    if match:
                        jaString = match.group(1)
                        choiceList = jaString.split(",")

                        # Translate
                        question = translatedText
                        response = translateGPT(
                            choiceList,
                            f"Previous text for context: {question}\n",
                            True,
                        )
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]
                        choiceListTL = response[0]
                        translatedText = match.group(0)

                        # Replace Strings
                        for j in range(len(choiceListTL)):
                            choiceListTL[j] = choiceListTL[j].replace(" ", "_")
                            translatedText = translatedText.replace(choiceList[j], choiceListTL[j])

                        # Set Data
                        codeList[i]["parameters"][0] = translatedText

            ### Event Code: 102 Show Choice
            if "code" in codeList[i] and codeList[i]["code"] == 102 and CODE102 is True:
                choiceList = []
                varList = []
                for choice in range(len(codeList[i]["parameters"][0])):
                    jaString = codeList[i]["parameters"][0][choice]
                    jaString = jaString.replace(" 。", ".")

                    # Avoid Empty Strings
                    if jaString == "":
                        continue

                    # If and En Statements
                    ifVar = ""
                    ifList = re.findall(r"([ei][nf]\(.+?\)\)?\)?)", jaString)
                    if len(ifList) != 0:
                        for var in ifList:
                            jaString = jaString.replace(var, "")
                            ifVar += var
                    varList.append(ifVar)

                    # Append to List
                    choiceList.append(jaString)

                # Translate
                if len(textHistory) > 0:
                    response = translateGPT(
                        choiceList,
                        f"Reply with the English translation of the dialogue choice.\n\nPrevious text for context: {str(textHistory)}\n",
                        True,
                    )
                    translatedTextList = response[0]
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]
                else:
                    response = translateGPT(choiceList, "Reply with the English translation of the dialogue choice.", True)
                    translatedTextList = response[0]
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]

                # Check Mismatch
                if len(translatedTextList) == len(choiceList):
                    for choice in range(len(codeList[i]["parameters"][0])):
                        jaString = codeList[i]["parameters"][0][choice]
                        jaString = jaString.replace(" 。", ".")

                        # Avoid Empty Strings
                        if jaString == "":
                            continue

                        translatedText = translatedTextList[choice]

                        # Set Data
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]
                        if translatedText != "":
                            translatedText = varList[choice] + translatedText[0].upper() + translatedText[1:]
                        else:
                            translatedText = varList[choice] + translatedText
                        codeList[i]["parameters"][0][choice] = translatedText
                else:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)

            ### Event Code: 111 Script
            if "code" in codeList[i] and codeList[i]["code"] == 111 and CODE111 is True:
                for j in range(len(codeList[i]["parameters"])):
                    jaString = codeList[i]["parameters"][j]

                    # Check if String
                    if not isinstance(jaString, str):
                        i += 1
                        continue

                    # Only TL the Game Variable
                    if "$gameVariables" not in jaString:
                        i += 1
                        continue

                    # This is going to be the var being set. (IMPORTANT)
                    if "1045" not in jaString:
                        i += 1
                        continue

                    # Need to remove outside code and put it back later
                    matchList = re.findall(r"'(.*?)'", jaString)

                    for match in matchList:
                        response = translateGPT(match, "", False)
                        translatedText = response[0]
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]

                        # Remove characters that may break scripts
                        charList = [".", '"', "'", "\\n"]
                        for char in charList:
                            translatedText = translatedText.replace(char, "")

                        jaString = jaString.replace(match, translatedText)

                    # Set Data
                    translatedText = jaString
                    codeList[i]["parameters"][j] = translatedText

            ### Event Code: 320 Set Variable
            if "code" in codeList[i] and codeList[i]["code"] == 320 and CODE320 is True:
                jaString = codeList[i]["parameters"][1]
                if not isinstance(jaString, str):
                    i += 1
                    continue

                # Definitely don't want to mess with files
                if "■" in jaString or "_" in jaString:
                    i += 1
                    continue

                # If there isn't any Japanese in the text just skip
                if not re.search(LANGREGEX, jaString):
                    i += 1
                    continue

                # Translate
                response = getSpeaker(jaString)
                translatedText = response[0]
                totalTokens[0] += response[1][0]
                totalTokens[1] += response[1][1]

                # Remove characters that may break scripts
                charList = [".", '"', "'", "\\n"]
                for char in charList:
                    translatedText = translatedText.replace(char, "")

                # Set Data
                codeList[i]["parameters"][1] = translatedText

            # Iterate
            else:
                i += 1

        # EOF
        list401TL = []
        list408TL = []
        list122TL = []
        list356TL = []
        list357TL = []
        list355655TL = []
        list108TL = []
        PBAR = pbar

        # 401
        if len(list401) > 0:
            response = translateGPT(list401, "", True)
            list401TL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            if len(list401TL) != len(list401):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)

        # 122
        if len(list122) > 0:
            response = translateGPT(list122, "Keep your translation as brief as possible", True)
            list122TL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            if len(list122TL) != len(list122):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)

        # 355/655
        if len(list355655) > 0:
            response = translateGPT(list355655, textHistory, True)
            list355655TL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            if len(list355655TL) != len(list355655):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)

        # 108
        if len(list108) > 0:
            response = translateGPT(list108, textHistory, True)
            list108TL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            if len(list108TL) != len(list108):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)

        # 356
        if len(list356) > 0:
            response = translateGPT(list356, textHistory, True)
            list356TL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            if len(list356TL) != len(list356):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)

        # 357
        if len(list357) > 0:
            response = translateGPT(list357, textHistory, True)
            list357TL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            if len(list357TL) != len(list357):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)

        # 408
        if len(list408) > 0:
            response = translateGPT(list408, "", True)
            list408TL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            if len(list408TL) != len(list408):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)

        # Start Pass 2
        if setData:
            searchCodes(
                page,
                pbar,
                [list401TL, list122TL, list355655TL, list108TL, list356TL, list357TL, list408TL],
                filename,
            )

        # Delete all -1 codes
        codeListFinal = []
        for i in range(len(codeList)):
            if "code" in codeList[i] and codeList[i]["code"] != -1:
                codeListFinal.append(codeList[i])

        # Normal Format
        if "list" in page:
            page["list"] = codeListFinal

        # Special Format (Scenario)
        else:
            page[:] = codeListFinal
    except IndexError as e:
        traceback.print_exc()
    except Exception as e:
        traceback.print_exc()

    return totalTokens


def searchSS(state, pbar):
    totalTokens = [0, 0]

    # Name
    nameResponse = (
        translateGPT(
            state["name"],
            "Reply with only the " + LANGUAGE + " translation of the RPG Skill name.",
            False,
        )
        if "name" in state
        else ""
    )

    # Description
    descriptionResponse = (
        translateGPT(
            state["description"],
            "Reply with only the " + LANGUAGE + " translation of the description.",
            False,
        )
        if "description" in state
        else ""
    )

    # Messages
    message1Response = ""
    message4Response = ""
    message2Response = ""
    message3Response = ""

    if "message1" in state:
        if len(state["message1"]) > 0 and state["message1"][0] in [
            "は",
            "を",
            "の",
            "に",
            "が",
        ]:
            message1Response = translateGPT(
                "Taro" + state["message1"],
                "reply with only the gender neutral "
                + LANGUAGE
                + " translation of the action log. Always start the sentence with Taro. For example,\
Translate 'Taroを倒した！' as 'Taro was defeated!'",
                False,
            )
        else:
            message1Response = translateGPT(
                state["message1"],
                "reply with only the gender neutral " + LANGUAGE + " translation",
                False,
            )

    if "message2" in state:
        if len(state["message2"]) > 0 and state["message2"][0] in [
            "は",
            "を",
            "の",
            "に",
            "が",
        ]:
            message2Response = translateGPT(
                "Taro" + state["message2"],
                "reply with only the gender neutral "
                + LANGUAGE
                + " translation of the action log. Always start the sentence with Taro. For example,\
Translate 'Taroを倒した！' as 'Taro was defeated!'",
                False,
            )
        else:
            message2Response = translateGPT(
                state["message2"],
                "reply with only the gender neutral " + LANGUAGE + " translation",
                False,
            )

    if "message3" in state:
        if len(state["message3"]) > 0 and state["message3"][0] in [
            "は",
            "を",
            "の",
            "に",
            "が",
        ]:
            message3Response = translateGPT(
                "Taro" + state["message3"],
                "reply with only the gender neutral "
                + LANGUAGE
                + " translation of the action log. Always start the sentence with Taro. For example,\
Translate 'Taroを倒した！' as 'Taro was defeated!'",
                False,
            )
        else:
            message3Response = translateGPT(
                state["message3"],
                "reply with only the gender neutral " + LANGUAGE + " translation",
                False,
            )

    if "message4" in state:
        if len(state["message4"]) > 0 and state["message4"][0] in [
            "は",
            "を",
            "の",
            "に",
            "が",
        ]:
            message4Response = translateGPT(
                "Taro" + state["message4"],
                "reply with only the gender neutral "
                + LANGUAGE
                + " translation of the action log. Always start the sentence with Taro. For example,\
Translate 'Taroを倒した！' as 'Taro was defeated!'",
                False,
            )
        else:
            message4Response = translateGPT(
                state["message4"],
                "reply with only the gender neutral " + LANGUAGE + " translation",
                False,
            )

    # --- Batching pass: collect all note texts for all note types ---
    note_regexes = [
        (r"<help:([^>]*)>", False),
        (r"<STATE_HELP>\n(.*)\n", False),
        (r"<ShowHoverState:\s?(.+?)>", False),
        (r"<Detail:\s?(.+?)>", False),
    ]
    notesBatch = []
    notesBatchMap = []
    if "note" in state and state["note"]:
        note = state["note"]
        for regex, wordwrap in note_regexes:
            matches = re.findall(regex, note, re.DOTALL)
            for m in matches:
                match_text = m if isinstance(m, str) else m[0]
                notesBatch.append(match_text)
                notesBatchMap.append((regex, match_text, wordwrap))

    # --- Batch translate all notes ---
    translatedNotesBatch = []
    if notesBatch:
        response = translateGPT(notesBatch, f"Reply with only the {LANGUAGE} translation of the note text.", True)
        translatedNotesBatch = response[0]
        totalTokens[0] += response[1][0]
        totalTokens[1] += response[1][1]

    # --- Insert translated notes back ---
    note_insert_idx = 0
    if "note" in state and state["note"]:
        for regex, match_text, wordwrap in notesBatchMap:
            if note_insert_idx >= len(translatedNotesBatch):
                break
            translated = translatedNotesBatch[note_insert_idx]
            if wordwrap:
                translated = dazedwrap.wrapText(translated, width=NOTEWIDTH)
                translated = translated.replace('"', "")
            # Replace only the matched text in the note
            state["note"] = re.sub(re.escape(match_text), translated, state["note"], count=1)
            note_insert_idx += 1

    # Count totalTokens
    totalTokens[0] += nameResponse[1][0] if nameResponse != "" else 0
    totalTokens[1] += nameResponse[1][1] if nameResponse != "" else 0
    totalTokens[0] += descriptionResponse[1][0] if descriptionResponse != "" else 0
    totalTokens[1] += descriptionResponse[1][1] if descriptionResponse != "" else 0
    totalTokens[0] += message1Response[1][0] if message1Response != "" else 0
    totalTokens[1] += message1Response[1][1] if message1Response != "" else 0
    totalTokens[0] += message2Response[1][0] if message2Response != "" else 0
    totalTokens[1] += message2Response[1][1] if message2Response != "" else 0
    totalTokens[0] += message3Response[1][0] if message3Response != "" else 0
    totalTokens[1] += message3Response[1][1] if message3Response != "" else 0
    totalTokens[0] += message4Response[1][0] if message4Response != "" else 0
    totalTokens[1] += message4Response[1][1] if message4Response != "" else 0

    # Set Data
    if "name" in state:
        state["name"] = nameResponse[0].replace('"', "")
    if "description" in state:
        # Textwrap
        translatedText = descriptionResponse[0]
        translatedText = dazedwrap.wrapText(translatedText, width=LISTWIDTH)
        state["description"] = translatedText.replace('"', "")
    if "message1" in state:
        state["message1"] = message1Response[0].replace('"', "").replace("Taro", "")
    if "message2" in state:
        state["message2"] = message2Response[0].replace('"', "").replace("Taro", "")
    if "message3" in state:
        state["message3"] = message3Response[0].replace('"', "").replace("Taro", "")
    if "message4" in state:
        state["message4"] = message4Response[0].replace('"', "").replace("Taro", "")

    return totalTokens


def searchSystem(data, pbar):
    totalTokens = [0, 0]
    context = "Reply with only the " + LANGUAGE + ' translation of the UI textbox."'

    # Title
    response = translateGPT(
        data["gameTitle"],
        " Reply with the " + LANGUAGE + " translation of the game title name",
        False,
    )
    totalTokens[0] += response[1][0]
    totalTokens[1] += response[1][1]
    data["gameTitle"] = response[0].strip(".")

    # Terms
    for term in data["terms"]:
        if term != "messages":
            termList = data["terms"][term]
            for i in range(len(termList)):  # Last item is a messages object
                if termList[i] is not None:
                    response = translateGPT(termList[i], context, False)
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]
                    termList[i] = response[0].replace('"', "").strip()

    # Armor Types
    for i in range(len(data["armorTypes"])):
        response = translateGPT(
            data["armorTypes"][i],
            "Reply with only the " + LANGUAGE + " translation of the armor type",
            False,
        )
        totalTokens[0] += response[1][0]
        totalTokens[1] += response[1][1]
        data["armorTypes"][i] = response[0].replace('"', "").strip()

    # Skill Types
    for i in range(len(data["skillTypes"])):
        response = translateGPT(
            data["skillTypes"][i],
            "Reply with only the " + LANGUAGE + " translation",
            False,
        )
        totalTokens[0] += response[1][0]
        totalTokens[1] += response[1][1]
        data["skillTypes"][i] = response[0].replace('"', "").strip()

    # Equip Types
    for i in range(len(data["equipTypes"])):
        response = translateGPT(
            data["equipTypes"][i],
            "Reply with only the " + LANGUAGE + " translation of the equipment type. No disclaimers.",
            False,
        )
        totalTokens[0] += response[1][0]
        totalTokens[1] += response[1][1]
        data["equipTypes"][i] = response[0].replace('"', "").strip()

    # # Variables (Optional ususally)
    # for i in range(len(data['variables'])):
    #     response = translateGPT(data['variables'][i], 'Reply with only the '+ LANGUAGE +' translation of the title', False)
    #     totalTokens[0] += response[1][0]
    #     totalTokens[1] += response[1][1]
    #     data['variables'][i] = response[0].replace('\"', '').strip()

    # Messages
    messages = data["terms"]["messages"]
    for key, value in messages.items():
        response = translateGPT(
            value,
            "Reply with only the "
            + LANGUAGE
            + ' translation of the battle text.\nTranslate "常時ダッシュ" as "Always Dash"\nTranslate "次の%1まで" as Next %1.',
            False,
        )
        translatedText = response[0]

        # Remove characters that may break scripts
        charList = [".", '"', "\\n"]
        for char in charList:
            translatedText = translatedText.replace(char, "")

        totalTokens[0] += response[1][0]
        totalTokens[1] += response[1][1]
        messages[key] = translatedText

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
                False,
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

    return [input_list[i : i + batch_size] for i in range(0, len(input_list), batch_size)]


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
        msg.append({"role": "system", "content": "Translation History:"})
        msg.extend([{"role": "assistant", "content": h} for h in history])
    else:
        msg.append({"role": "assistant", "content": history})

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


def cleanTranslatedText(translatedText):
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
        "—": "―",
        "】": "]",
        "【": "[",
        "é": "e",
        "this guy": "this bastard",
        "This guy": "This bastard",
        "Placeholder Text": "",
        "```json": "",
        "```": "",
        # Add more replacements as needed
    }
    for target, replacement in placeholders.items():
        translatedText = translatedText.replace(target, replacement)

    # Remove Repeating Characters
    pattern = re.compile(r"(.)\s*\1(?:\s*\1){" + str(20 - 1) + r",}")
    translatedText = pattern.sub(lambda match: match.group(0).replace(" ", "")[:20], translatedText)

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
        translatedTextList = re.sub(r"(?<![\\])\"+(?![\n,])", r'"', translatedTextList)
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
    outputTotalTokens += round(len(enc.encode(user)) * 2.5)

    return [inputTotalTokens, outputTotalTokens]


@retry(exceptions=Exception, tries=5, delay=5)
def translateGPT(text, history, fullPromptFlag):
    global PBAR, MISMATCH, FILENAME
    if text:
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
                # Things to Check before starting translation
                if not re.search(LANGREGEX, str(tItem)):
                    if PBAR is not None:
                        PBAR.update(len(tItem))
                    if isinstance(tItem, list):
                        for j in range(len(tItem)):
                            tItem[j] = cleanTranslatedText(tItem[j])
                            tList[index] = tItem
                    else:
                        tList[index] = cleanTranslatedText(tItem)
                    history = tItem[-MAXHISTORY:]
                    continue

                # Before sending to translation, if we have a list of items, add the formatting
                if isinstance(tItem, list):
                    for j in range(len(tItem)):
                        if not tItem[j]:
                            tItem[j] = tItem[j].replace("", "Placeholder Text")
                    payload = {f"Line{i+1}": string for i, string in enumerate(tItem)}
                    payload = json.dumps(payload, indent=4, ensure_ascii=False)
                    varResponse = [payload, []]
                    subbedT = varResponse[0]
                else:
                    varResponse = [tItem, []]
                    subbedT = varResponse[0]

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

                # Set Tokens
                translatedText = response.choices[0].message.content

                # AI Refused, Try Again
                if not translatedText:
                    response = translateText(f"{system}\n You translate ALL content.", user, history, 0.1, format, model="gpt-4o")
                    translatedText = response.choices[0].message.content

                # Report Tokens
                totalTokens[0] += response.usage.prompt_tokens
                totalTokens[1] += response.usage.completion_tokens

                # Check Translation
                if translatedText:
                    translatedText = cleanTranslatedText(translatedText)
                    if isinstance(tItem, list):
                        extractedTranslations = extractTranslation(translatedText, True)
                        if extractedTranslations == None or len(tItem) != len(extractedTranslations):
                            # Mismatch. Try Again
                            response = translateText(system, user, history, 0.05, format, MODEL)
                            translatedText = response.choices[0].message.content
                            totalTokens[0] += response.usage.prompt_tokens
                            totalTokens[1] += response.usage.completion_tokens

                            # Formatting
                            translatedText = cleanTranslatedText(translatedText)
                            if isinstance(tItem, list):
                                extractedTranslations = extractTranslation(translatedText, True)
                                if extractedTranslations == None or len(tItem) != len(extractedTranslations):
                                    with open("log/mismatchHistory.txt", "a+", encoding="utf-8") as mismatchFile:
                                        mismatchFile.write(f"Mismatch: {FILENAME}\n")
                                        mismatchFile.write(f"Input:\n{subbedT}\n")
                                        mismatchFile.write(f"Output:\n{translatedText}\n")
                                        mismatch = True  # Just here for breakpoint
                        logFile.write(f"Input:\n{subbedT}\n")
                        logFile.write(f"Output:\n{translatedText}\n")

                        # Set if no mismatch
                        if mismatch == False:
                            tList[index] = extractedTranslations
                            history = extractedTranslations[-MAXHISTORY:]  # Update history if we have a list
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
                        tList[index] = translatedText.replace("Placeholder Text", "")
                else:
                    PBAR.write(f"AI Refused:{tItem}\n")

        # Combine if multilist
        if isinstance(tList[0], list):
            tList = [t for sublist in tList for t in sublist]

        # Return
        if format == "json":
            return [tList, totalTokens]
        else:
            return [tList[0], totalTokens]
    else:
        return [text, [0, 0]]
