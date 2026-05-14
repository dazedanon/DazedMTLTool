import json
import os
import re
import tempfile
import threading
import time
import traceback
from pathlib import Path

from colorama import Fore
from tqdm import tqdm

import util.dazedwrap as dazedwrap
from util.translation import (
    TranslationConfig,
    calculateCost,
    getPricingConfig,
    translateAI as sharedtranslateAI,
)


MODEL = os.getenv("model")
LANGUAGE = os.getenv("language").capitalize()
PROMPT = Path("prompt.txt").read_text(encoding="utf-8")
VOCAB = Path("vocab.txt").read_text(encoding="utf-8")
LOCK = threading.Lock()
WIDTH = int(os.getenv("width"))
MAXHISTORY = 10
ESTIMATE = ""
TOKENS = [0, 0]
NAMESLIST = []
MISMATCH = []
FILENAME = None
PBAR = None

BAR_FORMAT = "{l_bar}{bar:10}{r_bar}{bar:-10b}"
POSITION = 0
LEAVE = False

LANGREGEX = r"[一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９\uFF61-\uFF9F]+"
PRICING_CONFIG = getPricingConfig(MODEL)
BATCHSIZE = PRICING_CONFIG["batchSize"]

TRANSLATION_CONFIG = TranslationConfig(
    model=MODEL,
    language=LANGUAGE,
    prompt=PROMPT,
    vocab=VOCAB,
    langRegex=LANGREGEX,
    batchSize=BATCHSIZE,
    maxHistory=MAXHISTORY,
    estimateMode=False,
)


def handleYuris(filename, estimate):
    global ESTIMATE, FILENAME, TOKENS
    ESTIMATE = estimate
    FILENAME = filename

    try:
        start = time.time()
        translatedData = openFiles(filename)

        if not estimate:
            os.makedirs(os.path.dirname(os.path.join("translated", filename)) or "translated", exist_ok=True)
            with open("translated/" + filename, "w", encoding="utf-8", newline="\n") as outFile:
                json.dump(translatedData[0], outFile, ensure_ascii=False, indent=4)

        end = time.time()
        tqdm.write(getResultString(translatedData, end - start, filename))
        with LOCK:
            TOKENS[0] += translatedData[1][0]
            TOKENS[1] += translatedData[1][1]
    except Exception:
        traceback.print_exc()
        return "Fail"

    totalString = getResultString(["", TOKENS, None], end - start, "TOTAL")
    if MISMATCH:
        return totalString + Fore.RED + f"\nMismatch Errors: {MISMATCH}" + Fore.RESET
    return totalString


def openFiles(filename):
    with open("files/" + filename, "r", encoding="UTF-8-sig") as readFile:
        data = json.load(readFile)
        translatedData = parseYuris(data, filename)
    return translatedData


def parseYuris(data, filename):
    totalTokens = [0, 0]
    global PBAR

    if not isinstance(data, list):
        return [data, totalTokens, TypeError(f"{filename} must be a JSON array")]

    totalLines = sum(
        1
        for item in data
        if isinstance(item, dict) and isinstance(item.get("message"), str) and item["message"].strip()
    )

    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
        pbar.desc = filename
        PBAR = pbar
        try:
            result = translateYuris(data, filename)
            totalTokens[0] += result[0]
            totalTokens[1] += result[1]
        except Exception as e:
            traceback.print_exc()
            return [data, totalTokens, e]

    return [data, totalTokens, None]


def translateYuris(data, filename):
    global PBAR
    tokens = [0, 0]
    entries = []
    stringList = []

    for index, item in enumerate(data):
        if not isinstance(item, dict):
            continue

        speaker = ""
        if isinstance(item.get("name"), str) and item["name"].strip():
            speakerData = getSpeaker(item["name"].strip())
            speaker = speakerData[0]
            tokens[0] += speakerData[1][0]
            tokens[1] += speakerData[1][1]
            item["name"] = speaker

        message = item.get("message")
        if not isinstance(message, str) or not message.strip():
            continue
        # if not re.search(LANGREGEX, message):
        #     continue

        cleanMessage = message.replace("\r\n", " ").replace("\n", " ").strip()
        hasSpeaker = bool(speaker)
        stringList.append(f"[{speaker}]: {cleanMessage}" if hasSpeaker else cleanMessage)
        entries.append((index, message, hasSpeaker))

    if not stringList:
        return tokens

    PBAR.total = len(stringList)
    PBAR.refresh()

    response = translateAI(stringList, "Reply with the English Translation")
    tokens[0] += response[1][0]
    tokens[1] += response[1][1]
    translatedList = response[0]

    if len(stringList) != len(translatedList):
        with LOCK:
            if FILENAME not in MISMATCH:
                MISMATCH.append(FILENAME)
        return tokens

    for (index, originalMessage, hasSpeaker), translatedText in zip(entries, translatedList):
        if hasSpeaker:
            translatedText = stripSpeakerPrefix(translatedText)
        translatedText = translatedText.replace("\r\n", "\n")
        translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)
        translatedText = translatedText.replace("\n", "\r\n")
        data[index]["message"] = originalMessage.replace(originalMessage, translatedText)
        save_progress_json(data, filename)
        if PBAR is not None:
            PBAR.update(1)

    return tokens


def stripSpeakerPrefix(translated_text):
    """Same behavior as modules/json.translateJSON: strip [Name]: prefix from TL lines."""
    match = re.search(r"(^\[.+?\]\s?[|:]\s?)", translated_text)
    if match:
        translated_text = translated_text.replace(match.group(1), "")
    else:
        cjk_m = re.match(
            r"^[一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９\uFF61-\uFF9F]+\s*[\(（:]\s*",
            translated_text,
        )
        if cjk_m:
            translated_text = translated_text[cjk_m.end():]
            translated_text = re.sub(r"\s*[)）]\s*$", "", translated_text)
    return translated_text.strip()


def save_progress_json(data, filename):
    try:
        if ESTIMATE:
            return
        target = os.path.join("translated", filename)
        os.makedirs(os.path.dirname(target) or "translated", exist_ok=True)
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix=f"{os.path.basename(filename)}.",
            suffix=".tmp",
            dir=os.path.dirname(target) or "translated",
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8", newline="\n") as tmp_file:
                json.dump(data, tmp_file, ensure_ascii=False, indent=4)
            os.replace(tmp_path, target)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
    except Exception:
        traceback.print_exc()


def getResultString(translatedData, translationTime, filename):
    cost = calculateCost(translatedData[1][0], translatedData[1][1], MODEL)
    totalTokenstring = (
        Fore.YELLOW
        + f"[Input: {translatedData[1][0]}]"
        + f"[Output: {translatedData[1][1]}]"
        + f"[Cost: ${cost:,.4f}]"
    )
    timeString = Fore.BLUE + f"[{round(translationTime, 1)}s]"

    if translatedData[2] is None:
        return f"{filename}: {totalTokenstring}{timeString}" + Fore.GREEN + " \u2713 " + Fore.RESET

    try:
        raise translatedData[2]
    except Exception as e:
        traceback.print_exc()
        errorString = str(e) + Fore.RED
        return f"{filename}: {totalTokenstring}{timeString}" + Fore.RED + " \u2717 " + errorString + Fore.RESET


def getSpeaker(speaker):
    if not speaker:
        return ["", [0, 0]]

    for original, translated in NAMESLIST:
        if speaker == original:
            return [translated, [0, 0]]

    response = translateAI(
        speaker,
        "Reply with the " + LANGUAGE + " translation of the NPC name.",
        False,
    )
    response[0] = response[0].title().replace("'S", "'s").replace("Speaker: ", "")

    if re.search(r"([a-zA-Z？?])", response[0]) is None:
        response = translateAI(
            speaker,
            "Reply with the " + LANGUAGE + " translation of the NPC name.",
            False,
        )
        response[0] = response[0].title().replace("'S", "'s").replace("Speaker: ", "")

    NAMESLIST.append([speaker, response[0]])
    return response


def translateAI(text, history, history_ctx=None):
    global PBAR, MISMATCH, FILENAME
    TRANSLATION_CONFIG.estimateMode = bool(ESTIMATE)
    return sharedtranslateAI(
        text=text,
        history=history,
        config=TRANSLATION_CONFIG,
        filename=FILENAME,
        pbar=PBAR,
        lock=LOCK,
        mismatchList=MISMATCH,
    )
