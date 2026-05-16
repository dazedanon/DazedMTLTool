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

_ASSET_EXT = re.compile(
    r"\.(png|jpe?g|gif|webp|bmp|tga|tif|ogg|mp3|wav|mid|json|txt|xml|ttf|otf|woff2?|ks|tjs)\b",
    re.I,
)
# Typeface / UI font name tokens — translating breaks runtime font resolution.
_FONTISH = re.compile(
    r"ゴシック|ゴチック|明朝|Mincho|Gothic|ＰＧ|ＭＳ|メイリオ|Meiryo|游ゴ|Yu\s?Gothic|"
    r"Tahoma|Arial|Consolas|Segoe|SimSun|宋体|黑体|DF体|ヒラギノ|Hiragino|"
    r"Noto\s|IPA|Ricty|VL\s|@",
    re.I,
)


def _yuris_nonempty_messages(data: list) -> list[str]:
    out: list[str] = []
    for item in data:
        if isinstance(item, dict):
            msg = item.get("message")
            if isinstance(msg, str) and msg.strip():
                out.append(msg)
    return out


def _yuris_font_face_table(msgs: list[str]) -> bool:
    if not msgs or len(msgs) > 120:
        return False
    if any(len(m) > 120 for m in msgs):
        return False
    ascii_label = re.compile(r"^[A-Za-z0-9 _+.,'-]{1,64}$")
    for m in msgs:
        if _FONTISH.search(m):
            continue
        if ascii_label.fullmatch(m.strip()):
            continue
        return False
    return True


def yuris_whole_file_pass_through_reason(data) -> str | None:
    """
    When True, the file is copied to translated/ unchanged (no API).
    Heuristics: only resource paths, or only font-face style entries.
    """
    if not isinstance(data, list):
        return None
    msgs = _yuris_nonempty_messages(data)
    if not msgs:
        return None
    if all(_message_looks_like_asset_path(m) for m in msgs):
        return "path-only resource strings"
    if _yuris_font_face_table(msgs):
        return "font face list"
    return None


def _message_looks_like_asset_path(message: str) -> bool:
    """Skip resource-like strings: paths, URLs, and any line containing '_' (engine IDs / filenames)."""
    s = message.strip()
    if not s:
        return True
    if "://" in s:
        return True
    if re.match(r"^[A-Za-z]:[/\\]", s):
        return True
    if "\\" in s or "/" in s:
        norm = s.replace("\\", "/")
        tail = norm.rsplit("/", 1)[-1]
        if _ASSET_EXT.search(s):
            return True
        if re.fullmatch(r"[A-Za-z0-9_.-]+", tail):
            return True
    if "_" in s:
        return True
    # Common JP UI font face names (no underscores) — keep short to avoid snagging real prose.
    if len(s) <= 80 and any(t in s for t in ("ゴシック", "ゴチック", "明朝")):
        return True
    return False


def yuris_message_is_translatable(message: str) -> bool:
    return isinstance(message, str) and bool(message.strip()) and not _message_looks_like_asset_path(message)


def replace_yuris_problem_dashes(text: str) -> str:
    """Replace characters the Yuris runtime mishandles (e.g. ― U+2015 HORIZONTAL BAR)."""
    return text.replace("\u2015", "-")


def _yuris_pulse_progress_complete(filename: str) -> None:
    """
    GUI/ subprocess_runner polls modules.yuris.PBAR. Skipped files and 0-line files
    never touched tqdm otherwise, so the monitor never emits PROGRESS:...:n:total and
    rows sit at 0% or odd states until completion.
    """
    global PBAR
    with tqdm(
        total=1,
        bar_format=BAR_FORMAT,
        position=POSITION,
        leave=LEAVE,
        desc=filename,
    ) as pbar:
        PBAR = pbar
        pbar.update(1)
    PBAR = None


def handleYuris(filename, estimate):
    global ESTIMATE, FILENAME, TOKENS
    ESTIMATE = estimate
    FILENAME = filename

    try:
        start = time.time()
        with open("files/" + filename, "r", encoding="UTF-8-sig") as readFile:
            data = json.load(readFile)

        pass_reason = yuris_whole_file_pass_through_reason(data)
        if pass_reason:
            if not estimate:
                os.makedirs(os.path.dirname(os.path.join("translated", filename)) or "translated", exist_ok=True)
                with open("translated/" + filename, "w", encoding="utf-8", newline="\n") as outFile:
                    json.dump(data, outFile, ensure_ascii=False, indent=4)
            end = time.time()
            # Machine-readable line so the GUI can apply totals row state (same as other modules).
            c0 = calculateCost(0, 0, MODEL)
            tqdm.write(
                f"{filename}: [Input: 0][Output: 0][Cost: ${c0:.4f}]"
                f"[{round(end - start, 1)}s] [skipped] {pass_reason}"
            )
            _yuris_pulse_progress_complete(filename)
        else:
            translatedData = parseYuris(data, filename)

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


def parseYuris(data, filename):
    totalTokens = [0, 0]
    global PBAR

    if not isinstance(data, list):
        return [data, totalTokens, TypeError(f"{filename} must be a JSON array")]

    totalLines = sum(
        1
        for item in data
        if isinstance(item, dict) and yuris_message_is_translatable(item.get("message", ""))
    )

    # total=0 breaks tqdm + GUI progress monitor; still pulse 1/1 when nothing to translate.
    pbar_total = max(1, totalLines)
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=pbar_total, leave=LEAVE) as pbar:
        pbar.desc = filename
        PBAR = pbar
        try:
            if totalLines == 0:
                pbar.update(1)
            result = translateYuris(data, filename)
            totalTokens[0] += result[0]
            totalTokens[1] += result[1]
        except Exception as e:
            traceback.print_exc()
            return [data, totalTokens, e]
        finally:
            PBAR = None

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
        if not yuris_message_is_translatable(message):
            continue

        cleanMessage = message.replace("\r\n", " ").replace("\n", " ").strip()
        cleanMessage = replace_yuris_problem_dashes(cleanMessage)
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
        translatedText = replace_yuris_problem_dashes(translatedText)
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
