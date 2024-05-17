# Libraries
import json, os, re, textwrap, threading, time, traceback, tiktoken, openai, csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from colorama import Fore
from dotenv import load_dotenv
from retry import retry
from tqdm import tqdm

# Open AI
load_dotenv()
if os.getenv('api').replace(' ', '') != '':
    openai.base_url = os.getenv('api')
openai.organization = os.getenv('org')
openai.api_key = os.getenv('key')

#Globals
MODEL = os.getenv('model')
TIMEOUT = int(os.getenv('timeout'))
LANGUAGE = os.getenv('language').capitalize()
PROMPT = Path('prompt.txt').read_text(encoding='utf-8')
VOCAB = Path('vocab.txt').read_text(encoding='utf-8')
THREADS = int(os.getenv('threads'))
LOCK = threading.Lock()
WIDTH = int(os.getenv('width'))
LISTWIDTH = int(os.getenv('listWidth'))
NOTEWIDTH = int(os.getenv('noteWidth'))
MAXHISTORY = 10
ESTIMATE = ''
TOKENS = [0, 0]
NAMESLIST = []
NAMES = False    # Output a list of all the character names found
BRFLAG = False   # If the game uses <br> instead
FIXTEXTWRAP = True  # Overwrites textwrap
IGNORETLTEXT = True    # Ignores all translated text.
MISMATCH = []   # Lists files that thdata a mismatch error (Length of GPT list response is wrong)
BRACKETNAMES = False

# Pricing - Depends on the model https://openai.com/pricing
# Batch Size - GPT 3.5 Struggles past 15 lines per request. GPT4 struggles past 50 lines per request
# If you are getting a MISMATCH LENGTH error, lower the batch size.
if 'gpt-3.5' in MODEL:
    INPUTAPICOST = .002 
    OUTPUTAPICOST = .002
    BATCHSIZE = 10
    FREQUENCY_PENALTY = 0.2
elif 'gpt-4' in MODEL:
    INPUTAPICOST = .005
    OUTPUTAPICOST = .015
    BATCHSIZE = 40
    FREQUENCY_PENALTY = 0.1

#tqdm Globals
BAR_FORMAT='{l_bar}{bar:10}{r_bar}{bar:-10b}'
POSITION = 0
LEAVE = False

def handleCSV(filename, estimate):
    global ESTIMATE, TOKENS
    ESTIMATE = estimate

    if not ESTIMATE:
        with open('translated/' + filename, 'w+t', newline='', encoding='utf-8') as writeFile:
            # Translate
            start = time.time()
            translatedData = openFiles(filename, writeFile)
            
            # Print Result
            end = time.time()
            tqdm.write(getResultString(translatedData, end - start, filename))
            with LOCK:
                TOKENS[0] += translatedData[1][0]
                TOKENS[1] += translatedData[1][1]
    else:
        # Translate
        start = time.time()
        translatedData = openFilesEstimate(filename)
        
        # Print Result
        end = time.time()
        tqdm.write(getResultString(translatedData, end - start, filename))
        with LOCK:
            TOKENS[0] += translatedData[1][0]
            TOKENS[1] += translatedData[1][1]


    # Print Total
    totalString = getResultString(['', TOKENS, None], end - start, 'TOTAL')

    # Print any errors on maps
    if len(MISMATCH) > 0:
        return totalString + Fore.RED + f'\nMismatch Errors: {MISMATCH}' + Fore.RESET
    else:
        return totalString

def openFiles(filename, writeFile):
    with open('files/' + filename, 'r', encoding='utf-8') as readFile, writeFile:
        translatedData = parseCSV(readFile, writeFile, filename)

    return translatedData

def openFilesEstimate(filename):
    with open('files/' + filename, 'r', encoding='utf-8') as readFile:
        translatedData = parseCSV(readFile, '', filename)

    return translatedData

def getResultString(translatedData, translationTime, filename):
    # File Print String
    totalTokenstring =\
        Fore.YELLOW +\
        '[Input: ' + str(translatedData[1][0]) + ']'\
        '[Output: ' + str(translatedData[1][1]) + ']'\
        '[Cost: ${:,.4f}'.format((translatedData[1][0] * .001 * INPUTAPICOST) +\
        (translatedData[1][1] * .001 * OUTPUTAPICOST)) + ']'
    timeString = Fore.BLUE + '[' + str(round(translationTime, 1)) + 's]'

    if translatedData[2] is None:
        # Success
        return filename + ': ' + totalTokenstring + timeString + Fore.GREEN + u' \u2713 ' + Fore.RESET
    else:
        # Fail
        try:
            raise translatedData[2]
        except Exception as e:
            traceback.print_exc()
            errorString = str(e) + Fore.RED
            return filename + ': ' + totalTokenstring + timeString + Fore.RED + u' \u2717 ' +\
                errorString + Fore.RESET
        
def parseCSV(readFile, writeFile, filename):
    totalTokens = [0,0]
    totalLines = 0
    textHistory = []
    global LOCK

    format = ''
    while format == '':
        format = input('\n\nSelect the CSV Format:\n\n1. Translator++\n2. Translate All (Depreciated)\n')
        match format:
            case '1':
                format = '1'
            case '2':
                format = '2'

    # Get total for progress bar
    totalLines = len(readFile.readlines())
    readFile.seek(0)

    reader = csv.reader(readFile, delimiter=',',)
    if not ESTIMATE:
        writer = csv.writer(writeFile, delimiter=',', quotechar='\"')
    else:
        writer = ''

    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
        pbar.desc=filename
        pbar.total=totalLines
        try:
            response = translateCSV(reader, pbar, writer, textHistory, format)
            totalTokens[0] = response[0]
            totalTokens[1] = response[1]
        except Exception as e:
            traceback.print_exc()
    return [reader, totalTokens, None]

def translateCSV(reader, pbar, writer, textHistory, format):
    translatedText = ''
    maxHistory = MAXHISTORY
    totalTokens = [0,0]
    global LOCK, ESTIMATE
    data = []
    batch = []
    i = 0

    try:
        # Grab All Rows
        for row in reader:
            data.append(row)

        # Batch
        while i < len(data):
            if len(batch) < BATCHSIZE:
                if 'Original Text' not in data[i]:
                    batch.append(data[i])
                pbar.update(1)
                i += 1
            else:
                match format:
                    # T++ Format: Japanese Text on column 1. English on Column 2
                    case '1':
                        # Put in Payload
                        payload = []
                        for row in batch:
                            if row[1] == "":
                                jaString = row[0]
                            # else:
                            #     jaString = row[]

                            # Remove Textwrap
                            jaString = jaString.replace('\n', ' ')
                            payload.append(jaString)

                        # Translate
                        response = translateGPT(payload, textHistory, True)
                        translatedTextList = response[0]
                        totalTokens[0] = response[1][0]
                        totalTokens[1] = response[1][1]

                        # MISMATCH
                        if len(translatedTextList) != len(payload):
                            pbar.write(f'Mismatch Error: {i-len(batch)}-{i}')
                            batch.clear()
                            continue

                        # Set Data
                        j = i - BATCHSIZE
                        for row in translatedTextList:
                            row = row.replace('"', '\\"')
                            row = row.replace(',', '\,')
                            data[j][1] = row
                            j += 1
                        batch.clear()
                        
                    # Translate Everything
                    case '2':
                        for i in range(len(data)):
                            # This will allow you to ignore certain columns
                            if i not in [1]:
                                continue
                            jaString = data[i]
                            matchList = re.findall(r':name\[(.+?),.+?\](.+?[」）\"。]+)', jaString)

                            # Start Translation
                            if len(matchList) > 0:
                                for match in matchList:
                                    speaker = match[0]
                                    text = match[1]

                                    # Translate Speaker
                                    response = translateGPT (speaker, 'Reply with the '+ LANGUAGE +' translation of the NPC name.', True)
                                    translatedSpeaker = response[0]
                                    totalTokens += response[1][0]
                                    totalTokens += response[1][1]

                                    # Translate Line
                                    jaText = re.sub(r'([\u3000-\uffef])\1{3,}', r'\1\1\1', text)
                                    response = translateGPT(translatedSpeaker + ': ' + jaText, 'Previous Translated Text: ' + '|'.join(textHistory), True)
                                    translatedText = response[0]
                                    totalTokens[0] += response[1][0]
                                    totalTokens[1] += response[1][1]

                                    # TextHistory is what we use to give GPT Context, so thats appended here.
                                    textHistory.append(translatedText)

                                    # Remove Speaker from translated text
                                    translatedText = re.sub(r'.+?: ', '', translatedText)

                                    # Set Data
                                    translatedSpeaker = translatedSpeaker.replace('\"', '')
                                    translatedText = translatedText.replace('\"', '')
                                    translatedText = translatedText.replace('「', '')
                                    translatedText = translatedText.replace('」', '')
                                    data[i] = data[i].replace('\n', ' ')

                                    # Textwrap
                                    translatedText = textwrap.fill(translatedText, width=WIDTH)

                                    translatedText = '「' + translatedText + '」'
                                    data[i] = re.sub(rf':name\[({re.escape(speaker)}),', f':name[{translatedSpeaker},', data[i])
                                    data[i] = data[i].replace(text, translatedText)

                                    # Keep History at fixed length.
                                    with LOCK:
                                        if len(textHistory) > maxHistory:
                                            textHistory.pop(0)

                            with LOCK:
                                if not ESTIMATE:
                                    writer.writerow(data)
                        pbar.update(1)

        # Leftovers
        if format == '1':
            # Put in Payload
            payload = []
            for row in batch:
                if row[1] == "":
                    jaString = row[0]
                else:
                    continue

                # Remove Textwrap
                jaString = jaString.replace('\n', ' ')
                payload.append(jaString)

            # Translate
            response = translateGPT(payload, textHistory, True)
            translatedTextList = response[0]
            totalTokens[0] = response[1][0]
            totalTokens[1] = response[1][1]

            # MISMATCH
            if len(translatedTextList) != len(payload):
                pbar.write(f'Mismatch Error: {i-BATCHSIZE}-{i}')
                batch.clear()
            else:
                # Set Data
                j = i - len(batch)
                for row in translatedTextList:
                    row = row.replace('"', '\\"')
                    row = row.replace(',', '\,')
                    data[j][1] = row
                    j += 1
                batch.clear()

        # Write all Data
        with LOCK:
            if not ESTIMATE:
                for row in data:
                    writer.writerow(row)

    except Exception as e:
        traceback.print_exc()
    
    return totalTokens
    

def subVars(jaString):
    jaString = jaString.replace('\u3000', ' ')

    # Nested
    count = 0
    nestedList = re.findall(r'[\\]+[\w]+\[[\\]+[\w]+\[[0-9]+\]\]', jaString)
    nestedList = set(nestedList)
    if len(nestedList) != 0:
        for icon in nestedList:
            jaString = jaString.replace(icon, '{Nested_' + str(count) + '}')
            count += 1

    # Icons
    count = 0
    iconList = re.findall(r'[\\]+[iIkKwWaA]+\[[0-9]+\]', jaString)
    iconList = set(iconList)
    if len(iconList) != 0:
        for icon in iconList:
            jaString = jaString.replace(icon, '{Ascii_' + str(count) + '}')
            count += 1

    # Colors
    count = 0
    colorList = re.findall(r'[\\]+[cC]\[[0-9]+\]', jaString)
    colorList = set(colorList)
    if len(colorList) != 0:
        for color in colorList:
            jaString = jaString.replace(color, '{Color_' + str(count) + '}')
            count += 1

    # Names
    count = 0
    nameList = re.findall(r'[\\]+[nN]\[.+?\]+', jaString)
    nameList = set(nameList)
    if len(nameList) != 0:
        for name in nameList:
            jaString = jaString.replace(name, '{Noun_' + str(count) + '}')
            count += 1

    # Variables
    count = 0
    varList = re.findall(r'[\\]+[vV]\[[0-9]+\]', jaString)
    varList = set(varList)
    if len(varList) != 0:
        for var in varList:
            jaString = jaString.replace(var, '{Var_' + str(count) + '}')
            count += 1

    # Formatting
    count = 0
    formatList = re.findall(r'[\\]+[\w]+\[.+?\]', jaString)
    formatList = set(formatList)
    if len(formatList) != 0:
        for var in formatList:
            jaString = jaString.replace(var, '{FCode_' + str(count) + '}')
            count += 1

    # Put all lists in list and return
    allList = [nestedList, iconList, colorList, nameList, varList, formatList]
    return [jaString, allList]

def resubVars(translatedText, allList):
    # Fix Spacing and ChatGPT Nonsense
    matchList = re.findall(r'\[\s?.+?\s?\]', translatedText)
    if len(matchList) > 0:
        for match in matchList:
            text = match.strip()
            translatedText = translatedText.replace(match, text)

    # Nested
    count = 0
    if len(allList[0]) != 0:
        for var in allList[0]:
            translatedText = translatedText.replace('{Nested_' + str(count) + '}', var)
            count += 1

    # Icons
    count = 0
    if len(allList[1]) != 0:
        for var in allList[1]:
            translatedText = translatedText.replace('{Ascii_' + str(count) + '}', var)
            count += 1

    # Colors
    count = 0
    if len(allList[2]) != 0:
        for var in allList[2]:
            translatedText = translatedText.replace('{Color_' + str(count) + '}', var)
            count += 1

    # Names
    count = 0
    if len(allList[3]) != 0:
        for var in allList[3]:
            translatedText = translatedText.replace('{Noun_' + str(count) + '}', var)
            count += 1

    # Vars
    count = 0
    if len(allList[4]) != 0:
        for var in allList[4]:
            translatedText = translatedText.replace('{Var_' + str(count) + '}', var)
            count += 1
    
    # Formatting
    count = 0
    if len(allList[5]) != 0:
        for var in allList[5]:
            translatedText = translatedText.replace('{FCode_' + str(count) + '}', var)
            count += 1

    return translatedText

def batchList(input_list, batch_size):
    if not isinstance(batch_size, int) or batch_size <= 0:
        raise ValueError("batch_size must be a positive integer")
        
    return [input_list[i:i + batch_size] for i in range(0, len(input_list), batch_size)]

def createContext(fullPromptFlag, subbedT):
    characters = 'Game Characters:\n\
ミオリ (Miori) - Female\n\
'
    
    system = PROMPT if fullPromptFlag else \
        f"\
You are an expert Eroge Game translator who translates Japanese text to English.\n\
You are going to be translating text from a videogame.\n\
I will give you lines of text, and you must translate each line to the best of your ability.\n\
- Translate 'マンコ' as 'pussy'\n\
- Translate 'おまんこ' as 'pussy'\n\
- Translate 'お尻' as 'butt'\n\
- Translate '尻' as 'ass'\n\
- Translate 'お股' as 'crotch'\n\
- Translate '秘部' as 'genitals'\n\
- Translate 'チンポ' as 'dick'\n\
- Translate 'チンコ' as 'cock'\n\
- Translate 'ショーツ' as 'panties\n\
- Translate 'おねショタ' as 'Onee-shota'\n\
- Translate 'よかった' as 'thank goodness'\n\
Output ONLY the {LANGUAGE} translation in the following format: `Translation: <{LANGUAGE.upper()}_TRANSLATION>`\
"
    user = f'{subbedT}'
    return characters, system, user

def translateText(characters, system, user, history):
    # Prompt
    msg = [{"role": "system", "content": system + characters}]

    # Characters
    msg.append({"role": "system", "content": characters})

    # History
    if isinstance(history, list):
        msg.extend([{"role": "assistant", "content": h} for h in history])
    else:
        msg.append({"role": "assistant", "content": history})
    
    # Content to TL
    msg.append({"role": "user", "content": f'{user}'})
    response = openai.chat.completions.create(
        temperature=0.1,
        frequency_penalty=0.1,
        presence_penalty=0.1,
        model=MODEL,
        messages=msg,
    )
    return response

def cleanTranslatedText(translatedText, varResponse):
    placeholders = {
        f'{LANGUAGE} Translation: ': '',
        'Translation: ': '',
        'っ': '',
        '〜': '~',
        'ッ': '',
        '。': '.',
        'Placeholder Text': ''
        # Add more replacements as needed
    }
    for target, replacement in placeholders.items():
        translatedText = translatedText.replace(target, replacement)

    translatedText = resubVars(translatedText, varResponse[1])
    return [line for line in translatedText.replace('\\n', '\n').split('\n') if line]

def extractTranslation(translatedTextList, is_list):
    pattern = r'`?<Line(\d+)>([\\]*.*?[\\]*?)<\/?Line\d+>`?'
    # If it's a batch (i.e., list), extract with tags; otherwise, return the single item.
    if is_list:
        return [re.findall(pattern, line)[0][1] for line in translatedTextList if re.search(pattern, line)]
    else:
        matchList = re.findall(pattern, translatedTextList)
        return matchList[0][1] if matchList else translatedTextList

def countTokens(characters, system, user, history):
    inputTotalTokens = 0
    outputTotalTokens = 0
    enc = tiktoken.encoding_for_model('gpt-4')
    
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
    outputTotalTokens += round(len(enc.encode(user))*3)

    return [inputTotalTokens, outputTotalTokens]

def combineList(tlist, text):
    if isinstance(text, list):
        return [t for sublist in tlist for t in sublist]
    return tlist[0]

@retry(exceptions=Exception, tries=5, delay=5)
def translateGPT(text, history, fullPromptFlag):
    totalTokens = [0, 0]
    if isinstance(text, list):
        tList = batchList(text, BATCHSIZE)
    else:
        tList = [text]

    for index, tItem in enumerate(tList):
        # Before sending to translation, if we have a list of items, add the formatting
        if isinstance(tItem, list):
            payload = '\n'.join([f'`<Line{i}>{item}</Line{i}>`' for i, item in enumerate(tItem)])
            payload = payload.replace('``', '`Placeholder Text`')
            varResponse = subVars(payload)
            subbedT = varResponse[0]
        else:
            varResponse = subVars(tItem)
            subbedT = varResponse[0]

        # Things to Check before starting translation
        if not re.search(r'[一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９]+', subbedT):
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
        response = translateText(characters, system, user, history)
        translatedText = response.choices[0].message.content
        totalTokens[0] += response.usage.prompt_tokens
        totalTokens[1] += response.usage.completion_tokens

        # Formatting
        translatedTextList = cleanTranslatedText(translatedText, varResponse)
        if isinstance(tItem, list):
            extractedTranslations = extractTranslation(translatedTextList, True)
            tList[index] = extractedTranslations
            if len(tItem) != len(translatedTextList):
                mismatch = True     # Just here so breakpoint can be set
            history = extractedTranslations[-10:]  # Update history if we have a list
        else:
            # Ensure we're passing a single string to extractTranslation
            extractedTranslations = extractTranslation('\n'.join(translatedTextList), False)
            tList[index] = extractedTranslations

    finalList = combineList(tList, text)
    return [finalList, totalTokens]