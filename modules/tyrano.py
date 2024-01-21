# Libraries
import json, os, re, textwrap, threading, time, traceback, tiktoken, openai
from pathlib import Path
from colorama import Fore
from dotenv import load_dotenv
from retry import retry
from tqdm import tqdm

# Open AI
load_dotenv()
if os.getenv('api').replace(' ', '') != '':
    openai.api_base = os.getenv('api')
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
FIXTEXTWRAP = False  # Overwrites textwrap
IGNORETLTEXT = False    # Ignores all translated text.
MISMATCH = []   # Lists files that throw a mismatch error (Length of GPT list response is wrong)

#tqdm Globals
BAR_FORMAT='{l_bar}{bar:10}{r_bar}{bar:-10b}'
POSITION = 0
LEAVE = False

# Pricing - Depends on the model https://openai.com/pricing
# Batch Size - GPT 3.5 Struggles past 15 lines per request. GPT4 struggles past 50 lines per request
# If you are getting a MISMATCH LENGTH error, lower the batch size.
if 'gpt-3.5' in MODEL:
    INPUTAPICOST = .002 
    OUTPUTAPICOST = .002
    BATCHSIZE = 10
elif 'gpt-4' in MODEL:
    INPUTAPICOST = .01
    OUTPUTAPICOST = .03
    BATCHSIZE = 1

def handleTyrano(filename, estimate):
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
            with open('translated/' + filename, 'w', encoding='utf8', errors='ignore') as outFile:
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
    with open('files/' + filename, 'r', encoding='utf8') as readFile:
        translatedData = parseTyrano(readFile, filename)

        # Delete lines marked for deletion
        finalData = []
        for line in translatedData[0]:
            if line != '\\d\n':
                finalData.append(line)
        translatedData[0] = finalData
    
    return translatedData

def parseTyrano(readFile, filename):
    totalTokens = [0,0]
    totalLines = 0

    # Get total for progress bar
    data = readFile.readlines()
    totalLines = len(data)

    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
        pbar.desc=filename
        pbar.total=totalLines

        try:
            result = translateTyrano(data, pbar, totalLines)
            totalTokens[0] += result[0]
            totalTokens[1] += result[1]
        except Exception as e:
            traceback.print_exc()
            return [data, totalTokens, e]
    return [data, totalTokens, None]

def translateTyrano(data, pbar, totalLines):
    textHistory = []
    batch = []
    currentGroup = []
    maxHistory = MAXHISTORY
    tokens = [0,0]
    speaker = ''
    insertBool = False
    global LOCK, ESTIMATE
    i = 0
    batchStartIndex = 0

    while i < len(data):
        # Speaker
        if '#' in data[i]:
            matchList = re.findall(r'#【(.+)】', data[i])
            if len(matchList) != 0:
                response = getSpeaker(matchList[0])
                speaker = response[0]
                tokens[0] += response[1][0]
                tokens[1] += response[1][1]
                data[i] = '#【' + speaker + '】\n'
            else:
                speaker = ''

        # Choices
        elif 'glink' in data[i]:
            matchList = re.findall(r'\[glink.+text=\"(.+?)\".+', data[i])
            if len(matchList) != 0:
                originalText = matchList[0]
                if len(textHistory) > 0:
                    response = translateGPT(matchList[0], 'Keep your translation as brief as possible. Previous text for context: ' + textHistory[len(textHistory)-1] + '\n\nReply in the style of a dialogue option.', False)
                else:
                    response = translateGPT(matchList[0], '\n\nReply in the style of a dialogue option.', False)
                translatedText = response[0]
                tokens[0] += response[1][0]
                tokens[1] += response[1][1]

                # Remove characters that may break scripts
                charList = ['.', '\"', '\\n']
                for char in charList:
                    translatedText = translatedText.replace(char, '')

                # Escape all '
                translatedText = translatedText.replace('\\', '')
                translatedText = translatedText.replace("'", "\\\'")
                translatedText = translatedText.replace(' ', '\u00A0')

                # Set Data
                translatedText = data[i].replace(originalText, translatedText)
                data[i] = translatedText                

        # Lines
        matchList = re.findall(r'(.+?)\[[rpcms]+\]$', data[i])
        if len(matchList) > 0:
            # Skip if comment
            if matchList[0][0] == ';':
                continue

            # Grab Text
            currentGroup.append(matchList[0])
            if len(data) > i+1:
                while re.search(r'(.+?)\[[rpcms]+\]$', data[i+1]) is not None:
                    if insertBool is True:
                        data[i] = '\d\n'
                        pbar.update(1)
                    i += 1
                    matchList = re.findall(r'(.+?)\[[rpcms]+\]$', data[i])
                    if len(matchList) > 0:
                        currentGroup.append(matchList[0])
            # Join up 401 groups for better translation.
            if len(currentGroup) > 0:
                finalJAString = ' '.join(currentGroup)
                oldjaString = finalJAString

            # Remove any textwrap
            if FIXTEXTWRAP == True:
                finalJAString = finalJAString.replace('[r]', ' ')

            # Remove Extra Stuff bad for translation.
            finalJAString = finalJAString.replace('ﾞ', '')
            finalJAString = finalJAString.replace('・', '.')
            finalJAString = finalJAString.replace('‶', '')
            finalJAString = finalJAString.replace('”', '')
            finalJAString = finalJAString.replace('―', '-')
            finalJAString = finalJAString.replace('ー', '-')
            finalJAString = finalJAString.replace('…', '...')
            finalJAString = re.sub(r'(\.{3}\.+)', '...', finalJAString)
            finalJAString = finalJAString.replace('　', ' ')

            # Furigana Removal
            matchList = re.findall(r'(\[ruby\stext=.+text=\"(.+)\"\])', finalJAString)
            if len(matchList) > 0:
                finalJAString = finalJAString.replace(matchList[0][0], matchList[0][1])

            # Add Speaker (If there is one)
            if speaker != '':
                finalJAString = f'{speaker}: {finalJAString}'

            # [Passthrough 1] Pulling From File
            if insertBool is False:
                # Append to List and Clear Values
                batch.append(finalJAString)
                speaker = ''

                # Translate Batch if Full
                if len(batch) == BATCHSIZE:
                    # Translate
                    response = translateGPT(batch, textHistory, True)
                    tokens[0] += response[1][0]
                    tokens[1] += response[1][1]
                    translatedBatch = response[0]
                    textHistory = translatedBatch[-10:]

                    # Set Values
                    if len(batch) == len(translatedBatch):
                        i = batchStartIndex
                        insertBool = True

                    # Mismatch
                    else:
                        pbar.write(f'Mismatch: {batchStartIndex} - {i}')
                        MISMATCH.append(batch)
                        batchStartIndex = i
                        batch.clear()

                i += 1
                if insertBool is True:
                    pbar.update(1)
                currentGroup = []

            # [Passthrough 2] Setting Data
            else:
                # Get Text
                translatedText = translatedBatch[0]
                translatedText = translatedText.replace('\\"', '\"')
                translatedText = translatedText.replace('[', '(')
                translatedText = translatedText.replace(']', ')')

                # Remove added speaker
                translatedText = re.sub(r'^.+?:\s', '', translatedText)

                # Textwrap
                translatedText = textwrap.fill(translatedText, width=WIDTH)
                textList = translatedText.split('\n')
                    
                # Set Text
                data[i] = '\d\n'
                for line in textList:
                    # Wordwrap Text
                    if '[r]' not in line:
                        line = textwrap.fill(line, width=WIDTH)
                        line = line.replace('\n', '[r]')
                    
                    # Set
                    data.insert(i, line.strip() + '[r]\n')
                    i+=1
                data[i-1] = data[i-1].replace('[r]', '[p]')
                translatedBatch.pop(0)
                speaker = ''
                currentGroup = []

                # If Batch is empty. Move on.
                if len(translatedBatch) == 0:
                    insertBool = False
                    batchStartIndex = i
                    batch.clear()

        # Nothing relevant. Skip Line.
        else:
            i += 1
            if insertBool is True:
                pbar.update(1)

        # Translate Batch if not empty and EOF
        if len(batch) != 0 and i >= len(data):
            # Translate
            response = translateGPT(batch, textHistory, True)
            tokens[0] += response[1][0]
            tokens[1] += response[1][1]
            translatedBatch = response[0]
            textHistory = translatedBatch[-10:]

            # Set Values
            if len(batch) == len(translatedBatch):
                i = batchStartIndex
                insertBool = True

            # Mismatch
            else:
                pbar.write(f'Mismatch: {batchStartIndex} - {i}')
                MISMATCH.append(batch)
                batchStartIndex = i
                batch.clear()

            currentGroup = []
    return tokens

# Save some money and enter the character before translation
def getSpeaker(speaker):
    match speaker:
        case '瞳':
            return ['Hitomi', [0,0]]
        case 'アイ ':
            return ['Ai', [0,0]]
        case 'リン':
            return ['Rin', [0,0]]
        case '小虎':
            return ['Kotora', [0,0]]
        case '玫瑰 ':
            return ['Rose', [0,0]]
        case '創 ':
            return ['So', [0,0]]
        case '葛生':
            return ['Kuzu', [0,0]]
        case '愛梨':
            return ['Airi', [0,0]]
        case '朋美':
            return ['Tomomi', [0,0]]
        case '玄治郎':
            return ['Genjirou', [0,0]]
        case '稼津央':
            return ['Kazuo', [0,0]]
        case '美沙緒':
            return ['Misao', [0,0]]
        case '怜':
            return ['Sato', [0,0]]
        case 'オス':
            return ['Oz', [0,0]]
        case '穂村':
            return ['Homura', [0,0]]
        case '吉野':
            return ['Yoshino', [0,0]]
        case '忠彦':
            return ['Tadahiko', [0,0]]
        case _:
            return translateGPT(speaker, 'Reply with only the '+ LANGUAGE +' translation of the NPC name.', False)
        
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
瞳 (Hitomi) - Female\n\
リン (Rin) - Female\n\
アイ (Ai) - Female\n\
玫瑰 (Meigui) - Male\n\
創 (So) - Male\n\
小虎 (Kotora) - Female\n\
'
    
    system = PROMPT if fullPromptFlag else \
        f'\
You are an expert Eroge Game translator who translates Japanese text to English.\n\
You are going to be translating text from a videogame.\n\
I will give you lines of text, and you must translate each line to the best of your ability.\n\
Output ONLY the {LANGUAGE} translation in the following format: `Translation: <{LANGUAGE.upper()}_TRANSLATION>`'
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
        'ー': '-',
        'ッ': '',
        '。': '.',
        'Placeholder Text': ''
        # Add more replacements as needed
    }
    for target, replacement in placeholders.items():
        translatedText = translatedText.replace(target, replacement)

    translatedText = resubVars(translatedText, varResponse[1])
    return [line for line in translatedText.split('\n') if line]

def extractTranslation(translatedTextList, is_list):
    pattern = r'<Line(\d+)>[\\]*`?(.*?)[\\]*?`?</?Line\d+>'
    # If it's a batch (i.e., list), extract with tags; otherwise, return the single item.
    if is_list:
        return [re.findall(pattern, line)[0][1] for line in translatedTextList if re.search(pattern, line)]
    else:
        matchList = re.findall(pattern, translatedTextList)
        return matchList[0][1] if matchList else translatedTextList

def countTokens(characters, system, user, history):
    inputTotalTokens = 0
    outputTotalTokens = 0
    enc = tiktoken.encoding_for_model(MODEL)
    
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
    outputTotalTokens += round(len(enc.encode(user))/1.5)

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
            payload = '\n'.join([f'<Line{i}>`{item}`</Line{i}>' for i, item in enumerate(tItem)])
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

