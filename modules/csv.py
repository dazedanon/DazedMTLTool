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
import csv
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
NAMES = False  # Output a list of all the character names found
BRFLAG = False  # If the game uses <br> instead
FIXTEXTWRAP = True  # Overwrites textwrap
IGNORETLTEXT = True  # Ignores all translated text.
MISMATCH = []  # Lists files that thdata a mismatch error (Length of GPT list response is wrong)
BRACKETNAMES = False

# Regex - Need to change this if you want to translate from/to other languages. Default is Japanese Regex
LANGREGEX = r"[一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９\uFF61-\uFF9F]+"

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
ENCODING = "cp932"


def handleCSV(filename, estimate):
    global ESTIMATE, TOKENS
    ESTIMATE = estimate

    if not ESTIMATE:
        with open("translated/" + filename, "w+t", newline="", encoding=ENCODING) as writeFile:
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
    with open("files/" + filename, "r", encoding="cp932") as readFile, writeFile:
        translatedData = parseCSV(readFile, writeFile, filename)

    return translatedData


def openFilesEstimate(filename):
    with open("files/" + filename, "r", encoding="cp932") as readFile:
        translatedData = parseCSV(readFile, "", filename)

    return translatedData


def getResultString(translatedData, translationTime, filename):
    # File Print String
    totalTokenstring = (
        Fore.YELLOW + "[Input: " + str(translatedData[1][0]) + "]"
        "[Output: "
        + str(translatedData[1][1])
        + "]" "[Cost: ${:,.4f}".format((translatedData[1][0] * 0.001 * INPUTAPICOST) + (translatedData[1][1] * 0.001 * OUTPUTAPICOST))
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
        writer = csv.writer(writeFile, delimiter=",")
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
                            translatedText = textwrap.fill(translatedText, WIDTH)
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
                        translatedText = textwrap.fill(translatedText, WIDTH)
                        translatedText = translatedText.replace("\n", "\\n")

                        # Set Data
                        data[i][targetColumn] = translatedText

                    # Iterate
                    i += 1

                # In Place Format
                case "3":
                    # Set columns to translate. Leave empty to translate all.
                    targetColumns = []

                    # False - Place translation in source column
                    # True - Place translation in next column
                    targetNextRow = False

                    for j in range(len(data[i])):
                        if j not in targetColumns:
                            # Check if Translated
                            jaString = data[i][j]

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
                                translatedText = textwrap.fill(translatedText, WIDTH)
                                translatedText = translatedText.replace("\n", "\\n")

                                # Set Data
                                if targetNextRow:
                                    data[i][j + 1] = translatedText
                                else:
                                    data[i][j] = translatedText

                    # Iterate
                    i += 1

                # Speaker & Text Format
                case "4":
                    # Set columns to translate. Leave empty to translate all.
                    speakerColumn = 8
                    textColumn = 20
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

                            # Remove speaker
                            if speaker:
                                translatedText = re.sub(r"^\[?(.+?)\]?\s?[|:]\s?", "", translatedText)

                            # Add Wordwrap
                            translatedText = textwrap.fill(translatedText, WIDTH)
                            translatedText = translatedText.replace("\n", "\\n")

                            # Set Data
                            data[i][textColumn] = translatedText

                    # Iterate
                    i += 1

        # EOF
        if len(stringList) > 0:
            # Set Progress
            pbar.total = len(stringList)
            pbar.refresh()

            # Translate
            response = translateGPT(stringList, "", True)
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

            # If there isn't any Japanese in the text just skip
            if not re.search(LANGREGEX, speaker):
                return [speaker, [0, 0]]

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
        "Placeholder Text": "",
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
    outputTotalTokens += round(len(enc.encode(user)) * 3)

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
                    for j in range(len(tItem)):
                       tItem[j] = cleanTranslatedText(tItem[j])
                       tList[index] = tItem
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
                translatedText = response.choices[0].message.content
                totalTokens[0] += response.usage.prompt_tokens
                totalTokens[1] += response.usage.completion_tokens

                # Check Translation
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
