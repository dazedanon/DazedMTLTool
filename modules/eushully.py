# Libraries
import os, re, textwrap, threading, time, traceback, tiktoken, openai
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
NOTEWIDTH = 70
MAXHISTORY = 10
ESTIMATE = ''
TOKENS = [0, 0]
NAMESLIST = []
NAMES = False    # Output a list of all the character names found
BRFLAG = False   # If the game uses <br> instead
FIXTEXTWRAP = True  # Overwrites textwrap
IGNORETLTEXT = False    # Ignores all translated text.
MISMATCH = []   # Lists files that throw a mismatch error (Length of GPT list response is wrong)

#tqdm Globals
BAR_FORMAT='{l_bar}{bar:10}{r_bar}{bar:-10b}'
POSITION = 0
LEAVE = False
PBAR = None

# Pricing - Depends on the model https://openai.com/pricing
# Batch Size - GPT 3.5 Struggles past 15 lines per request. GPT4 struggles past 50 lines per request
# If you are getting a MISMATCH LENGTH error, lower the batch size.
if 'gpt-3.5' in MODEL:
    INPUTAPICOST = .002 
    OUTPUTAPICOST = .002
    BATCHSIZE = 10
elif 'gpt-4' in MODEL:
    INPUTAPICOST = .005
    OUTPUTAPICOST = .015
    BATCHSIZE = 40

def handleEushully(filename, estimate):
    global ESTIMATE
    ESTIMATE = estimate

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
        totalString = getResultString(['', TOKENS, None], end - start, 'TOTAL')

        # Print any errors on maps
        if len(MISMATCH) > 0:
            return totalString + Fore.RED + f'\nMismatch Errors: {MISMATCH}' + Fore.RESET
        else:
            return totalString
    
    else:
        try:
            with open('translated/' + filename, 'w', encoding='utf-8', errors='ignore') as outFile:
                start = time.time()
                translatedData = openFiles(filename)

                # Print Result
                end = time.time()
                outFile.writelines(translatedData[0])
                tqdm.write(getResultString(translatedData, end - start, filename))
                with LOCK:
                    TOKENS[0] += translatedData[1][0]
                    TOKENS[1] += translatedData[1][1]
        except Exception as e:
            traceback.print_exc()
            return 'Fail'

    return getResultString(['', TOKENS, None], end - start, 'TOTAL')

def getResultString(translatedData, translationTime, filename):
    # File Print String
    totalTokenstring =\
        Fore.YELLOW +\
        '[Input: ' + str(translatedData[1][0]) + ']'\
        '[Output: ' + str(translatedData[1][1]) + ']'\
        '[Cost: ${:,.4f}'.format((translatedData[1][0] * .001 * INPUTAPICOST) +\
        (translatedData[1][1] * .001 * OUTPUTAPICOST)) + ']'
    timeString = Fore.BLUE + '[' + str(round(translationTime, 1)) + 's]'

    if translatedData[2] == None:
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

def openFiles(filename):
    with open('files/' + filename, 'r', encoding='utf-8') as readFile:
        translatedData = parseRegex(readFile, filename)

        # Delete lines marked for deletion
        finalData = []
        for line in translatedData[0]:
            if line != '\\d\n':
                finalData.append(line)
        translatedData[0] = finalData
    
    return translatedData

def parseRegex(readFile, filename):
    totalTokens = [0,0]

    # Read File into data
    data = readFile.readlines()

    # Create Progress Bar
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE) as pbar:
        pbar.desc=filename

        try:
            result = translateEushully(data, pbar, filename, [])
            totalTokens[0] += result[0]
            totalTokens[1] += result[1]
        except Exception as e:
            traceback.print_exc()
            return [data, totalTokens, e]
    return [data, totalTokens, None]

def translateEushully(data, pbar, filename, translatedList):
    stringList = []
    currentGroup = []
    tokens = [0,0]
    speaker = ''
    voice = False
    global LOCK, ESTIMATE, PBAR
    i = 0

    while i < len(data):
        voice = False
        # Speaker
        if 'mov (global-int 46e2)' in data[i]:
            # Get Speaker
            speaker = re.search(r'mov \(global-int 46e2\)\s(.+)', data[i]).group(1)
            response = getSpeaker(speaker)
            speaker = response[0]
            tokens[0] += response[1][0]
            tokens[1] += response[1][1]
            i += 1

        # Show Text
        if any(x in data[i] for x in ['show-text']):
            # Lines
            regex = r'(.*?)"(.*)"'
            match = re.search(regex, data[i])
            # Grab Strings
            if match != None and match.group(2) != '':
                originalString = match.group(2)
                jaString = match.group(2)
                currentGroup = [jaString]
                while 'end-text-line' in data[i+1] and any(x in data[i+2] for x in ['show-text']):
                    match = re.search(regex, data[i+2])
                    if match != None:
                        currentGroup.append(match.group(2))
                        if translatedList == []:
                            del(data[i])
                            del(data[i])
                jaString = ' '.join(currentGroup)
                
                # Pass 1
                if translatedList == []:
                    # Add String
                    if speaker:
                        stringList.append(f'[{speaker}]: {jaString.strip()}')
                    else:
                        stringList.append(jaString.strip())
                
                # Pass 2
                else:
                    # Get Text
                    if translatedList:
                        # Grab and Pop
                        translatedText = translatedList[0]
                        translatedList.pop(0)

                        # Set to None if empty list
                        if len(translatedList) <= 0:
                            translatedList = None

                        # Replace Quotes
                        translatedText = translatedText.replace('"', "'")

                        # Remove speaker
                        if speaker != '':
                            translatedText = re.sub(r'^\[?(.+?)\]?\s?[|:]\s?', '', translatedText)

                        # Textwrap
                        translatedText = textwrap.fill(translatedText, width=WIDTH)
                        translatedTextList = translatedText.split('\n')

                        # Set Data
                        if len(translatedTextList) > 1:
                            for j in range(len(translatedTextList)):
                                if any(x in data[i] for x in ['show-text', 'set-string', 'concat']):
                                    del(data[i])
                                data.insert(i, f'{match.group(1)}"{translatedTextList[j]}"\n')
                                i += 1
                                if 'end-text-line' not in data[i]:
                                    data.insert(i, 'end-text-line 0\n')
                                i += 1
                        else:
                            data[i] = f'{match.group(1)}"{translatedTextList[0]}"\n'
                speaker = ''
                i += 1
                
            # Nothing relevant. Skip Line.
            else:
                i += 1

        # Set String
        elif 'set-string' in data[i]:
            # Lines
            regex = r'(.*?)"(.*)"'
            match = re.search(regex, data[i])
            # Grab Strings
            if match != None and match.group(2) != '':
                originalString = match.group(2)
                jaString = match.group(2)
                currentGroup = [jaString]
                
                # Remove Textwrap
                jaString = jaString.replace('\\n', ' ')
                
                # Pass 1
                if translatedList == []:
                    # Add String
                    stringList.append(jaString.strip())
                
                # Pass 2
                else:
                    # Get Text
                    if translatedList:
                        # Grab and Pop
                        translatedText = translatedList[0]
                        translatedList.pop(0)

                        # Set to None if empty list
                        if len(translatedList) <= 0:
                            translatedList = None

                        # Replace Quotes
                        translatedText = translatedText.replace('"', "'")

                        # Textwrap
                        translatedText = textwrap.fill(translatedText, width=LISTWIDTH)
                        translatedText = translatedText.replace('\n', '\\n')

                        # Set Data
                        data[i] = data[i].replace(originalString, translatedText)   
                speaker = ''    
                i += 1

            # Nothing relevant. Skip Line.
            else:
                i += 1
        else:
            i += 1

    # EOF
    if len(stringList) > 0:
        # Set Progress
        pbar.total = len(stringList)
        pbar.refresh()
        
        # Translate
        PBAR = pbar
        response = translateGPT(stringList, '', True)
        tokens[0] += response[1][0]
        tokens[1] += response[1][1]
        translatedList = response[0]

        # Set Strings
        if len(stringList) == len(translatedList):
            translateEushully(data, pbar, filename, translatedList)

        # Mismatch
        else:
            with LOCK:
                if filename not in MISMATCH:
                    MISMATCH.append(filename)
    return tokens

# Save some money and enter the character before translation
def getSpeaker(speaker):
    match speaker:
        case '1':
            return ['Klaus', [0,0]]
        case '2':
            return ['Helmina', [0,0]]
        case '3':
            return ['Juliana', [0,0]]
        case '4':
            return ['Reginia', [0,0]]
        case '5':
            return ['Luciel', [0,0]]
        case '6':
            return ['Mavislaine', [0,0]]
        case '7':
            return ['Cerouge', [0,0]]
        case '8':
            return ['Maize', [0,0]]
        case '9':
            return ['Elvire', [0,0]]
        case 'a':
            return ['Beatrice', [0,0]]
        case '295':
            return ['Orc', [0,0]]
        case '232':
            return ['Archangel', [0,0]]
        case '238':
            return ['False Juliana', [0,0]]
        case '239':
            return ['False Regina', [0,0]]
        case '23a':
            return ['False Luciel', [0,0]]
        case '23d':
            return ['False Mavislaine', [0,0]]
        case 'cb':
            return ['Olga Niza Kite', [0,0]]
        case 'c9':
            return ['Demon Beast Lupus', [0,0]]
        case 'ca':
            return ['Evelinael', [0,0]]
        case '10':
            return ['Eukleia', [0,0]]
        case '15':
            return ['Lily', [0,0]]
        case '16':
            return ['Kupuko', [0,0]]
        case 'b':
            return ['Ramiel', [0,0]]
        case 'c':
            return ['Henriette', [0,0]]
        case 'd':
            return ['Camilla', [0,0]]
        case 'cc':
            return ['Gogonaua', [0,0]]
        case '65':
            return ['Demon Lord Reyvalois', [0,0]]
        case 'd0':
            return ['Demon Ranwald', [0,0]]
        case '205':
            return ['Vanqueor', [0,0]]
        case '66':
            return ['Angel Martina', [0,0]]
        case '21f':
            return ['Hiten Demon', [0,0]]
        case 'd2':
            return ['Lena Eli', [0,0]]
        case _:
            return ['Unknown', [0,0]]

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
グレイス (Grace) - Female\n\
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
        '「': '\"',
        ' 」': '\"',
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
    pattern = r'`?<[Ll]ine\d+>([\\]*.*?[\\]*?)<\/?[Ll]ine\d+>`?'
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
    global PBAR
    
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
        if not re.search(r'[一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９]+', subbedT):
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
                        mismatch = True # Just here for breakpoint

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
