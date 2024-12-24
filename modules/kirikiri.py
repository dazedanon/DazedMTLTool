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

# Pricing - Depends on the model https://openai.com/pricing
# Batch Size - GPT 3.5 Struggles past 15 lines per request. GPT4 struggles past 50 lines per request
# If you are getting a MISMATCH LENGTH error, lower the batch size.
if "gpt-3.5" in MODEL:
    INPUTAPICOST = 0.002
    OUTPUTAPICOST = 0.002
    BATCHSIZE = 10
elif "gpt-4" in MODEL:
    INPUTAPICOST = 0.0025
    OUTPUTAPICOST = 0.01
    BATCHSIZE = 40
else:
    INPUTAPICOST = float(os.getenv("input_cost"))
    OUTPUTAPICOST = float(os.getenv("output_cost"))
    BATCHSIZE = int(os.getenv("batchsize"))
    FREQUENCY_PENALTY = float(os.getenv("frequency_penalty"))

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
        + "]" "[Cost: ${:,.4f}".format((translatedData[1][0] * 0.001 * INPUTAPICOST) + (translatedData[1][1] * 0.001 * OUTPUTAPICOST))
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
                    translatedText = textwrap.fill(translatedText, width=WIDTH)
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
        response = translateGPT(
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
        response = translateGPT(
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
        "—": "―",
        "】": "]",
        "【": "[",
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

            # Things to Check before starting translation
            if not re.search(r"[一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９\uFF61-\uFF9F]+", subbedT):
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
                if extractedTranslations == None or len(tItem) != len(extractedTranslations):
                    # Mismatch. Try Again
                    response = translateText(system, user, history, 0.05, format, "gpt-4o")
                    translatedText = response.choices[0].message.content
                    totalTokens[0] += response.usage.prompt_tokens
                    totalTokens[1] += response.usage.completion_tokens

                    # Formatting
                    translatedText = cleanTranslatedText(translatedText, varResponse)
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
