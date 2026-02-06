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
FILENAME = None

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

def handlePlugin(filename, estimate):
    global ESTIMATE, PBAR, FILENAME
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
            # Perform translation first; incremental progress writes happen during translation.
            # We no longer keep the destination file open simultaneously to avoid Windows locking issues
            # during atomic os.replace operations inside save_progress_lines.
            start = time.time()
            translatedData = openFiles(filename)

            # Ensure final state is flushed (in case no incremental writes occurred for some reason).
            save_progress_lines(translatedData[0], filename)

            # Print Result
            end = time.time()
            tqdm.write(getResultString(translatedData, end - start, filename))
            with LOCK:
                TOKENS[0] += translatedData[1][0]
                TOKENS[1] += translatedData[1][1]
        except Exception:
            traceback.print_exc()
            return "Fail"

    return getResultString(["", TOKENS, None], end - start, "TOTAL")


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


def openFiles(filename):
    with open("files/" + filename, "r", encoding="utf_8") as readFile:
        translatedData = parsePlugin(readFile, filename)

        # Delete lines marked for deletion
        finalData = []
        for line in translatedData[0]:
            if line != "\\d\n":
                finalData.append(line)
        translatedData[0] = finalData

    return translatedData


def parsePlugin(readFile, filename):
    totalTokens = [0, 0]

    # Read File into data
    data = readFile.readlines()

    # Create Progress Bar
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE) as pbar:
        pbar.desc = filename

        try:
            result = translatePlugin(data, pbar, filename, [])
            totalTokens[0] += result[0]
            totalTokens[1] += result[1]
        except Exception as e:
            traceback.print_exc()
            return [data, totalTokens, e]
    return [data, totalTokens, None]


def save_progress_lines(lines, filename, encoding="utf_8"):
    """Atomically save current line-based translation progress."""
    try:
        if ESTIMATE:
            return
        global LOCK
        os.makedirs("translated", exist_ok=True)
        # Use a single lock to prevent concurrent replace attempts on Windows (which causes PermissionError)
        with LOCK:
            tmp_fd, tmp_path = tempfile.mkstemp(prefix=f"{filename}.", suffix=".tmp", dir="translated")
            try:
                with os.fdopen(tmp_fd, "w", encoding=encoding, newline="\n", errors="ignore") as tmp_file:
                    tmp_file.writelines(lines)

                dest_path = os.path.join("translated", filename)
                # Retry a few times in case another process/thread still has the file open momentarily.
                for attempt in range(5):
                    try:
                        os.replace(tmp_path, dest_path)
                        break
                    except PermissionError:
                        if attempt == 4:
                            raise
                        time.sleep(0.1 * (attempt + 1))
            finally:
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
    except Exception:
        traceback.print_exc()


def saveCheckLines(lines, filename, tokens=None, encoding="utf_8"):
    """Save progress only when tokens indicate work or when explicitly called after a mutation."""
    try:
        if tokens is not None:
            if not (isinstance(tokens, (list, tuple)) and len(tokens) >= 2 and (tokens[0] or tokens[1])):
                return
        save_progress_lines(lines, filename, encoding=encoding)
    except Exception:
        traceback.print_exc()


def translatePlugin(data, pbar, filename, translatedList):
    if len(translatedList) > 0:
        questList = translatedList[0]
        custom = translatedList[1]
        sceneMenuText = translatedList[2] if len(translatedList) > 2 else []
        sceneMenuCommonHelpText = translatedList[3] if len(translatedList) > 3 else []
        sceneMenuHelpText = translatedList[4] if len(translatedList) > 4 else []
        setData = True
    else:
        questList = [[], [], [], [], [], []]
        custom = []
        sceneMenuText = []
        sceneMenuCommonHelpText = []
        sceneMenuHelpText = []
        setData = False
    currentGroup = []
    tokens = [0, 0]
    speaker = ""
    voice = False
    global LOCK, ESTIMATE
    i = 0
    in_disp_list = False
    brace_count = 0

    # Category
    with open("log/translations.txt", "a+", encoding="utf-8") as tlFile:
                tlFile.write(f"\nCustom:\n")
                tlFile.close()

    while i < len(data):
        voice = False
        speaker = ""

        # Track if we're inside CBR_travel_data block
        if 'data_map_name_list' in data[i]:
            in_disp_list = True
            brace_count = 0
        
        if in_disp_list:
            # Count braces to know when we exit the object
            brace_count += data[i].count('{') - data[i].count('}')
            if brace_count < 0:
                in_disp_list = False

        # Nested array strings (e.g., this.disp_list = { key: { subkey: ["string1", "string2"] } })
        # Matches strings inside arrays within object literals
        if in_disp_list:
            regex_nested = r'"([^"]*[一-龠ぁ-ゔァ-ヴー]+[^"]*)"'
            matchList = re.findall(regex_nested, data[i])
            if len(matchList) > 0:
                for match in matchList:
                    # Save Original String
                    jaString = match
                    originalString = jaString

                    # Replace \n for translation
                    jaStringClean = jaString.replace("\\n", " ")

                    if jaStringClean.strip():
                        # Pass 1
                        if setData == False:
                            custom.append(jaStringClean.strip())

                        # Pass 2
                        else:
                            if custom:
                                # Grab and Pop
                                translatedText = custom[0]
                                custom.pop(0)

                                # Set to None if empty list
                                if len(custom) <= 0:
                                    custom = []

                                # Restore original newlines but keep translated text
                                # Count original newlines
                                newline_count = jaString.count("\\n")
                                if newline_count > 0:
                                    # Textwrap the translation
                                    translatedText = dazedwrap.wrapText(translatedText, 50)
                                    translatedText = translatedText.replace("\n", "\\n")

                                # Escape quotes in translation
                                translatedText = translatedText.replace('"', '\\"')

                                # Set Data
                                data[i] = data[i].replace(f'"{originalString}"', f'"{translatedText}"')
                                saveCheckLines(data, filename)

        # Custom
        # Useful Regex's
        # r'"Text[\\]+":[\\]+"(.+?)[\\]+",'
        # r'"HelpText[\\]+":[\\]+"(.+?)[\\]+",'
        # r"this.drawTextEx\(\\'(.+?)\',"
        # r'txtSubject.+?"(.+)"'
        regex = r'txtSubject.+?"(.+)"'
        matchList = re.findall(regex, data[i])
        if len(matchList) > 0:
            for match in matchList:
                # Save Original String
                jaString = match
                originalString = jaString
                newline = None
                colorCode = None

                # Make sure it contains Japanese
                if not re.search(LANGREGEX, jaString):
                    continue

                # Make sure didn't grab \\
                if re.search(r"^[\\]+$", jaString):
                    continue

                # Replace \n and \c
                if re.search(r"\\+n", jaString):
                    newline = re.search(r"\\+n", jaString).group(0)
                    jaString = re.sub(r"\\+n", r"\\n", jaString)
                if re.search(r"\\+C", jaString):
                    colorCode = re.search(r"\\+C", jaString).group(0)
                    jaString = re.sub(r"\\+C", r"\\C", jaString)

                # Remove any textwrap
                jaString = jaString.replace("\\n", " ")

                if jaString.replace("\u3000", "") and jaString:
                    # Pass 1
                    if setData == False and jaString.strip():
                        custom.append(jaString.strip())

                    # Pass 2
                    else:
                        if custom:
                            # Grab and Pop
                            translatedText = custom[0]
                            custom.pop(0)

                            # Set to None if empty list
                            if len(translatedList) <= 0:
                                translatedList = None

                            # Replace Single Quotes
                            translatedText = re.sub(r"([^\\'])'", r"\1՚", translatedText)
                            translatedText = re.sub(r"([^\\'])\"", r"\1՚", translatedText)

                            # Replace \n and \c
                            if newline:
                                # Textwrap
                                # translatedText = dazedwrap.wrapText(translatedText, WIDTH)
                                translatedText = re.sub(r"\n", re.escape(newline), translatedText)
                            if colorCode:
                                translatedText = re.sub(r"\n", re.escape(colorCode), translatedText)

                            # Set Data
                            with open("log/translations.txt", "a+", encoding="utf-8") as tlFile:
                                tlFile.write(f"{originalString} ({translatedText})\n")
                            data[i] = data[i].replace(originalString, translatedText)
                            saveCheckLines(data, filename)

        # Quest Name
        regex = r'[\\]+"QuestName[\\]+":[\\]+"(.*?)[\\]+"'
        matchList = re.findall(regex, data[i])
        if len(matchList) > 0:
            for match in matchList:
                if match:
                    # Save Original String
                    originalString = match

                    # Remove any textwrap
                    match = match.replace(newline, " ")

                    # Pass 1
                    if setData == False:
                        # Add String
                        if match != "\\\\\\\\":
                            questList[0].append(match.strip())

                    # Pass 2
                    else:
                        if questList[0]:
                            # Grab and Pop
                            translatedText = questList[0][0]
                            questList[0].pop(0)

                            # Set to None if empty list
                            if len(translatedList) <= 0:
                                translatedList = None

                            # Replace Single Quotes
                            translatedText = translatedText.replace('"', "'")
                            translatedText = re.sub(r"([^\\'])'", r"\1\\'", translatedText)

                            # Set Data
                            data[i] = data[i].replace(originalString, translatedText)
                            saveCheckLines(data, filename)

        # Quest Client
        regex = r'QuestClientName[\\]+":[\\]+"(.*?)[\\]+"'
        matchList = re.findall(regex, data[i])
        if len(matchList) > 0:
            for match in matchList:
                if match:
                    # Save Original String
                    originalString = match

                    # Pass 1
                    if setData == False:
                        # Add String
                        if match != "\\\\\\\\":
                            questList[1].append(match.strip())

                    # Pass 2
                    else:
                        if questList[1]:
                            # Grab and Pop
                            translatedText = questList[1][0]
                            questList[1].pop(0)

                            # Set to None if empty list
                            if len(translatedList) <= 0:
                                translatedList = None

                            # Replace Single Quotes
                            translatedText = translatedText.replace('"', "'")
                            translatedText = re.sub(r"([^\\'])'", r"\1\\'", translatedText)

                            # Set Data
                            data[i] = data[i].replace(originalString, translatedText)
                            saveCheckLines(data, filename)

        # Quest Location
        regex = r'QuestLocation[\\]+":[\\]+"(.*?)[\\]+"'
        matchList = re.findall(regex, data[i])
        if len(matchList) > 0:
            for match in matchList:
                if match:
                    # Save Original String
                    originalString = match

                    # Pass 1
                    if setData == False:
                        # Add String
                        if match != "\\\\\\\\":
                            questList[2].append(match.strip())

                    # Pass 2
                    else:
                        if questList[2]:
                            # Grab and Pop
                            translatedText = questList[2][0]
                            questList[2].pop(0)

                            # Set to None if empty list
                            if len(translatedList) <= 0:
                                translatedList = None

                            # Replace Single Quotes
                            translatedText = translatedText.replace('"', "'")
                            translatedText = re.sub(r"([^\\'])'", r"\1\\'", translatedText)

                            # Set Data
                            data[i] = data[i].replace(originalString, translatedText)
                            saveCheckLines(data, filename)

        # Quest Target
        regex = r'PlaceInformation[\\]+":[\\]+"(.*?)[\\]+"'
        matchList = re.findall(regex, data[i])
        if len(matchList) > 0:
            for match in matchList:
                if match:
                    # Save Original String
                    originalString = match

                    # Pass 1
                    if setData == False:
                        # Add String
                        if match != "\\\\\\\\":
                            questList[3].append(match.strip())

                    # Pass 2
                    else:
                        if questList[3]:
                            # Grab and Pop
                            translatedText = questList[3][0]
                            questList[3].pop(0)

                            # Set to None if empty list
                            if len(translatedList) <= 0:
                                translatedList = None

                            # Replace Single Quotes
                            translatedText = translatedText.replace('"', "'")
                            translatedText = re.sub(r"([^\\'])'", r"\1\\'", translatedText)

                            # Set Data
                            data[i] = data[i].replace(originalString, translatedText)
                            saveCheckLines(data, filename)

        # Quest Summary
        regex = r'[\\]+"QuestContent[\\]+":[\\]+"[\\]+"(.*?)[\\]+"[\\]+"'
        matchList = re.findall(regex, data[i])
        if len(matchList) > 0:
            for match in matchList:
                if match:
                    # Save Original String
                    originalString = match

                    # Remove any textwrap
                    match = match.replace(r"\\\\\\\\n", " ")
                    match = match.replace(r"\\\\\\\\\\\\\\\\c", "\\c")

                    # Pass 1
                    if setData == False:
                        # Add String
                        if match != "\\\\\\\\":
                            questList[4].append(match.strip())

                    # Pass 2
                    else:
                        if questList[4]:
                            # Grab and Pop
                            translatedText = questList[4][0]
                            questList[4].pop(0)

                            # Set to None if empty list
                            if len(translatedList) <= 0:
                                translatedList = None

                            # Textwrap
                            translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)
                            translatedText = translatedText.replace("\n", r"\\\\\\\\n")
                            match = match.replace("\\c", r"\\\\\\\\\\\\\\\\c")

                            # Replace Single Quotes
                            translatedText = translatedText.replace('"', "'")
                            translatedText = re.sub(r"([^\\'])'", r"\1\\'", translatedText)

                            # Set Data
                            data[i] = data[i].replace(originalString, translatedText)
                            saveCheckLines(data, filename)

        # Quest Goal 1
        regex = r'ObjectiveContent[\\]+":[\\]+"[\\]+"(.*?)[\\]+"'
        matchList = re.findall(regex, data[i])
        if len(matchList) > 0:
            for match in matchList:
                if match:
                    # Save Original String
                    originalString = match

                    # Remove any textwrap
                    match = match.replace(r"\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\n", " ")

                    # Pass 1
                    if setData == False:
                        # Add String
                        if match != "\\\\\\\\":
                            questList[5].append(match.strip())

                    # Pass 2
                    else:
                        if questList[5]:
                            # Grab and Pop
                            translatedText = questList[5][0]
                            questList[5].pop(0)

                            # Set to None if empty list
                            if len(translatedList) <= 0:
                                translatedList = None

                            # Textwrap
                            translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)
                            translatedText = translatedText.replace("\n", r"\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\n")

                            # Replace Single Quotes
                            translatedText = translatedText.replace('"', "'")
                            translatedText = re.sub(r"([^\\'])'", r"\1\\'", translatedText)

                            # Set Data
                            data[i] = data[i].replace(originalString, translatedText)
                            saveCheckLines(data, filename)

        # SceneCustomMenu - Text (Command Labels)
        regex = r'[\\]+"Text[\\]+":[\\]+"(.+?)[\\]+"'
        matchList = re.findall(regex, data[i])
        if len(matchList) > 0:
            for match in matchList:
                if match:
                    jaString = match
                    originalString = jaString

                    # Make sure it contains Japanese
                    if not re.search(LANGREGEX, jaString):
                        continue

                    # Make sure didn't grab only backslashes
                    if re.search(r"^[\\]+$", jaString):
                        continue

                    if jaString.replace("\u3000", "").strip():
                        # Pass 1
                        if setData == False:
                            sceneMenuText.append(jaString.strip())

                        # Pass 2
                        else:
                            if sceneMenuText:
                                # Grab and Pop
                                translatedText = sceneMenuText[0]
                                sceneMenuText.pop(0)

                                # Replace quotes
                                translatedText = translatedText.replace('"', "'")
                                translatedText = re.sub(r"([^\\'])'" , r"\1\\'", translatedText)

                                # Set Data
                                data[i] = data[i].replace(originalString, translatedText)
                                saveCheckLines(data, filename)

        # SceneCustomMenu - CommonHelpText
        regex = r'[\\]+"CommonHelpText[\\]+":[\\]+"(.+?)[\\]+"'
        matchList = re.findall(regex, data[i])
        if len(matchList) > 0:
            for match in matchList:
                if match:
                    jaString = match
                    originalString = jaString

                    # Make sure it contains Japanese
                    if not re.search(LANGREGEX, jaString):
                        continue

                    # Make sure didn't grab only backslashes
                    if re.search(r"^[\\]+$", jaString):
                        continue

                    if jaString.replace("\u3000", "").strip():
                        # Pass 1
                        if setData == False:
                            sceneMenuCommonHelpText.append(jaString.strip())

                        # Pass 2
                        else:
                            if sceneMenuCommonHelpText:
                                # Grab and Pop
                                translatedText = sceneMenuCommonHelpText[0]
                                sceneMenuCommonHelpText.pop(0)

                                # Replace quotes
                                translatedText = translatedText.replace('"', "'")
                                translatedText = re.sub(r"([^\\'])'" , r"\1\\'", translatedText)

                                # Set Data
                                data[i] = data[i].replace(originalString, translatedText)
                                saveCheckLines(data, filename)

        # SceneCustomMenu - HelpText (Command Help)
        regex = r'[\\]+"HelpText[\\]+":[\\]+"(.+?)[\\]+"'
        matchList = re.findall(regex, data[i])
        if len(matchList) > 0:
            for match in matchList:
                if match:
                    jaString = match
                    originalString = jaString

                    # Make sure it contains Japanese
                    if not re.search(LANGREGEX, jaString):
                        continue

                    # Make sure didn't grab only backslashes
                    if re.search(r"^[\\]+$", jaString):
                        continue

                    if jaString.replace("\u3000", "").strip():
                        # Pass 1
                        if setData == False:
                            sceneMenuHelpText.append(jaString.strip())

                        # Pass 2
                        else:
                            if sceneMenuHelpText:
                                # Grab and Pop
                                translatedText = sceneMenuHelpText[0]
                                sceneMenuHelpText.pop(0)

                                # Replace quotes
                                translatedText = translatedText.replace('"', "'")
                                translatedText = re.sub(r"([^\\'])'" , r"\1\\'", translatedText)

                                # Set Data
                                data[i] = data[i].replace(originalString, translatedText)
                                saveCheckLines(data, filename)

        # Next Line
        i += 1

    # EOF
    translate = False
    questListTL = [[], [], [], [], [], []]
    customTL = []

    # Quest
    if len(questList) > 0:
        # Set Progress
        pbar.total = sum(len(quest) for quest in questList)
        pbar.refresh()
        PBAR = pbar

        # Quest Name
        response = translateAI(questList[0], "Quest Name", True)
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        questName = response[0]

        # Quest Client
        response = translateAI(questList[1], "Quest Client", True)
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        questClient = response[0]

        # Quest Location
        response = translateAI(questList[2], "Quest Location", True)
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        questLocation = response[0]

        # Quest Target
        response = translateAI(questList[3], "Quest Location", True)
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        questTarget = response[0]

        # Quest Summary
        response = translateAI(questList[4], "Quest Summary", True)
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        questSummary = response[0]

        # Quest Goal 1
        response = translateAI(questList[5], "Quest Goal", True)
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        questGoal1 = response[0]

        # Check Mismatch
        if (
            len(questName) == len(questList[0])
            or len(questClient) == len(questList[1])
            or len(questLocation) == len(questList[2])
            or len(questTarget) == len(questList[3])
            or len(questSummary) == len(questList[4])
            or len(questGoal1) == len(questList[5])
        ):
            # Set Strings
            questListTL = [questName, questClient, questLocation, questTarget, questSummary, questGoal1]
            translate = True

        # Mismatch
        else:
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)

    # Custom
    if custom:
        # Set Progress
        pbar.total = len(custom)
        pbar.refresh()
        PBAR = pbar

        # TL
        response = translateAI(custom, "Relic Name", True)
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        customResponse = response[0]

        # Check Mismatch
        if len(custom) == len(customResponse):
            customTL = customResponse
            translate = True

        # Mismatch
        else:
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)

    # SceneCustomMenu Text
    sceneMenuTextTL = []
    sceneMenuCommonHelpTextTL = []
    sceneMenuHelpTextTL = []

    if sceneMenuText:
        # Set Progress
        pbar.total = len(sceneMenuText)
        pbar.refresh()
        PBAR = pbar

        # TL
        response = translateAI(sceneMenuText, "Menu Item", True)
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        sceneMenuTextResponse = response[0]

        # Check Mismatch
        if len(sceneMenuText) == len(sceneMenuTextResponse):
            sceneMenuTextTL = sceneMenuTextResponse
            translate = True

        # Mismatch
        else:
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)

    # SceneCustomMenu CommonHelpText
    if sceneMenuCommonHelpText:
        # Set Progress
        pbar.total = len(sceneMenuCommonHelpText)
        pbar.refresh()
        PBAR = pbar

        # TL
        response = translateAI(sceneMenuCommonHelpText, "Menu Help Text", True)
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        sceneMenuCommonHelpTextResponse = response[0]

        # Check Mismatch
        if len(sceneMenuCommonHelpText) == len(sceneMenuCommonHelpTextResponse):
            sceneMenuCommonHelpTextTL = sceneMenuCommonHelpTextResponse
            translate = True

        # Mismatch
        else:
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)

    # SceneCustomMenu HelpText
    if sceneMenuHelpText:
        # Set Progress
        pbar.total = len(sceneMenuHelpText)
        pbar.refresh()
        PBAR = pbar

        # TL
        response = translateAI(sceneMenuHelpText, "Menu Help Text", True)
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        sceneMenuHelpTextResponse = response[0]

        # Check Mismatch
        if len(sceneMenuHelpText) == len(sceneMenuHelpTextResponse):
            sceneMenuHelpTextTL = sceneMenuHelpTextResponse
            translate = True

        # Mismatch
        else:
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)

    # Pass 2
    if translate and not setData:
        translatePlugin(data, pbar, filename, [questListTL, customTL, sceneMenuTextTL, sceneMenuCommonHelpTextTL, sceneMenuHelpTextTL])
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
