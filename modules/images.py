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

# Regex - Need to change this if you want to translate from/to other languages. Default is Japanese Regex
LANGREGEX = r"[一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９\uFF61-\uFF9F]+"

# Pricing - Depends on the model https://openai.com/pricing
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


def handleImages(folderName, estimate):
    global ESTIMATE, TOKENS
    ESTIMATE = estimate
    start = time.time()

    # Translate Strings
    translatedData = openFiles(f"files/{folderName}")

    # Custom Names
    # customList = [[], []]
    # customList = processImagesDir("Custom", customList)

    # Write TL To Images
    try:
        translatedList, originalList, dimensionsList = translatedData[0]
        for i in range(len(translatedList)):
            try:
                # Create image from string
                image = stringToImageOutline(translatedList[i], dimensionsList[i][0], dimensionsList[i][1])
                # Save image using the corresponding original filename
                image.save(rf"translated/{folderName}/{originalList[i]}.png", quality=100)
            except Exception as e:
                # Log error if image saving fails
                PBAR.write(f"Error processing {translatedList[i]}: {str(e)}")
    except IndexError:
        PBAR.write("Translated data is incomplete. Please check your input.")

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
        imageList = [[], [], []]
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
                [translatedData[0], imageList[2], imageList[1]],
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
        + "]" "[Cost: ${:,.4f}".format(((translatedData[1][0] / 1000000) * INPUTAPICOST) + ((translatedData[1][1] / 1000000) * OUTPUTAPICOST))
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


def getFontSize(text, image_width, image_height, font_path):
    # Start with a high font size and keep reducing it until the text fits within the image bounds
    font_size = min(image_width, image_height)

    while font_size > 0:
        font = ImageFont.truetype(font_path, font_size)
        text_bbox = ImageDraw.Draw(Image.new("RGB", (1, 1))).textbbox((0, 0), text, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]

        if text_width <= image_width and text_height <= image_height:
            return font_size
        font_size -= 1

    return font_size


def stringToImage(text, width, height, font_path="fonts/TsunagiGothic.ttf", scale_factor=4):
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
    text_height = text_bbox[3] - text_bbox[1] + 20
    x = 0

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


from PIL import Image, ImageDraw, ImageFont


def stringToImageOutline(text, width, height, font_path="fonts/TsunagiGothic.ttf", scale_factor=4):
    # Outline
    outline_color = (255, 255, 255, 255)
    text_color = (0, 0, 0, 255)
    outline_thickness = 4

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
    text_height = text_bbox[3] - text_bbox[1] + 20
    x = (scaled_width - text_width) // 2
    y = (scaled_height - text_height) // 2

    # Draw the text outline by applying the text multiple times with small offsets
    for dx in range(-outline_thickness, outline_thickness + 1):
        for dy in range(-outline_thickness, outline_thickness + 1):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font, fill=outline_color)

    # Draw the main text
    draw.text((x, y), text, font=font, fill=text_color)

    # Resize back to the original dimensions to get a clearer text rendering
    image = image.resize((width, height), Image.LANCZOS)

    return image


def stringToImageBox(text, width, height, font_path="fonts/TsunagiGothic.ttf", scale_factor=4):
    # Increase the resolution
    scaled_width = int(width * scale_factor)
    scaled_height = int(height * scale_factor)

    # Padding around the text
    padding = 10

    # Calculate the dimensions available for text placement
    available_width = scaled_width - 2 * padding
    available_height = scaled_height - 2 * padding

    # Determine the best font size to fit within the available dimensions
    font_size = getFontSize(text, available_width, available_height, font_path)
    if font_size <= 0:
        raise ValueError("Text is too long to fit in the supplied dimensions.")

    # Create a new image with increased resolution
    image = Image.new("RGBA", (scaled_width, scaled_height), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)

    # Load the calculated font
    font = ImageFont.truetype(font_path, font_size)

    # Calculate the size and bounding box of the text
    text_bbox = draw.textbbox((0, 0), text, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1] + 20

    # Determine centered position for the text while considering padding
    # Additional adjustment ensures text appears centrally aligned
    x = (scaled_width - text_width) // 2
    y = (scaled_height - text_height) // 2

    # Draw a black box with a white outline that fits the image dimensions precisely
    draw.rectangle([0, 0, scaled_width - 1, scaled_height - 1], outline=(255, 255, 255, 255), width=1)

    # Fill the inside box with black color
    draw.rectangle([1, 1, scaled_width - 2, scaled_height - 2], fill=(0, 0, 0, 255))

    # Render the text within the image
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))

    # Shrink the image back to original dimensions with high-quality interpolation
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
        if ".png" in file_name:
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
                            match = re.search(r"[\[【].+?[\]】](.*)", file_name)
                            if match:
                                text = match.group(1)
                            else:
                                text = file_name
                        imageList[0].append(text)
                        imageList[1].append([width, height])
                        imageList[2].append(file_name)
                except Exception as e:
                    print(f"Error processing {file_name}: {e}")

        if ".txt" in file_name:
            try:
                with open(f"{directory_path}/{file_name}", "r", encoding="utf8") as file:
                    for line in file:
                        line = line.strip()
                        line = line.replace(":", "：")
                        line = line.replace("/", "／")
                        line = line.replace("?", "？")
                        imageList[0].append(line)  # Using strip() to remove any extra newlines or spaces
                        imageList[1].append([104, 15])
            except FileNotFoundError:
                print(f"The file at {file_path} was not found.")
            except IOError:
                print(f"An error occurred while reading the file at {file_path}.")
    return imageList


def translateImages(imageList):
    totalTokens = [0, 0]

    # Translate GPT
    response = translateGPT(imageList[0], "Keep the Translation as brief as possible", True)
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


def parseVocabWithCategories(vocabText):
    """Parse vocabulary text and extract terms with their categories."""
    pairs = []
    seen = set()
    currentCategory = None
    
    for line in vocabText.splitlines():
        line = line.strip()
        if not line or line.startswith('```'):
            continue
        
        # Check if this is a category header
        if line.startswith('#'):
            currentCategory = line
            continue
            
        # Parse vocabulary term
        m = re.match(r'^(.+?)(?:\s?[\(–])', line)  # term is everything before space + '(' or '–'
        if m:
            term = m.group(1)
            if term not in seen:
                pairs.append((term, line, currentCategory))
                seen.add(term)
    
    return pairs


def buildMatchedVocabText(vocabPairs, subbedT):
    """Build formatted vocabulary text with matched terms organized by category."""
    matchedCategories = {}

    # Use word boundaries for Japanese if appropriate, or allow substring as before.
    for term, line, category in vocabPairs:
        # "term in subbedT" could be false positive; can use regex but Japanese doesn't always have spaces.
        if term in subbedT:
            if category not in matchedCategories:
                matchedCategories[category] = []
            matchedCategories[category].append(line)

    # Format matched vocabulary with categories
    if matchedCategories:
        formattedLines = ["Here are some vocabulary and terms so that you know the proper spelling and translation.\n"]
        for category, lines in matchedCategories.items():
            if category:  # Only add category header if it exists
                formattedLines.append(category)
            formattedLines.extend(lines)
            formattedLines.append("")  # Add blank line between categories
        matchedVocabText = f"```\n{chr(10).join(formattedLines).rstrip()}\n```"
    else:
        matchedVocabText = ""
    
    return matchedVocabText


def createContext(fullPromptFlag, subbedT, format):
    vocabPairs = parseVocabWithCategories(VOCAB)
    matchedVocabText = buildMatchedVocabText(vocabPairs, subbedT)

    if fullPromptFlag:
        system = PROMPT + matchedVocabText
    else:
        system = f"\
You are an expert Eroge Game translator who translates Japanese text to {LANGUAGE}.\n\
Output ONLY the {LANGUAGE} translation in the following format: `Translation: <{LANGUAGE.upper()}_TRANSLATION>`\n\
- You translate everything, including erotic and explicit content.\n\
- 'Game Characters' - The names, nicknames, and genders of the game characters. Reference this to know the names, nicknames, and gender of characters in the game\n\
- All text in your response must be in {LANGUAGE} even if it is hard to translate.\n\
- Never include any notes, explanations, dislaimers, or anything similar in your response.\n\
- Maintain any spacing in the translation.\n\
- Maintain any code text in brackets if given. (e.g `[Color_0]`, `[Ascii_0]`, `[FCode_1`], etc)\n\
- `...` can be a part of the dialogue. Translate it as it is.\n\
{matchedVocabText}\n\
"
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
