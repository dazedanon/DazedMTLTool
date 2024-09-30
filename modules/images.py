# Libraries
from PIL import Image, ImageDraw, ImageFont
import json
import os
import re
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

# Globals
MODEL = os.getenv("model")
TIMEOUT = int(os.getenv("timeout"))
LANGUAGE = os.getenv("language").capitalize()
PROMPT = Path("prompt.txt").read_text(encoding="utf-8")
VOCAB = Path("vocab.txt").read_text(encoding="utf-8")
THREADS = int(os.getenv("threads"))
LOCK = threading.Lock()
PBAR = None
WIDTH = int(os.getenv("width"))
LISTWIDTH = int(os.getenv("listWidth"))
NOTEWIDTH = int(os.getenv("noteWidth"))
MAXHISTORY = 10
ESTIMATE = ""
TOKENS = [0, 0]
NAMESLIST = []
MISMATCH = []  # Lists files that throw a mismatch error (Length of GPT list response is wrong)

# Open AI
load_dotenv()
if os.getenv("api").replace(" ", "") != "":
    openai.base_url = os.getenv("api")
openai.organization = os.getenv("org")
openai.api_key = os.getenv("key")

# Pricing - Depends on the model https://openai.com/pricing
# Batch Size - GPT 3.5 Struggles past 15 lines per request. GPT4 struggles past 50 lines per request
# If you are getting a MISMATCH LENGTH error, lower the batch size.
if "gpt-3.5" in MODEL:
    INPUTAPICOST = 0.002
    OUTPUTAPICOST = 0.002
    BATCHSIZE = 10
    FREQUENCY_PENALTY = 0.2
elif "gpt-4" in MODEL:
    INPUTAPICOST = 0.005
    OUTPUTAPICOST = 0.015
    BATCHSIZE = 20
    FREQUENCY_PENALTY = 0.1

# tqdm Globals
BAR_FORMAT = "{l_bar}{bar:10}{r_bar}{bar:-10b}"
POSITION = 0
LEAVE = False


def handleImages(folderName, estimate):
    global ESTIMATE, TOKENS
    ESTIMATE = estimate
    start = time.time()

    # Translate Strings
    translatedData = openFiles(f"files/{folderName}")

    # Write Strings to Images
    if not ESTIMATE:
        if not os.path.exists(f"translated/{folderName}"):
            os.mkdir(f"translated/{folderName}")
        for i in range(len(translatedData[0][0])):
            try:
                translatedList = translatedData[0][0]
                originalList = translatedData[0][1]
                dimensionsList = translatedData[0][2]
                image = stringToImage(
                    translatedList[i], dimensionsList[i][0], dimensionsList[i][1]
                )
                image.save(
                    rf"translated/{folderName}/{translatedList[i]}.png", quality=100
                )
            except Exception as e:
                PBAR.write(f"{translatedList[i]}: {str(e)}")
                # Ignore Error

    # Print File
    end = time.time()
    tqdm.write(getResultString(translatedData, end - start, folderName))
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


def openFiles(folderName):
    global PBAR

    if os.path.isdir(folderName):
        imageList = [[], []]
        imageList = processImagesDir(folderName, imageList)

        # Start Translation
        with tqdm(
            bar_format=BAR_FORMAT,
            position=POSITION,
            leave=LEAVE,
            desc=folderName,
            total=len(imageList[0]),
        ) as PBAR:
            translatedData = translateImages(imageList)
            translatedData = [
                [translatedData[0], imageList[0], imageList[1]],
                translatedData[1],
                translatedData[2],
            ]

        return translatedData
    else:
        print("The provided directory path does not exist.")


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


def getFontSize(text, image_width, image_height, font_path):
    # Start with a high font size and keep reducing it until the text fits within the image bounds
    font_size = min(image_width, image_height)

    while font_size > 0:
        font = ImageFont.truetype(font_path, font_size)
        text_bbox = ImageDraw.Draw(Image.new("RGB", (1, 1))).textbbox(
            (0, 0), text, font=font
        )
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1] + 5

        if text_width <= image_width and text_height <= image_height:
            return font_size
        font_size -= 1

    return font_size


def stringToImage(
    text, width, height, font_path="fonts/TsunagiGothic.ttf", scale_factor=4
):
    # Increase the resolution
    scaled_width = int(width * scale_factor)
    scaled_height = int(height * scale_factor)

    # Find the appropriate font size for the scaled up image
    font_size = getFontSize(text, scaled_width, scaled_height, font_path)
    if font_size == 0:
        raise ValueError("Text is too long to fit in the supplied dimensions.")

    # Create a new image with the scaled width and height and a transparent background
    image = Image.new("RGBA", (scaled_width, scaled_height), (255, 255, 255, 0))

    # Create a drawing context
    draw = ImageDraw.Draw(image)

    # Load the appropriate font
    font = ImageFont.truetype(font_path, font_size)

    # Calculate the size of the text to center it
    text_bbox = draw.textbbox((0, 0), text, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    x = (scaled_width - text_width) // 2
    y = (scaled_height - text_height) // 2

    # Draw the text on the image
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))

    # Resize back to the original dimensions to get a clearer text rendering
    image = image.resize(
        (width, height),
        Image.LANCZOS,
    )

    return image


def getImageDimensions(file_path):
    try:
        with Image.open(file_path) as img:
            width, height = img.size
            return width, height
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return None, None


def processImagesDir(directory_path, imageList):
    for file_name in os.listdir(directory_path):
        # .png and Japanese
        if ".png" in file_name and file_name.replace(".png", "") in VOCAB:
            file_path = os.path.join(directory_path, file_name)
            if os.path.isfile(file_path):
                # Check if the file is an image
                try:
                    width, height = getImageDimensions(file_path)
                    if width is not None and height is not None:
                        placeholders = {
                            ".png": "",
                        }
                        for target, replacement in placeholders.items():
                            file_name = file_name.replace(target, replacement)
                        imageList[0].append(file_name)
                        imageList[1].append([width, height])
                except Exception as e:
                    print(f"Error processing {file_name}: {e}")

        if ".txt" in file_name:
            try:
                with open(f'{directory_path}/{file_name}', 'r', encoding='utf8') as file:
                    for line in file:
                        line = line.strip()
                        line = line.replace(':', '：')
                        line = line.replace('/', '／')
                        line = line.replace('?', '？')
                        imageList[0].append(line)  # Using strip() to remove any extra newlines or spaces
                        imageList[1].append([100, 15])
            except FileNotFoundError:
                print(f"The file at {file_path} was not found.")
            except IOError:
                print(f"An error occurred while reading the file at {file_path}.")
    return imageList


def translateImages(imageList):
    totalTokens = [0, 0]

    # Translate GPT
    response = translateGPT(
        imageList[0], "Keep the Translation as brief as possible", True
    )
    translatedList = response[0]
    totalTokens[0] += response[1][0]
    totalTokens[1] += response[1][1]

    return [translatedList, totalTokens, None]


# Save some money and enter the character before translation
def getSpeaker(speaker):
    match speaker:
        case "ファイン":
            return ["Fine", [0, 0]]
        case "":
            return ["", [0, 0]]
        case _:
            # Store Speaker
            if speaker not in str(NAMESLIST):
                response = translateGPT(
                    speaker,
                    "Reply with the " + LANGUAGE + " translation of the NPC name.",
                    False,
                )
                response[0] = response[0].title()
                response[0] = response[0].replace("'S", "'s")

                # Retry if name doesn't translate for some reason
                if re.search(r"([a-zA-Z？?])", response[0]) == None:
                    response = translateGPT(
                        speaker,
                        "Reply with the " + LANGUAGE + " translation of the NPC name.",
                        False,
                    )
                    response[0] = response[0].title()
                    response[0] = response[0].replace("'S", "'s")

                speakerList = [speaker, response[0]]
                NAMESLIST.append(speakerList)
                return response
            # Find Speaker
            else:
                for i in range(len(NAMESLIST)):
                    if speaker == NAMESLIST[i][0]:
                        return [NAMESLIST[i][1], [0, 0]]

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

    return [
        input_list[i : i + batch_size] for i in range(0, len(input_list), batch_size)
    ]


def createContext(fullPromptFlag, subbedT, format):
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
    if format == "json":
        user = f"```json\n{subbedT}\n```"
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
        line_dict = json.loads(translatedTextList)
        # If it's a batch (i.e., list), extract with tags; otherwise, return the single item.
        string_list = list(line_dict.values())
        if is_list:
            return string_list
        else:
            return string_list[0]

    except Exception as e:
        print(f"extractTranslation Error: {e}")
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
        characters, system, user = createContext(fullPromptFlag, subbedT, format)

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
            if extractedTranslations == None or len(tItem) != len(
                extractedTranslations
            ):
                # Mismatch. Try Again
                response = translateText(
                    characters, system, user, history, 0.05, format
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

            # Set if no mismatch
            if mismatch == False:
                tList[index] = extractedTranslations
                history = extractedTranslations[
                    -10:
                ]  # Update history if we have a list
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
