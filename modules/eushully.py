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
FORMATONLY = False # Only format text, no translation
MISMATCH = []   # Lists files that thdata a mismatch error (Length of GPT list response is wrong)
FILENAME = ''
BRACKETNAMES = False
TOTALLINES = 0
PBAR = None

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
    BATCHSIZE = 20
    FREQUENCY_PENALTY = 0.1

#tqdm Globals
BAR_FORMAT='{l_bar}{bar:10}{r_bar}{bar:-10b}'
POSITION = 0
LEAVE = False

def handleEushully(filename, estimate):
    global ESTIMATE, TOKENS, FILENAME
    ESTIMATE = estimate
    FILENAME = filename

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
        '[Lines: ' + str(TOTALLINES) + ']'\
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

    # Get total for progress bar
    totalLines = len(readFile.readlines())
    readFile.seek(0)
    data = []

    reader = csv.reader(readFile, delimiter=',',)
    if not ESTIMATE:
        writer = csv.writer(writeFile, delimiter=',', quoting=csv.QUOTE_STRINGS)
    else:
        writer = ''

    # Write All Rows to Data
    for row in reader:
        data.append(row)

    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
        pbar.desc=filename
        pbar.total=totalLines
        try:
            if 'SC' == filename[0:2] or 'SP' == filename[0:2]:
                response = translateDialogue(data, pbar, writer, format, filename, [])
                totalTokens[0] = response[0]
                totalTokens[1] = response[1]
            elif 'UI' == filename[0:2]:
                response = translateUI(data, pbar, writer, format, filename, [])
                totalTokens[0] = response[0]
                totalTokens[1] = response[1]
        except Exception as e:
            traceback.print_exc()
    return [reader, totalTokens, None]

def translateDialogue(data, pbar, writer, format, filename, translatedList):
    global LOCK, ESTIMATE, PBAR
    tokens = [0,0]
    stringList = [None] * 2
    i = 0

    try:
        # Set Variables
        speakerColumn = 0
        textSourceColumn = 1
        textTargetColumn = 3
        previousString = ''

        # Lists
        dialogueList = []
        setStringList = []

        # Parse Data
        while i in range(len(data)):
            # Dialogue
            if len(data[i][speakerColumn]) > 0 and data[i][speakerColumn][0].isupper() \
            or 'show-text' in data[i][speakerColumn] \
            or 'concat' in data[i][speakerColumn]:
                # Speaker
                speaker = ''
                if data[i][speakerColumn][0].isupper():
                    if speakerColumn != None:
                        response = getSpeaker(data[i][speakerColumn])
                        tokens[0] += response[1][0]
                        tokens[1] += response[1][1]
                        speaker = response[0]
                
                # Dialogue
                jaString = data[i][textSourceColumn]
                
                # Replace Unicode
                jaString = jaString.replace('\ue000', '...')

                # Pass 1
                if translatedList == []:
                    # Check if Dupe
                    if previousString == data[i][textSourceColumn]:
                        i += 1
                        continue

                    # Add to list
                    if speaker:
                        dialogueList.append(f'[{speaker}]: {jaString}')
                    else:
                        dialogueList.append(f'[InnerVoice]: {jaString}')
                    previousString = jaString
                    stringList[0] = dialogueList

                # Pass 2
                else:
                    if translatedList[0]:
                        # Check if Dupe
                        if previousString == data[i][textSourceColumn]:
                            while len(data[i]) < 4:
                                data[i].append(None)
                            data[i][textTargetColumn] = data[i-1][textTargetColumn]
                            i += 1
                            continue

                        # Grab and Pop
                        translatedText = translatedList[0][0]
                        translatedList[0].pop(0)

                        # Set to None if empty list
                        if len(translatedList[0]) <= 0:
                            translatedList[0] = None

                        # Remove speaker
                        translatedText = re.sub(r'^\[(.+?)\]\s?[|:]\s?', '', translatedText)

                        # Replace Quotes
                        translatedText = translatedText.replace('"', "'")

                        # Set Data
                        while len(data[i]) < 4:
                            data[i].append(None)
                        previousString = jaString
                        data[i][textTargetColumn] = f'{translatedText}'
            
            # Set String Command
            if 'set-string' in data[i][speakerColumn]:
                jaString = data[i][textSourceColumn]
                
                # Pass 1
                if translatedList == []:
                    setStringList.append(jaString)
                    stringList[1] = setStringList

                # Pass 2
                else:
                    if len(translatedList) > 1:
                        index = 1
                    else:
                        index = 0
                    # Grab and Pop
                    translatedText = translatedList[index][0]
                    translatedList[index].pop(0)

                    # Set to None if empty list
                    if len(translatedList[index]) <= 0:
                        translatedList[index] = -1
                    
                    # Set Data
                    while len(data[i]) < 4:
                        data[i].append(None)
                    data[i][textTargetColumn] = f'{translatedText}'

            # Iterate
            i += 1

        # EOF
        stringList = [x for x in stringList if x is not None]
        if len(stringList) > 0:  
            # Translate
            pbar.total = 0
            for i in range(len(stringList)):
                # Set Progress
                pbar.total += len(stringList[i])
                pbar.refresh()
                PBAR = pbar
                response = translateGPT(stringList[i], '', True)
                tokens[0] += response[1][0]
                tokens[1] += response[1][1]
                translatedList.append(response[0])

            # Set Strings
            if len(stringList) == len(translatedList):
                translateDialogue(data, pbar, writer, format, filename, translatedList)
        else:
            # Write all Data
            with LOCK:
                if not ESTIMATE:
                    for row in data:
                        writer.writerow(row)

    except Exception as e:
        traceback.print_exc()
    
    return tokens

def translateUI(data, pbar, writer, format, filename, translatedList):
    global LOCK, ESTIMATE
    tokens = [0,0]
    stringList = [None] * 1
    i = 0

    try:
        # Lists
        textList = []

        # Parse Data
        while i in range(len(data)):
            # Text
            for j in range(len(data[i])):
                jaString = data[i][j]

                # If Japanese Text, Translate it.
                if not re.search(r'[一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９]+', jaString):
                    continue
            
                # Replace Unicode
                jaString = jaString.replace('', '...')

                # Pass 1
                if translatedList == []:
                    # Add to list
                    textList.append(f'{jaString}')
                    stringList[0] = textList

                # Pass 2
                else:
                    if translatedList[0]:
                        # Grab and Pop
                        translatedText = translatedList[0][0]
                        translatedList[0].pop(0)

                        # Set to None if empty list
                        if len(translatedList[0]) <= 0:
                            translatedList[0] = None

                        # Replace Quotes
                        translatedText = translatedText.replace('"', "'")

                        # Set Data
                        if len(data[i]) > j + 1:
                            data[i][j+1] = f'{translatedText}'

            # Iterate
            i += 1

        # EOF
        stringList = [x for x in stringList if x is not None]
        if len(stringList) > 0:  
            # Translate
            pbar.total = 0
            for i in range(len(stringList)):
                # Set Progress
                pbar.total += len(stringList[i])
                pbar.refresh()
                response = translateGPT(stringList[i], '', True)
                tokens[0] += response[1][0]
                tokens[1] += response[1][1]
                translatedList.append(response[0])

            # Set Strings
            if len(stringList) == len(translatedList):
                translateUI(data, pbar, writer, format, filename, translatedList)

        # Write all Data
            with LOCK:
                if not ESTIMATE:
                    for row in data:
                        writer.writerow(row)

    except Exception as e:
        traceback.print_exc()
    
    return tokens
    

# Save some money and enter the character before translation
def getSpeaker(speaker):
    match speaker:
        case 'ファイン':
            return ['Fine', [0,0]]
        case '':
            return ['', [0,0]]
        case _:
            # Store Speaker
            if speaker not in str(NAMESLIST):
                response = translateGPT(speaker, 'Reply with only the '+ LANGUAGE +' translation of the NPC name.', False)
                response[0] = response[0].replace("'S", "'s")
                speakerList = [speaker, response[0]]
                NAMESLIST.append(speakerList)
                return response
            
            # Find Speaker
            else:
                for i in range(len(NAMESLIST)):
                    if speaker == NAMESLIST[i][0]:
                        return [NAMESLIST[i][1],[0,0]]
                               
    return [speaker,[0,0]]

def subVars(jaString):
    jaString = jaString.replace('\u3000', ' ')

    # Nested
    count = 0
    nestedList = re.findall(r'[\\]+[\w]+\[[\\]+[\w]+\[[0-9]+\]\]', jaString)
    nestedList = set(nestedList)
    if len(nestedList) != 0:
        for icon in nestedList:
            jaString = jaString.replace(icon, '[Nested_' + str(count) + ']')
            count += 1

    # Icons
    count = 0
    iconList = re.findall(r'[\\]+[iIkKwWaA]+\[[0-9]+\]', jaString)
    iconList = set(iconList)
    if len(iconList) != 0:
        for icon in iconList:
            jaString = jaString.replace(icon, '[Ascii_' + str(count) + ']')
            count += 1

    # Colors
    count = 0
    colorList = re.findall(r'[\\]+[cC]\[[0-9]+\]', jaString)
    colorList = set(colorList)
    if len(colorList) != 0:
        for color in colorList:
            jaString = jaString.replace(color, '[Color_' + str(count) + ']')
            count += 1

    # Names
    count = 0
    nameList = re.findall(r'[\\]+[nN]\[.+?\]+', jaString)
    nameList = set(nameList)
    if len(nameList) != 0:
        for name in nameList:
            jaString = jaString.replace(name, '[Noun_' + str(count) + ']')
            count += 1

    # Variables
    count = 0
    varList = re.findall(r'[\\]+[vV]\[[0-9]+\]', jaString)
    varList = set(varList)
    if len(varList) != 0:
        for var in varList:
            jaString = jaString.replace(var, '[Var_' + str(count) + ']')
            count += 1

    # Formatting
    count = 0
    formatList = re.findall(r'[\\]+[\w]+\[[a-zA-Z0-9\\\[\]\_,\s-]+\]', jaString)
    formatList = set(formatList)
    if len(formatList) != 0:
        for var in formatList:
            jaString = jaString.replace(var, '[FCode_' + str(count) + ']')
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
            translatedText = translatedText.replace('[Nested_' + str(count) + ']', var)
            count += 1

    # Icons
    count = 0
    if len(allList[1]) != 0:
        for var in allList[1]:
            translatedText = translatedText.replace('[Ascii_' + str(count) + ']', var)
            count += 1

    # Colors
    count = 0
    if len(allList[2]) != 0:
        for var in allList[2]:
            translatedText = translatedText.replace('[Color_' + str(count) + ']', var)
            count += 1

    # Names
    count = 0
    if len(allList[3]) != 0:
        for var in allList[3]:
            translatedText = translatedText.replace('[Noun_' + str(count) + ']', var)
            count += 1

    # Vars
    count = 0
    if len(allList[4]) != 0:
        for var in allList[4]:
            translatedText = translatedText.replace('[Var_' + str(count) + ']', var)
            count += 1
    
    # Formatting
    count = 0
    if len(allList[5]) != 0:
        for var in allList[5]:
            translatedText = translatedText.replace('[FCode_' + str(count) + ']', var)
            count += 1

    return translatedText

def batchList(input_list, batch_size):
    if not isinstance(batch_size, int) or batch_size <= 0:
        raise ValueError("batch_size must be a positive integer")
        
    return [input_list[i:i + batch_size] for i in range(0, len(input_list), batch_size)]

def createContext(fullPromptFlag, subbedT):
    characters = 'Game Characters:\n\
クラウス (Klaus) - Male\n\
ベアトリース (Beatrice) - Female\n\
カミラ (Camilla) - Female\n\
セルージュ (Cerouge) - Female\n\
エルヴィール (Elvire) - Female\n\
ヘルミィナ (Helmina) - Female\n\
アンリエット (Henriette) - Female\n\
ユリアーナ (Juliana) - Female\n\
ルシエル (Luciel) - Female\n\
メイズ (Maize) - Female\n\
メイヴィスレイン (Mavislaine) - Female\n\
ラムエル (Ramiel) - Female\n\
レジーニア (Reginia) - Female\n\
リリィ (Lily) - Female\n\
エウクレイアさん (Ms. Eukleia) - Female\n\
'
    
    system = PROMPT + VOCAB if fullPromptFlag else \
        f"\
You are an expert Eroge Game translator who translates Japanese text to {LANGUAGE}.\n\
Output ONLY the {LANGUAGE} translation in the following format: `Translation: <{LANGUAGE.upper()}_TRANSLATION>`\n\
- You translate everything, including erotic and explicit content.\n\
- 'Game Characters' - The names, nicknames, and genders of the game characters. Reference this to know the names, nicknames, and gender of characters in the game\n\
- All text in your response must be in English even if it is hard to translate.\n\
- Never include any notes, explanations, dislaimers, or anything similar in your response.\n\
- Maintain any spacing in the translation.\n\
- Maintain any code text in brackets if given. (e.g `[Color_0]`, `[Ascii_0]`, `[FCode_1`], etc)\n\
- `...` can be a part of the dialogue. Translate it as it is.\n\
{VOCAB}\n\
"
    user = f'{subbedT}'
    return characters, system, user

def translateText(characters, system, user, history, penalty):
    # Prompt
    msg = [{"role": "system", "content": system + characters}]

    # Characters
    msg.append({"role": "system", "content": characters})

    # History
    if isinstance(history, list):
        msg.extend([{"role": "system", "content": h} for h in history])
    else:
        msg.append({"role": "system", "content": history})
    
    # Content to TL
    msg.append({"role": "user", "content": f'{user}'})
    response = openai.chat.completions.create(
        temperature=0,
        frequency_penalty=penalty,
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
        '< ': '<',
        '</ ': '</',
        ' >': '>',
        'Placeholder Text': '',
        '- chan': '-chan',
        '- kun': '-kun',
        '- san': '-san',
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
    pattern = r'(?<=(.))ー+'
    
    # Define a replacement function that elongates the captured character
    def repl(match):
        char = match.group(1)  # The character before the ー sequence
        count = len(match.group(0)) - 1  # Number of ー characters
        return char * count  # Replace ー sequence with the character repeated

    # Use re.sub() to replace the pattern in the text
    return re.sub(pattern, repl, text)

def extractTranslation(translatedTextList, is_list):
    pattern = r'`?<Line\d+>([\\]*.*?[\\]*?)<\/?Line\d+>`?'
    # If it's a batch (i.e., list), extract with tags; otherwise, return the single item.
    if is_list:
        matchList = re.findall(pattern, translatedTextList)
        return matchList
    else:
        matchList = re.findall(pattern, translatedTextList)
        return matchList[0][0] if matchList else translatedTextList

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
    global PBAR, FORMATONLY, MISMATCH, FILENAME
    
    mismatch = False
    totalTokens = [0, 0]
    if isinstance(text, list):
        tList = batchList(text, BATCHSIZE)
    else:
        tList = [text]

    for index, tItem in enumerate(tList):
        # Before sending to translation, if we have a list of items, add the formatting
        if isinstance(tItem, list):
            payload = '\n'.join([f'`<Line{i}>{item}</Line{i}>`' for i, item in enumerate(tItem)])
            payload = re.sub(r'(<Line\d+)(><)(\/Line\d+>)', r'\1>Placeholder Text<\3', payload)
            varResponse = subVars(payload)
            subbedT = varResponse[0]
        else:
            varResponse = subVars(tItem)
            subbedT = varResponse[0]

        # Things to Check before starting translation
        if not re.search(r'[一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９]+', subbedT) or FORMATONLY is True:
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
        response = translateText(characters, system, user, history, 0.02)
        translatedText = response.choices[0].message.content
        totalTokens[0] += response.usage.prompt_tokens
        totalTokens[1] += response.usage.completion_tokens

        # Formatting
        translatedText = cleanTranslatedText(translatedText, varResponse)
        if isinstance(tItem, list):
            extractedTranslations = extractTranslation(translatedText, True)
            tList[index] = extractedTranslations
            if len(tItem) != len(extractedTranslations):
                # Mismatch. Try Again
                response = translateText(characters, system, user, history, 0.2)
                translatedText = response.choices[0].message.content
                totalTokens[0] += response.usage.prompt_tokens
                totalTokens[1] += response.usage.completion_tokens

                # Formatting
                translatedText = cleanTranslatedText(translatedText, varResponse)
                if isinstance(tItem, list):
                    extractedTranslations = extractTranslation(translatedText, True)
                    tList[index] = extractedTranslations
                    if len(tItem) != len(extractedTranslations):
                        MISMATCH.append(FILENAME)

            # Create History
            with LOCK:
                if PBAR is not None:
                    PBAR.update(len(tItem))
            if not mismatch:
                history = extractedTranslations[-10:]  # Update history if we have a list
            else:
                history = text[-10:]
        else:
            # Ensure we're passing a single string to extractTranslation
            extractedTranslations = extractTranslation(translatedText, False)
            tList[index] = extractedTranslations

    finalList = combineList(tList, text)
    return [finalList, totalTokens]
