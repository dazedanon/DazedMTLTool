import os
import re
import textwrap
import threading
import time
import traceback
from pathlib import Path

import openai
import tiktoken
from colorama import Fore
from dotenv import load_dotenv
from retry import retry
from tqdm import tqdm

# Open AI
load_dotenv()
if os.getenv("api").replace(" ", "") != "":
    openai.api_base = os.getenv("api")
openai.organization = os.getenv("org")
openai.api_key = os.getenv("key")

# Globals
MODEL = os.getenv("model")
TIMEOUT = int(os.getenv("timeout"))
LANGUAGE = os.getenv("language").capitalize()
INPUTAPICOST = 0.002  # Depends on the model https://openai.com/pricing
OUTPUTAPICOST = 0.002
PROMPT = Path("prompt.txt").read_text(encoding="utf-8")
THREADS = int(
    os.getenv("threads")
)  # Controls how many threads are working on a single file (May have to drop this)
LOCK = threading.Lock()
WIDTH = int(os.getenv("width"))
LISTWIDTH = int(os.getenv("listWidth"))
NOTEWIDTH = 40
MAXHISTORY = 10
ESTIMATE = ""
totalTokens = [0, 0]
NAMESLIST = []

# tqdm Globals
BAR_FORMAT = "{l_bar}{bar:10}{r_bar}{bar:-10b}"
POSITION = 0
LEAVE = False

# Flags
NAMES = False  # Output a list of all the character names found
BRFLAG = False  # If the game uses <br> instead
FIXTEXTWRAP = True
IGNORETLTEXT = False


def handleSakuranbo(filename, estimate):
    global ESTIMATE
    totalTokens = [0, 0]
    ESTIMATE = estimate

    if estimate:
        start = time.time()
        translatedData = openFiles(filename)

        # Print Result
        end = time.time()
        tqdm.write(getResultString(translatedData, end - start, filename))
        if NAMES is True:
            tqdm.write(str(NAMESLIST))
        with LOCK:
            totalTokens[0] += translatedData[1][0]
            totalTokens[1] += translatedData[1][1]

        return getResultString(["", totalTokens, None], end - start, "TOTAL")

    else:
        try:
            with open("translated/" + filename, "w", encoding="utf-16") as outFile:
                start = time.time()
                translatedData = openFiles(filename)
                outFile.writelines(translatedData[0])

                # Print Result
                end = time.time()
                tqdm.write(getResultString(translatedData, end - start, filename))
                with LOCK:
                    totalTokens[0] += translatedData[1][0]
                    totalTokens[1] += translatedData[1][1]
        except Exception:
            traceback.print_exc()
            return "Fail"

    return getResultString(["", totalTokens, None], end - start, "TOTAL")


def getResultString(translatedData, translationTime, filename):
    # File Print String
    totalTokenstring = (
        Fore.YELLOW + "[Input: " + str(translatedData[1][0]) + "]"
        "[Output: " + str(translatedData[1][1]) + "]"
        "[Cost: ${:,.4f}".format(
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


def openFiles(filename):
    with open("files/" + filename, "r", encoding="utf-16") as readFile:
        translatedData = parseTyrano(readFile, filename)

        # Delete lines marked for deletion
        finalData = []
        for line in translatedData[0]:
            if line != "\\d\n":
                finalData.append(line)
        translatedData[0] = finalData

    return translatedData


def parseTyrano(readFile, filename):
    totalTokens = [0, 0]
    totalLines = 0

    # Get total for progress bar
    data = readFile.readlines()
    totalLines = len(data)

    with tqdm(
        bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE
    ) as pbar:
        pbar.desc = filename
        pbar.total = totalLines

        try:
            response = translateTyrano(data, pbar)
            totalTokens[0] = response[0]
            totalTokens[1] = response[1]
        except Exception as e:
            traceback.print_exc()
            return [data, totalTokens, e]
    return [data, totalTokens, None]


def translateTyrano(data, pbar):
    textHistory = []
    maxHistory = MAXHISTORY
    tokens = [0, 0]
    currentGroup = []
    syncIndex = 0
    speaker = ""
    delFlag = False
    global LOCK, ESTIMATE

    for i in range(len(data)):
        currentGroup = []
        matchList = []

        if syncIndex > i:
            i = syncIndex

        if '[▼]' in data[i]:
            data[i] = data[i].replace('[▼]'.strip(), '[page]\n')

        # If there isn't any Japanese in the text just skip
        if IGNORETLTEXT is True:
            if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', data[i]):
                # Keep textHistory list at length maxHistory
                textHistory.append('\"' + data[i] + '\"')
                if len(textHistory) > maxHistory:
                    textHistory.pop(0)
                currentGroup = []  
                continue

        # Speaker
        matchList = re.findall(r"^\[(.+)\sstorage=.+\]", data[i])
        if len(matchList) == 0:
            matchList = re.findall(r"^\[([^/].+)\]$", data[i])
        if len(matchList) > 0:
            if "主人公" in matchList[0]:
                speaker = "Protagonist"
            elif "思考" in matchList[0]:
                speaker = "Protagonist Inner Thoughts"
            elif "地の文" in matchList[0]:
                speaker = "Narrator"
            elif "マコ" in matchList[0]:
                speaker = "Mako"
            elif '少年' in matchList[0]:
                speaker = "Boy"
            elif '友達' in matchList[0]:
                speaker = "Friend"
            elif '少女' in matchList[0]:
                speaker = "Girl"
            else:
                response = translateGPT(
                    matchList[0],
                    "Reply with only the "
                    + LANGUAGE
                    + " translation of the NPC name",
                    True,
                )
                speaker = response[0]
                tokens[0] += response[1][0]
                tokens[1] += response[1][1]
                # data[i] = '#' + speaker + '\n'

        # Choices
        elif "glink" in data[i]:
            matchList = re.findall(r"\[glink.+text=\"(.+?)\".+", data[i])
            if len(matchList) != 0:
                if len(textHistory) > 0:
                    response = translateGPT(
                        matchList[0],
                        "Past Translated Text: "
                        + textHistory[len(textHistory) - 1]
                        + "\n\nReply in the style of a dialogue option.",
                        True,
                    )
                else:
                    response = translateGPT(matchList[0], "", False)
                translatedText = response[0]
                tokens[0] += response[1][0]
                tokens[1] += response[1][1]

                # Remove characters that may break scripts
                charList = [".", '"', "\\n"]
                for char in charList:
                    translatedText = translatedText.replace(char, "")

                # Escape all '
                translatedText = translatedText.replace("\\", "")
                translatedText = translatedText.replace("'", "\\'")

                # Set Data
                translatedText = data[i].replace(
                    matchList[0], translatedText.replace(" ", "\u00A0")
                )
                data[i] = translatedText

        # Grab Lines
        matchList = re.findall(r"^([^\n;@*\{\[].+[^;'{}\[]$)", data[i])
        if len(matchList) > 0 and (re.search(r'^\[(.+)\sstorage=.+\],', data[i-1]) or re.search(r'^\[(.+)\]$', data[i-1]) or re.search(r'^《(.+)》', data[i-1])):
            currentGroup.append(matchList[0])
            if len(data) > i + 1:
                matchList = re.findall(r"^([^\n;@*\{\[].+[^;'{}\[]$)", data[i + 1])
                while len(matchList) > 0:
                    delFlag = True
                    data[i] = "\d\n"  # \d Marks line for deletion
                    i += 1
                    matchList = re.findall(r"^([^\n;@*\{\[].+[^;'{}\[]$)", data[i])
                    if len(matchList) > 0:
                        currentGroup.append(matchList[0])

            # Join up 401 groups for better translation.
            if len(currentGroup) > 0:
                finalJAString = " ".join(currentGroup)

            # Remove any textwrap
            if FIXTEXTWRAP is True:
                finalJAString = finalJAString.replace("_", " ")

            # Check Speaker
            if speaker == "":
                response = translateGPT(finalJAString, textHistory, True)
                tokens[0] += response[1][0]
                tokens[1] += response[1][1]
                translatedText = response[0]
                textHistory.append('"' + translatedText + '"')
            else:
                response = translateGPT(
                    speaker + ": " + finalJAString, textHistory, True
                )
                tokens[0] += response[1][0]
                tokens[1] += response[1][1]
                translatedText = response[0]
                textHistory.append('"' + translatedText + '"')

            # Remove added speaker
            translatedText = re.sub(r"^.+:\s?", "", translatedText)

            # Set Data
            translatedText = translatedText.replace("ッ", "")
            translatedText = translatedText.replace("っ", "")
            translatedText = translatedText.replace("ー", "")
            translatedText = translatedText.replace('"', "")
            translatedText = translatedText.replace("[", "")
            translatedText = translatedText.replace("]", "")

            # Wordwrap Text
            if "_" not in translatedText:
                translatedText = textwrap.fill(translatedText, width=WIDTH)
                translatedText = translatedText.replace("\n", "_")

            # Set
            if delFlag is True:
                data.insert(i, translatedText.strip() + '\n')
                delFlag = False
            else:
                data[i] = translatedText.strip() + '\n'

            # Keep textHistory list at length maxHistory
            if len(textHistory) > maxHistory:
                textHistory.pop(0)
            currentGroup = []
            speaker = ""

        pbar.update(1)
        if len(data) > i + 1:
            syncIndex = i + 1
        else:
            break

        # Grab Lines
        matchList = re.findall(r"(^\[.+\sstorage=.+\](.+)\[/.+\])", data[i])
        if len(matchList) > 0:
            originalLine = matchList[0][0]
            originalText = matchList[0][1]
            currentGroup.append(matchList[0][1])
            if len(data) > i + 1:
                matchList = re.findall(r"^([^\n;@*\{\[].+[^;'{}\[]$)", data[i + 1])
                while len(matchList) > 0:
                    delFlag = True
                    data[i] = "\d\n"  # \d Marks line for deletion
                    i += 1
                    matchList = re.findall(r"^([^\n;@*\{\[].+[^;'{}\[]$)", data[i])
                    if len(matchList) > 0:
                        currentGroup.append(matchList[0])

            # Join up 401 groups for better translation.
            if len(currentGroup) > 0:
                finalJAString = " ".join(currentGroup)

            # Remove any textwrap
            if FIXTEXTWRAP is True:
                finalJAString = finalJAString.replace("_", " ")

            # Check Speaker
            if speaker == "":
                response = translateGPT(finalJAString, textHistory, True)
                tokens[0] += response[1][0]
                tokens[1] += response[1][1]
                translatedText = response[0]
                textHistory.append('"' + translatedText + '"')
            else:
                response = translateGPT(
                    speaker + ": " + finalJAString, textHistory, True
                )
                tokens[0] += response[1][0]
                tokens[1] += response[1][1]
                translatedText = response[0]
                textHistory.append('"' + translatedText + '"')

            # Remove added speaker
            translatedText = re.sub(r"^.+:\s?", "", translatedText)

            # Set Data
            translatedText = translatedText.replace("ッ", "")
            translatedText = translatedText.replace("っ", "")
            translatedText = translatedText.replace("ー", "")
            translatedText = translatedText.replace('"', "")
            translatedText = translatedText.replace("[", "")
            translatedText = translatedText.replace("]", "")

            # Wordwrap Text
            if "_" not in translatedText:
                translatedText = textwrap.fill(translatedText, width=WIDTH)
                translatedText = translatedText.replace("\n", "_")
                translatedText = originalLine.replace(originalText, translatedText)

            # Set
            if delFlag is True:
                data.insert(i, translatedText.strip() + '\n')
                delFlag = False
            else:
                data[i] = translatedText.strip() + '\n'

            # Keep textHistory list at length maxHistory
            if len(textHistory) > maxHistory:
                textHistory.pop(0)
            currentGroup = []
            speaker = ""

        pbar.update(1)
        if len(data) > i + 1:
            syncIndex = i + 1
        else:
            break

    return tokens

def subVars(jaString):
    jaString = jaString.replace("\u3000", " ")

    # Nested
    count = 0
    nestedList = re.findall(r"[\\]+[\w]+\[[\\]+[\w]+\[[0-9]+\]\]", jaString)
    nestedList = set(nestedList)
    if len(nestedList) != 0:
        for icon in nestedList:
            jaString = jaString.replace(icon, "{Nested_" + str(count) + "}")
            count += 1

    # Icons
    count = 0
    iconList = re.findall(r"[\\]+[iIkKwWaA]+\[[0-9]+\]", jaString)
    iconList = set(iconList)
    if len(iconList) != 0:
        for icon in iconList:
            jaString = jaString.replace(icon, "{Ascii_" + str(count) + "}")
            count += 1

    # Colors
    count = 0
    colorList = re.findall(r"[\\]+[cC]\[[0-9]+\]", jaString)
    colorList = set(colorList)
    if len(colorList) != 0:
        for color in colorList:
            jaString = jaString.replace(color, "{Color_" + str(count) + "}")
            count += 1

    # Names
    count = 0
    nameList = re.findall(r"[\\]+[nN]\[.+?\]+", jaString)
    nameList = set(nameList)
    if len(nameList) != 0:
        for name in nameList:
            jaString = jaString.replace(name, "{N_" + str(count) + "}")
            count += 1

    # Variables
    count = 0
    varList = re.findall(r"[\\]+[vV]\[[0-9]+\]", jaString)
    varList = set(varList)
    if len(varList) != 0:
        for var in varList:
            jaString = jaString.replace(var, "{Var_" + str(count) + "}")
            count += 1

    # Formatting
    count = 0
    if "笑えるよね." in jaString:
        print("t")
    formatList = re.findall(r"[\\]+[\w]+\[.+?\]", jaString)
    formatList = set(formatList)
    if len(formatList) != 0:
        for var in formatList:
            jaString = jaString.replace(var, "{FCode_" + str(count) + "}")
            count += 1

    # Put all lists in list and return
    allList = [nestedList, iconList, colorList, nameList, varList, formatList]
    return [jaString, allList]


def resubVars(translatedText, allList):
    # Fix Spacing and ChatGPT Nonsense
    matchList = re.findall(r"\[\s?.+?\s?\]", translatedText)
    if len(matchList) > 0:
        for match in matchList:
            text = match.strip()
            translatedText = translatedText.replace(match, text)

    # Nested
    count = 0
    if len(allList[0]) != 0:
        for var in allList[0]:
            translatedText = translatedText.replace("{Nested_" + str(count) + "}", var)
            count += 1

    # Icons
    count = 0
    if len(allList[1]) != 0:
        for var in allList[1]:
            translatedText = translatedText.replace("{Ascii_" + str(count) + "}", var)
            count += 1

    # Colors
    count = 0
    if len(allList[2]) != 0:
        for var in allList[2]:
            translatedText = translatedText.replace("{Color_" + str(count) + "}", var)
            count += 1

    # Names
    count = 0
    if len(allList[3]) != 0:
        for var in allList[3]:
            translatedText = translatedText.replace("{N_" + str(count) + "}", var)
            count += 1

    # Vars
    count = 0
    if len(allList[4]) != 0:
        for var in allList[4]:
            translatedText = translatedText.replace("{Var_" + str(count) + "}", var)
            count += 1

    # Formatting
    count = 0
    if len(allList[5]) != 0:
        for var in allList[5]:
            translatedText = translatedText.replace("{FCode_" + str(count) + "}", var)
            count += 1

    # Remove Color Variables Spaces
    # if '\\c' in translatedText:
    #     translatedText = re.sub(r'\s*(\\+c\[[1-9]+\])\s*', r' \1', translatedText)
    #     translatedText = re.sub(r'\s*(\\+c\[0+\])', r'\1', translatedText)
    return translatedText


@retry(exceptions=Exception, tries=5, delay=5)
def translateGPT(t, history, fullPromptFlag):
    # Sub Vars
    varResponse = subVars(t)
    subbedT = varResponse[0]

    # If there isn't any Japanese in the text just skip
    if not re.search(r"[一-龠]+|[ぁ-ゔ]+|[ァ-ヴ]+|[\uFF00-\uFFEF]", subbedT):
        return (t, [0, 0])

    # If ESTIMATE is True just count this as an execution and return.
    if ESTIMATE:
        enc = tiktoken.encoding_for_model(MODEL)
        historyRaw = ""
        if isinstance(history, list):
            for line in history:
                historyRaw += line
        else:
            historyRaw = history

        inputTotalTokens = len(enc.encode(historyRaw)) + len(enc.encode(PROMPT))
        outputTotalTokens = (
            len(enc.encode(t)) * 2
        )  # Estimating 2x the size of the original text
        totalTokens = [inputTotalTokens, outputTotalTokens]
        return (t, totalTokens)

    # Characters
    context = "Game Characters:\
        Character: マコ == Mako - Gender: Female\
        Character: 主人公 == Protagonist - Gender: Male"

    # Prompt
    if fullPromptFlag:
        system = PROMPT
        user = "Line to Translate = " + subbedT
    else:
        system = (
            "Output ONLY the "
            + LANGUAGE
            + " translation in the following format: `Translation: <"
            + LANGUAGE.upper()
            + "_TRANSLATION>`"
        )
        user = "Line to Translate = " + subbedT

    # Create Message List
    msg = []
    msg.append({"role": "system", "content": system})
    msg.append({"role": "user", "content": context})
    if isinstance(history, list):
        for line in history:
            msg.append({"role": "user", "content": line})
    else:
        msg.append({"role": "user", "content": history})
    msg.append({"role": "user", "content": user})

    response = openai.ChatCompletion.create(
        temperature=0,
        frequency_penalty=0.2,
        presence_penalty=0.2,
        model=MODEL,
        messages=msg,
        request_timeout=TIMEOUT,
    )

    # Save Translated Text
    translatedText = response.choices[0].message.content
    totalTokens = [response.usage.prompt_tokens, response.usage.completion_tokens]

    # Resub Vars
    translatedText = resubVars(translatedText, varResponse[1])

    # Remove Placeholder Text
    translatedText = translatedText.replace(LANGUAGE + " Translation: ", "")
    translatedText = translatedText.replace("Translation: ", "")
    translatedText = translatedText.replace("Line to Translate = ", "")
    translatedText = translatedText.replace("Translation = ", "")
    translatedText = translatedText.replace("Translate = ", "")
    translatedText = translatedText.replace(LANGUAGE + " Translation:", "")
    translatedText = translatedText.replace("Translation:", "")
    translatedText = translatedText.replace("Line to Translate =", "")
    translatedText = translatedText.replace("Translation =", "")
    translatedText = translatedText.replace("Translate =", "")
    translatedText = translatedText.replace("っ", "")
    translatedText = translatedText.replace("ッ", "")
    translatedText = translatedText.replace("ぁ", "")
    translatedText = translatedText.replace("。", ".")
    translatedText = translatedText.replace("、", ",")
    translatedText = translatedText.replace("？", "?")
    translatedText = translatedText.replace("！", "!")

    # Return Translation
    if (
        len(translatedText) > 15 * len(t)
        or "I'm sorry, but I'm unable to assist with that translation" in translatedText
    ):
        raise Exception
    else:
        return [translatedText, totalTokens]
