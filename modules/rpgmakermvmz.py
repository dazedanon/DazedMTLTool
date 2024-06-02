# Libraries
import json, os, re, textwrap, threading, time, traceback, tiktoken, openai
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
MISMATCH = []   # Lists files that throw a mismatch error (Length of GPT list response is wrong)
BRACKETNAMES = False
PBAR = None

# Pricing - Depends on the model https://openai.com/pricing
# Batch Size - GPT 3.5 Struggles past 15 lines per request. GPT4 struggles past 50 lines per request
# If you are getting a MISMATCH LENGTH error, lower the batch size.
if 'gpt-3.5' in MODEL:
    INPUTAPICOST = .002 
    OUTPUTAPICOST = .002
    BATCHSIZE = 10
    FREQUENCY_PENALTY = 0.2
elif 'gpt-4o' in MODEL:
    INPUTAPICOST = .005
    OUTPUTAPICOST = .015
    BATCHSIZE = 20
    FREQUENCY_PENALTY = 0.1

#tqdm Globals
BAR_FORMAT='{l_bar}{bar:10}{r_bar}{bar:-10b}'
POSITION = 0
LEAVE = False

# Dialogue / Scroll
CODE401 = True
CODE405 = True
CODE408 = False

# Choices
CODE102 = True

# Variables
CODE122 = False

# Names
CODE101 = False

# Other
CODE355655 = False
CODE357 = False
CODE657 = False
CODE356 = False
CODE320 = False
CODE324 = False
CODE111 = False
CODE108 = False

def handleMVMZ(filename, estimate):
    global ESTIMATE, TOKENS
    ESTIMATE = estimate

    # Translate
    start = time.time()
    translatedData = openFiles(filename)
    
    # Translate
    if not estimate:
        try:
            with open('translated/' + filename, 'w', encoding='utf-8') as outFile:
                json.dump(translatedData[0], outFile, ensure_ascii=False, indent=4)
        except Exception:
            traceback.print_exc()
            return 'Fail'
    
    # Print File
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

def openFiles(filename):
    with open('files/' + filename, 'r', encoding='utf-8-sig') as f:
        data = json.load(f)

        # Map Files
        if 'Map' in filename and filename != 'MapInfos.json':
            translatedData = parseMap(data, filename)

        # CommonEvents Files
        elif 'CommonEvents' in filename:
            translatedData = parseCommonEvents(data, filename)

        # Actor File
        elif 'Actors' in filename:
            translatedData = parseNames(data, filename, 'Actors')

        # Armor File
        elif 'Armors' in filename:
            translatedData = parseNames(data, filename, 'Armors')

        # Weapons File
        elif 'Weapons' in filename:
            translatedData = parseNames(data, filename, 'Weapons')
        
        # Classes File
        elif 'Classes' in filename:
            translatedData = parseNames(data, filename, 'Classes')

        # Enemies File
        elif 'Enemies' in filename:
            translatedData = parseNames(data, filename, 'Enemies')

        # Items File
        elif 'Items' in filename:
            translatedData = parseNames(data, filename, 'Items')

        # MapInfo File
        elif 'MapInfos' in filename:
            translatedData = parseNames(data, filename, 'MapInfos')

        # Skills File
        elif 'Skills' in filename:
            translatedData = parseNames(data, filename, 'Skills')

        # Troops File
        elif 'Troops' in filename:
            translatedData = parseTroops(data, filename)

        # States File
        elif 'States' in filename:
            translatedData = parseSS(data, filename)

        # System File
        elif 'System' in filename:
            translatedData = parseSystem(data, filename)

        # Scenario File
        elif 'Scenario' in filename:
            translatedData = parseScenario(data, filename)

        else:
            raise NameError(filename + ' Not Supported')
    
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

def parseMap(data, filename):
    totalTokens = [0, 0]
    totalLines = 0
    events = data['events']
    global LOCK

    # Translate displayName for Map files
    if 'Map' in filename:
        response = translateGPT(data['displayName'], 'Reply with only the '+ LANGUAGE +' translation of the RPG location name', False)
        totalTokens[0] += response[1][0]
        totalTokens[1] += response[1][1]
        data['displayName'] = response[0].replace('\"', '')

    # Get total for progress bar
    for event in events:
        if event is not None:
            for page in event['pages']:
                totalLines += len(page['list'])
    
    # Thread for each page in file
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE) as pbar:
        pbar.desc=filename
        with ThreadPoolExecutor(max_workers=THREADS) as executor:
            for event in events:
                if event is not None:
                    # This translates ID of events. (May break the game)
                    if '<namePop:' in event['note']:
                        response = translateNoteOmitSpace(event, r'<namePop:(.*?)\s?>.+')
                        totalTokens[0] += response[0]
                        totalTokens[1] += response[1]

                    futures = [executor.submit(searchCodes, page, pbar, [], filename) for page in event['pages'] if page is not None]
                    for future in as_completed(futures):
                        try:
                            totalTokensFuture = future.result()
                            totalTokens[0] += totalTokensFuture[0]
                            totalTokens[1] += totalTokensFuture[1]
                        except Exception as e:
                            traceback.print_exc()
                            return [data, totalTokens, e]
    return [data, totalTokens, None]

def translateNote(event, regex):
    # Regex String
    jaString = event['note']
    match = re.findall(regex, jaString, re.DOTALL)
    if match:
        tokens = [0,0]
        i = 0
        while i < len(match):
            initialJAString = match[i]
            # Remove any textwrap
            modifiedJAString = initialJAString.replace('\n', ' ')

            # Translate
            response = translateGPT(modifiedJAString, 'Reply with only the '+ LANGUAGE +' translation.', False)
            translatedText = response[0]
            tokens[0] += response[1][0]
            tokens[1] += response[1][1]

            # Textwrap
            translatedText = textwrap.fill(translatedText, width=NOTEWIDTH)
            translatedText = translatedText.replace('\"', '')
            jaString = jaString.replace(initialJAString, translatedText)
            event['note'] = jaString
            i += 1
        return tokens
    return [0,0]

# For notes that can't have spaces.
def translateNoteOmitSpace(event, regex):
    # Regex that only matches text inside LB.
    jaString = event['note']

    match = re.findall(regex, jaString, re.DOTALL)
    if match:
        oldJAString = match[0]
        # Remove any textwrap
        jaString = re.sub(r'\n', ' ', oldJAString)

        # Translate
        response = translateGPT(jaString, 'Reply with the '+ LANGUAGE +' translation of the location name.', False)
        translatedText = response[0]

        translatedText = translatedText.replace('\"', '')
        translatedText = translatedText.replace(' ', '_')
        event['note'] = event['note'].replace(oldJAString, translatedText)
        return response[1]
    return [0,0]

def parseCommonEvents(data, filename):
    totalTokens = [0, 0]
    totalLines = 0
    global LOCK

    # Get total for progress bar
    for page in data:
        if page is not None:
            totalLines += len(page['list'])

    with tqdm(bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE) as pbar:
        pbar.desc=filename
        with ThreadPoolExecutor(max_workers=THREADS) as executor:
            futures = [executor.submit(searchCodes, page, pbar, [], filename) for page in data if page is not None]
            for future in as_completed(futures):
                try:
                    totalTokensFuture = future.result()
                    totalTokens[0] += totalTokensFuture[0]
                    totalTokens[1] += totalTokensFuture[1]
                except Exception as e:
                    traceback.print_exc()
                    return [data, totalTokens, e]
    return [data, totalTokens, None]

def parseTroops(data, filename):
    totalTokens = [0, 0]
    totalLines = 0
    global LOCK

    # Get total for progress bar
    for troop in data:
        if troop is not None:
            for page in troop['pages']:
                totalLines += len(page['list']) + 1 # The +1 is because each page has a name.

    with tqdm(bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE) as pbar:
        pbar.desc=filename
        for troop in data:
            if troop is not None:
                with ThreadPoolExecutor(max_workers=THREADS) as executor:
                    futures = [executor.submit(searchCodes, page, pbar, [], filename) for page in troop['pages'] if page is not None]
                    for future in as_completed(futures):
                        try:
                            totalTokensFuture = future.result()
                            totalTokens[0] += totalTokensFuture[0]
                            totalTokens[1] += totalTokensFuture[1]
                        except Exception as e:
                            traceback.print_exc()
                            return [data, totalTokens, e]
    return [data, totalTokens, None]
    
def parseNames(data, filename, context):
    totalTokens = [0, 0]
    totalLines = 0
    totalLines += len(data)
                
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE) as pbar:
            pbar.desc=filename
            try:
                result = searchNames(data, pbar, context)       
                totalTokens[0] += result[0]
                totalTokens[1] += result[1]
            except Exception as e:
                traceback.print_exc()
                return [data, totalTokens, e]
    return [data, totalTokens, None]

def parseSS(data, filename):
    totalTokens = [0, 0]
    totalLines = 0
    totalLines += len(data)
                
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE) as pbar:
            pbar.desc=filename
            for ss in data:
                if ss is not None:
                    try:
                        result = searchSS(ss, pbar)       
                        totalTokens[0] += result[0]
                        totalTokens[1] += result[1]
                    except Exception as e:
                        traceback.print_exc()
                        return [data, totalTokens, e]
    return [data, totalTokens, None]

def parseSystem(data, filename):
    totalTokens = [0, 0]
    totalLines = 0

    # Calculate Total Lines
    for term in data['terms']:
        termList = data['terms'][term]
        totalLines += len(termList)
    totalLines += len(data['gameTitle'])
    totalLines += len(data['terms']['messages'])
    totalLines += len(data['variables'])
    totalLines += len(data['equipTypes'])
    totalLines += len(data['armorTypes'])
    totalLines += len(data['skillTypes'])
                
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE) as pbar:
        pbar.desc=filename
        try:
            result = searchSystem(data, pbar)       
            totalTokens[0] += result[0]
            totalTokens[1] += result[1]
        except Exception as e:
            traceback.print_exc()
            return [data, totalTokens, e]
    return [data, totalTokens, None]

def parseScenario(data, filename):
    totalTokens = [0, 0]
    totalLines = 0
    global LOCK

    # Get total for progress bar
    for page in data.items():
        totalLines += len(page[1])

    with tqdm(bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE) as pbar:
        pbar.desc=filename
        with ThreadPoolExecutor(max_workers=THREADS) as executor:
            futures = [executor.submit(searchCodes, page[1], pbar, [], filename) for page in data.items() if page[1] is not None]
            for future in as_completed(futures):
                try:
                    totalTokensFuture = future.result()
                    totalTokens[0] += totalTokensFuture[0]
                    totalTokens[1] += totalTokensFuture[1]
                except Exception as e:
                    traceback.print_exc()
                    return [data, totalTokens, e]
    return [data, totalTokens, None]

def searchNames(data, pbar, context):
    totalTokens = [0, 0]
    nameList = []
    profileList = []
    nicknameList = []
    descriptionList = []
    noteList = []
    i = 0 # Counter
    j = 0 # Counter 2
    filling = False
    mismatch = False
    batchFull = False

    # Set the context of what we are translating
    if 'Actors' in context:
        newContext = 'Reply with only the '+ LANGUAGE +' translation of the NPC name'
    if 'Armors' in context:
        newContext = 'Reply with only the '+ LANGUAGE +' translation of the RPG equipment name'
    if 'Classes' in context:
        newContext = 'Reply with only the '+ LANGUAGE +' translation of the RPG class name'
    if 'MapInfos' in context:
        newContext = 'Reply with only the '+ LANGUAGE +' translation of the location name'
    if 'Enemies' in context:
        newContext = 'Reply with only the '+ LANGUAGE +' translation of the enemy NPC name'
    if 'Weapons' in context:
        newContext = 'Reply with only the '+ LANGUAGE +' translation of the RPG weapon name'
    if 'Items' in context:
        newContext = 'Reply with only the '+ LANGUAGE +' translation of the RPG item name'
    if 'Skills' in context:
        newContext = 'Reply with only the '+ LANGUAGE +' translation of the RPG skill name'

    # Names
    while i < len(data) or filling == True:
        if i < len(data):
            # Empty Data
            if data[i] is None or data[i]['name'] == "":
                i += 1
                
                continue  

            # Filling up Batch
            filling = True
            if context in 'Actors':
                if len(nameList) < BATCHSIZE:
                    nameList.append(data[i]['name'])
                    nicknameList.append(data[i]['nickname'])
                    profileList.append(data[i]['profile'].replace('\n', ' '))
                    
                    i += 1
                else:
                    batchFull = True
            if context in ['Armors', 'Weapons', 'Items']:
                if len(nameList) < BATCHSIZE:
                    nameList.append(data[i]['name'])
                    descriptionList.append(data[i]['description'].replace('\n', ' '))
                    if '<hint:' in data[i]['note']:
                        tokensResponse = translateNote(data[i], r'<hint:(.*?)>')
                        totalTokens[0] += tokensResponse[0]
                        totalTokens[1] += tokensResponse[1]
                    if '<SGDescription:' in data[i]['note']:
                        tokensResponse = translateNote(data[i], r'<SGDescription:(.*?)>')
                        totalTokens[0] += tokensResponse[0]
                        totalTokens[1] += tokensResponse[1]
                    if '<SG説明:' in data[i]['note']:
                        tokensResponse = translateNote(data[i], r'<SG説明:(.*?)>')
                        totalTokens[0] += tokensResponse[0]
                        totalTokens[1] += tokensResponse[1]
                    if '<SG説明2:' in data[i]['note']:
                        tokensResponse = translateNote(data[i], r'<SG説明2:(.*?)>')
                        totalTokens[0] += tokensResponse[0]
                        totalTokens[1] += tokensResponse[1]
                    if '<SG説明3:' in data[i]['note']:
                        tokensResponse = translateNote(data[i], r'<SG説明3:(.*?)>')
                        totalTokens[0] += tokensResponse[0]
                        totalTokens[1] += tokensResponse[1]
                    if '<SG説明4:' in data[i]['note']:
                        tokensResponse = translateNote(data[i], r'<SG説明4:(.*?)>')
                        totalTokens[0] += tokensResponse[0]
                        totalTokens[1] += tokensResponse[1]
                    if '<SGカテゴリ:' in data[i]['note']:
                        tokensResponse = translateNote(data[i], r'<SGカテゴリ:(.*?)>')
                        totalTokens[0] += tokensResponse[0]
                        totalTokens[1] += tokensResponse[1]
                    if 'Switch Shop Description' in data[i]['note']:
                        tokensResponse = translateNote(data[i], r'<Switch Shop Description>\n(.*)\n')
                        totalTokens[0] += tokensResponse[0]
                        totalTokens[1] += tokensResponse[1]
                    if '<MapText:' in data[i]['note']:
                        tokensResponse = translateNote(data[i], r'<MapText:(.*?)>')
                        totalTokens[0] += tokensResponse[0]
                        totalTokens[1] += tokensResponse[1]
                    
                    i += 1
                else:
                    batchFull = True
            if context in ['Skills']:
                if len(nameList) < BATCHSIZE:
                    nameList.append(data[i]['name'])
                    descriptionList.append(data[i]['description'].replace('\n', ' '))
                    
                    # Messages
                    number = 1
                    while number < 5:
                        if f'message{number}' in data[i]:
                            if len(data[i][f'message{number}']) > 0 and data[i][f'message{number}'][0] in ['は', 'を', 'の', 'に', 'が']:
                                msgResponse = translateGPT('Taro' + data[i][f'message{number}'], 'reply with only the gender neutral '+ LANGUAGE +' translation of the action log. Always start the sentence with Taro. For example, Translate \'Taroを倒した！\' as \'Taro was defeated!\'', False)
                                data[i][f'message{number}'] = msgResponse[0].replace('Taro', '')
                                totalTokens[0] += msgResponse[1][0]
                                totalTokens[1] += msgResponse[1][1]
                                number += 1

                            else:
                                msgResponse = translateGPT(data[i][f'message{number}'], 'reply with only the gender neutral '+ LANGUAGE +' translation', False)
                                data[i][f'message{number}'] = msgResponse[0]
                                totalTokens[0] += msgResponse[1][0]
                                totalTokens[1] += msgResponse[1][1]
                                number += 1
                        else:
                            number += 1
                    
                    i += 1
                else:
                    batchFull = True
            if context in ['Enemies', 'Classes', 'MapInfos']:
                if len(nameList) < BATCHSIZE:
                    nameList.append(data[i]['name'])
                    
                    i += 1
                else:
                    batchFull = True

        # Batch Full
        if batchFull == True or i >= len(data):
            k = j   # Original Index
            if context in 'Actors':
                # Name
                response = translateGPT(nameList, newContext, True)
                translatedNameBatch = response[0]
                totalTokens[0] += response[1][0]
                totalTokens[1] += response[1][1]

                # Nickname
                response = translateGPT(nicknameList, newContext, True)
                translatedNicknameBatch = response[0]
                totalTokens[0] += response[1][0]
                totalTokens[1] += response[1][1]

                # Profile
                response = translateGPT(profileList, '', True)
                translatedProfileBatch = response[0]
                totalTokens[0] += response[1][0]
                totalTokens[1] += response[1][1]

                # Set Data
                if len(nameList) == len(translatedNameBatch):
                    j = k
                    while j < i:
                        # Empty Data
                        if data[j] is None or data[j]['name'] == "":
                            j += 1
                            continue 
                        else:
                            # Get Text
                            data[j]['name'] = translatedNameBatch[0]
                            data[j]['nickname'] = translatedNicknameBatch[0]
                            data[j]['profile'] = textwrap.fill(translatedProfileBatch[0], LISTWIDTH)
                            translatedNameBatch.pop(0)
                            translatedNicknameBatch.pop(0)
                            translatedProfileBatch.pop(0)

                            # If Batch is empty. Move on.
                            if len(translatedNameBatch) == 0:
                                nameList.clear()
                                filling = False
                            j += 1
                else:
                    mismatch = True

            if context in ['Armors', 'Weapons', 'Items', 'Skills']:
                # Name
                response = translateGPT(nameList, newContext, True)
                translatedNameBatch = response[0]
                totalTokens[0] += response[1][0]
                totalTokens[1] += response[1][1]

                # Description
                response = translateGPT(descriptionList, f'Reply with only the {LANGUAGE} translation of the text.', True)
                translatedDescriptionBatch = response[0]
                totalTokens[0] += response[1][0]
                totalTokens[1] += response[1][1]

                # Set Data
                if len(nameList) == len(translatedNameBatch):
                    j = k
                    while j < i:
                        # Empty Data
                        if data[j] is None or data[j]['name'] == "":
                            j += 1
                            continue 
                        else:
                            # Get Text
                            data[j]['name'] = translatedNameBatch[0]
                            data[j]['description'] = textwrap.fill(translatedDescriptionBatch[0], LISTWIDTH)
                            translatedNameBatch.pop(0)
                            translatedDescriptionBatch.pop(0)

                            # If Batch is empty. Move on.
                            if len(translatedNameBatch) == 0:
                                nameList.clear()
                                descriptionList.clear()
                                batchFull = False
                                filling = False
                            j += 1
                else:
                    mismatch = True
            if context in ['Enemies', 'Classes', 'MapInfos']:
                response = translateGPT(nameList, newContext, True)
                translatedNameBatch = response[0]
                totalTokens[0] += response[1][0]
                totalTokens[1] += response[1][1]

                # Set Data
                if len(nameList) == len(translatedNameBatch):
                    j = k
                    while j < i:
                        # Empty Data
                        if data[j] is None or data[j]['name'] == "":
                            j += 1
                            continue 
                        else:
                            # Get Text
                            data[j]['name'] = translatedNameBatch[0]
                            translatedNameBatch.pop(0)

                            # If Batch is empty. Move on.
                            if len(translatedNameBatch) == 0:
                                nameList.clear()
                                batchFull = False
                                filling = False
                            j += 1
                else:
                    mismatch = True

            # Mismatch
            if mismatch == True:
                MISMATCH.append(nameList)
                nameList.clear()
                profileList.clear()
                descriptionList.clear()
                filling = False
                mismatch = False
                
                i += 1

    return totalTokens

def searchCodes(page, pbar, jobList, filename):
    if len(jobList) > 0:
        docList = jobList[0]
        scriptList = jobList[1]
        setData = True
    else:
        docList = []
        scriptList = []
        setData = False
    currentGroup = []
    textHistory = []
    match = []
    totalTokens = [0, 0]
    translatedText = ''
    speaker = ''
    speakerID = None
    nametag = ''
    syncIndex = 0
    CLFlag = False
    maxHistory = MAXHISTORY
    global LOCK
    global NAMESLIST
    global MISMATCH
    global PBAR
    with LOCK:
        PBAR = pbar


    # Begin Parsing File
    try:
        # Normal Format
        if 'list' in page:
            codeList = page['list']

        # Special Format (Scenario)
        else:
            codeList = page

        # Iterate through page
        i = 0
        while i < len(codeList):
            with LOCK:  
                # syncIndex will keep i in sync when it gets modified
                if syncIndex > i:
                    i = syncIndex
                if len(codeList) <= i:
                    break

            ## Event Code: 401 Show Text
            if 'code' in codeList[i] and codeList[i]['code'] in [401, 405, -1] and (CODE401 or CODE405):
                # Save Code and starting index (j)
                code = codeList[i]['code']
                j = i
                endtag = ''

                # Grab String
                if len(codeList[i]['parameters']) > 0:
                    jaString = codeList[i]['parameters'][0]
                else:
                    codeList[i]['code'] = -1
                    i += 1
                    continue

                # Speaker Check
                # Colors
                speakerList = re.findall(r'^[\\]+[cC]\[[\d]+\](.+?)[\\]+[Cc]\[[\d]\]\\?\\?$', jaString)

                # Brackets
                if len(speakerList) == 0:
                    speakerList = re.findall(r'^【(.*?)】$', jaString)

                # None
                if len(speakerList) == 0:
                    if len(jaString) < 40 \
                    and 'code' in codeList[i+1] \
                    and codeList[i+1]['code'] in [401, 405, -1] \
                    and len(codeList[i+1]['parameters']) > 0 \
                    and len(codeList[i+1]['parameters'][0]) > 0:
                        if codeList[i+1]['parameters'][0][0] in ['「', '"', '(', '（', '*', '[']:
                            speakerList = re.findall(r'.+', jaString)

                if len(speakerList) != 0 and codeList[i+1]['code'] in [401, 405, -1]:
                    # Get Speaker
                    response = getSpeaker(speakerList[0])
                    speaker = response[0]
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]

                    # Set Data
                    codeList[i]['parameters'][0] = jaString.replace(speakerList[0], speaker)

                    # Iterate to next string
                    i += 1
                    j = i
                    while codeList[i]['code'] in [-1]:
                        i += 1
                        j = i
                    jaString = codeList[i]['parameters'][0]

                # Using this to keep track of 401's in a row.
                currentGroup.append(jaString)

                # Join Up 401's into single string
                if len(codeList) > i+1:
                    while codeList[i+1]['code'] in [401, 405, -1]:
                        if setData == True:
                            codeList[i]['parameters'] = []
                            codeList[i]['code'] = -1
                        i += 1
                        j = i

                        # Only add if not empty
                        if len(codeList[i]['parameters']) > 0:
                            jaString = codeList[i]['parameters'][0]
                            currentGroup.append(jaString)

                        # Make sure not the end of the list.
                        if len(codeList) <= i+1:
                            break

                # Format String
                if len(currentGroup) > 0:
                    finalJAString = ' '.join(currentGroup).replace('？', '?')
                    oldjaString = finalJAString

                    # Check if Empty
                    if finalJAString == '':
                        i += 1
                        continue

                    # Set Back
                    if setData == True:
                        codeList[i]['parameters'] = [finalJAString]

                    ### \\n<Speaker>
                    nCase = None
                    if finalJAString[0] != '\\':
                        regex = r'(.*?)([\\]+[kKnN][wWcC]?[<](.*?)[>].*)'
                        nCase = 0
                    else:
                        regex = r'([\\]+[kKnN][wWcC]?[<](.*?)[>])'
                        nCase = 1
                    matchList = re.findall(regex, finalJAString)
                    if len(matchList) > 0:  
                        if nCase == 0:
                            nametag = matchList[0][1]
                            speaker = matchList[0][2]
                        elif nCase == 1:
                            nametag = matchList[0][0]
                            speaker = matchList[0][1]

                        # Translate Speaker  
                        response = getSpeaker(speaker)
                        tledSpeaker = response[0]
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]

                        # Set Nametag and Remove from Final String
                        finalJAString = finalJAString.replace(nametag, '')
                        nametag = nametag.replace(speaker, tledSpeaker)
                        speaker = tledSpeaker

                        # Set dialogue
                        if nCase == 0:
                            codeList[i]['parameters'] = [finalJAString + nametag]
                        elif nCase == 1:
                            codeList[i]['parameters'] = [nametag + finalJAString]
                            
                    ### Brackets
                    matchList = re.findall\
                        (r'^([\\]+[cC]\[[0-9]+\]【?(.+?)】?[\\]+[cC]\[[0-9]+\])|^(【(.+)】)', finalJAString)  
                    
                    # Handle both cases of the regex  
                    if len(matchList) != 0 and BRACKETNAMES is True:
                        if matchList[0][0] != '':
                            match0 = matchList[0][0]
                            match1 = matchList[0][1]
                        else:
                            match0 = matchList[0][2]
                            match1 = matchList[0][3]

                        # Translate Speaker
                        speakerID = j
                        response = getSpeaker(match1)
                        speaker = response[0]
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]

                        # Set Nametag and Remove from Final String
                        fullSpeaker = match0.replace(match1, speaker)
                        finalJAString = finalJAString.replace(match0, '')

                        # Set next item as dialogue
                        if codeList[j + 1]['code'] == 401 or codeList[j + 1]['code'] == -1:
                            # Set name var to top of list
                            codeList[j]['parameters'] = [fullSpeaker]
                            codeList[j]['code'] = code
                            j += 1
                            codeList[j]['parameters'] = [finalJAString]
                            codeList[j]['code'] = code
                        else:
                            # Set nametag in string
                            codeList[j]['parameters'] = [fullSpeaker + finalJAString]
                            codeList[j]['code'] = code

                    # Catch Vars that may break the TL
                    varString = ''
                    matchList = re.findall(r'^[\\_]+[\w]+\[[a-zA-Z0-9\\\[\]\_,\s-]+\]', finalJAString)    
                    if len(matchList) != 0:
                        varString = matchList[0]
                        finalJAString = finalJAString.replace(matchList[0], '')

                    # Remove any textwrap
                    if FIXTEXTWRAP is True:
                        finalJAString = re.sub(r'\n', ' ', finalJAString)
                        finalJAString = finalJAString.replace('<br>', ' ')

                    # Remove Extra Stuff bad for translation.
                    finalJAString = finalJAString.replace('ﾞ', '')
                    finalJAString = finalJAString.replace('―', '-')
                    finalJAString = finalJAString.replace('…', '...')
                    finalJAString = finalJAString.replace('。', '.')
                    finalJAString = re.sub(r'(\.{3}\.+)', '...', finalJAString)
                    finalJAString = finalJAString.replace('　', '')
                    finalJAString = finalJAString.replace('」', '\"')
                    finalJAString = finalJAString.replace('」', '\"')

                    ### Remove format codes
                    # Furigana
                    rcodeMatch = re.findall(r'([\\]+[r][b]?\[.*?,(.*?)\])', finalJAString)
                    if len(rcodeMatch) > 0:
                        for match in rcodeMatch:
                            finalJAString = finalJAString.replace(match[0],match[1])

                    # Remove any RPGMaker Code at start
                    ffMatch = re.search(r'^([.\\]+[aAbBcCdDeEfFgGhHiIjJlLmMoOpPqQrRsStTuUvVwWxXyYzZ]+\[.+?\])+', finalJAString)
                    if ffMatch != None:
                        finalJAString = finalJAString.replace(ffMatch.group(0), '')
                        nametag += ffMatch.group(0)

                    # Formatting
                    formatMatch = re.findall(r'[\\]+[!><.|#^{}]', finalJAString)
                    if len(formatMatch) > 0:
                        for match in formatMatch:
                            finalJAString = finalJAString.replace(match, '')

                    # Center Lines
                    if '\\CL' in finalJAString or '\\ac' in finalJAString:
                        finalJAString = finalJAString.replace('\\CL ', '')
                        finalJAString = finalJAString.replace('\\CL', '')
                        finalJAString = finalJAString.replace('\\ac ', '')
                        finalJAString = finalJAString.replace('\\ac', '')
                        CLFlag = True

                    # If there isn't any Japanese in the text just skip
                    if IGNORETLTEXT is True:
                        if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', finalJAString):
                            # Keep textHistory list at length maxHistory
                            textHistory.append('\"' + finalJAString + '\"')
                            if len(textHistory) > maxHistory:
                                textHistory.pop(0)
                            currentGroup = []  
                            i += 1
                            continue

                    # 1st Passthrough (Grabbing Data)
                    if setData == False:
                        if speaker == '' and finalJAString != '':
                            docList.append(finalJAString)
                        elif finalJAString != '':
                            docList.append(f'[{speaker}]: {finalJAString}')
                        else:
                            docList.append(speaker)
                        speaker = ''
                        match = []
                        currentGroup = []
                        syncIndex = i + 1                          

                    # 2nd Passthrough (Setting Data) 
                    else:
                        # Grab Translated String
                        if len(docList) > 0:
                            translatedText = docList[0]
                            
                            # Remove speaker
                            if speaker != '':
                                matchSpeakerList = re.findall(r'^\[?(.+?)\]?\s?[|:]\s?', translatedText)
                                if len(matchSpeakerList) > 0:
                                    newSpeaker = matchSpeakerList[0]
                                    nametag = nametag.replace(speaker, newSpeaker)
                                translatedText = re.sub(r'^\[?(.+?)\]?\s?[|:]\s?', '', translatedText)

                            # Textwrap
                            if FIXTEXTWRAP is True:
                                translatedText = textwrap.fill(translatedText, width=WIDTH)
                                if BRFLAG is True:
                                    translatedText = translatedText.replace('\n', '<br>')   

                            ### Add Var Strings
                            # CL Flag
                            if CLFlag:
                                translatedText = '\\ac ' + translatedText
                                translatedText = translatedText.replace('\n', '\n\\ac ')
                                translatedText = re.sub(r'[\\]+?ac\s+', r'\\ac ', translatedText)
                                CLFlag = False

                            # Nametag
                            if nCase == 0:
                                translatedText = translatedText + nametag
                            else:
                                translatedText = nametag + translatedText
                            nametag = ''

                            # Endtag
                            if endtag != '':
                                translatedText = translatedText + endtag
                                endtag = ''

                            # //SE[#]
                            translatedText = varString + translatedText

                            # Set Data
                            if speakerID != None:
                                codeList[speakerID]['parameters'] = [fullSpeaker]
                            codeList[j]['parameters'] = [translatedText]
                            codeList[j]['code'] = code
                            speaker = ''
                            match = []
                            currentGroup = []
                            syncIndex = i + 1
                            docList.pop(0)                                

            ## Event Code: 122 [Set Variables]
            if 'code' in codeList[i] and codeList[i]['code'] == 122 and CODE122 is True:
                # This is going to be the var being set. (IMPORTANT)
                if codeList[i]['parameters'][0] not in list(range(0, 20)):
                    i += 1
                    continue
                  
                jaString = codeList[i]['parameters'][4]
                if not isinstance(jaString, str):
                    i += 1
                    continue
                
                # Definitely don't want to mess with files
                if 'gameV' in jaString or '_' in jaString:
                    i += 1
                    continue

                # Need to remove outside code and put it back later
                matchedText = re.search(r"[\'\"\`](.*)[\'\"\`]", jaString)

                if matchedText != None:
                    # Remove Textwrap
                    finalJAString = matchedText.group(1).replace('\\n', ' ')

                    # Pass 1
                    if setData == False:
                        scriptList.append(finalJAString)

                    # Pass 2
                    else:  
                        if len(scriptList) > 0:            
                            # Grab and Replace
                            translatedText = scriptList[0]
                            translatedText = jaString.replace(jaString, translatedText)

                            # Remove characters that may break scripts
                            charList = ['\"', '\\n']
                            for char in charList:
                                translatedText = translatedText.replace(char, '')
                        
                            # Textwrap
                            translatedText = textwrap.fill(translatedText, width=80)
                            translatedText = translatedText.replace('\n', '\\n')
                            translatedText = '\"' + translatedText + '\"'

                            # Set
                            codeList[i]['parameters'][4] = translatedText
                            scriptList.pop(0)

            ## Event Code: 357 [Picture Text] [Optional]
            if 'code' in codeList[i] and codeList[i]['code'] == 357 and CODE357 is True:
                headerString = codeList[i]['parameters'][0]

                if headerString == 'LL_GalgeChoiceWindow':
                    ### Message Text First
                    jaString = codeList[i]['parameters'][3]['messageText']

                    # Remove any textwrap & TL
                    jaString = re.sub(r'\n', ' ', jaString)
                    response = translateGPT(jaString, '', False)
                    translatedText = response[0]
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]

                    # Textwrap & Set
                    translatedText = textwrap.fill(translatedText, width=WIDTH)
                    codeList[i]['parameters'][3]['messageText'] = translatedText

                    ### Choices
                    jaString = codeList[i]['parameters'][3]['choices']
                    matchList = re.findall(r'"label[\\]*":[\\]*"(.*?)[\\]', jaString)
                    if matchList != None:
                        # Translate
                        question = codeList[i]['parameters'][3]['messageText']
                        response = translateGPT(matchList, f'Previous text for context: {question}\n\nThis will be a dialogue option', True)
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]
                        translatedText = jaString

                        # Replace Strings
                        for j in range(len(matchList)):
                            translatedText = translatedText.replace(matchList[j], response[0][j])

                        # Set Data
                        codeList[i]['parameters'][3]['choices'] = translatedText

                if 'SoR_GabWindow' in headerString:
                    argVar = 'arg1'
                    ### Message Text First
                    if argVar in codeList[i]['parameters'][3]:
                        jaString = codeList[i]['parameters'][3][argVar]

                        # If there isn't any Japanese in the text just skip
                        if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', jaString):
                            i += 1
                            continue

                        # Remove any textwrap & TL
                        jaString = re.sub(r'\n', ' ', jaString)
                        response = translateGPT(jaString, '', False)
                        translatedText = response[0]
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]

                        # Textwrap & Set
                        translatedText = textwrap.fill(translatedText, width=WIDTH)
                        codeList[i]['parameters'][3][argVar] = translatedText
                        pbar.update(1)
                
            ## Event Code: 657 [Picture Text] [Optional]
            if 'code' in codeList[i] and codeList[i]['code'] == 657 and CODE657 is True:
                if 'text' in codeList[i]['parameters'][0]:
                    jaString = codeList[i]['parameters'][0]
                    if not isinstance(jaString, str):
                        i += 1
                        continue
                    
                    # Definitely don't want to mess with files
                    if '_' in jaString:
                        i += 1
                        continue

                    # If there isn't any Japanese in the text just skip
                    if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', jaString):
                        i += 1
                        continue

                    # Remove outside text
                    startString = re.search(r'^[^一-龠ぁ-ゔァ-ヴー\<\>【】\\]+', jaString)
                    jaString = re.sub(r'^[^一-龠ぁ-ゔァ-ヴー\<\>【】\\]+', '', jaString)
                    endString = re.search(r'[^一-龠ぁ-ゔァ-ヴー\<\>【】。！？\\]+$', jaString)
                    jaString = re.sub(r'[^一-龠ぁ-ゔァ-ヴー\<\>【】。！？\\]+$', '', jaString)
                    if startString is None:
                        startString = ''
                    else:
                        startString = startString.group()
                    if endString is None:
                        endString = ''
                    else:
                        endString = endString.group()

                    # Remove any textwrap
                    jaString = re.sub(r'\n', ' ', jaString)

                    # Translate
                    response = translateGPT(jaString, '', True)
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]
                    translatedText = response[0]

                    # Remove characters that may break scripts
                    charList = ['.', '\"', "'"]
                    for char in charList:
                        translatedText = translatedText.replace(char, '')

                    # Textwrap
                    translatedText = textwrap.fill(translatedText, width=WIDTH)
                    translatedText = startString + translatedText + endString

                    # Set Data
                    codeList[i]['parameters'][0] = translatedText

        ## Event Code: 101 [Name] [Optional]
            if 'code' in codeList[i] and codeList[i]['code'] == 101 and CODE101 is True:
                isVar = False
                
                # Grab String
                jaString = ''  
                if len(codeList[i]['parameters']) > 4:
                    jaString = codeList[i]['parameters'][4]
                # Check for Var
                elif len(codeList[i]['parameters']) > 0:
                    jaString = codeList[i]['parameters'][0]
                    isVar = True
                if not isinstance(jaString, str):
                    i += 1
                    continue

                # Force Speaker using var
                if 'ari' in jaString.lower():
                    speaker = 'Arisa'
                    i += 1
                    continue
                elif 'riika' in jaString.lower():
                    speaker = 'Rika'
                    i += 1
                    continue
                elif 'sutera' in jaString.lower():
                    speaker = 'Stella'
                    i += 1
                    continue

                # Get Speaker
                response = getSpeaker(jaString)
                totalTokens[0] += response[1][0]
                totalTokens[1] += response[1][1]
                speaker = response[0]
                
                # Validate Speaker is not empty
                if len(speaker) > 0:
                    if isVar == False:
                        codeList[i]['parameters'][4] = speaker
                        i += 1
                        continue
                    else:
                        codeList[i]['parameters'][0] = speaker
                        isVar = False
                        i += 1
                        continue
                else:
                    speaker = ''

            ## Event Code: 355 or 655 Scripts [Optional]
            if 'code' in codeList[i] and (codeList[i]['code'] == 355 or codeList[i]['code'] == 655) and CODE355655 is True:
                matchList = []
                jaString = codeList[i]['parameters'][0]

                # Skip Console Logs
                if 'console.log' in jaString:
                    i += 1
                    continue
                # Skip if
                if 'if(' in jaString:
                    i += 1
                    continue
                # Skip if
                if 'list' in jaString:
                    i += 1
                    continue

                stringList = []
                matchList = re.findall(r"this.BLogAdd\(.+?\"(.+?)\"", jaString)
                if len(matchList) > 0:
                    for match in matchList:
                        # Remove Textwrap
                        match = match.replace('\\n', ' ')
                        stringList.append(match)

                # If there isn't any Japanese in the text just skip
                # if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', jaString):
                #     continue

                # Skip These
                # if 'this.' in jaString:
                #     continue

                # Need to remove outside code and put it back later
                # matchList = re.findall(r'.+"(.*?)".*[;,]$', jaString)

                # Want to translate this script
                if 'this.BLogAdd' not in jaString:
                    i += 1
                    continue

                # Translate
                if len(matchList) > 0:

                    response = translateGPT(stringList, 'Reply with the '+ LANGUAGE +' translation of the text.', True)
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]
                    translatedTextList = response[0]
                    translatedText = jaString
                    
                    # Replace Each Instance
                    for j in range(len(translatedTextList)):
                        # Remove characters that may break scripts
                        translatedTextList[j] = translatedTextList[j].replace('"', r'\"')
                        translatedTextList[j] = translatedTextList[j].replace("'", r"\'")
                        translatedTextList[j] = translatedTextList[j].replace(".", r"\.")
                        
                        # Wordwrap
                        translatedTextList[j] = textwrap.fill(translatedTextList[j], width=WIDTH).replace('\n', '\\n')

                        # Replace Instance
                        translatedText = translatedText.replace(matchList[j], translatedTextList[j])

                    # Set Data
                    codeList[i]['parameters'][0] = translatedText

            ## Event Code: 408 (Script)
            if 'code' in codeList[i] and (codeList[i]['code'] == 408) and CODE408 is True:
                jaString = codeList[i]['parameters'][0]

                # If there isn't any Japanese in the text just skip
                if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', jaString):
                    i += 1
                    continue

                if 'secretText' in jaString:
                    regex = r'secretText:\s?(.+)'
                elif 'title' in jaString:
                    regex = r'title:\s?(.+)'
                else:
                    regex = r'(.+)'

                # Need to remove outside code and put it back later
                matchList = re.findall(regex, jaString)
                
                for match in matchList:
                    # Remove Textwrap
                    match = match.replace('\n', ' ')
                    response = translateGPT(match, 'Reply with the '+ LANGUAGE +' translation of the achievement title.', False)
                    translatedText = response[0]
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]

                    # Replace
                    translatedText = jaString.replace(match, translatedText)

                    # Remove characters that may break scripts
                    charList = ['.', '\"', '\\n']
                    for char in charList:
                        translatedText = translatedText.replace(char, '')

                    # Textwrap
                    translatedText = textwrap.fill(translatedText, width=WIDTH)

                    # Set Data
                    codeList[i]['parameters'][0] = translatedText

            ## Event Code: 108 (Script)
            if 'code' in codeList[i] and (codeList[i]['code'] == 108) and CODE108 is True:
                jaString = codeList[i]['parameters'][0]

                # If there isn't any Japanese in the text just skip
                if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', jaString):
                    i += 1
                    continue

                # Translate
                if 'info:' in jaString:
                    regex = r'info:(.*)'
                elif 'ActiveMessage:' in jaString:
                    regex = r'<ActiveMessage:(.*)>'
                elif 'event_text' in jaString:
                    regex = r'event_text\s?:\s?(.*)'
                else:
                    i += 1
                    continue

                # Need to remove outside code and put it back later
                matchList = re.findall(regex, jaString)

                # Translate
                if len(matchList) > 0:
                    response = translateGPT(matchList[0], 'Reply with the '+ LANGUAGE +' translation of the text.', False)
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]
                    translatedText = response[0]

                    # Remove characters that may break scripts
                    charList = ['.', '\"']
                    for char in charList:
                        translatedText = translatedText.replace(char, '')
                    translatedText = translatedText.replace('"', '\"')
                    translatedText = translatedText.replace(' ', '_')
                    translatedText = jaString.replace(matchList[0], translatedText)

                    # Set Data
                    codeList[i]['parameters'][0] = translatedText

            ## Event Code: 356
            if 'code' in codeList[i] and codeList[i]['code'] == 356 and CODE356 is True:
                jaString = codeList[i]['parameters'][0]
                oldjaString = jaString

                # Grab Speaker
                if 'Tachie showName' in jaString:
                    matchList = re.findall(r'Tachie showName (.+)', jaString)
                    if len(matchList) > 0:
                        # Translate
                        response = translateGPT(matchList[0], 'Reply with the '+ LANGUAGE +' translation of the NPC name.', False)
                        translatedText = response[0]
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]

                        # Set Text
                        speaker = translatedText
                        speaker = speaker.replace(' ', ' ')
                        codeList[i]['parameters'][0] = jaString.replace(matchList[0], speaker)
                    i += 1
                    continue

                # Want to translate this script
                if 'D_TEXT ' in jaString:
                    regex = r'D_TEXT\s(.*?)\s.+'
                elif 'ShowInfo':
                    regex = r'ShowInfo\s(.*)'
                elif 'PushGab':
                    regex = r'PushGab\s(.*)'
                elif 'addLog':
                    regex = r'addLog\s(.*)'
                else:
                    regex = r''

                # Remove any textwrap
                jaString = re.sub(r'\n', '_', jaString)

                # Capture Arguments and text
                textMatch = re.search(regex, jaString)
                if textMatch != None:
                    text = textMatch.group(1)

                    # Using this to keep track of 401's in a row. Throws IndexError at EndOfList (Expected Behavior)
                    currentGroup.append(text)

                    # Check Next Codes for text
                    while (codeList[i+1]['code'] == 356):
                        match = re.search(regex, codeList[i+1]['parameters'][0])
                        if match == None:
                            break
                        else:
                            jaString = codeList[i+1]['parameters'][0]
                            textMatch = re.search(regex, jaString)
                            if textMatch != None:
                                currentGroup.append(textMatch.group(1))
                            i += 1

                    # Set Final List
                    finalList = currentGroup

                    # Clear Group and Reset Index
                    currentGroup = [] 
                    i = i - len(finalList) + 1

                    # Translate
                    response = translateGPT(finalList, 'Reply with the '+ LANGUAGE +' Translation.', True)
                    finalListTL = response[0]
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]                        

                    for j in range(len(finalListTL)):
                        # Grab String Again For Replace
                        jaString = codeList[i]['parameters'][0]
                        textMatch = re.search(regex, jaString)
                        if textMatch != None:
                            text = textMatch.group(1)

                        # Grab
                        translatedText = finalListTL[j]

                        # Textwrap
                        translatedText = textwrap.fill(translatedText, width=LISTWIDTH, drop_whitespace=False)

                        # Remove characters that may break scripts
                        charList = ['.', '\"']
                        for char in charList:
                            translatedText = translatedText.replace(char, '')
                        
                        # Cant have spaces?
                        translatedText = translatedText.replace(' ', '_')

                        # Fix spacing after ___
                        translatedText = translatedText.replace('__\n', '__')
                    
                        # Put Args Back
                        translatedText = jaString.replace(text, translatedText)
                        
                        # Set Data
                        codeList[i]['parameters'][0] = translatedText
                        i += 1
                    else:
                        i += 1
                        continue

                if 'namePop' in jaString:
                    matchList = re.findall(r'namePop\s\d+\s(.+?)\s.+', jaString)
                    if len(matchList) > 0:
                        # Translate
                        text = matchList[0]
                        response = translateGPT(text, 'Reply with the '+ LANGUAGE +' Translation', False)
                        translatedText = response[0]
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]

                        # Set Data
                        translatedText = jaString.replace(text, translatedText)
                        codeList[i]['parameters'][0] = translatedText

                if 'LL_InfoPopupWIndowMV' in jaString:
                    matchList = re.findall(r'LL_InfoPopupWIndowMV\sshowWindow\s(.+?) .+', jaString)
                    if len(matchList) > 0:
                        # Translate
                        text = matchList[0]
                        response = translateGPT(text, 'Reply with the '+ LANGUAGE +' Translation', False)
                        translatedText = response[0]
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]

                        # Set Data
                        translatedText = translatedText.replace(' ', '_')
                        translatedText = jaString.replace(text, translatedText)
                        codeList[i]['parameters'][0] = translatedText

                if 'OriginMenuStatus SetParam' in jaString:
                    matchList = re.findall(r'OriginMenuStatus\sSetParam\sparam[\d]\s(.*)', jaString)
                    if len(matchList) > 0:
                        # Translate
                        text = matchList[0]
                        response = translateGPT(text, 'Reply with the '+ LANGUAGE +' Translation', False)
                        translatedText = response[0]
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]

                        # Set Data
                        translatedText = translatedText.replace(' ', '_')
                        translatedText = jaString.replace(text, translatedText)
                        codeList[i]['parameters'][0] = translatedText

                # LL_GalgeChoiceWindowMV Message
                if  'LL_GalgeChoiceWindowMV setMessageText' in jaString:
                    ### Message Text First
                    match = re.search(r'LL_GalgeChoiceWindowMV setMessageText (.+)', jaString)
                    if match:
                        jaString = match.group(1)

                        # Remove any textwrap & TL
                        jaString = re.sub(r'\n', ' ', jaString)
                        response = translateGPT(jaString, '', False)
                        translatedText = response[0]
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]

                        # Textwrap & Replace Whitespace
                        translatedText = textwrap.fill(translatedText, width=WIDTH)
                        translatedText = translatedText.replace(' ', '_')

                        # Replace and Set
                        translatedText = match.group(0).replace(match.group(1), translatedText)
                        codeList[i]['parameters'][0] = translatedText

                # LL_GalgeChoiceWindowMV Choices
                if 'LL_GalgeChoiceWindowMV setChoices':
                    match = re.search(r'LL_GalgeChoiceWindowMV setChoices (.+)', jaString)
                    if match:
                        jaString = match.group(1)
                        choiceList = jaString.split(',')

                        # Translate
                        question = translatedText
                        response = translateGPT(choiceList, f'Previous text for context: {question}\n\nThis will be a dialogue option', True)
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]
                        choiceListTL = response[0]
                        translatedText = match.group(0)

                        # Replace Strings
                        for j in range(len(choiceListTL)):
                            choiceListTL[j] = choiceListTL[j].replace(' ', '_')
                            translatedText = translatedText.replace(choiceList[j], choiceListTL[j])

                        # Set Data
                        codeList[i]['parameters'][0] = translatedText
        
            ### Event Code: 102 Show Choice
            if 'code' in codeList[i] and codeList[i]['code'] == 102 and CODE102 is True:
                choiceList = []
                varList = []
                for choice in range(len(codeList[i]['parameters'][0])):
                    jaString = codeList[i]['parameters'][0][choice]
                    jaString = jaString.replace(' 。', '.')

                    # Avoid Empty Strings
                    if jaString == '':
                        i += 1
                        continue

                    # If and En Statements
                    ifVar = ''
                    enVar = ''
                    ifList = re.findall(r'(if\(.*?\))', jaString)
                    enList = re.findall(r'(en\(.*?\))', jaString)
                    if len(ifList) != 0:
                        jaString = jaString.replace(ifList[0], '')
                        ifVar = ifList[0]
                    if len(enList) != 0:
                        jaString = jaString.replace(enList[0], '')
                        enVar = enList[0]
                    varList.append(ifVar + enVar)

                    # Append to List
                    choiceList.append(jaString)

                # Translate
                if len(textHistory) > 0:
                    response = translateGPT(choiceList, 'This will be a dialogue option. Previous text for context: ' + textHistory[len(textHistory)-1] + '\n\nThis will be a dialogue option', True)
                    translatedTextList = response[0]
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]
                else:
                    response = translateGPT(choiceList, 'This will be a dialogue option', True)
                    translatedTextList = response[0]
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]

                # Check Mismatch
                if len(translatedTextList) == len(choiceList):
                    for choice in range(len(codeList[i]['parameters'][0])):
                        translatedText = translatedTextList[choice]

                        # Set Data
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]
                        if translatedText != '':
                            translatedText = varList[choice] + translatedText[0].upper() + translatedText[1:]
                        else:
                            translatedText = varList[choice] + translatedText
                        codeList[i]['parameters'][0][choice] = translatedText
                else:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)

            ### Event Code: 111 Script
            if 'code' in codeList[i] and codeList[i]['code'] == 111 and CODE111 is True:
                for j in range(len(codeList[i]['parameters'])):
                    jaString = codeList[i]['parameters'][j]

                    # Check if String
                    if not isinstance(jaString, str):
                        i += 1
                        continue

                    # Only TL the Game Variable
                    if '$gameVariables' not in jaString:
                        i += 1
                        continue

                    # This is going to be the var being set. (IMPORTANT)
                    if '1045' not in jaString:
                        i += 1
                        continue

                    # Need to remove outside code and put it back later
                    matchList = re.findall(r"'(.*?)'", jaString)
                    
                    for match in matchList:
                        response = translateGPT(match, '', False)
                        translatedText = response[0]
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]

                        # Remove characters that may break scripts
                        charList = ['.', '\"', '\'', '\\n']
                        for char in charList:
                            translatedText = translatedText.replace(char, '')

                        jaString = jaString.replace(match, translatedText)

                    # Set Data
                    translatedText = jaString
                    codeList[i]['parameters'][j] = translatedText

            ### Event Code: 320 Set Variable
            if 'code' in codeList[i] and codeList[i]['code'] == 320 and CODE320 is True:
                jaString = codeList[i]['parameters'][1]
                if not isinstance(jaString, str):
                    i += 1
                    continue
                
                # Definitely don't want to mess with files
                if '■' in jaString or '_' in jaString:
                    i += 1
                    continue

                # If there isn't any Japanese in the text just skip
                if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', jaString):
                    i += 1
                    continue
                
                # Translate
                getSpeaker(jaString)

                # Remove characters that may break scripts
                charList = ['.', '\"', '\'', '\\n']
                for char in charList:
                    translatedText = translatedText.replace(char, '')

                # Set Data
                codeList[i]['parameters'][1] = translatedText
            
            # Iterate
            else:
                i += 1

        # End of the line
        docListTL = []
        scriptListTL = []
        setData = False
        PBAR = pbar
        
        # 401
        if len(docList) > 0:
            response = translateGPT(docList, textHistory, True)
            docListTL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            if len(docListTL) != len(docList):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)
            else:
                setData = True

        # 122
        if len(scriptList) > 0:
            response = translateGPT(scriptList, textHistory, True)
            scriptListTL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            if len(scriptListTL) != len(scriptList):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)
            else:
                setData = True

        # Start Pass 2
        if setData:
            searchCodes(page, pbar, [docListTL, scriptListTL], filename)

        # Delete all -1 codes
        codeListFinal = []
        for i in range(len(codeList)):
            if 'code' in codeList[i] and codeList[i]['code'] != -1:
                codeListFinal.append(codeList[i])

        # Normal Format
        if 'list' in page:
            page['list'] = codeListFinal

        # Special Format (Scenario)
        else:
            page = codeListFinal

    except IndexError as e:
        traceback.print_exc()
        raise Exception(str(e) + 'Failed to translate: ' + oldjaString) from None
    except Exception as e:
        traceback.print_exc()
        raise Exception(str(e) + 'Failed to translate: ' + oldjaString) from None   

    return totalTokens

def searchSS(state, pbar):
    totalTokens = [0, 0]

    # Name
    nameResponse = translateGPT(state['name'], 'Reply with only the '+ LANGUAGE +' translation of the RPG Skill name.', False) if 'name' in state else ''

    # Description
    descriptionResponse = translateGPT(state['description'], 'Reply with only the '+ LANGUAGE +' translation of the description.', False) if 'description' in state else ''

    # Messages
    message1Response = ''
    message4Response = ''
    message2Response = ''
    message3Response = ''
    
    if 'message1' in state:
        if len(state['message1']) > 0 and state['message1'][0] in ['は', 'を', 'の', 'に', 'が']:
            message1Response = translateGPT('Taro' + state['message1'], 'reply with only the gender neutral '+ LANGUAGE +' translation of the action log. Always start the sentence with Taro. For example,\
Translate \'Taroを倒した！\' as \'Taro was defeated!\'', False)
        else:
            message1Response = translateGPT(state['message1'], 'reply with only the gender neutral '+ LANGUAGE +' translation', False)

    if 'message2' in state:
        if len(state['message2']) > 0 and state['message2'][0] in ['は', 'を', 'の', 'に', 'が']:
            message2Response = translateGPT('Taro' + state['message2'], 'reply with only the gender neutral '+ LANGUAGE +' translation of the action log. Always start the sentence with Taro. For example,\
Translate \'Taroを倒した！\' as \'Taro was defeated!\'', False)
        else:
            message2Response = translateGPT(state['message2'], 'reply with only the gender neutral '+ LANGUAGE +' translation', False)

    if 'message3' in state:
        if len(state['message3']) > 0 and state['message3'][0] in ['は', 'を', 'の', 'に', 'が']:
            message3Response = translateGPT('Taro' + state['message3'], 'reply with only the gender neutral '+ LANGUAGE +' translation of the action log. Always start the sentence with Taro. For example,\
Translate \'Taroを倒した！\' as \'Taro was defeated!\'', False)
        else:
            message3Response = translateGPT(state['message3'], 'reply with only the gender neutral '+ LANGUAGE +' translation', False)

    if 'message4' in state:
        if len(state['message4']) > 0 and state['message4'][0] in ['は', 'を', 'の', 'に', 'が']:
            message4Response = translateGPT('Taro' + state['message4'], 'reply with only the gender neutral '+ LANGUAGE +' translation of the action log. Always start the sentence with Taro. For example,\
Translate \'Taroを倒した！\' as \'Taro was defeated!\'', False)
        else:
            message4Response = translateGPT(state['message4'], 'reply with only the gender neutral '+ LANGUAGE +' translation', False)

    # if 'note' in state:
    if 'help' in state['note']:
        totalTokens[0] += translateNote(state, r'<help:([^>]*)>')[0]
        totalTokens[1] += translateNote(state, r'<help:([^>]*)>')[1]
    
    # Count totalTokens
    totalTokens[0] += nameResponse[1][0] if nameResponse != '' else 0
    totalTokens[1] += nameResponse[1][1] if nameResponse != '' else 0
    totalTokens[0] += descriptionResponse[1][0] if descriptionResponse != '' else 0
    totalTokens[1] += descriptionResponse[1][1] if descriptionResponse != '' else 0
    totalTokens[0] += message1Response[1][0] if message1Response != '' else 0
    totalTokens[1] += message1Response[1][1] if message1Response != '' else 0
    totalTokens[0] += message2Response[1][0] if message2Response != '' else 0
    totalTokens[1] += message2Response[1][1] if message2Response != '' else 0
    totalTokens[0] += message3Response[1][0] if message3Response != '' else 0
    totalTokens[1] += message3Response[1][1] if message3Response != '' else 0
    totalTokens[0] += message4Response[1][0] if message4Response != '' else 0
    totalTokens[1] += message4Response[1][1] if message4Response != '' else 0

    # Set Data
    if 'name' in state:
        state['name'] = nameResponse[0].replace('\"', '')
    if 'description' in state:
        # Textwrap
        translatedText = descriptionResponse[0]
        translatedText = textwrap.fill(translatedText, width=LISTWIDTH)
        state['description'] = translatedText.replace('\"', '')
    if 'message1' in state:
        state['message1'] = message1Response[0].replace('\"', '').replace('Taro', '')
    if 'message2' in state:
        state['message2'] = message2Response[0].replace('\"', '').replace('Taro', '')
    if 'message3' in state:
        state['message3'] = message3Response[0].replace('\"', '').replace('Taro', '')
    if 'message4' in state:
        state['message4'] = message4Response[0].replace('\"', '').replace('Taro', '')

    
    return totalTokens

def searchSystem(data, pbar):
    totalTokens = [0, 0]
    context = 'Reply with only the '+ LANGUAGE +' translation of the UI textbox."'

    # Title
    response = translateGPT(data['gameTitle'], ' Reply with the '+ LANGUAGE +' translation of the game title name', False)
    totalTokens[0] += response[1][0]
    totalTokens[1] += response[1][1]
    data['gameTitle'] = response[0].strip('.')
    
    
    # Terms
    for term in data['terms']:
        if term != 'messages':
            termList = data['terms'][term]
            for i in range(len(termList)):  # Last item is a messages object
                if termList[i] is not None:
                    response = translateGPT(termList[i], context, False)
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]
                    termList[i] = response[0].replace('\"', '').strip()
                    

    # Armor Types
    for i in range(len(data['armorTypes'])):
        response = translateGPT(data['armorTypes'][i], 'Reply with only the '+ LANGUAGE +' translation of the armor type', False)
        totalTokens[0] += response[1][0]
        totalTokens[1] += response[1][1]
        data['armorTypes'][i] = response[0].replace('\"', '').strip()
        

    # Skill Types
    for i in range(len(data['skillTypes'])):
        response = translateGPT(data['skillTypes'][i], 'Reply with only the '+ LANGUAGE +' translation', False)
        totalTokens[0] += response[1][0]
        totalTokens[1] += response[1][1]
        data['skillTypes'][i] = response[0].replace('\"', '').strip()
        

    # Equip Types
    for i in range(len(data['equipTypes'])):
        response = translateGPT(data['equipTypes'][i], 'Reply with only the '+ LANGUAGE +' translation of the equipment type. No disclaimers.', False)
        totalTokens[0] += response[1][0]
        totalTokens[1] += response[1][1]
        data['equipTypes'][i] = response[0].replace('\"', '').strip()
        

    # Variables (Optional ususally)
    # for i in range(len(data['variables'])):
    #     response = translateGPT(data['variables'][i], 'Reply with only the '+ LANGUAGE +' translation of the title', False)
    #     totalTokens[0] += response[1][0]
    #     totalTokens[1] += response[1][1]
    #     data['variables'][i] = response[0].replace('\"', '').strip()
    #     

    # Messages
    messages = (data['terms']['messages'])
    for key, value in messages.items():
        response = translateGPT(value, 'Reply with only the '+ LANGUAGE +' translation of the battle text.\nTranslate "常時ダッシュ" as "Always Dash"\nTranslate "次の%1まで" as Next %1.', False)
        translatedText = response[0]

        # Remove characters that may break scripts
        charList = ['.', '\"', '\\n']
        for char in charList:
            translatedText = translatedText.replace(char, '')

        totalTokens[0] += response[1][0]
        totalTokens[1] += response[1][1]
        messages[key] = translatedText
        
    
    return totalTokens

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
                response = translateGPT(speaker, 'Reply with the '+ LANGUAGE +' translation of the NPC name.', False)
                response[0] = response[0].title()
                response[0] = response[0].replace("'S", "'s")

                # Retry if name doesn't translate for some reason
                if re.search(r'([a-zA-Z？?])', response[0]) == None:
                    response = translateGPT(speaker, 'Reply with the '+ LANGUAGE +' translation of the NPC name.', False)
                    response[0] = response[0].title()
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
        matchList = re.findall(pattern, translatedTextList, flags=re.DOTALL)
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
