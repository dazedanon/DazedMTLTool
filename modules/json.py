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
PROMPT = Path("prompt.txt").read_text(encoding="utf-8")
VOCAB = Path("vocab.txt").read_text(encoding="utf-8")
LOCK = threading.Lock()
WIDTH = int(os.getenv("width"))
LISTWIDTH = int(os.getenv("listWidth"))
NOTEWIDTH = 70
MAXHISTORY = 10
ESTIMATE = ""
TOKENS = [0, 0]
NAMESLIST = []
FILENAME = None
NAMES = False  # Output a list of all the character names found
BRFLAG = False  # If the game uses <br> instead
FIXTEXTWRAP = True  # Overwrites textwrap
IGNORETLTEXT = False  # Ignores all translated text.
MISMATCH = []  # Lists files that throw a mismatch error (Length of GPT list response is wrong)

# tqdm Globals
BAR_FORMAT = "{l_bar}{bar:10}{r_bar}{bar:-10b}"
POSITION = 0
LEAVE = False
PBAR = None

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

def handleJSON(filename, estimate):
    global ESTIMATE, totalTokens, FILENAME
    ESTIMATE = estimate
    FILENAME = filename

    if estimate:
        start = time.time()
        translatedData = openFiles(filename)

        # Print Result
        end = time.time()
        tqdm.write(getResultString(translatedData, end - start, filename))
        with LOCK:
            TOKENS[0] += translatedData[1][0]
            TOKENS[1] += translatedData[1][1]

        return getResultString(["", TOKENS, None], end - start, "TOTAL")

    else:
        try:
            start = time.time()
            translatedData = openFiles(filename)

            # Write final result after translation is complete
            with open("translated/" + filename, "w", encoding="utf-8", newline="\n") as outFile:
                json.dump(translatedData[0], outFile, ensure_ascii=False, indent=4)
            
            # Print Result
            end = time.time()
            tqdm.write(getResultString(translatedData, end - start, filename))
            with LOCK:
                TOKENS[0] += translatedData[1][0]
                TOKENS[1] += translatedData[1][1]
        except Exception:
            return "Fail"

    return getResultString(["", TOKENS, None], end - start, "TOTAL")


def openFiles(filename):
    with open("files/" + filename, "r", encoding="UTF-8-sig") as f:
        data = json.load(f)

        # Map Files
        if ".json" in filename:
            translatedData = parseJSON(data, filename)

        else:
            raise NameError(filename + " Not Supported")

    return translatedData


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


def parseJSON(data, filename):
    totalTokens = [0, 0]
    totalLines = 0
    totalLines = len(data)
    global LOCK, PBAR

    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
        pbar.desc = filename
        PBAR = pbar
        try:
            # Check if data is a simple key-value dict (not a list)
            if isinstance(data, dict) and not isinstance(data, list):
                # Check if it's a simple key-value format (all values are strings, not nested objects)
                if all(isinstance(v, str) for v in data.values()):
                    result = translateSimpleKeyValueJSON(data, filename)
                # PSData format (Nupu_PSData.json - MailDatas, MemoryData, ShopDatas, hStData)
                elif any(k in data for k in ["MailDatas", "MemoryData", "ShopDatas", "hStData"]):
                    result = translatePSData(data, filename)
                # RdData format (RdData.json - dgnDatas with dungeon/dialogue data)
                elif "dgnDatas" in data:
                    result = translateRdData(data, filename)
                # GameSetting format (Nupu_GameSetting.json - fzCardDatas, fzDeckDatas, rentalDecks)
                elif any(k in data for k in ["fzCardDatas", "fzDeckDatas", "rentalDecks"]):
                    result = translateGameSetting(data, filename)
                else:
                    result = translateJSON(data, filename, [])
            else:
                result = translateJSON(data, filename, [])
            totalTokens[0] += result[0]
            totalTokens[1] += result[1]
        except Exception as e:
            traceback.print_exc()
            return [data, totalTokens, e]
    return [data, totalTokens, None]


def save_progress_json(data, filename):
    """Save current JSON translation progress."""
    try:
        if ESTIMATE:
            return
        os.makedirs("translated", exist_ok=True)
        tmp_path = os.path.join("translated", f"{filename}.tmp")
        final_path = os.path.join("translated", filename)
        with open(tmp_path, "w", encoding="utf-8", newline="\n") as outFile:
            json.dump(data, outFile, ensure_ascii=False, indent=4)
        os.replace(tmp_path, final_path)
    except Exception:
        traceback.print_exc()


def translateSimpleKeyValueJSON(data, filename):
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
    stringList = []
    keyList = []
    
    # Pass 1: Collect all keys that need translation
    for key, value in data.items():
        # Check if the key contains text matching the language regex
        if re.search(LANGREGEX, key):
            # Strip whitespace and newline characters for translation
            # cleanKey = key.strip().replace("\r\n", "").replace("\n", "").replace("\r", "")
            # if cleanKey:
            stringList.append(key)
            keyList.append(key)  # Store original key for reference
    
    # Translate all keys if any were found
    if stringList:
        PBAR.total = len(stringList)
        PBAR.refresh()
        
        response = translateAI(stringList, "Reply with the English Translation", True)
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        translatedList = response[0]
        
        # Check for mismatch
        if len(stringList) != len(translatedList):
            with LOCK:
                if FILENAME not in MISMATCH:
                    MISMATCH.append(FILENAME)
        
        # Pass 2: Update the values with translations
        for i, key in enumerate(keyList):
            if i < len(translatedList):
                translatedText = translatedList[i]
                # Set the translated text as the value
                data[key] = translatedText
                
                # Save progress after each translation
                save_progress_json(data, filename)
    
    return tokens


def translatePSData(data, filename):
    """Translate PSData JSON format (e.g. Nupu_PSData.json).
    
    Handles four sections:
    - MailDatas: In-game mail/message system
    - MemoryData: Scene/CG gallery memories  
    - ShopDatas: Shop configurations and dialogue
    - hStData: Status rank descriptions
    
    Only translates player-visible text fields.
    """
    global LOCK, ESTIMATE, FILENAME, PBAR, MISMATCH
    tokens = [0, 0]

    def batchTranslate(stringList, context):
        """Translate a list of strings and return translations. Returns [] on mismatch."""
        nonlocal tokens
        if not stringList:
            return []
        response = translateAI(stringList, context, True)
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        if len(stringList) != len(response[0]):
            with LOCK:
                if FILENAME not in MISMATCH:
                    MISMATCH.append(FILENAME)
            return []
        return response[0]

    # ================================================================
    # PASS 1: Collect all translatable strings from every section
    # ================================================================

    # -- MailDatas --
    mailNameS, mailNameI = [], []
    mailTitleS, mailTitleI = [], []
    mailListNameS, mailListNameI = [], []
    mailTextS, mailTextI = [], []

    if "MailDatas" in data:
        for i, m in enumerate(data["MailDatas"]):
            if m.get("Name") and re.search(LANGREGEX, m["Name"]):
                mailNameS.append(m["Name"])
                mailNameI.append(i)
            if m.get("Title") and re.search(LANGREGEX, m["Title"]):
                mailTitleS.append(m["Title"])
                mailTitleI.append(i)
            if m.get("MailListName") and re.search(LANGREGEX, m["MailListName"]):
                mailListNameS.append(m["MailListName"])
                mailListNameI.append(i)
            if m.get("MailText") and re.search(LANGREGEX, m["MailText"]):
                mailTextS.append(m["MailText"].replace("\r\n", " ").replace("\n", " ").strip())
                mailTextI.append(i)

    # -- MemoryData --
    memTitleS, memTitleI = [], []
    memSetuS, memSetuI = [], []
    memHintS, memHintI = [], []
    memPtnS, memPtnI = [], []        # indices are (memIdx, ptnIdx)
    memDtlSetuS, memDtlSetuI = [], []  # indices are (memIdx, dtlIdx)

    if "MemoryData" in data:
        for i, mem in enumerate(data["MemoryData"]):
            if mem.get("_Title") and re.search(LANGREGEX, mem["_Title"]):
                memTitleS.append(mem["_Title"])
                memTitleI.append(i)
            if mem.get("_Setu") and re.search(LANGREGEX, mem["_Setu"]):
                memSetuS.append(mem["_Setu"].replace("\r\n", " ").replace("\n", " ").strip())
                memSetuI.append(i)
            if mem.get("_Hint") and re.search(LANGREGEX, mem["_Hint"]):
                memHintS.append(mem["_Hint"])
                memHintI.append(i)
            if "_Ptn" in mem and isinstance(mem["_Ptn"], list):
                for j, p in enumerate(mem["_Ptn"]):
                    if p and re.search(LANGREGEX, p):
                        memPtnS.append(p)
                        memPtnI.append((i, j))
            if "_DtlCheck" in mem and isinstance(mem["_DtlCheck"], list):
                for j, dtl in enumerate(mem["_DtlCheck"]):
                    if isinstance(dtl, dict) and dtl.get("_Setu") and re.search(LANGREGEX, dtl["_Setu"]):
                        memDtlSetuS.append(dtl["_Setu"].replace("\r\n", " ").replace("\n", " ").strip())
                        memDtlSetuI.append((i, j))

    # -- ShopDatas --
    shopNameS, shopNameI = [], []
    shopTextFields = ["buySelf", "emptySelf", "firstSelf", "husokuSelf",
                      "randSelf1", "randSelf2", "randSelf3"]
    shopTextS = {f: [] for f in shopTextFields}
    shopTextI = {f: [] for f in shopTextFields}

    if "ShopDatas" in data:
        for i, shop in enumerate(data["ShopDatas"]):
            if shop.get("name") and re.search(LANGREGEX, shop["name"]):
                shopNameS.append(shop["name"])
                shopNameI.append(i)
            for field in shopTextFields:
                if field in shop and isinstance(shop[field], dict):
                    text = shop[field].get("text", "")
                    if text and re.search(LANGREGEX, text):
                        shopTextS[field].append(text.replace("\r\n", " ").replace("\n", " ").strip())
                        shopTextI[field].append(i)

    # -- hStData --
    rankArrayNames = ["KutiRankDatas", "MuneRankDatas", "SiriRankDatas", "TituRankDatas"]
    rankSetuS, rankSetuI = [], []      # indices are (arrayName, idx)
    rankText1S, rankText1I = [], []
    rankText2S, rankText2I = [], []

    if "hStData" in data:
        hst = data["hStData"]
        for arrName in rankArrayNames:
            if arrName in hst and isinstance(hst[arrName], list):
                for i, rank in enumerate(hst[arrName]):
                    if rank.get("rankSetu") and re.search(LANGREGEX, rank["rankSetu"]):
                        rankSetuS.append(rank["rankSetu"].replace("\r\n", " ").replace("\n", " ").strip())
                        rankSetuI.append((arrName, i))
                    if rank.get("rankText1") and re.search(LANGREGEX, rank["rankText1"]):
                        rankText1S.append(rank["rankText1"])
                        rankText1I.append((arrName, i))
                    if rank.get("rankText2") and re.search(LANGREGEX, rank["rankText2"]):
                        rankText2S.append(rank["rankText2"])
                        rankText2I.append((arrName, i))

    # Set progress bar total
    totalItems = (
        len(mailNameS) + len(mailTitleS) + len(mailListNameS) + len(mailTextS)
        + len(memTitleS) + len(memSetuS) + len(memHintS) + len(memPtnS) + len(memDtlSetuS)
        + len(shopNameS) + sum(len(v) for v in shopTextS.values())
        + len(rankSetuS) + len(rankText1S) + len(rankText2S)
    )
    PBAR.total = totalItems
    PBAR.refresh()

    # ================================================================
    # PASS 2: Translate each batch and apply results back to data
    # ================================================================

    # -- MailDatas --
    if "MailDatas" in data:
        mails = data["MailDatas"]

        for tl, idx in zip(batchTranslate(mailNameS, "Character Name"), mailNameI):
            mails[idx]["Name"] = tl
        if mailNameS:
            save_progress_json(data, filename)

        for tl, idx in zip(batchTranslate(mailTitleS, "Mail Subject"), mailTitleI):
            mails[idx]["Title"] = tl
        if mailTitleS:
            save_progress_json(data, filename)

        for tl, idx in zip(batchTranslate(mailListNameS, "Mail List Entry"), mailListNameI):
            mails[idx]["MailListName"] = tl
        if mailListNameS:
            save_progress_json(data, filename)

        for tl, idx in zip(batchTranslate(mailTextS, "Mail Body Text"), mailTextI):
            mails[idx]["MailText"] = dazedwrap.wrapText(tl, WIDTH)
        if mailTextS:
            save_progress_json(data, filename)

    # -- MemoryData --
    if "MemoryData" in data:
        memories = data["MemoryData"]

        for tl, idx in zip(batchTranslate(memTitleS, "Scene Title"), memTitleI):
            memories[idx]["_Title"] = tl
        if memTitleS:
            save_progress_json(data, filename)

        for tl, idx in zip(batchTranslate(memSetuS, "Scene Description"), memSetuI):
            memories[idx]["_Setu"] = tl
        if memSetuS:
            save_progress_json(data, filename)

        for tl, idx in zip(batchTranslate(memHintS, "Hint Text"), memHintI):
            memories[idx]["_Hint"] = tl
        if memHintS:
            save_progress_json(data, filename)

        for tl, (mi, pi) in zip(batchTranslate(memPtnS, "Scene Description"), memPtnI):
            memories[mi]["_Ptn"][pi] = tl
        if memPtnS:
            save_progress_json(data, filename)

        for tl, (mi, di) in zip(batchTranslate(memDtlSetuS, "Character Commentary"), memDtlSetuI):
            memories[mi]["_DtlCheck"][di]["_Setu"] = dazedwrap.wrapText(tl, WIDTH)
        if memDtlSetuS:
            save_progress_json(data, filename)

    # -- ShopDatas --
    if "ShopDatas" in data:
        shops = data["ShopDatas"]

        for tl, idx in zip(batchTranslate(shopNameS, "Shop Name"), shopNameI):
            shops[idx]["name"] = tl
        if shopNameS:
            save_progress_json(data, filename)

        for field in shopTextFields:
            for tl, idx in zip(batchTranslate(shopTextS[field], "Shop Dialogue"), shopTextI[field]):
                shops[idx][field]["text"] = dazedwrap.wrapText(tl, WIDTH)
            if shopTextS[field]:
                save_progress_json(data, filename)

    # -- hStData --
    if "hStData" in data:
        hst = data["hStData"]

        for tl, (an, idx) in zip(batchTranslate(rankSetuS, "Rank Description"), rankSetuI):
            hst[an][idx]["rankSetu"] = dazedwrap.wrapText(tl, WIDTH)
        if rankSetuS:
            save_progress_json(data, filename)

        for tl, (an, idx) in zip(batchTranslate(rankText1S, "Rank Label"), rankText1I):
            hst[an][idx]["rankText1"] = tl
        if rankText1S:
            save_progress_json(data, filename)

        for tl, (an, idx) in zip(batchTranslate(rankText2S, "Rank Subtitle"), rankText2I):
            hst[an][idx]["rankText2"] = tl
        if rankText2S:
            save_progress_json(data, filename)

    return tokens


def translateRdData(data, filename):
    """Translate RdData JSON format (e.g. RdData.json).
    
    Handles dungeon data with nested dialogue, choices, and UI text.
    Only translates player-visible text fields.
    """
    global LOCK, ESTIMATE, FILENAME, PBAR, MISMATCH
    tokens = [0, 0]

    def batchTranslate(stringList, context):
        """Translate a list of strings and return translations. Returns [] on mismatch."""
        nonlocal tokens
        if not stringList:
            return []
        response = translateAI(stringList, context, True)
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        if len(stringList) != len(response[0]):
            with LOCK:
                if FILENAME not in MISMATCH:
                    MISMATCH.append(FILENAME)
            return []
        return response[0]

    if "dgnDatas" not in data:
        return tokens

    dgns = data["dgnDatas"]

    # ================================================================
    # PASS 1: Collect all translatable strings
    # ================================================================

    # -- Dungeon-level short fields --
    dgnNameS, dgnNameI = [], []
    clearTxtS, clearTxtI = [], []
    hosyuTxtS, hosyuTxtI = [], []
    firstHosyuTxtS, firstHosyuTxtI = [], []
    memoTxtS, memoTxtI = [], []
    appMemoTxtS, appMemoTxtI = [], []
    areaMemoS, areaMemoI = [], []

    # -- Dungeon-level long text fields --
    naiyoTxtS, naiyoTxtI = [], []
    naiyoTxtExS, naiyoTxtExI = [], []
    johoTxtS, johoTxtI = [], []
    johoTxtExS, johoTxtExI = [], []

    # -- Floor names --
    kaisoNameS, kaisoNameI = [], []  # (dgnIdx, kaisoIdx)

    # -- Dialogue (talkDatas / talkDatasEx) --
    talkNameS, talkNameI = [], []               # (dgnIdx, talkKey, talkIdx)
    speakerNameS, speakerNameI = [], []         # (dgnIdx, talkKey, talkIdx, speechIdx)
    dialogueS, dialogueI = [], []               # (dgnIdx, talkKey, talkIdx, speechIdx)

    # -- Choice events (sijiDatas) --
    sijiNameS, sijiNameI = [], []               # (dgnIdx, sijiIdx)
    sijiChoiceS, sijiChoiceI = [], []           # (dgnIdx, sijiIdx)

    for di, dgn in enumerate(dgns):
        if dgn is None:
            continue

        # Dungeon short fields
        if dgn.get("name") and re.search(LANGREGEX, dgn["name"]):
            dgnNameS.append(dgn["name"])
            dgnNameI.append(di)
        if dgn.get("clearTxt") and re.search(LANGREGEX, dgn["clearTxt"]):
            clearTxtS.append(dgn["clearTxt"])
            clearTxtI.append(di)
        if dgn.get("hosyuTxt") and re.search(LANGREGEX, dgn["hosyuTxt"]):
            hosyuTxtS.append(dgn["hosyuTxt"])
            hosyuTxtI.append(di)
        if dgn.get("firstHosyuTxt") and re.search(LANGREGEX, dgn["firstHosyuTxt"]):
            firstHosyuTxtS.append(dgn["firstHosyuTxt"])
            firstHosyuTxtI.append(di)
        if dgn.get("memoTxt") and re.search(LANGREGEX, dgn["memoTxt"]):
            memoTxtS.append(dgn["memoTxt"])
            memoTxtI.append(di)
        if dgn.get("appMemoTxt") and re.search(LANGREGEX, dgn["appMemoTxt"]):
            appMemoTxtS.append(dgn["appMemoTxt"])
            appMemoTxtI.append(di)
        if dgn.get("areaMemo") and re.search(LANGREGEX, dgn["areaMemo"]):
            areaMemoS.append(dgn["areaMemo"])
            areaMemoI.append(di)

        # Dungeon long text fields (strip line breaks for translation)
        if dgn.get("naiyoTxt") and re.search(LANGREGEX, dgn["naiyoTxt"]):
            naiyoTxtS.append(dgn["naiyoTxt"].replace("\r\n", " ").replace("\n", " ").strip())
            naiyoTxtI.append(di)
        if dgn.get("naiyoTxtEx") and re.search(LANGREGEX, dgn["naiyoTxtEx"]):
            naiyoTxtExS.append(dgn["naiyoTxtEx"].replace("\r\n", " ").replace("\n", " ").strip())
            naiyoTxtExI.append(di)
        if dgn.get("johoTxt") and re.search(LANGREGEX, dgn["johoTxt"]):
            johoTxtS.append(dgn["johoTxt"].replace("\r\n", " ").replace("\n", " ").strip())
            johoTxtI.append(di)
        if dgn.get("johoTxtEx") and re.search(LANGREGEX, dgn["johoTxtEx"]):
            johoTxtExS.append(dgn["johoTxtEx"].replace("\r\n", " ").replace("\n", " ").strip())
            johoTxtExI.append(di)

        # Floor names
        if "kaisoDatas" in dgn and isinstance(dgn["kaisoDatas"], list):
            for ki, kaiso in enumerate(dgn["kaisoDatas"]):
                if isinstance(kaiso, dict) and kaiso.get("kaisoName") and re.search(LANGREGEX, kaiso["kaisoName"]):
                    kaisoNameS.append(kaiso["kaisoName"])
                    kaisoNameI.append((di, ki))

        # Dialogue from talkDatas and talkDatasEx
        for talkKey in ["talkDatas", "talkDatasEx"]:
            if talkKey in dgn and isinstance(dgn[talkKey], list):
                for ti, talk in enumerate(dgn[talkKey]):
                    if not isinstance(talk, dict):
                        continue
                    if talk.get("name") and re.search(LANGREGEX, talk["name"]):
                        talkNameS.append(talk["name"])
                        talkNameI.append((di, talkKey, ti))
                    if "speachDatas" in talk and isinstance(talk["speachDatas"], list):
                        for si, speech in enumerate(talk["speachDatas"]):
                            if not isinstance(speech, dict):
                                continue
                            if speech.get("name") and re.search(LANGREGEX, speech["name"]):
                                speakerNameS.append(speech["name"])
                                speakerNameI.append((di, talkKey, ti, si))
                            if speech.get("text") and re.search(LANGREGEX, speech["text"]):
                                dialogueS.append(speech["text"].replace("\r\n", " ").replace("\n", " ").strip())
                                dialogueI.append((di, talkKey, ti, si))

        # Choice events (sijiDatas)
        if "sijiDatas" in dgn and isinstance(dgn["sijiDatas"], list):
            for si, siji in enumerate(dgn["sijiDatas"]):
                if not isinstance(siji, dict):
                    continue
                if siji.get("name") and re.search(LANGREGEX, siji["name"]):
                    sijiNameS.append(siji["name"])
                    sijiNameI.append((di, si))
                if siji.get("choiceSijiTxt") and re.search(LANGREGEX, siji["choiceSijiTxt"]):
                    sijiChoiceS.append(siji["choiceSijiTxt"].replace("\r\n", " ").replace("\n", " ").strip())
                    sijiChoiceI.append((di, si))

    # Set progress bar total
    totalItems = (
        len(dgnNameS) + len(clearTxtS) + len(hosyuTxtS) + len(firstHosyuTxtS)
        + len(memoTxtS) + len(appMemoTxtS) + len(areaMemoS)
        + len(naiyoTxtS) + len(naiyoTxtExS) + len(johoTxtS) + len(johoTxtExS)
        + len(kaisoNameS)
        + len(talkNameS) + len(speakerNameS) + len(dialogueS)
        + len(sijiNameS) + len(sijiChoiceS)
    )
    PBAR.total = totalItems
    PBAR.refresh()

    # ================================================================
    # PASS 2: Translate each batch and apply results back to data
    # ================================================================

    # -- Dungeon short fields --
    for tl, idx in zip(batchTranslate(dgnNameS, "Dungeon Name"), dgnNameI):
        dgns[idx]["name"] = tl
    if dgnNameS:
        save_progress_json(data, filename)

    for tl, idx in zip(batchTranslate(clearTxtS, "Clear Condition"), clearTxtI):
        dgns[idx]["clearTxt"] = tl
    if clearTxtS:
        save_progress_json(data, filename)

    for tl, idx in zip(batchTranslate(hosyuTxtS, "Reward Description"), hosyuTxtI):
        dgns[idx]["hosyuTxt"] = tl
    if hosyuTxtS:
        save_progress_json(data, filename)

    for tl, idx in zip(batchTranslate(firstHosyuTxtS, "First Clear Reward"), firstHosyuTxtI):
        dgns[idx]["firstHosyuTxt"] = tl
    if firstHosyuTxtS:
        save_progress_json(data, filename)

    for tl, idx in zip(batchTranslate(memoTxtS, "Memo Label"), memoTxtI):
        dgns[idx]["memoTxt"] = tl
    if memoTxtS:
        save_progress_json(data, filename)

    for tl, idx in zip(batchTranslate(appMemoTxtS, "App Memo"), appMemoTxtI):
        dgns[idx]["appMemoTxt"] = tl
    if appMemoTxtS:
        save_progress_json(data, filename)

    for tl, idx in zip(batchTranslate(areaMemoS, "Area Label"), areaMemoI):
        dgns[idx]["areaMemo"] = tl
    if areaMemoS:
        save_progress_json(data, filename)

    # -- Dungeon long text fields (with word wrap) --
    for tl, idx in zip(batchTranslate(naiyoTxtS, "Mission Description"), naiyoTxtI):
        dgns[idx]["naiyoTxt"] = dazedwrap.wrapText(tl, WIDTH)
    if naiyoTxtS:
        save_progress_json(data, filename)

    for tl, idx in zip(batchTranslate(naiyoTxtExS, "Extended Mission Description"), naiyoTxtExI):
        dgns[idx]["naiyoTxtEx"] = dazedwrap.wrapText(tl, WIDTH)
    if naiyoTxtExS:
        save_progress_json(data, filename)

    for tl, idx in zip(batchTranslate(johoTxtS, "Info Text"), johoTxtI):
        dgns[idx]["johoTxt"] = dazedwrap.wrapText(tl, WIDTH)
    if johoTxtS:
        save_progress_json(data, filename)

    for tl, idx in zip(batchTranslate(johoTxtExS, "Extended Info Text"), johoTxtExI):
        dgns[idx]["johoTxtEx"] = dazedwrap.wrapText(tl, WIDTH)
    if johoTxtExS:
        save_progress_json(data, filename)

    # -- Floor names --
    for tl, (di, ki) in zip(batchTranslate(kaisoNameS, "Floor Name"), kaisoNameI):
        dgns[di]["kaisoDatas"][ki]["kaisoName"] = tl
    if kaisoNameS:
        save_progress_json(data, filename)

    # -- Dialogue event names --
    for tl, (di, tk, ti) in zip(batchTranslate(talkNameS, "Event Label"), talkNameI):
        dgns[di][tk][ti]["name"] = tl
    if talkNameS:
        save_progress_json(data, filename)

    # -- Speaker names --
    for tl, (di, tk, ti, si) in zip(batchTranslate(speakerNameS, "Character Name"), speakerNameI):
        dgns[di][tk][ti]["speachDatas"][si]["name"] = tl
    if speakerNameS:
        save_progress_json(data, filename)

    # -- Dialogue text (with word wrap) --
    for tl, (di, tk, ti, si) in zip(batchTranslate(dialogueS, "Dialogue"), dialogueI):
        dgns[di][tk][ti]["speachDatas"][si]["text"] = dazedwrap.wrapText(tl, WIDTH)
    if dialogueS:
        save_progress_json(data, filename)

    # -- Choice event names --
    for tl, (di, si) in zip(batchTranslate(sijiNameS, "Event Name"), sijiNameI):
        dgns[di]["sijiDatas"][si]["name"] = tl
    if sijiNameS:
        save_progress_json(data, filename)

    # -- Choice text (with word wrap) --
    for tl, (di, si) in zip(batchTranslate(sijiChoiceS, "Choice Event Text"), sijiChoiceI):
        dgns[di]["sijiDatas"][si]["choiceSijiTxt"] = dazedwrap.wrapText(tl, WIDTH)
    if sijiChoiceS:
        save_progress_json(data, filename)

    return tokens


def translateGameSetting(data, filename):
    """Translate GameSetting JSON format (e.g. Nupu_GameSetting.json).
    
    Handles card data, deck definitions, and rental decks.
    Only translates player-visible text fields.
    """
    global LOCK, ESTIMATE, FILENAME, PBAR, MISMATCH
    tokens = [0, 0]

    def batchTranslate(stringList, context):
        """Translate a list of strings and return translations. Returns [] on mismatch."""
        nonlocal tokens
        if not stringList:
            return []
        response = translateAI(stringList, context, True)
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        if len(stringList) != len(response[0]):
            with LOCK:
                if FILENAME not in MISMATCH:
                    MISMATCH.append(FILENAME)
            return []
        return response[0]

    # ================================================================
    # PASS 1: Collect all translatable strings
    # ================================================================

    # -- fzCardDatas: card descriptions --
    desc1S, desc1I = [], []
    desc2S, desc2I = [], []

    if "fzCardDatas" in data:
        for i, card in enumerate(data["fzCardDatas"]):
            if card.get("desc1") and re.search(LANGREGEX, card["desc1"]):
                desc1S.append(card["desc1"].replace("\r\n", " ").replace("\n", " ").strip())
                desc1I.append(i)
            if card.get("desc2") and re.search(LANGREGEX, card["desc2"]):
                desc2S.append(card["desc2"].replace("\r\n", " ").replace("\n", " ").strip())
                desc2I.append(i)

    # -- fzDeckDatas: deck name and description --
    deckNameS, deckNameI = [], []
    deckDescS, deckDescI = [], []

    if "fzDeckDatas" in data:
        for i, deck in enumerate(data["fzDeckDatas"]):
            if deck.get("name") and re.search(LANGREGEX, deck["name"]):
                deckNameS.append(deck["name"])
                deckNameI.append(i)
            if deck.get("desc") and re.search(LANGREGEX, deck["desc"]):
                deckDescS.append(deck["desc"].replace("\r\n", " ").replace("\n", " ").strip())
                deckDescI.append(i)

    # -- rentalDecks: memo label --
    rentalMemoS, rentalMemoI = [], []

    if "rentalDecks" in data:
        for i, rental in enumerate(data["rentalDecks"]):
            if rental.get("memo") and re.search(LANGREGEX, rental["memo"]):
                rentalMemoS.append(rental["memo"])
                rentalMemoI.append(i)

    # Set progress bar total
    totalItems = (
        len(desc1S) + len(desc2S)
        + len(deckNameS) + len(deckDescS)
        + len(rentalMemoS)
    )
    PBAR.total = totalItems
    PBAR.refresh()

    # ================================================================
    # PASS 2: Translate each batch and apply results back to data
    # ================================================================

    # -- fzCardDatas --
    if "fzCardDatas" in data:
        cards = data["fzCardDatas"]

        for tl, idx in zip(batchTranslate(desc1S, "Card Description"), desc1I):
            cards[idx]["desc1"] = dazedwrap.wrapText(tl, WIDTH)
        if desc1S:
            save_progress_json(data, filename)

        for tl, idx in zip(batchTranslate(desc2S, "Card Description"), desc2I):
            cards[idx]["desc2"] = dazedwrap.wrapText(tl, WIDTH)
        if desc2S:
            save_progress_json(data, filename)

    # -- fzDeckDatas --
    if "fzDeckDatas" in data:
        decks = data["fzDeckDatas"]

        for tl, idx in zip(batchTranslate(deckNameS, "Deck Name"), deckNameI):
            decks[idx]["name"] = tl
        if deckNameS:
            save_progress_json(data, filename)

        for tl, idx in zip(batchTranslate(deckDescS, "Deck Description"), deckDescI):
            decks[idx]["desc"] = dazedwrap.wrapText(tl, WIDTH)
        if deckDescS:
            save_progress_json(data, filename)

    # -- rentalDecks --
    if "rentalDecks" in data:
        rentals = data["rentalDecks"]

        for tl, idx in zip(batchTranslate(rentalMemoS, "Deck Label"), rentalMemoI):
            rentals[idx]["memo"] = tl
        if rentalMemoS:
            save_progress_json(data, filename)

    return tokens


def translateJSON(data, filename, translatedList):
    global LOCK, ESTIMATE, FILENAME, PBAR, MISMATCH
    if translatedList:
        stringList = translatedList[0]
        eventList = translatedList[1]
    else:
        stringList = []
        eventList = [[], [], [], [], [], [], []]  # [title, process, text, key, target, job, place]
    tokens = [0, 0]
    speaker = ""
    i = 0
    stringListTL = []
    eventListTL = [[], [], [], [], [], [], []]

    while i < len(data):
        speakerKey = "character_nameText"
        messageKey = "m_text"

        # Event List Format - Key
        if "key" in data[i] and data[i]["key"]:
            jaString = data[i]["key"]
            
            # Pass 1
            if not translatedList:
                eventList[3].append(jaString.strip())
            
            # Pass 2
            else:
                if eventList[3]:
                    translatedText = eventList[3][0]
                    eventList[3].pop(0)
                    
                    # Set Data
                    data[i]["key"] = translatedText
                    save_progress_json(data, filename)

        # Event List Format - Title
        if "title" in data[i] and data[i]["title"]:
            jaString = data[i]["title"]
            
            # Pass 1
            if not translatedList:
                eventList[0].append(jaString.strip())
            
            # Pass 2
            else:
                if eventList[0]:
                    translatedText = eventList[0][0]
                    eventList[0].pop(0)
                    
                    # Set Data
                    data[i]["title"] = translatedText
                    save_progress_json(data, filename)

        # Event List Format - Target
        if "target" in data[i] and data[i]["target"]:
            jaString = data[i]["target"]
            
            # Pass 1
            if not translatedList:
                eventList[4].append(jaString.strip())
            
            # Pass 2
            else:
                if eventList[4]:
                    translatedText = eventList[4][0]
                    eventList[4].pop(0)
                    
                    # Set Data
                    data[i]["target"] = translatedText
                    save_progress_json(data, filename)

        # Event List Format - Job
        if "job" in data[i] and data[i]["job"]:
            jaString = data[i]["job"]
            
            # Pass 1
            if not translatedList:
                eventList[5].append(jaString.strip())
            
            # Pass 2
            else:
                if eventList[5]:
                    translatedText = eventList[5][0]
                    eventList[5].pop(0)
                    
                    # Set Data
                    data[i]["job"] = translatedText
                    save_progress_json(data, filename)

        # Event List Format - Place
        if "place" in data[i] and data[i]["place"]:
            jaString = data[i]["place"]
            
            # Pass 1
            if not translatedList:
                eventList[6].append(jaString.strip())
            
            # Pass 2
            else:
                if eventList[6]:
                    translatedText = eventList[6][0]
                    eventList[6].pop(0)
                    
                    # Set Data
                    data[i]["place"] = translatedText
                    save_progress_json(data, filename)

        # Event List Format - Process
        if "process" in data[i] and data[i]["process"]:
            jaString = data[i]["process"]
            
            # Pass 1
            if not translatedList:
                eventList[1].append(jaString.strip())
            
            # Pass 2
            else:
                if eventList[1]:
                    translatedText = eventList[1][0]
                    eventList[1].pop(0)
                    
                    # Set Data
                    data[i]["process"] = translatedText
                    save_progress_json(data, filename)

        # Event List Format - Text
        if "text" in data[i] and data[i]["text"]:
            jaString = data[i]["text"]
            # Pass 1
            if not translatedList:
                # Replace \n with space for translation
                jaStringClean = jaString.replace("\n", " ")
                eventList[2].append(jaStringClean.strip())
            
            # Pass 2
            else:
                if eventList[2]:
                    translatedText = eventList[2][0]
                    eventList[2].pop(0)
                    
                    # Apply text wrapping and restore linebreaks
                    translatedText = dazedwrap.wrapText(translatedText, 70)
                    
                    # Set Data
                    data[i]["text"] = translatedText
                    save_progress_json(data, filename)

        # Speaker
        if speakerKey in data[i] and data[i][speakerKey]:
            # Grab and TL
            speaker = data[i][speakerKey]
            response = getSpeaker(speaker)
            speaker = response[0]
            tokens[0] += response[1][0]
            tokens[1] += response[1][1]

            # Set Speaker
            data[i][speakerKey] = speaker

        # Dialogue
        if messageKey in data[i]\
            and data[i][messageKey].strip()\
            and data[i][messageKey] != "a"\
            and data[i][messageKey].replace("\u3000", "").strip() != "":
            jaString = data[i][messageKey]

            # Save Original String
            originalString = jaString

            # If there isn't any Japanese in the text just skip
            if not re.search(LANGREGEX, jaString):
                i += 1
                continue

            # Pass 1
            if not translatedList:
                # Strip Spaces
                jaString = jaString.strip()

                # Remove Textwrap
                # jaString = jaString.replace('\n', ' ')

                if jaString:
                    if speaker:
                        stringList.append(f"[{speaker}]: {jaString}")
                    else:
                        stringList.append(jaString)

            # Pass 2
            else:
                # Get Text
                if stringList:
                    # Grab and Pop
                    translatedText = stringList[0]
                    stringList.pop(0)

                    # Set to None if empty list
                    if len(stringList) <= 0:
                        stringList = None

                    # Remove speaker
                    match = re.search(r'(^\[.+?\]\s?[|:]\s?)', translatedText)
                    if match:
                        translatedText = translatedText.replace(match.group(1), "") 

                    # Escape Quotes
                    translatedText = re.sub(r'(?<!\\)"', r"", translatedText)

                    # Remove characters that may break scripts
                    # translatedText = translatedText.replace("<", "(")
                    # translatedText = translatedText.replace(">", ")")
                    translatedText = translatedText.replace("『", "")
                    translatedText = translatedText.replace("』", "")

                    # Remove GPT ' Quotes
                    if translatedText:
                        if translatedText[0] == "'":
                            translatedText = translatedText[1:]
                        if translatedText[-1] == "'":
                            translatedText = translatedText[:-1]
                    else:
                        print("Warning: Empty Translation for", originalString)

                    # Textwrap
                    # translatedText = dazedwrap.wrapText(translatedText, width=WIDTH)  
                    
                    # Set Data
                    if "『" in data[i][messageKey] and "』" not in translatedText:
                        data[i][messageKey] = data[i][messageKey].replace(originalString, f"『{translatedText}』")
                    else:
                        data[i][messageKey] = data[i][messageKey].replace(originalString, f"{translatedText}")

                    # Save progress after each message replacement
                    save_progress_json(data, filename)
        # Next Value
        i += 1       

    # EOF - Only do translation if this is Pass 1 (collecting strings)
    if not translatedList:
        # Event List
        if any(eventList):
            PBAR.total = sum(len(event) for event in eventList)
            PBAR.refresh()
            
            # Event Title
            if eventList[0]:
                response = translateAI(eventList[0], "Event Title", True)
                tokens[0] += response[1][0]
                tokens[1] += response[1][1]
                eventListTL[0] = response[0]
                
                if len(eventList[0]) != len(eventListTL[0]):
                    with LOCK:
                        if FILENAME not in MISMATCH:
                            MISMATCH.append(FILENAME)

            # Event Process
            if eventList[1]:
                response = translateAI(eventList[1], "Event Process", True)
                tokens[0] += response[1][0]
                tokens[1] += response[1][1]
                eventListTL[1] = response[0]
                
                if len(eventList[1]) != len(eventListTL[1]):
                    with LOCK:
                        if FILENAME not in MISMATCH:
                            MISMATCH.append(FILENAME)

            # Event Text
            if eventList[2]:
                response = translateAI(eventList[2], "Event Description", True)
                tokens[0] += response[1][0]
                tokens[1] += response[1][1]
                eventListTL[2] = response[0]
                
                if len(eventList[2]) != len(eventListTL[2]):
                    with LOCK:
                        if FILENAME not in MISMATCH:
                            MISMATCH.append(FILENAME)

            # Event Key
            if eventList[3]:
                response = translateAI(eventList[3], "Event Key", True)
                tokens[0] += response[1][0]
                tokens[1] += response[1][1]
                eventListTL[3] = response[0]
                
                if len(eventList[3]) != len(eventListTL[3]):
                    with LOCK:
                        if FILENAME not in MISMATCH:
                            MISMATCH.append(FILENAME)

            # Event Target
            if eventList[4]:
                response = translateAI(eventList[4], "Character Name", True)
                tokens[0] += response[1][0]
                tokens[1] += response[1][1]
                eventListTL[4] = response[0]
                
                if len(eventList[4]) != len(eventListTL[4]):
                    with LOCK:
                        if FILENAME not in MISMATCH:
                            MISMATCH.append(FILENAME)

            # Event Job
            if eventList[5]:
                response = translateAI(eventList[5], "Job/Occupation", True)
                tokens[0] += response[1][0]
                tokens[1] += response[1][1]
                eventListTL[5] = response[0]
                
                if len(eventList[5]) != len(eventListTL[5]):
                    with LOCK:
                        if FILENAME not in MISMATCH:
                            MISMATCH.append(FILENAME)

            # Event Place
            if eventList[6]:
                response = translateAI(eventList[6], "Location Name", True)
                tokens[0] += response[1][0]
                tokens[1] += response[1][1]
                eventListTL[6] = response[0]
                
                if len(eventList[6]) != len(eventListTL[6]):
                    with LOCK:
                        if FILENAME not in MISMATCH:
                            MISMATCH.append(FILENAME)

        # String List
        if stringList:
            PBAR.total = len(stringList)
            PBAR.refresh()
            response = translateAI(stringList, "Reply with the English Translation", True)
            tokens[0] += response[1][0]
            tokens[1] += response[1][1]
            stringListTL = response[0]

            if len(stringList) != len(stringListTL):
                # Mismatch
                with LOCK:
                    if FILENAME not in MISMATCH:
                        MISMATCH.append(FILENAME)

        # Pass 2: Set Strings (recursive call)
        translateJSON(data, filename, [stringListTL, eventListTL])
    
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
