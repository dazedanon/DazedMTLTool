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

# tqdm Globals
BAR_FORMAT = "{l_bar}{bar:10}{r_bar}{bar:-10b}"
POSITION = 0
LEAVE = False

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


def handleWOLF2(filename, estimate):
    global ESTIMATE
    ESTIMATE = estimate

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
            with open(
                "translated/" + filename, "w", encoding="shift_jis", errors="ignore"
            ) as outFile:
                start = time.time()
                translatedData = openFiles(filename)

                # Print Result
                end = time.time()
                outFile.writelines(translatedData[0])
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

    if translatedData[2] == None:
        # Success
        return (
            filename + ": " + totalTokenstring + timeString + Fore.GREEN + " \u2713 " + Fore.RESET
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


def openFiles(filename):
    with open("files/" + filename, "r", encoding="shift_jis") as readFile:
        translatedData = parseWOLF(readFile, filename)

        # Delete lines marked for deletion
        finalData = []
        for line in translatedData[0]:
            if line != "\\d\n":
                finalData.append(line)
        translatedData[0] = finalData

    return translatedData


def parseWOLF(readFile, filename):
    totalTokens = [0, 0]

    # Read File into data
    data = readFile.readlines()

    # Create Progress Bar
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE) as pbar:
        pbar.desc = filename

        try:
            result = translateWOLF(data, [], pbar, filename)
            totalTokens[0] += result[0]
            totalTokens[1] += result[1]
        except Exception as e:
            traceback.print_exc()
            return [data, totalTokens, e]
    return [data, totalTokens, None]


def translateWOLF(data, translatedList, pbar, filename):
    stringList = []
    currentGroup = []
    tokens = [0, 0]
    speaker = ""
    global LOCK, ESTIMATE, PBAR
    PBAR = pbar
    i = 0

    while i < len(data):
        # Speaker
        matchList = re.findall(r"(.*)：", data[i])
        if len(matchList) != 0:
            response = getSpeaker(matchList[0])
            speaker = response[0]
            tokens[0] += response[1][0]
            tokens[1] += response[1][1]
            data[i] = f"{speaker}：\n"
            i += 1
        else:
            speaker = ""

        # Options
        if "//選択肢" in data[i]:
            i += 1
            choiceList = []
            initialIndex = i
            while "//" in data[i] and "の場合" not in data[i]:
                choiceList.append(re.search(r"\/\/(.*)", data[i]).group(1))
                i += 1

            # Translate
            response = translateGPT(choiceList, "This will be a dialogue option", True)
            tokens[0] += response[1][0]
            tokens[1] += response[1][1]
            choiceListTL = response[0]

            # Set Data
            if len(choiceList) == len(choiceListTL):
                # Set Data
                i = initialIndex
                while "//" in data[i] and "の場合" not in data[i]:
                    choiceListTL[0] = choiceListTL[0].replace(", ", "、")
                    data[i] = f"//{choiceListTL[0]}\n"
                    choiceListTL.pop(0)
                    i += 1

            # Mismatch
            else:
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)

        # Lines
        if r"/" not in data[i] and "@" not in data[i] and data[i] != "\n":
            # Pass 1
            if translatedList == []:
                # Grab Consecutive Strings
                currentGroup.append(data[i])
                i += 1
                while (
                    i < len(data) and r"/" not in data[i] and "@" not in data[i] and data[i] != "\n"
                ):
                    currentGroup.append(data[i])
                    i += 1

                # Join up 401 groups for better translation.
                if len(currentGroup) > 0:
                    jaString = "".join(currentGroup)
                    currentGroup = []

                # Remove any textwrap
                jaString = jaString.replace("\n", " ")

                # Add Speaker (If there is one)
                if speaker != "":
                    jaString = f"{speaker}: {jaString}"

                # Add String
                stringList.append(jaString)
                i += 1

            # Pass 2
            else:
                # Insert Strings
                while (
                    i < len(data) and r"/" not in data[i] and "@" not in data[i] and data[i] != "\n"
                ):
                    data.pop(i)

                # Get Text
                translatedText = translatedList[0]
                translatedList.pop(0)

                if len(translatedList) <= 0:
                    translatedList = None

                # Remove added speaker
                # translatedText = re.sub(r"^.+?:\s", "", translatedText)

                # Textwrap
                translatedText = textwrap.fill(translatedText, width=WIDTH)

                # Set Data
                data.insert(i, f"{translatedText}\n")
                i += 1

        # Nothing relevant. Skip Line.
        else:
            i += 1

    # EOF
    if len(stringList) > 0:
        # Set Progress
        pbar.total = len(stringList)
        pbar.refresh()

        # Translate
        response = translateGPT(stringList, "", True)
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        translatedList = response[0]

        # Set Strings
        if len(stringList) == len(translatedList):
            translateWOLF(data, translatedList, pbar, filename)

        # Mismatch
        else:
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)
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


def subVars(jaString):
    jaString = jaString.replace("\u3000", " ")

    # Formatting
    count = 0
    codeList = re.findall(r"[\\]+[\w]+\[[a-zA-Z0-9\\\[\]\_,\s-]+\]", jaString)
    codeList = set(codeList)
    if len(codeList) != 0:
        for var in codeList:
            jaString = jaString.replace(var, "[FCode_" + str(count) + "]")
            count += 1

    # Put all lists in list and return
    return [jaString, codeList]


def resubVars(translatedText, codeList):
    # Fix Spacing and ChatGPT Nonsense
    matchList = re.findall(r"\[\s?.+?\s?\]", translatedText)
    if len(matchList) > 0:
        for match in matchList:
            text = match.strip()
            translatedText = translatedText.replace(match, text)

    # Formatting
    count = 0
    if len(codeList) != 0:
        for var in codeList:
            translatedText = translatedText.replace("[FCode_" + str(count) + "]", var)
            count += 1

    return translatedText


def batchList(input_list, batch_size):
    if not isinstance(batch_size, int) or batch_size <= 0:
        raise ValueError("batch_size must be a positive integer")

    return [input_list[i : i + batch_size] for i in range(0, len(input_list), batch_size)]


def createContext(fullPromptFlag, subbedT):
    characters = "Game Characters:\n\
ロラン (Roland) - Male\n\
リュカ (Ryuka) - Male\n\
レックス (Rex) - Male\n\
タバサ (Tabasa) - Female\n\
アルス (Ars) - Male\n\
アマカラ (Amakara) - Male\n\
エリー (Eri) - Female\n\
リオ (Rio) - Female\n\
サマル (Samal) - Male\n\
ムーン (Moon) - Female\n\
アリーナ (Arina) - Female\n\
クリフト (Cliff) - Male\n\
マーニャ (Manya) - Female\n\
ミネア (Minea) - Female\n\
デボラ (Debora) - Female\n\
ビアンカ (Bianca) - Female\n\
フローラ (Flora) - Female\n\
バーバラ (Barbara) - Female\n\
ミレーユ (Mireyu) - Female\n\
アイラ (Aira) - Female\n\
フォズ (Foz) - Female\n\
マリベル (Maribel) - Female\n\
ククール (Kukool) - Male\n\
ゲルダ (Gerda) - Female\n\
ゼシカ (Jessica) - Female\n\
ヤンガス (Yangus) - Male\n\
ラヴィエル (Raviel) - Female\n\
セティア (Setia) - Female\n\
ダイ (Dai) - Male\n\
ヒュンケル (Hyunckel) - Male\n\
ポップ (Pop) - Male\n\
マァム (Maam) - Female\n\
レオナ (Leona) - Female\n\
アステア (Astea) - Female\n\
イヨ (Iyo) - Female\n\
ジャガン (Jagan) - Male\n\
ヤオ (Yao) - Female\n\
デイジィ (Daisy) - Female\n\
バイシュン (Baishun) - Male\n\
ブライ (Buraimu) - Male\n\
ハッサン (Hassan) - Male\n\
アロマ (Aroma) - Female\n\
ピッケ (Pikke) - Female\n\
ドラオ (Dorao) - Male\n\
"

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
    if isinstance(subbedT, list):
        user = f"```json\n{subbedT}```"
    else:
        user = subbedT
    return characters, system, user


def translateText(characters, system, user, history, penalty, format):
    # Prompt
    msg = [{"role": "system", "content": system + characters}]

    # Characters
    msg.append({"role": "system", "content": characters})

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
        model=MODEL,
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
        "Placeholder Text": "",
        # Add more replacements as needed
    }
    for target, replacement in placeholders.items():
        translatedText = translatedText.replace(target, replacement)

    # Elongate Long Dashes (Since GPT Ignores them...)
    translatedText = elongateCharacters(translatedText)
    translatedText = resubVars(translatedText, varResponse[1])
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


def countTokens(characters, system, user, history):
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
    inputTotalTokens += len(enc.encode(characters))
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
    global PBAR

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
            varResponse = subVars(payload)
            subbedT = varResponse[0]
        else:
            varResponse = subVars(tItem)
            subbedT = varResponse[0]

        # Things to Check before starting translation
        if not re.search(r"[一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９]+", subbedT):
            if PBAR is not None:
                PBAR.update(len(tItem))
            continue

        # Create Message
        characters, system, user = createContext(fullPromptFlag, subbedT)

        # Calculate Estimate
        if ESTIMATE:
            estimate = countTokens(characters, system, user, history)
            totalTokens[0] += estimate[0]
            totalTokens[1] += estimate[1]
            continue

        # Translating
        response = translateText(characters, system, user, history, 0.05, format)
        translatedText = response.choices[0].message.content
        totalTokens[0] += response.usage.prompt_tokens
        totalTokens[1] += response.usage.completion_tokens

        # Check Translation
        translatedText = cleanTranslatedText(translatedText, varResponse)
        if isinstance(tItem, list):
            extractedTranslations = extractTranslation(translatedText, True)
            if extractedTranslations == None or len(tItem) != len(extractedTranslations):
                # Mismatch. Try Again
                response = translateText(characters, system, user, history, 0.05, format)
                translatedText = response.choices[0].message.content
                totalTokens[0] += response.usage.prompt_tokens
                totalTokens[1] += response.usage.completion_tokens

                # Formatting
                translatedText = cleanTranslatedText(translatedText, varResponse)
                if isinstance(tItem, list):
                    extractedTranslations = extractTranslation(translatedText, True)
                    if extractedTranslations == None or len(tItem) != len(extractedTranslations):
                        mismatch = True  # Just here for breakpoint

            # Set if no mismatch
            if mismatch == False:
                tList[index] = extractedTranslations
                history = extractedTranslations[-10:]  # Update history if we have a list
            else:
                history = text[-10:]
                mismatch = False

            # Update Loading Bar
            with LOCK:
                if PBAR is not None:
                    PBAR.update(len(tItem))
        else:
            # Ensure we're passing a single string to extractTranslation
            tList[index] = translatedText

    finalList = combineList(tList, text)
    return [finalList, totalTokens]
