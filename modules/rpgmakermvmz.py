from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import re
import sys
import textwrap
import threading
import time
import traceback
import tiktoken

from colorama import Fore
from dotenv import load_dotenv
import openai
from retry import retry
from tqdm import tqdm

#Globals
load_dotenv()
openai.organization = os.getenv('org')
openai.api_key = os.getenv('key')

APICOST = .002 # Depends on the model https://openai.com/pricing
PROMPT = Path('prompt.txt').read_text(encoding='utf-8')
THREADS = 20 # For GPT4 rate limit will be hit if you have more than 1 thread.
LOCK = threading.Lock()
WIDTH = 50
LISTWIDTH = 60
MAXHISTORY = 10
ESTIMATE = ''
TOTALCOST = 0
TOKENS = 0
TOTALTOKENS = 0
NAMESLIST = []

#tqdm Globals
BAR_FORMAT='{l_bar}{bar:10}{r_bar}{bar:-10b}'
POSITION=0
LEAVE=False

# Flags
CODE401 = True
CODE405 = True
CODE102 = False
CODE122 = False
CODE101 = False
CODE355655 = False
CODE357 = False
CODE657 = False
CODE356 = False
CODE320 = False
CODE324 = False
CODE111 = False
CODE408 = False
CODE108 = False
NAMES = True # Output a list of all the character names found

def handleMVMZ(filename, estimate):
    global ESTIMATE, TOKENS, TOTALTOKENS, TOTALCOST
    ESTIMATE = estimate

    if estimate:
        start = time.time()
        translatedData = openFiles(filename)

        # Print Result
        end = time.time()
        tqdm.write(getResultString(['', TOKENS, None], end - start, filename))
        tqdm.write(str(NAMESLIST))
        with LOCK:
            TOTALCOST += TOKENS * .001 * APICOST
            TOTALTOKENS += TOKENS
            TOKENS = 0

        return getResultString(['', TOTALTOKENS, None], end - start, 'TOTAL')
    
    else:
        with open('translated/' + filename, 'w', encoding='UTF-8') as outFile:
            start = time.time()
            translatedData = openFiles(filename)

            # Print Result
            end = time.time()
            json.dump(translatedData[0], outFile, ensure_ascii=False)
            tqdm.write(getResultString(translatedData, end - start, filename))
            with LOCK:
                TOTALCOST += translatedData[1] * .001 * APICOST
                TOTALTOKENS += translatedData[1]

    return getResultString(['', TOTALTOKENS, None], end - start, 'TOTAL')

def openFiles(filename):
    with open('files/' + filename, 'r', encoding='UTF-8') as f:
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
            translatedData = parseThings(data, filename)

        # MapInfo File
        elif 'MapInfos' in filename:
            translatedData = parseNames(data, filename, 'MapInfos')

        # Skills File
        elif 'Skills' in filename:
            translatedData = parseSS(data, filename)

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
    tokenString = Fore.YELLOW + '[' + str(translatedData[1]) + \
        ' Tokens/${:,.4f}'.format(translatedData[1] * .001 * APICOST) + ']'
    timeString = Fore.BLUE + '[' + str(round(translationTime, 1)) + 's]'

    if translatedData[2] == None:
        # Success
        return filename + ': ' + tokenString + timeString + Fore.GREEN + u' \u2713 ' + Fore.RESET

    else:
        # Fail
        try:
            raise translatedData[2]
        except Exception as e:
            errorString = str(e) + Fore.RED
            return filename + ': ' + tokenString + timeString + Fore.RED + u' \u2717 ' +\
                errorString + Fore.RESET

def parseMap(data, filename):
    totalTokens = 0
    totalLines = 0
    events = data['events']
    global LOCK

    # Translate displayName for Map files
    if 'Map' in filename:
        response = translateGPT(data['displayName'], 'Reply with only the english translation of the RPG location name', False)
        totalTokens += response[1]
        data['displayName'] = response[0].strip('.\"')

    # Get total for progress bar
    for event in events:
        if event is not None:
            for page in event['pages']:
                totalLines += len(page['list'])
    
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
        pbar.desc=filename
        pbar.total=totalLines
        with ThreadPoolExecutor(max_workers=THREADS) as executor:
            for event in events:
                if event is not None:
                    # This translates text above items on the map.
                    # if 'LB:' in event['note']:
                        # totalTokens += translateNote(event, r'(?<=LB:)[^u0000-u0080]+')

                    futures = [executor.submit(searchCodes, page, pbar) for page in event['pages'] if page is not None]
                    for future in as_completed(futures):
                        try:
                            totalTokens += future.result()
                        except Exception as e:
                            return [data, totalTokens, e]
    return [data, totalTokens, None]

def translateNote(event, regex):
    # Regex that only matches text inside LB.
    jaString = event['note']

    match = re.findall(regex, jaString, re.DOTALL)
    if match:
        oldJAString = match[0]
        # Remove any textwrap
        jaString = re.sub(r'\n', ' ', oldJAString)

        # Translate
        response = translateGPT(jaString, 'Reply with the English translation of the description.', True)
        translatedText = response[0]

        # Textwrap
        translatedText = textwrap.fill(translatedText, width=LISTWIDTH)

        translatedText = translatedText.replace('\"', '')
        event['note'] = event['note'].replace(oldJAString, translatedText)
        return response[1]
    return 0

def parseCommonEvents(data, filename):
    totalTokens = 0
    totalLines = 0
    global LOCK

    # Get total for progress bar
    for page in data:
        if page is not None:
            totalLines += len(page['list'])

    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
        pbar.desc=filename
        pbar.total=totalLines
        with ThreadPoolExecutor(max_workers=THREADS) as executor:
            futures = [executor.submit(searchCodes, page, pbar) for page in data if page is not None]
            for future in as_completed(futures):
                try:
                    totalTokens += future.result()
                except Exception as e:
                    return [data, totalTokens, e]
    return [data, totalTokens, None]

def parseTroops(data, filename):
    totalTokens = 0
    totalLines = 0
    global LOCK

    # Get total for progress bar
    for troop in data:
        if troop is not None:
            for page in troop['pages']:
                totalLines += len(page['list']) + 1 # The +1 is because each page has a name.

    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
        pbar.desc=filename
        pbar.total=totalLines
        for troop in data:
            if troop is not None:
                with ThreadPoolExecutor(max_workers=THREADS) as executor:
                    futures = [executor.submit(searchCodes, page, pbar) for page in troop['pages'] if page is not None]
                    for future in as_completed(futures):
                        try:
                            totalTokens += future.result()
                        except Exception as e:
                            return [data, totalTokens, e]
    return [data, totalTokens, None]
    
def parseNames(data, filename, context):
    totalTokens = 0
    totalLines = 0
    totalLines += len(data)
                
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
            pbar.desc=filename
            pbar.total=totalLines
            for name in data:
                if name is not None:
                    try:
                        result = searchNames(name, pbar, context)       
                        totalTokens += result
                    except Exception as e:
                        return [data, totalTokens, e]
    return [data, totalTokens, None]

def parseThings(data, filename):
    totalTokens = 0
    totalLines = 0
    totalLines += len(data)
                
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
            pbar.desc=filename
            pbar.total=totalLines
            for name in data:
                if name is not None:
                    try:
                        result = searchThings(name, pbar)       
                        totalTokens += result
                    except Exception as e:
                        return [data, totalTokens, e]
    return [data, totalTokens, None]

def parseSS(data, filename):
    totalTokens = 0
    totalLines = 0
    totalLines += len(data)
                
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
            pbar.desc=filename
            pbar.total=totalLines
            for ss in data:
                if ss is not None:
                    try:
                        result = searchSS(ss, pbar)       
                        totalTokens += result
                    except Exception as e:
                        return [data, totalTokens, e]
    return [data, totalTokens, None]

def parseSystem(data, filename):
    totalTokens = 0
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
                
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
        pbar.desc=filename
        pbar.total=totalLines
        try:
            result = searchSystem(data, pbar)       
            totalTokens += result
        except Exception as e:
            return [data, totalTokens, e]
    return [data, totalTokens, None]

def parseScenario(data, filename):
    totalTokens = 0
    totalLines = 0
    global LOCK

    # Get total for progress bar
    for page in data.items():
        totalLines += len(page[1])

    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
        pbar.desc=filename
        pbar.total=totalLines
        with ThreadPoolExecutor(max_workers=THREADS) as executor:
            futures = [executor.submit(searchCodes, page[1], pbar) for page in data.items() if page[1] is not None]
            for future in as_completed(futures):
                try:
                    totalTokens += future.result()
                except Exception as e:
                    return [data, totalTokens, e]
    return [data, totalTokens, None]

def searchThings(name, pbar):
    tokens = 0

    # Name
    nameResponse = translateGPT(name['name'], 'Reply with only the english translation of the RPG item name.', False) if 'name' in name else ''

    # Description
    descriptionResponse = translateGPT(name['description'], 'Reply with only the english translation of the description.', False) if 'description' in name else ''

    if '<SG説明:' in name['note']:
        tokens += translateNote(name, r'<SGカテゴリ:([\s\S]*?)>')

    # Count Tokens
    tokens += nameResponse[1] if nameResponse != '' else 0
    tokens += descriptionResponse[1] if descriptionResponse != '' else 0

    # Set Data
    if 'name' in name:
        name['name'] = nameResponse[0].strip('\"')
    if 'description' in name:
        description = textwrap.fill(descriptionResponse[0], LISTWIDTH)
        name['description'] = description.strip('\"')

    pbar.update(1)
    return tokens

def searchNames(name, pbar, context):
    tokens = 0

    # Set the context of what we are translating
    if 'Actors' in context:
        newContext = 'Reply with only the english translation of the NPC name'
    if 'Armors' in context:
        newContext = 'Reply with only the english translation of the RPG equipment name'
    if 'Classes' in context:
        newContext = 'Reply with only the english translation of the RPG class name'
    if 'MapInfos' in context:
        newContext = 'Reply with only the english translation of the location name'
    if 'Enemies' in context:
        newContext = 'Reply with only the english translation of the enemy NPC name'
    if 'Weapons' in context:
        newContext = 'Reply with only the english translation of the RPG weapon name'

    # Extract Data
    responseList = []
    responseList.append(translateGPT(name['name'], newContext, False))
    if 'Actors' in context:
        responseList.append(translateGPT(name['profile'], '', True))
        responseList.append(translateGPT(name['nickname'], 'Reply with ONLY the english translation of the NPC nickname', False))

    if 'Armors' in context or 'Weapons' in context:
        if 'description' in name:
            responseList.append(translateGPT(name['description'], '', True))
        else:
            responseList.append(['', 0])
        if 'hint' in name['note']:
            tokens += translateNote(name, r'<hint:([^>]*)>')

    if 'Enemies' in context:
        if 'taneoya' in name['note']:
            tokens += translateNote(name, r'<taneoya:([^>]*)>')

        if 'desc2' in name['note']:
            tokens += translateNote(name, r'<desc2:([^>]*)>')

        if 'desc3' in name['note']:
            tokens += translateNote(name, r'<desc3:([^>]*)>')

    # Extract all our translations in a list from response
    for i in range(len(responseList)):
        tokens += responseList[i][1]
        responseList[i] = responseList[i][0]

    # Set Data
    name['name'] = responseList[0].strip('.\"')
    if 'Actors' in context:
        translatedText = textwrap.fill(responseList[1], LISTWIDTH)
        name['profile'] = translatedText.strip('\"')
        translatedText = textwrap.fill(responseList[2], LISTWIDTH)
        name['nickname'] = translatedText.strip('\"')
        if '<特徴1:' in name['note']:
            tokens += translateNote(name, r'<特徴1:([^>]*)>')

    if 'Armors' in context or 'Weapons' in context:
        translatedText = textwrap.fill(responseList[1], LISTWIDTH)
        if 'description' in name:
            name['description'] = translatedText.strip('\"')
            if '<SG説明:' in name['note']:
                tokens += translateNote(name, r'<SG説明:([^>]*)>')
    pbar.update(1)

    return tokens

def searchCodes(page, pbar):
    translatedText = ''
    currentGroup = []
    textHistory = []
    maxHistory = MAXHISTORY
    tokens = 0
    speaker = ''
    speakerVar = ''
    nametag = ''
    match = []
    syncIndext = 0
    global LOCK
    global NAMESLIST

    try:
        if 'list' in page:
            codeList = page['list']
        else:
            codeList = page
        for i in range(len(codeList)):
            with LOCK:
                pbar.update(1)

            ### All the codes are here which translate specific functions in the MAP files.
            ### IF these crash or fail your game will do the same. Use the flags to skip codes.

            ## Event Code: 401 Show Text
            if codeList[i]['code'] == 401 and CODE401 == True or codeList[i]['code'] == 405 and CODE405:  
                # Use this to place text later
                j = i

                # Grab String  
                jaString = codeList[i]['parameters'][0]

                # Using this to keep track of 401's in a row. Throws IndexError at EndOfList (Expected Behavior)
                currentGroup.append(jaString)

                while (codeList[i+1]['code'] == 401 or codeList[i+1]['code'] == 405):
                    codeList[i]['parameters'][0] = ''
                    codeList[i]['code'] = 0
                    i += 1

                    jaString = codeList[i]['parameters'][0]
                    currentGroup.append(jaString)

                # Join up 401 groups for better translation.
                if len(currentGroup) > 0:
                    finalJAString = ''.join(currentGroup)
                    oldjaString = finalJAString

                    # Check for speaker
                    if '\\N' in finalJAString or '\\n' in finalJAString:
                        match = re.findall(r'(.+[Nn]<(.+)>)', finalJAString)
                        if len(match) != 0:
                            response = translateGPT(match[0][1], 'Reply with only the english translation of the NPC name', True)
                            tokens += response[1]
                            speaker = response[0].strip('.')
                            nametag = match[0][0].replace(match[0][1], speaker)
                            finalJAString = finalJAString.replace(match[0][0], '')
                            
                            # Put names in list
                            if NAMES == True and speaker not in NAMESLIST:
                                with LOCK:
                                    NAMESLIST.append(speaker)
                    elif '\\kw' in finalJAString:
                        match = re.findall(r'\\+kw\[[0-9]+\]', finalJAString)
                        if len(match) != 0:
                            if '1' in match[0]:
                                speaker = 'Ayako Nagatsuki'
                            if '2' in match[0]:
                                speaker = 'Rei'
                            
                            # Set name var to top of list
                            codeList[j]['parameters'][0] = match[0]
                            codeList[j]['code'] = 401

                            # Set next item as dialogue
                            j += 1
                            codeList[j]['parameters'][0] = match[0]
                            codeList[j]['code'] = 401

                            # Remove from final string
                            finalJAString = finalJAString.replace(match[0], '')
                    elif '【' in finalJAString:
                        if '\\z' in finalJAString:
                            match = re.findall(r'(.+?【(.+?)】.+?\\z\[[0-9]+\])', finalJAString)
                        else:
                            match = re.findall(r'(.+?【(.+?)】)', finalJAString)
                        
                        if len(match) != 0:
                            response = translateGPT(match[0][1], 'Reply with only the english translation of the NPC name', True)
                            tokens += response[1]
                            speaker = response[0].strip('.')
                            nametag = match[0][0].replace(match[0][1], speaker)
                            finalJAString = finalJAString.replace(match[0][0], '')

                            # Set name var to top of list
                            codeList[j]['parameters'][0] = nametag
                            codeList[j]['code'] = 401

                            # Set next item as dialogue
                            j += 1
                            codeList[j]['parameters'][0] = finalJAString
                            codeList[j]['code'] = 401
                            
                            # Put names in list
                            if NAMES == True and speaker not in NAMESLIST:
                                with LOCK:
                                    NAMESLIST.append(speaker)
                                    
                    # Need to remove outside code and put it back later
                    startString = re.search(r'^[^一-龠ぁ-ゔァ-ヴー【】（）[]<>「」『』a-zA-Z0-9Ａ-Ｚ０-９\\]+', finalJAString)
                    finalJAString = re.sub(r'^[^一-龠ぁ-ゔァ-ヴー【】（）[]<>「」『』a-zA-Z0-9Ａ-Ｚ０-９\\]+', '', finalJAString)
                    if startString is None: startString = ''
                    else:  startString = startString.group()                    

                    # Remove any textwrap
                    finalJAString = re.sub(r'\n', ' ', finalJAString)
                    finalJAString = finalJAString.replace('ﾞ', '')
                    finalJAString = finalJAString.replace('。', '.')
                    finalJAString = finalJAString.replace('・', '.')
                    finalJAString = finalJAString.replace('‶', '')
                    finalJAString = finalJAString.replace('”', '')
                    finalJAString = finalJAString.replace('―', '-')
                    finalJAString = finalJAString.replace('…', '...')
                    finalJAString = finalJAString.replace('　', '')

                    # Translate
                    if speaker == '' and finalJAString != '':
                        response = translateGPT(finalJAString, 'Previous Translated Text: ' + '|'.join(textHistory), True)
                        tokens += response[1]
                        translatedText = response[0]
                        textHistory.append('\"' + translatedText + '\"')
                    elif finalJAString != '':
                        response = translateGPT(speaker + ': ' + finalJAString, 'Previous Translated Text: ' + '|'.join(textHistory), True)
                        tokens += response[1]
                        translatedText = response[0]
                        textHistory.append('\"' + translatedText + '\"')

                        # Remove added speaker and add nametag
                        translatedText = re.sub(r'^.+?:\s', '', translatedText)
                        translatedText = nametag + translatedText
                        speaker = ''                
                        nametag = ''
                    else:
                        translatedText = finalJAString    

                    # Textwrap
                    translatedText = textwrap.fill(translatedText, width=WIDTH)

                    # Start String
                    translatedText = startString + translatedText

                    # Set Data
                    translatedText = translatedText.replace('ッ', '')
                    translatedText = translatedText.replace('っ', '')
                    translatedText = translatedText.replace('ー', '')
                    translatedText = translatedText.replace('\"', '')
                    translatedText = translatedText.replace('\\CL ', '\\CL')
                    translatedText = translatedText.replace('\\CL', '\\CL ')
                    codeList[i]['parameters'][0] = ''
                    codeList[i]['code'] = 0
                    codeList[j]['parameters'][0] = translatedText
                    codeList[j]['code'] = 401
                    speaker = ''
                    match = []

                    # Keep textHistory list at length maxHistory
                    if len(textHistory) > maxHistory:
                        textHistory.pop(0)
                    currentGroup = []              

            ## Event Code: 122 [Set Variables]
            if codeList[i]['code'] == 122 and CODE122 == True:  
                # This is going to be the var being set. (IMPORTANT)
                varNum = codeList[i]['parameters'][0]
                if varNum != 53:
                    continue
                  
                jaString = codeList[i]['parameters'][4]
                if type(jaString) != str:
                    continue
                
                # Definitely don't want to mess with files
                if '■' in jaString or '_' in jaString:
                    continue

                # If there isn't any Japanese in the text just skip
                if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', jaString):
                    continue

                # Need to remove outside code and put it back later
                matchList = re.findall(r"\'(.*?)\'", jaString)
                
                for match in matchList:
                    response = translateGPT(match, '', True)
                    translatedText = response[0]
                    tokens += response[1]

                    # Remove characters that may break scripts
                    charList = ['.', '\"', '\'', '\\n']
                    for char in charList:
                        translatedText = translatedText.replace(char, '')

                    jaString = jaString.replace(match, translatedText)

                # Set Data
                translatedText = jaString
                codeList[i]['parameters'][4] = translatedText

        ## Event Code: 357 [Picture Text] [Optional]
            if codeList[i]['code'] == 357 and CODE357 == True:    
                if 'message' in codeList[i]['parameters'][3]:
                    jaString = codeList[i]['parameters'][3]['message']
                    if type(jaString) != str:
                        continue
                    
                    # Definitely don't want to mess with files
                    if '_' in jaString:
                        continue

                    # If there isn't any Japanese in the text just skip
                    if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', jaString):
                        continue

                    # Need to remove outside code and put it back later
                    oldjaString = jaString
                    startString = re.search(r'^[^一-龠ぁ-ゔァ-ヴー【】（）「」a-zA-ZＡ-Ｚ０-９\\]+', jaString)
                    finalJAString = re.sub(r'^[^一-龠ぁ-ゔァ-ヴー【】（）「」a-zA-ZＡ-Ｚ０-９\\]+', '', jaString)
                    if startString is None: startString = ''
                    else:  startString = startString.group()

                    # Remove any textwrap
                    finalJAString = re.sub(r'\n', ' ', finalJAString)

                    # Translate
                    response = translateGPT(finalJAString, '', True)
                    tokens += response[1]
                    translatedText = response[0]

                    # Textwrap
                    translatedText = textwrap.fill(translatedText, width=WIDTH)

                    # Set Data
                    codeList[i]['parameters'][3]['message'] = startString + translatedText
            
        ## Event Code: 657 [Picture Text] [Optional]
            if codeList[i]['code'] == 657 and CODE657 == True:    
                if 'text' in codeList[i]['parameters'][0]:
                    jaString = codeList[i]['parameters'][0]
                    if type(jaString) != str:
                        continue
                    
                    # Definitely don't want to mess with files
                    if '_' in jaString:
                        continue

                    # If there isn't any Japanese in the text just skip
                    if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', jaString):
                        continue

                    # Remove outside text
                    startString = re.search(r'^[^一-龠ぁ-ゔァ-ヴー\<\>【】\\]+', jaString)
                    jaString = re.sub(r'^[^一-龠ぁ-ゔァ-ヴー\<\>【】\\]+', '', jaString)
                    endString = re.search(r'[^一-龠ぁ-ゔァ-ヴー\<\>【】。！？\\]+$', jaString)
                    jaString = re.sub(r'[^一-龠ぁ-ゔァ-ヴー\<\>【】。！？\\]+$', '', jaString)
                    if startString is None: startString = ''
                    else:  startString = startString.group()
                    if endString is None: endString = ''
                    else: endString = endString.group()

                    # Remove any textwrap
                    jaString = re.sub(r'\n', ' ', jaString)

                    # Translate
                    response = translateGPT(jaString, '', True)
                    tokens += response[1]
                    translatedText = response[0]

                    # Remove characters that may break scripts
                    charList = ['.', '\"', "'"]
                    for char in charList:
                        translatedText = translatedText.replace(char, '')

                    # Textwrap
                    translatedText = textwrap.fill(translatedText, width=WIDTH)
                    translatedText = startString + translatedText + endString

                    # Set Data
                    if '\\' in jaString:
                        print('Hi')
                    codeList[i]['parameters'][0] = translatedText

        ## Event Code: 101 [Name] [Optional]
            if codeList[i]['code'] == 101 and CODE101 == True:    
                jaString = codeList[i]['parameters'][4]
                if type(jaString) != str:
                    continue
                
                # Definitely don't want to mess with files
                if '_' in jaString:
                    continue

                # If there isn't any Japanese in the text just skip
                if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', jaString):
                    speaker = jaString
                    continue

                # Need to remove outside code and put it back later
                startString = re.search(r'^[^一-龠ぁ-ゔァ-ヴー\<\>【】]+', jaString)
                jaString = re.sub(r'^[^一-龠ぁ-ゔァ-ヴー\<\>【】]+', '', jaString)
                endString = re.search(r'[^一-龠ぁ-ゔァ-ヴー\<\>【】。！？]+$', jaString)
                jaString = re.sub(r'[^一-龠ぁ-ゔァ-ヴー\<\>【】。！？]+$', '', jaString)
                if startString is None: startString = ''
                else:  startString = startString.group() + ' '
                if endString is None: endString = ''
                else: endString = endString.group()

                # Translate
                response = translateGPT(jaString, 'Reply with only the english translation of the NPC name.', False)
                tokens += response[1]
                translatedText = response[0]

                # Remove characters that may break scripts
                charList = ['.', '\"']
                for char in charList:
                    translatedText = translatedText.replace(char, '')

                translatedText = startString + translatedText + endString

                # Set Data
                speaker = translatedText
                codeList[i]['parameters'][4] = translatedText
                if NAMES == True and speaker not in NAMESLIST:
                    with LOCK:
                        NAMESLIST.append(speaker)

            ## Event Code: 355 or 655 Scripts [Optional]
            if (codeList[i]['code'] == 355) and CODE355655 == True:
                jaString = codeList[i]['parameters'][0]

                # If there isn't any Japanese in the text just skip
                if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', jaString):
                    continue

                # Want to translate this script
                if codeList[i]['code'] == 355 and '_logWindow.push' not in jaString:
                    continue

                # Don't want to touch certain scripts
                if codeList[i]['code'] == 655 and '.' in jaString:
                    continue

                # Need to remove outside code and put it back later
                startString = re.search(r'^[^一-龠ぁ-ゔァ-ヴー\<\>【】（）「」『』]+', jaString)
                jaString = re.sub(r'^[^一-龠ぁ-ゔァ-ヴー\<\>【】（）「」『』]+', '', jaString)
                endString = re.search(r'[^一-龠ぁ-ゔァ-ヴー\<\>【】（）「」『』。！？]+$', jaString)
                jaString = re.sub(r'[^一-龠ぁ-ゔァ-ヴー\<\>【】（）「」『』。！？]+$', '', jaString)
                if startString is None: startString = ''
                else:  startString = startString.group()
                if endString is None: endString = ''
                else: endString = endString.group()

                # Translate
                response = translateGPT(jaString, 'Reply with the English Translation of the text.', True)
                tokens += response[1]
                translatedText = response[0]

                # Remove characters that may break scripts
                charList = ['\"', "\'"]
                for char in charList:
                    translatedText = translatedText.replace(char, '')
                
                # Set Data
                translatedText = startString + translatedText + endString
                codeList[i]['parameters'][0] = translatedText

        ## Event Code: 408 (Script)
            if (codeList[i]['code'] == 408) and CODE408 == True:
                jaString = codeList[i]['parameters'][0]

                # If there isn't any Japanese in the text just skip
                if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', jaString):
                    continue

                # Want to translate this script
                # if 'ans:' not in jaString:
                #     continue

                # Need to remove outside code and put it back later
                startString = re.search(r'^[^一-龠ぁ-ゔァ-ヴー【】]+', jaString)
                jaString = re.sub(r'^[^一-龠ぁ-ゔァ-ヴー【】]+', '', jaString)
                endString = re.search(r'[^一-龠ぁ-ゔァ-ヴー【】。、…！？]+$', jaString)
                jaString = re.sub(r'[^一-龠ぁ-ゔァ-ヴー【】。、…！？]+$', '', jaString)
                if startString is None: startString = ''
                else:  startString = startString.group()
                if endString is None: endString = ''
                else: endString = endString.group()

                # Translate
                response = translateGPT(jaString, '', True)
                tokens += response[1]
                translatedText = response[0]

                # Remove characters that may break scripts
                charList = ['.', '\"']
                for char in charList:
                    translatedText = translatedText.replace(char, '')

                translatedText = startString + translatedText + endString

                translatedText = translatedText.replace('"', '\"')

                # Set Data
                codeList[i]['parameters'][0] = translatedText

            ## Event Code: 108 (Script)
            if (codeList[i]['code'] == 108) and CODE108 == True:
                jaString = codeList[i]['parameters'][0]

                # If there isn't any Japanese in the text just skip
                if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', jaString):
                    continue

                # Want to translate this script
                if 'event_text :' not in jaString:
                    continue

                # Need to remove outside code and put it back later
                startString = re.search(r'^[^一-龠ぁ-ゔァ-ヴー【】]+', jaString)
                jaString = re.sub(r'^[^一-龠ぁ-ゔァ-ヴー【】]+', '', jaString)
                endString = re.search(r'[^一-龠ぁ-ゔァ-ヴー【】。、…！？]+$', jaString)
                jaString = re.sub(r'[^一-龠ぁ-ゔァ-ヴー【】。、…！？]+$', '', jaString)
                if startString is None: startString = ''
                else:  startString = startString.group()
                if endString is None: endString = ''
                else: endString = endString.group()

                # Translate
                response = translateGPT(jaString, 'Reply with the English translation of the Event Title', True)
                tokens += response[1]
                translatedText = response[0]

                # Remove characters that may break scripts
                charList = ['.', '\"']
                for char in charList:
                    translatedText = translatedText.replace(char, '')

                translatedText = startString + translatedText + endString

                translatedText = translatedText.replace('"', '\"')

                # Set Data
                codeList[i]['parameters'][0] = translatedText

            ## Event Code: 356 D_TEXT
            if codeList[i]['code'] == 356 and CODE356 == True:
                jaString = codeList[i]['parameters'][0]
                oldjaString = jaString

                # If there isn't any Japanese in the text just skip
                if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', jaString):
                    continue

                # Want to translate this script
                if 'D_TEXT ' not in jaString:
                    continue
                
                # Remove any textwrap
                jaString = re.sub(r'\n', '_', jaString)

                # Capture Arguments and text
                arg1 = re.findall(r'^(\S+)', jaString)[0]
                arg2 = re.findall(r'(\S+)$', jaString)[0]
                dtext = re.findall(r'(?<=\s)(.*?)(?=\s)', jaString)[0]

                # Remove underscores
                dtext = re.sub(r'_', ' ', dtext)

                # Using this to keep track of 401's in a row. Throws IndexError at EndOfList (Expected Behavior)
                currentGroup.append(dtext)

                while (codeList[i+1]['code'] == 356):
                    # Want to translate this script
                    if 'D_TEXT ' not in codeList[i+1]['parameters'][0]:
                        break

                    codeList[i]['parameters'][0] = ''
                    i += 1
                    jaString = codeList[i]['parameters'][0]
                    dtext = re.findall(r'(?<=\s)(.*?)(?=\s)', jaString)[0]
                    currentGroup.append(dtext)

                # Join up 356 groups for better translation.
                if len(currentGroup) > 0:
                    finalJAString = ' '.join(currentGroup)
                else:
                    finalJAString = dtext
                
                # Translate
                response = translateGPT(finalJAString, '', True)
                translatedText = response[0]
                tokens += response[1]

                # Remove characters that may break scripts
                charList = ['.', '\"']
                for char in charList:
                    translatedText = translatedText.replace(char, '')

                # Textwrap
                translatedText = textwrap.fill(translatedText, width=30)
                
                # Cant have spaces?
                translatedText = translatedText.replace(' ', '_')
            
                # Put Args Back
                translatedText = arg1 + ' ' + translatedText + ' ' + arg2

                # Set Data
                codeList[i]['parameters'][0] = translatedText

                # Clear Group
                currentGroup = []  

            ### Event Code: 102 Show Choice
            if codeList[i]['code'] == 102 and CODE102 == True:
                for choice in range(len(codeList[i]['parameters'][0])):
                    jaString = codeList[i]['parameters'][0][choice]
                    jaString = jaString.replace(' 。', '.')

                    # Need to remove outside code and put it back later
                    startString = re.search(r'^en.+\)\s|^en.+\)|^if.+\)\s|^if.+\)', jaString)
                    jaString = re.sub(r'^en.+\)\s|^en.+\)|^if.+\)\s|^if.+\)', '', jaString)
                    endString = re.search(r'\sen.+$|en.+$|\sif.+$|if.+$', jaString)
                    jaString = re.sub(r'\sen.+$|en.+$|\sif.+$|if.+$', '', jaString)
                    if startString is None: startString = ''
                    else:  startString = startString.group()
                    if endString is None: endString = ''
                    else: endString = endString.group()

                    if len(textHistory) > 0:
                        response = translateGPT(jaString, 'Previous text for context: ' + textHistory[len(textHistory)-1], True)
                        translatedText = response[0]
                    else:
                        response = translateGPT(jaString, '', True)
                        translatedText = response[0]

                    # Remove characters that may break scripts
                    charList = ['.', '\"', '\\n']
                    for char in charList:
                        translatedText = translatedText.replace(char, '')

                    # Set Data
                    tokens += response[1]
                    codeList[i]['parameters'][0][choice] = startString + translatedText + endString

            ### Event Code: 111 Script
            if codeList[i]['code'] == 111 and CODE111 == True:
                for j in range(len(codeList[i]['parameters'])):
                    jaString = codeList[i]['parameters'][j]

                    # Check if String
                    if type(jaString) != str:
                        continue

                    # Only TL the Game Variable
                    if '$gameVariables' not in jaString:
                        continue

                    # This is going to be the var being set. (IMPORTANT)
                    if '1045' not in jaString:
                        continue

                    # Need to remove outside code and put it back later
                    matchList = re.findall(r"'(.*?)'", jaString)
                    
                    for match in matchList:
                        response = translateGPT(match, '', True)
                        translatedText = response[0]
                        tokens += response[1]

                        # Remove characters that may break scripts
                        charList = ['.', '\"', '\'', '\\n']
                        for char in charList:
                            translatedText = translatedText.replace(char, '')

                        jaString = jaString.replace(match, translatedText)

                    # Set Data
                    translatedText = jaString
                    codeList[i]['parameters'][j] = translatedText

            ### Event Code: 320 Set Variable
            if codeList[i]['code'] == 320 and CODE320 == True:                
                jaString = codeList[i]['parameters'][1]
                if type(jaString) != str:
                    continue
                
                # Definitely don't want to mess with files
                if '■' in jaString or '_' in jaString:
                    continue

                # If there isn't any Japanese in the text just skip
                if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', jaString):
                    continue
                
                response = translateGPT(jaString, 'Reply with the English translation of the NPC name.', True)
                translatedText = response[0]
                tokens += response[1]

                # Remove characters that may break scripts
                charList = ['.', '\"', '\'', '\\n']
                for char in charList:
                    translatedText = translatedText.replace(char, '')

                # Set Data
                codeList[i]['parameters'][1] = translatedText

    except IndexError as e:
        # This is part of the logic so we just pass it
        traceback.print_exc()
        # raise Exception(str(e) + '|Line:' + tracebackLineNo)  
    except Exception as e:
        traceback.print_exc()
        raise Exception(str(e) + 'Failed to translate: ' + oldjaString)  
                
    # Append leftover groups in 401
    if len(currentGroup) > 0:
        # Translate
        response = translateGPT(finalJAString, 'Previous Translated Text for Context: ' + '\n\n'.join(textHistory), True)
        tokens += response[1]
        translatedText = response[0]

        # TextHistory is what we use to give GPT Context, so thats appended here.
        textHistory.append('\"' + translatedText + '\"')

        # Textwrap
        translatedText = textwrap.fill(translatedText, width=WIDTH)

        # Resub start and end
        translatedText = startString + translatedText

        # Set Data
        translatedText = translatedText.replace('ッ', '')
        translatedText = translatedText.replace('っ', '')
        translatedText = translatedText.replace('\"', '')
        codeList[i]['parameters'][0] = translatedText
        speaker = ''
        match = []

        # Keep textHistory list at length maxHistory
        if len(textHistory) > maxHistory:
            textHistory.pop(0)
        currentGroup = []    

    return tokens

def searchSS(state, pbar):
    '''Searches skills and states json files'''
    tokens = 0

    # Name
    nameResponse = translateGPT(state['name'], 'Reply with only the english translation of the RPG Skill name.', True) if 'name' in state else ''

    # Description
    descriptionResponse = translateGPT(state['description'], 'Reply with only the english translation of the description.', True) if 'description' in state else ''

    # Messages
    message1Response = translateGPT('Taro' + state['message1'], 'reply with only the gender neutral english translation of the action.', True) if 'message1' in state else ''
    message2Response = translateGPT(state['message2'], 'reply with only the english translation of the text.', True) if 'message2' in state else ''
    message3Response = translateGPT(state['message3'], 'reply with only the english translation of the text.', True) if 'message3' in state else ''
    message4Response = translateGPT(state['message4'], 'reply with only the english translation of the text.', True) if 'message4' in state else ''

    # if 'note' in state:
    if 'Extended Description' in state['note']:
        tokens += translateNote(state, r'<Extended Description:([^>]*)>')
    
    # Count Tokens
    tokens += nameResponse[1] if nameResponse != '' else 0
    tokens += descriptionResponse[1] if descriptionResponse != '' else 0
    tokens += message1Response[1] if message1Response != '' else 0
    tokens += message2Response[1] if message2Response != '' else 0
    tokens += message3Response[1] if message3Response != '' else 0
    tokens += message4Response[1] if message4Response != '' else 0

    # Set Data
    if 'name' in state:
        state['name'] = nameResponse[0].strip('\"')
    if 'description' in state:
        # Textwrap
        translatedText = descriptionResponse[0]
        translatedText = textwrap.fill(translatedText, width=LISTWIDTH)
        state['description'] = translatedText.strip('\"')
    if 'message1' in state:
        state['message1'] = message1Response[0].strip('\"').replace('Taro', '')
    if 'message2' in state:
        state['message2'] = message2Response[0].strip('\"')
    if 'message3' in state:
        state['message3'] = message3Response[0].strip('\"')
    if 'message4' in state:
        state['message4'] = message4Response[0].strip('\"')

    pbar.update(1)
    return tokens

def searchSystem(data, pbar):
    tokens = 0
    context = 'Reply with only the english translation of the UI textbox'

    # Title
    response = translateGPT(data['gameTitle'], ' Reply with the English translation of the game title name', False)
    tokens += response[1]
    data['gameTitle'] = response[0].strip('.')
    pbar.update(1)
    
    # Terms
    for term in data['terms']:
        if term != 'messages':
            termList = data['terms'][term]
            for i in range(len(termList)):  # Last item is a messages object
                if termList[i] is not None:
                    response = translateGPT(termList[i], context, False)
                    tokens += response[1]
                    termList[i] = response[0].strip('.\"')
                    pbar.update(1)

    # Armor Types
    for i in range(len(data['armorTypes'])):
        response = translateGPT(data['armorTypes'][i], 'Reply with only the english translation of the armor type', False)
        tokens += response[1]
        data['armorTypes'][i] = response[0].strip('.\"')
        pbar.update(1)

    # Skill Types
    for i in range(len(data['skillTypes'])):
        response = translateGPT(data['skillTypes'][i], 'Reply with only the english translation', False)
        tokens += response[1]
        data['skillTypes'][i] = response[0].strip('.\"')
        pbar.update(1)

    # Equip Types
    for i in range(len(data['equipTypes'])):
        response = translateGPT(data['equipTypes'][i], 'Reply with only the english translation of the equipment type. No disclaimers.', False)
        tokens += response[1]
        data['equipTypes'][i] = response[0].strip('.\"')
        pbar.update(1)

    # Variables (Optional ususally)
    # for i in range(len(data['variables'])):
    #     response = translateGPT(data['variables'][i], 'Reply with only the english translation of the name', False)
    #     tokens += response[1]
    #     data['variables'][i] = response[0].strip('.\"')
    #     pbar.update(1)

    # Messages
    messages = (data['terms']['messages'])
    for key, value in messages.items():
        response = translateGPT(value, 'Reply with only the english translation of the battle text.', False)
        translatedText = response[0]

        # Remove characters that may break scripts
        charList = ['.', '\"', '\\n']
        for char in charList:
            translatedText = translatedText.replace(char, '')

        tokens += response[1]
        messages[key] = translatedText
        pbar.update(1)
    
    return tokens

def subVars(jaString):
    varRegex = r'\\+[a-zA-Z]+\[[0-9a-zA-Z\\\[\]]+\]+|[\\]+[#|]+|\\+[\\\[\]\.<>a-zA-Z0-9]+'
    count = 0

    varList = re.findall(varRegex, jaString)
    if len(varList) != 0:
        for var in varList:
            jaString = jaString.replace(var, '{x' + str(count) + '}')
            count += 1

    return [jaString, varList]

def resubVars(translatedText, varList):
    count = 0
    
    if len(varList) != 0:
        for var in varList:
            translatedText = translatedText.replace('{x' + str(count) + '}', var)
            count += 1

    # Remove Color Variables Spaces
    if '\\c' in translatedText:
        translatedText = re.sub(r'\s*(\\+c\[[1-9]+\])\s*', r' \1', translatedText)
        translatedText = re.sub(r'\s*(\\+c\[0+\])', r'\1', translatedText)
    return translatedText

@retry(exceptions=Exception, tries=5, delay=5)
def translateGPT(t, history, fullPromptFlag):
    with LOCK:
        # If ESTIMATE is True just count this as an execution and return.
        if ESTIMATE:
            global TOKENS
            enc = tiktoken.encoding_for_model("gpt-3.5-turbo-0613")
            TOKENS += len(enc.encode(t)) * 2 + len(enc.encode(history)) + len(enc.encode(PROMPT))
            return (t, 0)
    
    # Sub Vars
    varResponse = subVars(t)
    subbedT = varResponse[0]

    # If there isn't any Japanese in the text just skip
    if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', subbedT):
        return(t, 0)

    """Translate text using GPT"""
    context = 'Eroge Names Context: レイン == Rain | Female, フィルス == Phils | Female, メイル == Meryl | Female, ジャス == Jazz | Male'
    if fullPromptFlag:
        system = PROMPT 
        user = 'Line to Translate: ' + subbedT
    else:
        system = 'You are an expert translator who translates everything to English. Reply with only the English Translation of the text.' 
        user = 'Line to Translate: ' + subbedT
    response = openai.ChatCompletion.create(
        temperature=0,
        frequency_penalty=1,
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": context},
            {"role": "user", "content": history},
            {"role": "user", "content": user}
        ],
        request_timeout=30,
    )

    # Save Translated Text
    translatedText = response.choices[0].message.content
    tokens = response.usage.total_tokens

    # Resub Vars
    translatedText = resubVars(translatedText, varResponse[1])

    # Remove Placeholder Text
    translatedText = translatedText.replace('English Translation: ', '')
    translatedText = translatedText.replace('Translation: ', '')
    translatedText = translatedText.replace('Line to Translate: ', '')
    translatedText = translatedText.replace('English Translation:', '')
    translatedText = translatedText.replace('Translation:', '')
    translatedText = translatedText.replace('Line to Translate:', '')

    # Return Translation
    if len(translatedText) > 15 * len(t) or "I'm sorry, but I'm unable to assist with that translation" in translatedText:
        return [t, response.usage.total_tokens]
    else:
        return [translatedText, tokens]