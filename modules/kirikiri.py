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
from util.translation import TranslationConfig, translateAI as sharedtranslateAI, getPricingConfig, calculateCost, getPricingConfig, calculateCost
import tempfile

# Globals
MODEL = os.getenv("model")
TIMEOUT = int(os.getenv("timeout"))
LANGUAGE = os.getenv("language").capitalize()
from util.paths import PROMPT_PATH, VOCAB_PATH

PROMPT = PROMPT_PATH.read_text(encoding="utf-8")
VOCAB = VOCAB_PATH.read_text(encoding="utf-8")
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
            start = time.time()
            translatedData = openFiles(filename)
            end = time.time()

            # Final write safeguard: if for some reason the progress file was
            # never written (e.g. no translatable lines triggered saves), write it now.
            try:
                if translatedData[0]:
                    os.makedirs("translated", exist_ok=True)
                    final_path = os.path.join("translated", filename)
                    # Write directly (small risk window acceptable on final flush)
                    with open(final_path, "w", encoding="cp932", errors="ignore", newline="\n") as f:
                        f.writelines(translatedData[0])
            except Exception:
                traceback.print_exc()

            tqdm.write(getResultString(translatedData, end - start, filename))
            with LOCK:
                TOKENS[0] += translatedData[1][0]
                TOKENS[1] += translatedData[1][1]
        except Exception:
            traceback.print_exc()
            # Don't blindly remove the file; it may contain partial progress.
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


def save_progress_lines(lines, filename, encoding="cp932"):
    """Atomically (with retries) save current line-based translation progress.

    Rationale:
    Windows raises PermissionError if the destination file is open elsewhere.
    We avoid holding an open handle outside this function and add a small
    exponential backoff retry loop to handle transient locks (e.g. AV scanners).
    """
    if ESTIMATE:
        return

    max_attempts = 5
    backoff = 0.05  # seconds
    tmp_fd = None
    tmp_path = None

    for attempt in range(1, max_attempts + 1):
        try:
            os.makedirs("translated", exist_ok=True)

            # Create temp file every attempt (prior one cleaned in finally).
            tmp_fd, tmp_path = tempfile.mkstemp(prefix=f"{filename}.", suffix=".tmp", dir="translated")
            with os.fdopen(tmp_fd, "w", encoding=encoding, newline="\n", errors="ignore") as tmp_file:
                tmp_file.writelines(lines)
                tmp_file.flush()
                os.fsync(tmp_file.fileno())

            dest_path = os.path.join("translated", filename)
            try:
                os.replace(tmp_path, dest_path)
            except PermissionError as e:
                # Retry on Windows-specific sharing violation
                if attempt < max_attempts:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                else:
                    raise e
            # Success, break loop
            break
        except Exception:
            if attempt == max_attempts:
                traceback.print_exc()
        finally:
            # Ensure temp file removed if it still exists
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            tmp_fd = None
            tmp_path = None


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
    taggedDialogueRegex = r"^\[(?P<tag>[^\s\]/]+)(?:\s[^\]]*)?\](?P<text>.*?)\[/\1\]"

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
            save_progress_lines(data, filename)
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
                save_progress_lines(data, filename)

        # Tagged dialogue lines e.g., [思考 storage="..."]text[/思考]
        tagged = re.match(taggedDialogueRegex, data[i])
        if tagged and DIALOGUE:
            tag_name = tagged.group('tag')
            jaString = tagged.group('text')

            # Pass 1: enqueue with speaker from closing tag
            if not setData:
                # Remove inline wrapping
                jaString_clean = jaString.replace("[r]", " ")
                # Remove furigana
                matchList = re.findall(furiganaRegex, jaString_clean)
                if matchList:
                    for fm in matchList:
                        jaString_clean = jaString_clean.replace(fm[0], fm[1])

                # Resolve speaker via getSpeaker
                resolved = getSpeaker(tag_name)
                tag_speaker = resolved[0]
                tokens[0] += resolved[1][0]
                tokens[1] += resolved[1][1]

                if tag_speaker:
                    stringList.append(f"[{tag_speaker}]: {jaString_clean.strip()}")
                else:
                    stringList.append(jaString_clean.strip())

            # Pass 2: apply translated text back between tags
            else:
                if len(stringList) > 0:
                    translatedText = stringList[0]
                    stringList.pop(0)
                    # Remove Speaker label if present
                    translatedText = re.sub(r"\[.*?\]:\s", "", translatedText)
                    # Wrap and convert newlines to [r]
                    translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)
                    translatedText = translatedText.replace("\n", "[r]")
                    # Replace quotes as per convention
                    data[i] = data[i].replace("'", '"')
                    translatedText = translatedText.replace('"', "'")
                    # Replace only inner content
                    data[i] = data[i].replace(jaString, translatedText)
                    save_progress_lines(data, filename)

        # Simple narrative line handling: translate each whitespace-led, non-tag, non-command line independently.
        # This avoids reflowing or merging blocks, preventing misplaced text.
        if not re.match(r"^\[", data[i]) and not data[i].lstrip().startswith("@"):
            if re.match(r"^[ \t\u3000]+", data[i]):
                # Skip standalone markers like [▼]
                if data[i].strip() == "[▼]":
                    pass
                else:
                    # Pass 1
                    if not setData:
                        line_content = data[i].rstrip("\n")
                        # Remove inline wrapping markers and glyph markers
                        line_content = line_content.replace("[r]", " ")
                        line_content = re.sub(r"\[▼\]", "", line_content)
                        # Remove furigana blocks
                        matchList = re.findall(furiganaRegex, line_content)
                        if matchList:
                            for fm in matchList:
                                line_content = line_content.replace(fm[0], fm[1])
                        cleaned = line_content.strip()
                        if cleaned:
                            stringList.append(cleaned)
                    # Pass 2
                    else:
                        if len(stringList) > 0:
                            translatedText = stringList[0]
                            stringList.pop(0)
                            translatedText = re.sub(r"\[.*?\]:\s", "", translatedText)
                            translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)
                            translatedText = translatedText.replace("\n", "[r]")
                            indent_match = re.match(r"^([ \t\u3000]+)", data[i])
                            indent = indent_match.group(1) if indent_match else ""
                            data[i] = f"{indent}{translatedText}\n"
                            save_progress_lines(data, filename)

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
                    translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)
                    translatedText = translatedText.replace("\n", "[r]")

                    # Replace Quotes
                    data[i] = data[i].replace("'", '"')
                    translatedText = translatedText.replace('"', "'")
                    data[i] = data[i].replace(jaString, translatedText)
                    save_progress_lines(data, filename)

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
        response = translateAI(
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
        response = translateAI(
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

def translateAI(text, history, history_ctx=None):
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
        config=TRANSLATION_CONFIG,
        filename=FILENAME,
        pbar=PBAR,
        lock=LOCK,
        mismatchList=MISMATCH
    )
