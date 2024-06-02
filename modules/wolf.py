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
NAMESLIST = []   # Keep list for consistency
TERMSLIST = []   # Keep list for consistency
NAMES = False    # Output a list of all the character names found
BRFLAG = False   # If the game uses <br> instead
FIXTEXTWRAP = True  # Overwrites textwrap
IGNORETLTEXT = False    # Ignores all translated text.
MISMATCH = []   # Lists files that throw a mismatch error (Length of GPT list response is wrong)
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

# Dialogue / Scroll
CODE101 = True
CODE102 = True
CODE122 = True

# Other
CODE210 = True
CODE300 = True
CODE250 = True

# Database
NPCFLAG = True
SCENARIOFLAG = True
ITEMFLAG = True
COLLECTIONFLAG = True
ARMORFLAG = True
OTHERFLAG = True

def handleWOLF(filename, estimate):
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
        if "'events':" in str(data):
            if len(data['events']) > 0:
                translatedData = parseMap(data, filename)
            else:
                return [data, [0,0], None]

        # Map Files
        elif "'types':" in str(data):
            translatedData = parseDB(data, filename)

        # Other Files
        elif "'commands':" in str(data):
            translatedData = parseOther(data, filename)
            
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

def parseOther(data, filename):
    totalTokens = [0, 0]
    totalLines = 0
    events = data['commands']
    global LOCK
    
    # Thread for each page in file
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE) as pbar:
        pbar.desc=filename
        pbar.total=totalLines
        translationData = searchCodes(events, pbar, [], filename)
        try:
            totalTokens[0] += translationData[0]
            totalTokens[1] += translationData[1]
        except Exception as e:
            return [data, totalTokens, e]
    return [data, totalTokens, None]

def parseDB(data, filename):
    totalTokens = [0, 0]
    totalLines = 0
    events = data['types']
    global LOCK
    
    # Thread for each page in file
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, leave=LEAVE) as pbar:
        pbar.desc=filename
        pbar.total=totalLines
        translationData = searchDB(events, pbar, [], filename)
        try:
            totalTokens[0] += translationData[0]
            totalTokens[1] += translationData[1]
        except Exception as e:
            return [data, totalTokens, e]
    return [data, totalTokens, None]

def parseMap(data, filename):
    totalTokens = [0, 0]
    totalLines = 0
    events = data['events']
    global LOCK

    # Get total for progress bar
    for event in events:
        if event is not None:
            for page in event['pages']:
                totalLines += len(page['list'])
    
    # Thread for each page in file
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
        pbar.desc=filename
        pbar.total=totalLines
        with ThreadPoolExecutor(max_workers=THREADS) as executor:
            for event in events:
                if event is not None:
                    futures = [executor.submit(searchCodes, page['list'], pbar, [], filename) for page in event['pages'] if page is not None]
                    for future in as_completed(futures):
                        try:
                            totalTokensFuture = future.result()
                            totalTokens[0] += totalTokensFuture[0]
                            totalTokens[1] += totalTokensFuture[1]
                        except Exception as e:
                            return [data, totalTokens, e]
    return [data, totalTokens, None]

def searchCodes(events, pbar, translatedList, filename):
    codeList = events
    stringList = []
    textHistory = []
    totalTokens = [0, 0]
    translatedText = ''
    speaker = ''
    nametag = ''
    initialJAString = ''
    global LOCK
    global NAMESLIST
    global MISMATCH

    # Calculate Total Length
    code_flags = {
        102: CODE102,
        122: CODE122,
        300: CODE300,
        250: CODE250
    }
    totalList = 0
    for code_item in codeList:
        if code_flags.get(code_item['code'], False):
            totalList += 1
    pbar.total = totalList
    pbar.refresh()
    
    # Begin Parsing File
    try:
        # Iterate through events
        i = 0
        while i < len(codeList):
            ### Event Code: 101 Message
            if codeList[i]['code'] == 101 and CODE101 == True:
                # Grab String
                jaString = codeList[i]['stringArgs'][0]
                initialJAString = jaString

                # Catch Vars that may break the TL
                varString = ''
                matchList = re.findall(r'^[\\_]+[\w]+\[[a-zA-Z0-9\\\[\]\_,\s-]+\]', jaString)    
                if len(matchList) != 0:
                    varString = matchList[0]
                    jaString = jaString.replace(matchList[0], '')

                # Grab Speaker
                if '：\n' in jaString:
                    nameList = re.findall(r'(.*)：\n', jaString)
                    if nameList is not None:
                        # TL Speaker
                        response = getSpeaker(nameList[0], pbar, filename)
                        speaker = response[0]
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]
                                                
                        # Set nametag and remove from string
                        nametag = f'{speaker}：\n'
                        jaString = jaString.replace(f'{nameList[0]}：\n', '')

                # Remove Textwrap
                jaString = jaString.replace('\n', ' ')

                # 1st Pass (Save Text to List)
                if len(translatedList) == 0:
                    if speaker == '':
                        stringList.append(jaString)
                    else:
                        stringList.append(f'[{speaker}]: {jaString}')

                # 2nd Pass (Set Text)
                else:
                    # Grab Translated String
                    translatedText = translatedList[0]
                    
                    # Remove speaker
                    matchSpeakerList = re.findall(r'^(\[.+?\]\s?[|:]\s?)\s?', translatedText)
                    if len(matchSpeakerList) > 0:
                        translatedText = translatedText.replace(matchSpeakerList[0], '')

                    # Textwrap
                    if FIXTEXTWRAP is True:
                        translatedText = textwrap.fill(translatedText, width=WIDTH)

                    # Add back Nametag
                    translatedText = nametag + translatedText
                    nametag = ''

                    # Add back Potential Variables in String
                    translatedText = varString + translatedText

                    # Set Data
                    codeList[i]['stringArgs'][0] = translatedText

                    # Reset Data and Pop Item
                    speaker = ''
                    translatedList.pop(0)
                    
                    # If this is the last item in list, set to empty string
                    if len(translatedList) == 0:
                        translatedList = ''

            ### Event Code: 102 Choices
            if codeList[i]['code'] == 102 and CODE102 == True:
                # Grab Choice List
                choiceList = codeList[i]['stringArgs']

                # Translate
                response = translateGPT(choiceList, f'Reply with the {LANGUAGE} translation of the dialogue choice', True, pbar, filename)
                translatedChoiceList = response[0]
                totalTokens[0] = response[1][0]
                totalTokens[1] = response[1][1]

                # Validate and Set Data
                if len(choiceList) == len(translatedChoiceList):
                    codeList[i]['stringArgs'] = translatedChoiceList

            ### Event Code: 210 Common Event
            if codeList[i]['code'] == 210 and CODE210 == True:
                if 'stringArgs' in codeList[i] and len(codeList[i]['stringArgs']) > 1:
                    # Grab Event List
                    jaString = codeList[i]['stringArgs'][1]

                    # Translate
                    response = translateGPT(jaString, f'Reply with the {LANGUAGE} translation of the location', False, pbar, filename)
                    translatedText = response[0]
                    totalTokens[0] = response[1][0]
                    totalTokens[1] = response[1][1]

                    # Validate and Set Data
                    codeList[i]['stringArgs'][1] = translatedText

            ### Event Code: 122 SetString
            if codeList[i]['code'] == 122 and CODE122 == True:
                if 'stringArgs' in codeList[i] and len(codeList[i]['stringArgs']) > 0:
                    # Grab String
                    jaString = codeList[i]['stringArgs'][0]

                    # Translate Conversations
                    if '：Nothing' in jaString:
                        # Separate into list
                        stringList = jaString.split('\n\n')

                        # Remove Textwrap
                        for j in range(len(stringList)):
                            stringList[j] = stringList[j].replace('\n', ' ')

                        # Translate
                        response = translateGPT(stringList, f'Reply with the {LANGUAGE} translation of the text', True, pbar, filename)
                        translatedList = response[0]
                        totalTokens[0] = response[1][0]
                        totalTokens[1] = response[1][1]

                        # Validate and Set Data
                        if len(stringList) == len(translatedList):
                            # Adjust Speaker and Add Textwrap
                            for j in range(len(translatedList)):
                                translatedList[j] = textwrap.fill(translatedList[j], WIDTH)
                                translatedList[j] = re.sub(r'^\[?(.+?)\]?:', r'\1：', translatedList[j])
                                translatedList[j] = translatedList[j].replace('：', '：\n')
                                translatedList[j] = translatedList[j].replace('：\n ', '：\n')

                            # Join back into single string
                            translatedList = '\n\n'.join(translatedList)
                            
                            # Set String
                            codeList[i]['stringArgs'][0] = translatedList
                    
                    # Translate Other Strings [Specific Files Only]
                    else:
                        if not re.search(r'\.[\w]+$', jaString)\
                        and jaString != ''\
                        and '_' not in jaString\
                        and '",' not in jaString\
                        and '/' not in jaString:
                            # Things to Check before starting translation
                            if re.search(r'[一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９]+', jaString):
                                # Remove Textwrap
                                jaString = jaString.replace('\n', ' ')

                                # Translate
                                response = translateGPT(jaString, f'Reply with the {LANGUAGE} translation of the text', False, pbar, filename)
                                translatedText = response[0]
                                totalTokens[0] = response[1][0]
                                totalTokens[1] = response[1][1]

                                # Textwrap
                                translatedText = textwrap.fill(translatedText, WIDTH)

                                # Set String
                                codeList[i]['stringArgs'][0] = translatedText

            ### Event Code: 300 Common Events
            if codeList[i]['code'] == 300 and CODE300 == True:
                # Validate size
                if len(codeList[i]['stringArgs']) > 1:
                    # Grab String
                    jaString = codeList[i]['stringArgs'][1]

                    # Skip Heavy Var Text
                    if 'Hシナリオtext演出' in codeList[i]['stringArgs'][0] or r'/evcg' in jaString:
                        i += 1
                        continue

                    # Catch Vars that may break the TL
                    varString = ''
                    matchList = re.findall(r'^[\\_]+[\w]+\[[a-zA-Z0-9\\\[\]\_,\s-]+\]', jaString)    
                    if len(matchList) != 0:
                        varString = matchList[0]
                        jaString = jaString.replace(matchList[0], '')

                    # Remove Textwrap
                    jaString = jaString.replace('\n', ' ')

                    # Translate
                    response = translateGPT(jaString, f'Reply with the {LANGUAGE} translation of the text.', False, pbar, filename)
                    translatedText = response[0]
                    totalTokens[0] = response[1][0]
                    totalTokens[1] = response[1][1]

                    # Add Textwrap
                    translatedText = textwrap.fill(translatedText, WIDTH)

                    # Add back Potential Variables in String
                    translatedText = varString + translatedText

                    # Set Data
                    codeList[i]['stringArgs'][1] = translatedText

            ### Event Code: 250 Common Events
            if codeList[i]['code'] == 250 and CODE250 == True:
                foundTerm = False

                # Validate size
                if len(codeList[i]['stringArgs']) > 0:
                    # Grab String
                    jaString = codeList[i]['stringArgs'][0]

                    # Catch Vars that may break the TL
                    varString = ''
                    matchList = re.findall(r'^[\\_]+[\w]+\[[a-zA-Z0-9\\\[\]\_,\s-]+\]', jaString)    
                    if len(matchList) != 0:
                        varString = matchList[0]
                        jaString = jaString.replace(matchList[0], '')

                    # Check if term already translated
                    for j in range(len(TERMSLIST)):
                        if jaString == TERMSLIST[j][0]:
                            translatedText = TERMSLIST[j][1]
                            foundTerm = True

                    # Translate
                    if foundTerm == False:
                        response = translateGPT(jaString, f'Reply with the {LANGUAGE} translation of the text.', False, pbar, filename)
                        translatedText = response[0]
                        totalTokens[0] = response[1][0]
                        totalTokens[1] = response[1][1]
                        TERMSLIST.append([jaString, translatedText])

                    # Add back Potential Variables in String
                    translatedText = varString + translatedText

                    # Set Data
                    codeList[i]['stringArgs'][0] = translatedText
        
            ### Iterate
            i += 1
             
        # End of the line
        if translatedList == [] and stringList != []:
            pbar.total = len(stringList)
            pbar.refresh()
            response = translateGPT(stringList, textHistory, True, pbar, filename)
            translatedList = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            if len(translatedList) != len(stringList):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)
            else:
                stringList = []
                searchCodes(events, pbar, translatedList, filename)
        else:         
            # Set Data
            events = codeList

    except IndexError as e:
        traceback.print_exc()
        raise Exception(str(e) + 'Failed to translate: ' + initialJAString) from None
    except Exception as e:
        traceback.print_exc()
        raise Exception(str(e) + 'Failed to translate: ' + initialJAString) from None   

    return totalTokens

# Database
def searchDB(events, pbar, jobList, filename):
    # Set Lists
    if len(jobList) > 0:
        scenarioList = jobList[0]
        NPCList = jobList[1]
        itemList = jobList[2]
        collectionList = jobList[3]
        armorList = jobList[4]
        otherList = jobList[5]
        setData = True
    else:
        scenarioList = [[],[],[]]
        NPCList = []
        itemList = [[],[],[]]
        armorList = [[],[]]
        otherList = [[],[],[],[]]
        collectionList = []
        setData = False
    
    # Vars/Globals
    translatedList = []
    totalTokens = [0, 0]
    initialJAString = ''
    tableList = events
    global LOCK
    global NAMESLIST
    global MISMATCH
    
    # Calculate Total
    totalLines = 0
    for table in tableList:
        if table['name'] == 'NPC' and NPCFLAG == True:
            for NPC in table['data']:
                totalLines += len(NPC['data'])
        if table['name'] == 'Hシナリオ' and SCENARIOFLAG == True:
            for hScenario in table['data']:
                totalLines += len(hScenario['data'])
    pbar.total = totalLines
    pbar.refresh()

    # Begin Parsing File
    try:
        for table in tableList:

            # Translate NPC Table
            if table['name'] == 'NPC' and NPCFLAG == True:
                varList = []
                stringList = []
                for NPC in table['data']:                                            
                    # TL Dialogue
                    dataList = NPC['data']

                    # Modify each string
                    for j in range(len(dataList)):
                        jaString = dataList[j].get('value')
                        # Check String
                        if j == 0:
                            continue
                        if not isinstance(jaString, str):
                            continue
                        if len(jaString) < 1:
                            continue
            
                        # Append and Replace Var
                        matchVar = re.findall(r'^\/b\r\n', jaString)
                        if len(matchVar) > 0:
                            varList.append(True)
                            jaString = re.sub(r'^\/b\r\n', '', jaString)
                        else:
                            varList.append(False)

                        # Replace special character sequences with a var
                        jaString = jaString.replace('\r\n\r\n', '[BREAK_1]')

                        # Remove the rest of the textwrap
                        jaString = jaString.replace('\n', ' ')
                        jaString = jaString.replace('\r', '')

                        # Add to List
                        stringList.append(jaString)
                        
                    # Translate
                    response = translateGPT(stringList, f'Reply with the {LANGUAGE} translation of the text.', True, pbar, filename)
                    translatedList = response[0]
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]

                    # Validate
                    if len(translatedList) != len(stringList):
                        with LOCK:
                            if filename not in MISMATCH:
                                MISMATCH.append(filename)
                    else:
                        k = 0
                        for j in range(len(dataList)):
                            jaString = dataList[j].get('value')
                            # Check String
                            if j == 0:
                                continue
                            if not isinstance(jaString, str):
                                continue
                            if len(jaString) < 1:
                                continue
                            
                            # Textwrap
                            if FIXTEXTWRAP is True:
                                translatedList[k] = textwrap.fill(translatedList[k], width=WIDTH)

                            # Replace special character sequences with a var
                            translatedList[k] = translatedList[k].replace('[BREAK_1]', '\r\n\r\n')
                            translatedList[k] = translatedList[k].replace('：', '：\r\n')
                            translatedList[k] = translatedList[k].replace(':', '：\r\n')

                            # Append and Replace Var
                            if varList[k] == True:
                                translatedList[k] = f'/b\r\n{translatedList[k]}' 

                            # Replace other /b
                            translatedList[k] = translatedList[k].replace('/b ', '/b\r\n')

                            # Remove whitespace after newline
                            translatedList[k] = translatedList[k].replace('\n ', '\n')                           
                        
                            # Set Text
                            dataList[j].update({'value': translatedList[k]})
                            k += 1

                        # Reset Lists
                        stringList.clear()
                        varList.clear()

            # Grab Scenarios
            if table['name'] == 'Hシナリオ' and SCENARIOFLAG == True:
                for hScenario in table['data']:                                            
                    dataList = hScenario['data']

                    # Parse
                    # Pass 1 (Grab Data)
                    if setData == False:
                        if dataList[1].get('value') != '':
                            scenarioList[0].append(dataList[1].get('value'))
                        if dataList[44].get('value') != '':
                            scenarioList[1].append(dataList[44].get('value'))
                        if dataList[45].get('value') != '':
                            scenarioList[2].append(dataList[45].get('value'))

                    # Pass 2 (Set Data)
                    else:
                        if dataList[1].get('value') != '':
                            dataList[1].update({'value': scenarioList[0][0]})
                            scenarioList[0].pop(0)
                        if dataList[44].get('value') != '':
                            dataList[44].update({'value': scenarioList[1][0]})
                            scenarioList[1].pop(0)
                        if dataList[45].get('value') != '':
                            dataList[45].update({'value': scenarioList[2][0]})
                            scenarioList[2].pop(0)

            # Grab Items
            if table['name'] == '道具' and ITEMFLAG == True:
                for item in table['data']:                                            
                    dataList = item['data']

                    # Parse
                    if '名前' in dataList[0].get('name') and dataList[0].get('value') != '':
                        # Pass 1 (Grab Data)
                        if setData == False:
                            itemList[0].append(dataList[0].get('value'))
                            itemList[1].append(dataList[20].get('value').replace('\n', ' '))
                            itemList[2].append(dataList[21].get('value').replace('\n', ' '))

                        # Pass 2 (Set Data)
                        else:
                            dataList[0].update({'value': itemList[0][0]})
                            itemList[0].pop(0)
                            dataList[20].update({'value': itemList[1][0]})
                            itemList[1].pop(0)
                            itemList[2][0] = textwrap.fill(itemList[2][0], LISTWIDTH)
                            dataList[21].update({'value': itemList[2][0]})
                            itemList[2].pop(0)

            # Grab Armors
            if table['name'] == '防具' and ARMORFLAG == True:
                for armor in table['data']:                                            
                    dataList = armor['data']

                    # Parse
                    if '名前' in dataList[0].get('name'):
                        # Pass 1 (Grab Data)
                        if setData == False:
                            if dataList[0].get('value') != '':
                                armorList[0].append(dataList[0].get('value'))
                            if dataList[1].get('value') != '':
                                armorList[1].append(dataList[1].get('value').replace('\n', ' '))

                        # Pass 2 (Set Data)
                        else:
                            if dataList[0].get('value') != '':
                                dataList[0].update({'value': armorList[0][0]})
                                armorList[0].pop(0)
                            if dataList[1].get('value') != '':
                                dataList[1].update({'value': armorList[1][0]})
                                armorList[1].pop(0)

            # Grab Other
            if table['name'] == 'ダンジョン敵' and OTHERFLAG == True:
                for other in table['data']:                                            
                    dataList = other['data']

                    # Parse
                    if '名前' in dataList[0].get('name'):
                        # Pass 1 (Grab Data)
                        if setData == False:
                            if dataList[0].get('value') != '':
                                otherList[0].append(dataList[0].get('value'))
                            # if dataList[1].get('value') != '':
                            #     otherList[1].append('Taro' + dataList[1].get('value'))
                            # if dataList[2].get('value') != '':
                            #     otherList[2].append('Taro' + dataList[2].get('value'))

                        # Pass 2 (Set Data)
                        else:
                            if dataList[0].get('value') != '':
                                dataList[0].update({'value': otherList[0][0]})
                                otherList[0].pop(0)
                            # if dataList[1].get('value') != '':
                            #     dataList[1].update({'value': otherList[1][0].replace('Taro', '')})
                            #     otherList[1].pop(0)
                            # if dataList[2].get('value') != '':
                            #     dataList[2].update({'value': otherList[2][0].replace('Taro', '')})
                            #     otherList[2].pop(0)

            # Grab Collection
            if table['name'] == '採取' and COLLECTIONFLAG == True:
                for object in table['data']:                                            
                    dataList = object['data']

                    # Parse
                    if dataList[15].get('value') != '' and dataList[0].get('name') == 'オブジェクト名':
                        # Pass 1 (Grab Data)
                        jaString = dataList[15].get('value')
                        speaker = re.search(r'(.*)：\r\n', jaString)
                        if setData == False:
                            collectionList.append(dataList[15].get('value'))

                        # Pass 2 (Set Data)
                        else:
                            if speaker == None:
                                # Remove speaker
                                matchSpeakerList = re.findall(r'^(\[.+?\]\s?[|:]\s?)\s?', collectionList[0])
                                if len(matchSpeakerList) > 0:
                                    collectionList[0] = collectionList[0].replace(matchSpeakerList[0], '')
                            else:
                                # Reformat Speaker
                                matchSpeaker = re.search(r'^\[(.+?)\]\s?[|:]\s?\s?(.+)', collectionList[0])
                                if matchSpeaker != None:
                                    collectionList[0] = f'{matchSpeaker.group(1)}：\r\n{matchSpeaker.group(2)}'
                            dataList[15].update({'value': collectionList[0]})
                            collectionList.pop(0)

        # Translation
        scenarioListTL = [[],[],[]]
        NPCListTL = []
        itemListTL = [[],[],[]]
        collectionListTL = []
        armorListTL = [[],[]]
        otherListTL = [[],[],[]]

        translate = False

        # SCENARIO
        if len(scenarioList[0]) > 0:
            # Progress Bar
            total = 0
            for scenarioArray in scenarioList:
                total += len(scenarioArray)
            pbar.total = total
            pbar.refresh()

            # Name
            response = translateGPT(scenarioList[0], 'Reply with only the '+ LANGUAGE +' translation', True, pbar, filename)
            nameListTL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            # Desc 1
            response = translateGPT(scenarioList[1], 'reply with only the gender neutral '+ LANGUAGE +' translation of the NPC name', True, pbar, filename)
            descListTL1 = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            # Desc 2
            response = translateGPT(scenarioList[2], 'reply with only the gender neutral '+ LANGUAGE +' translation of the NPC name', True, pbar, filename)
            descListTL2 = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]

            # Check Mismatch
            if len(nameListTL) != len(scenarioList[0]) or\
            len(descListTL1) != len(scenarioList[1]) or\
            len(descListTL2) != len(scenarioList[2]):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)
            else:
                scenarioListTL = [nameListTL, descListTL1, descListTL2]
                translate = True 

        # ITEMS
        if len(itemList[0]) > 0:
            # Progress Bar
            total = 0
            for itemArray in itemList:
                total += len(itemArray)
            pbar.total = total
            pbar.refresh()

            # Name
            response = translateGPT(itemList[0], 'Reply with only the '+ LANGUAGE +' translation of the RPG item name', True, pbar, filename)
            nameListTL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            # Desc 1
            response = translateGPT(itemList[1], 'Reply with only the '+ LANGUAGE +' translation', True, pbar, filename)
            descListTL1 = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            # Desc 2
            response = translateGPT(itemList[2], 'Reply with only the '+ LANGUAGE +' translation', True, pbar, filename)
            descListTL2 = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]

            # Check Mismatch
            if len(nameListTL) != len(itemList[0]) or\
            len(descListTL1) != len(itemList[1]) or\
            len(descListTL2) != len(itemList[2]):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)
            else:
                itemListTL = [nameListTL, descListTL1, descListTL2]
                translate = True  

        # Armor
        if len(armorList[0]) > 0:
            # Progress Bar
            total = 0
            for armorArray in armorList:
                total += len(armorArray)
            pbar.total = total
            pbar.refresh()

            # Name
            response = translateGPT(armorList[0], 'Reply with only the '+ LANGUAGE +' translation of the RPG item name', True, pbar, filename)
            nameListTL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            # Desc 1
            response = translateGPT(armorList[1], 'Reply with only the '+ LANGUAGE +' translation', True, pbar, filename)
            descListTL1 = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]

            # Check Mismatch
            if len(nameListTL) != len(armorList[0]) or\
            len(descListTL1) != len(armorList[1]):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)
            else:
                armorListTL = [nameListTL, descListTL1]
                translate = True  

        # Other
        if len(otherList[0]) > 0:
            # Progress Bar
            total = 0
            for otherArray in otherList:
                total += len(otherArray)
            pbar.total = total
            pbar.refresh()

            # Name
            response = translateGPT(otherList[0], 'Reply with only the '+ LANGUAGE +' translation of the RPG item name', True, pbar, filename)
            nameListTL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            # Desc 1
            response = translateGPT(otherList[1], 'reply with only the gender neutral '+ LANGUAGE +' translation of the action log. Always start the sentence with Taro. For example, Translate \'Taroを倒した！\' as \'Taro was defeated!\'', True, pbar, filename)
            descListTL1 = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]
            # Desc 2
            response = translateGPT(otherList[2], 'reply with only the gender neutral '+ LANGUAGE +' translation of the action log. Always start the sentence with Taro. For example, Translate \'Taroを倒した！\' as \'Taro was defeated!\'', True, pbar, filename)
            descListTL2 = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]

            # Check Mismatch
            if len(nameListTL) != len(otherList[0]) or\
            len(descListTL1) != len(otherList[1]) or\
            len(descListTL2) != len(otherList[2]):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)
            else:
                otherListTL = [nameListTL, descListTL1, descListTL2]
                translate = True  

        # COLLECTION
        if len(collectionList) > 0:
            # Progress Bar
            total = 0
            total += len(collectionList)
            pbar.total = total
            pbar.refresh()

            # Name
            response = translateGPT(collectionList, 'Reply with only the '+ LANGUAGE +' translation', True, pbar, filename)
            collectionListTL = response[0]
            totalTokens[0] += response[1][0]
            totalTokens[1] += response[1][1]

            # Check Mismatch
            if len(collectionListTL) != len(collectionList):
                with LOCK:
                    if filename not in MISMATCH:
                        MISMATCH.append(filename)
            else:
                translate = True
            
        # Start Pass 2
        if translate == True:
            jobList.append(scenarioListTL)
            jobList.append(NPCListTL)
            jobList.append(itemListTL)
            jobList.append(collectionListTL)
            jobList.append(armorListTL)
            jobList.append(otherListTL)
            searchDB(events, pbar, jobList, filename)                

    except IndexError as e:
        traceback.print_exc()
        raise Exception(str(e) + 'Failed to translate: ' + initialJAString) from None
    except Exception as e:
        traceback.print_exc()
        raise Exception(str(e) + 'Failed to translate: ' + initialJAString) from None   

    return totalTokens

# Save some money and enter the character before translation
def getSpeaker(speaker, pbar, filename):
    match speaker:
        case 'ファイン':
            return ['Fine', [0,0]]
        case '':
            return ['', [0,0]]
        case _:
            # Store Speaker
            if speaker not in str(NAMESLIST):
                response = translateGPT(speaker, 'Reply with only the '+ LANGUAGE +' translation of the NPC name.', False, pbar, filename)
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
リリア (Lilia) - Female\n\
シェリル (Sheryl) - Female\n\
チロ (Chiro) - Female\n\
メルキュール (Mercury) - Female\n\
のじゃっち (Nojachi) - Female\n\
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

def translateText(characters, system, user, history):
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
        temperature=0.1,
        frequency_penalty=0.1,
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
def translateGPT(text, history, fullPromptFlag, pbar, filename):
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
        translatedText = cleanTranslatedText(translatedText, varResponse)
        if isinstance(tItem, list):
            extractedTranslations = extractTranslation(translatedText, True)
            if len(tItem) != len(extractedTranslations):
                # Mismatch. Try Again
                response = translateText(characters, system, user, history)
                translatedText = response.choices[0].message.content
                totalTokens[0] += response.usage.prompt_tokens
                totalTokens[1] += response.usage.completion_tokens

                # Formatting
                translatedText = cleanTranslatedText(translatedText, varResponse)
                if isinstance(tItem, list):
                    extractedTranslations = extractTranslation(translatedText, True)
                    if len(tItem) == len(extractedTranslations):
                        tList[index] = extractedTranslations
                    else:
                        MISMATCH.append(filename)
            else:
                tList[index] = extractedTranslations

            # Create History
            history = tList[index]  # Update history if we have a list
            pbar.update(len(tList[index]))

        else:
            # Ensure we're passing a single string to extractTranslation
            extractedTranslations = extractTranslation(translatedText, False)
            tList[index] = extractedTranslations
            pbar.update(1)

    finalList = combineList(tList, text)
    return [finalList, totalTokens]
