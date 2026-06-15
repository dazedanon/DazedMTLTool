# modules/aquedi4.py

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
# from modules.json import translateSimpleKeyValueJSON
import tempfile

# Boilerplate Globals
MODEL = os.getenv("model")
TIMEOUT = int(os.getenv("timeout"))
LANGUAGE = os.getenv("language").capitalize()
from util.paths import PROMPT_PATH, VOCAB_PATH

PROMPT = PROMPT_PATH.read_text(encoding="utf-8")
VOCAB = VOCAB_PATH.read_text(encoding="utf-8")
LOCK = threading.Lock()
ESTIMATE = ""
TOKENS = [0, 0]
MISMATCH = []
FILENAME = None
PBAR = None
BAR_FORMAT = "{l_bar}{bar:10}{r_bar}{bar:-10b}"

# Flag to control line break replacement
REPLACE_LINEBREAKS_WITH_PIPES = True

LANGREGEX = r"[一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９\uFF61-\uFF9F]+"
TRANSLATION_CONFIG = TranslationConfig(
    model=MODEL,
    language=LANGUAGE,
    prompt=PROMPT,
    vocab=VOCAB,
    langRegex=LANGREGEX,
    batchSize=int(os.getenv("batchsize", 10)),
    maxHistory=10,
    estimateMode=False
)
# End Boilerplate

def handleAquedi4(filename, estimate):
    """Main handler for Aquedi4 JSON files."""
    global ESTIMATE, TOKENS, FILENAME
    ESTIMATE = estimate
    FILENAME = filename

    try:
        start = time.time()
        translatedData = openFiles(filename)

        if not estimate:
            # Write final result after translation is complete
            with open("translated/" + filename, "w", encoding="utf-8", newline="\n") as outFile:
                json.dump(translatedData[0], outFile, ensure_ascii=False, indent=4)
        
        end = time.time()
        tqdm.write(getResultString(translatedData, end - start, filename))
        with LOCK:
            TOKENS[0] += translatedData[1][0]
            TOKENS[1] += translatedData[1][1]

    except Exception as e:
        traceback.print_exc()
        return "Fail"

    return getResultString(["", TOKENS, None], end - start, "TOTAL")


def openFiles(filename):
    """Opens and parses the JSON file."""
    with open("files/" + filename, "r", encoding="UTF-8-sig") as f:
        data = json.load(f)
        translatedData = parseAquedi4JSON(data, filename)
    return translatedData


def parseAquedi4JSON(data, filename):
    """Parses and translates the simple key-value JSON."""
    totalTokens = [0, 0]
    totalLines = 0
    totalLines = len(data)
    global LOCK, PBAR

    stringList = []
    keyList = []
    if isinstance(data, dict) and all(isinstance(v, str) for v in data.values()):
        for key, value in data.items():
            if re.search(LANGREGEX, key):
                stringList.append(key)
                keyList.append(key)
    
    with tqdm(total=len(stringList), bar_format=BAR_FORMAT, position=0, leave=False) as pbar:
        pbar.desc = filename
        PBAR = pbar

        # from modules.json import translateSimpleKeyValueJSON
        
        try:
            if stringList:
                result = translateSimpleKeyValueJSON(data, filename, stringList, keyList)
                totalTokens[0] += result[0]
                totalTokens[1] += result[1]
            else:
                pbar.write(f"Warning: {filename} is not in the expected simple key-value format. Skipping.")
        except Exception as e:
            traceback.print_exc()
            return [data, totalTokens, e]
            
    return [data, totalTokens, None]


def translateSimpleKeyValueJSON(data, filename, stringList, keyList):
    """
    Translate simple key-value JSON format where keys contain Japanese text
    and values are placeholder strings like "TODO".
    
    Format example:
    {
        "\\r\\nスタビライザー": "TODO",
        "\\r\\nプラグインなし": "TODO"
    }
    """
    global LOCK, ESTIMATE, FILENAME, PBAR, MISMATCH
    tokens = [0, 0]

    preparedStringList = []
    if REPLACE_LINEBREAKS_WITH_PIPES:
        for s in stringList:
            preparedStringList.append(s.replace("\r\n", "|").replace("\n", "|"))
    else:
        preparedStringList = stringList
    
    # Translate all keys if any were found
    if preparedStringList:
        PBAR.total = len(preparedStringList)
        PBAR.refresh()
        
        response = translateAI(preparedStringList, "Reply with the English Translation")
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        translatedList = response[0]
        
        # Check for mismatch
        if len(preparedStringList) != len(translatedList):
            with LOCK:
                if FILENAME not in MISMATCH:
                    MISMATCH.append(FILENAME)
        
        # Pass 2: Update the values with translations
        for i, original_key in enumerate(keyList):
            if i < len(translatedList):
                translatedText = translatedList[i]

                if REPLACE_LINEBREAKS_WITH_PIPES:
                    translatedText = translatedText.replace("|", "\r\n")
                # Set the translated text as the value
                data[original_key] = translatedText
                
                # Save progress after each translation
                save_progress_json(data, filename)
    
    return tokens

def save_progress_json(data, filename):
    """Save current JSON translation progress."""
    try:
        if ESTIMATE: return
        os.makedirs("translated", exist_ok=True)
        tmp_path = os.path.join("translated", f"{filename}.tmp")
        final_path = os.path.join("translated", filename)
        with open(tmp_path, "w", encoding="utf-8", newline="\n") as outFile:
            json.dump(data, outFile, ensure_ascii=False, indent=4)
        os.replace(tmp_path, final_path)
    except Exception:
        traceback.print_exc()


def getResultString(translatedData, translationTime, filename):
    cost = calculateCost(translatedData[1][0], translatedData[1][1], MODEL)
    totalTokenstring = (
        Fore.YELLOW + f"[Input: {translatedData[1][0]}]"
        f"[Output: {translatedData[1][1]}]"
        f"[Cost: ${cost:,.4f}]"
    )
    timeString = Fore.BLUE + f"[{round(translationTime, 1)}s]"

    if translatedData[2] is None:
        return f"{filename}: {totalTokenstring}{timeString}" + Fore.GREEN + " \u2713 " + Fore.RESET
    else:
        errorString = str(translatedData[2]) + Fore.RED
        return f"{filename}: {totalTokenstring}{timeString}" + Fore.RED + " \u2717 " + errorString + Fore.RESET

def translateAI(text, history, history_ctx=None):
    """Legacy wrapper for the shared translation utility."""
    global PBAR, MISMATCH, FILENAME
    TRANSLATION_CONFIG.estimateMode = bool(ESTIMATE)
    return sharedtranslateAI(
        text=text,
        history=history,
        config=TRANSLATION_CONFIG,
        filename=FILENAME,
        pbar=PBAR,
        lock=LOCK,
        mismatchList=MISMATCH
    )