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
from util.translation import TranslationConfig, translateAI as sharedtranslateAI, getPricingConfig, calculateCost

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
FILENAME = None

# Open AI
load_dotenv()
if os.getenv("api").replace(" ", "") != "":
    openai.base_url = os.getenv("api")
openai.organization = os.getenv("org")
openai.api_key = os.getenv("key")

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

# tqdm Globals
BAR_FORMAT = "{l_bar}{bar:10}{r_bar}{bar:-10b}"
POSITION = 0
LEAVE = False


def handleImages(folderName, estimate):
    global ESTIMATE, TOKENS, FILENAME
    ESTIMATE = estimate
    FILENAME = folderName
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
    response = translateAI(imageList[0], "Keep the Translation as brief as possible", True)
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
