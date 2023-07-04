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
THREADS = 20
LOCK = threading.Lock()
WIDTH = 70
LISTWIDTH = 80
MAXHISTORY = 10
ESTIMATE = ''
TOTALCOST = 0
TOKENS = 0
TOTALTOKENS = 0

#tqdm Globals
BAR_FORMAT='{l_bar}{bar:10}{r_bar}{bar:-10b}'
POSITION=0
LEAVE=False

# Flags
CODE401 = True
CODE405 = False
CODE102 = True
CODE122 = False
CODE101 = False
CODE355655 = False
CODE357 = False
CODE657 = False
CODE356 = True
CODE320 = False
CODE324 = False
CODE111 = False
CODE408 = False

def handleMVMZ(filename, estimate):
    global ESTIMATE, TOKENS, TOTALTOKENS, TOTALCOST
    ESTIMATE = estimate

    if estimate:
        start = time.time()
        translatedData = openFiles(filename)

        # Print Result
        end = time.time()
        tqdm.write(getResultString(['', TOKENS, None], end - start, filename))
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

    match = re.search(regex, jaString)
    if match:
        jaString = match.group(1)
        # Need to remove outside code
        jaString = re.sub(r'^[^一-龠ぁ-ゔァ-ヴー\<\>【】]+', '', jaString)
        jaString = re.sub(r'[^一-龠ぁ-ゔァ-ヴー\<\>【】。！？]+$', '', jaString)
        oldjaString = jaString

        # Remove any textwrap
        jaString = re.sub(r'\n', ' ', jaString)
        
        response = translateGPT(jaString, '', True)
        translatedText = response[0]

        # Textwrap
        translatedText = textwrap.fill(translatedText, width=LISTWIDTH)

        event['note'] = event['note'].replace(oldjaString, translatedText)
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

def searchThings(name, pbar):
    tokens = 0

    # Set the context of what we are translating
    responseList = []
    responseList.append(translateGPT(name['name'], 'Reply with only the English translation of the RPG Item name.', False))
    responseList.append(translateGPT(name['description'], 'Reply with only the English translation of the description.', False))

    # if '<SG説明:' in name['note']:
        # tokens += translateNote(name, r'<SG説明:([\s\S]*?)>')

    # Extract all our translations in a list from response
    for i in range(len(responseList)):
        tokens += responseList[i][1]
        responseList[i] = responseList[i][0]

    # Set Data
    name['name'] = responseList[0].strip('.\"')
    responseList[1] = textwrap.fill(responseList[1], LISTWIDTH)
    name['description'] = responseList[1].strip('\"')
    # name['note'] = responseList[2]
    pbar.update(1)

    return tokens

def searchNames(name, pbar, context):
    tokens = 0

    # Set the context of what we are translating
    if 'Actors' in context:
        newContext = 'Reply with only the english translation of the NPC name'
    if 'Armors' in context:
        newContext = 'Reply with only the english translation of the RPG armor/clothing name'
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
        responseList.append(translateGPT(name['description'], '', True))

    if 'Enemies' in context:
        if 'desc1' in name['note']:
            tokens += translateNote(name, r'<desc1:([^>]*)>')

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

    if 'Armors' in context or 'Weapons' in context:
        translatedText = textwrap.fill(responseList[1], LISTWIDTH)
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
    match = []
    global LOCK

    try:
        for i in range(len(page['list'])):
            with LOCK:
                pbar.update(1)

            ### All the codes are here which translate specific functions in the MAP files.
            ### IF these crash or fail your game will do the same. Use the flags to skip codes.

            ## Event Code: 401 Show Text
            if page['list'][i]['code'] == 401 and CODE401 == True or page['list'][i]['code'] == 405 and CODE405:    
                jaString = page['list'][i]['parameters'][0]
                if "peek inside" in jaString:
                    print('hi')
                oldjaString = jaString
                jaString = jaString.replace('ﾞ', '')
                jaString = jaString.replace('。', '.')
                jaString = jaString.replace('・', '.')
                jaString = jaString.replace('‶', '')
                jaString = jaString.replace('”', '')
                jaString = jaString.replace('ー', '-')
                jaString = jaString.replace('―', '-')
                jaString = jaString.replace('…', '...')
                jaString = re.sub(r'([\u3000-\uffef])\1{3,}', r'\1\1\1', jaString)

                # Using this to keep track of 401's in a row. Throws IndexError at EndOfList (Expected Behavior)
                currentGroup.append(jaString)

                while (page['list'][i+1]['code'] == 401 or page['list'][i+1]['code'] == 405):
                    del page['list'][i]  
                    jaString = page['list'][i]['parameters'][0]
                    jaString = jaString.replace('ﾞ', '')
                    jaString = jaString.replace('。', '.')
                    jaString = jaString.replace('・', '.')
                    jaString = jaString.replace('‶', '')
                    jaString = jaString.replace('”', '')
                    jaString = jaString.replace('ー', '-')
                    jaString = jaString.replace('―', '-')
                    jaString = jaString.replace('…', '...')
                    jaString = re.sub(r'([\u3000-\uffef])\1{3,}', r'\1\1\1', jaString)
                    currentGroup.append(jaString)

                # Join up 401 groups for better translation.
                if len(currentGroup) > 0:
                    finalJAString = ' '.join(currentGroup)

                    # Check for speaker
                    if '\\N' in finalJAString:
                        match = re.findall(r'[\\]+N<([一-龠ぁ-ゔァ-ヴー]+)>', finalJAString)
                        if len(match) != 0:
                            response = translateGPT(match[0], 'Reply with only the english translation of the NPC name', False)
                            tokens += response[1]
                            speaker = response[0].strip('.')

                            finalJAString = finalJAString.replace(match[0], speaker)

                    # Need to remove outside code and put it back later
                    startString = re.search(r'^[^一-龠ぁ-ゔァ-ヴー【】（）「」『』a-zA-Z0-9Ａ-Ｚ０-９\\]+', finalJAString)
                    finalJAString = re.sub(r'^[^一-龠ぁ-ゔァ-ヴー【】（）「」『』a-zA-Z0-9Ａ-Ｚ０-９\\]+', '', finalJAString)
                    if startString is None: startString = ''
                    else:  startString = startString.group()

                    # Remove any textwrap
                    finalJAString = re.sub(r'\n', ' ', finalJAString)

                    # Translate
                    response = translateGPT(finalJAString, 'Previous Text for Context: ' + '\n\n'.join(textHistory), True)
                    tokens += response[1]
                    translatedText = response[0]

                    # TextHistory is what we use to give GPT Context, so thats appended here.
                    # rawTranslatedText = re.sub(r'[\\<>]+[a-zA-Z]+\[[a-zA-Z0-9]+\]', '', translatedText)
                    textHistory.append('\"' + translatedText + '\"')

                    # if speakerCaught == True:
                    #     translatedText = speakerRaw + ':\n' + translatedText
                    #     speakerCaught = False

                    # Textwrap
                    translatedText = textwrap.fill(translatedText, width=WIDTH)

                    # Resub start and end
                    translatedText = startString + translatedText

                    # Set Data
                    translatedText = translatedText.replace('ッ', '')
                    translatedText = translatedText.replace('っ', '')
                    translatedText = translatedText.replace('\"', '')
                    page['list'][i]['parameters'][0] = translatedText
                    speaker = ''
                    match = []

                    # Keep textHistory list at length maxHistory
                    if len(textHistory) > maxHistory:
                        textHistory.pop(0)
                    currentGroup = []              

            ## Event Code: 122 [Control Variables] [Optional]
            if page['list'][i]['code'] == 122 and CODE122 == True:    
                jaString = page['list'][i]['parameters'][4]
                if type(jaString) != str:
                    continue
                
                # Definitely don't want to mess with files
                if '■' in jaString or '_' in jaString:
                    continue

                # If there isn't any Japanese in the text just skip
                if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', jaString):
                    continue
                
                # Definitely don't want to mess with files
                if '\"' not in jaString:
                    continue

                # Remove outside text
                oldjaString = jaString
                startString = re.search(r'^[^一-龠ぁ-ゔァ-ヴー\<\>【】\\]+', jaString)
                jaString = re.sub(r'^[^一-龠ぁ-ゔァ-ヴー\<\>【】\\]+', '', jaString)
                endString = re.search(r'[^一-龠ぁ-ゔァ-ヴー\<\>【】。！？\\]+$', jaString)
                jaString = re.sub(r'[^一-龠ぁ-ゔァ-ヴー\<\>【】。！？\\]+$', '', jaString)
                if startString is None: startString = ''
                else:  startString = startString.group()
                if endString is None: endString = ''
                else: endString = endString.group()

                # Translate
                response = translateGPT(jaString, '', True)
                tokens += response[1]
                translatedText = response[0]

                # Remove characters that may break scripts
                charList = ['.', '\"', "\'"]
                for char in charList:
                    translatedText = translatedText.replace(char, '')

                # Proper Formatting
                translatedText = translatedText.replace('"', '\"')

                # Set Data
                translatedText = startString + translatedText + endString
                page['list'][i]['parameters'][4] = translatedText

        ## Event Code: 357 [Picture Text] [Optional]
            if page['list'][i]['code'] == 357 and CODE357 == True:    
                if 'message' in page['list'][i]['parameters'][3]:
                    jaString = page['list'][i]['parameters'][3]['message']
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
                    page['list'][i]['parameters'][3]['message'] = startString + translatedText
            
        ## Event Code: 657 [Picture Text] [Optional]
            if page['list'][i]['code'] == 657 and CODE657 == True:    
                if 'text' in page['list'][i]['parameters'][0]:
                    jaString = page['list'][i]['parameters'][0]
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
                    page['list'][i]['parameters'][0] = translatedText

        ## Event Code: 101 [Name] [Optional]
            if page['list'][i]['code'] == 101 and CODE101 == True:    
                jaString = page['list'][i]['parameters'][4]
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
                page['list'][i]['parameters'][4] = translatedText

            ## Event Code: 355 or 655 Scripts [Optional]
            if (page['list'][i]['code'] == 355) and CODE355655 == True:
                jaString = page['list'][i]['parameters'][0]

                # If there isn't any Japanese in the text just skip
                if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', jaString):
                    continue

                # Want to translate this script
                if page['list'][i]['code'] == 355 and '_logWindow.push' not in jaString:
                    continue

                # Don't want to touch certain scripts
                if page['list'][i]['code'] == 655 and '.' in jaString:
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
                page['list'][i]['parameters'][0] = translatedText

        ## Event Code: 408 (Script)
            if (page['list'][i]['code'] == 408) and CODE408 == True:
                jaString = page['list'][i]['parameters'][0]

                # If there isn't any Japanese in the text just skip
                if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', jaString):
                    continue

                # Want to translate this script
                if page['list'][i]['code'] == 408 and '\\>' not in jaString:
                    continue

                # Need to remove outside code and put it back later
                startString = re.search(r'^[^一-龠ぁ-ゔァ-ヴー【】]+', jaString)
                jaString = re.sub(r'^[^一-龠ぁ-ゔァ-ヴー【】]+', '', jaString)
                endString = re.search(r'[^一-龠ぁ-ゔァ-ヴー【】。！？]+$', jaString)
                jaString = re.sub(r'[^一-龠ぁ-ゔァ-ヴー【】。！？]+$', '', jaString)
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
                page['list'][i]['parameters'][0] = translatedText

            ## Event Code: 356 D_TEXT
            if page['list'][i]['code'] == 356 and CODE356 == True:
                jaString = page['list'][i]['parameters'][0]
                oldjaString = jaString

                # If there isn't any Japanese in the text just skip
                if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', jaString):
                    continue

                # Want to translate this script
                if 'addLog' not in jaString:
                    continue

                # Need to remove outside code and put it back later
                startString = re.search(r'^[^一-龠ぁ-ゔァ-ヴー【】（）「」『』]+', jaString)
                jaString = re.sub(r'^[^一-龠ぁ-ゔァ-ヴー【】（）「」『』]+', '', jaString)
                endString = re.search(r' [^一-龠ぁ-ゔァ-ヴー\<\>【】（）「」『』 。！？]+$', jaString)
                jaString = re.sub(r' [^一-龠ぁ-ゔァ-ヴー\<\>【】（）「」『』 。！？]+$', '', jaString)
                if startString is None: startString = ''
                else:  startString = startString.group()
                if endString is None: endString = ''
                else: endString = endString.group()

                # Translate
                response = translateGPT(jaString, 'Reply with only the English Translation of the text.', True)
                tokens += response[1]
                translatedText = response[0]

                # Remove characters that may break scripts
                charList = ['.', '\"', '\\n']
                for char in charList:
                    translatedText = translatedText.replace(char, '')

                # Cant have spaces?
                translatedText = translatedText.replace(' ', '　')

                # Textwrap
                translatedText = textwrap.fill(translatedText, width=1000)

                # Set Data
                page['list'][i]['parameters'][0] = startString + translatedText + endString

            ### Event Code: 102 Show Choice
            if page['list'][i]['code'] == 102 and CODE102 == True:
                for choice in range(len(page['list'][i]['parameters'][0])):
                    jaString = page['list'][i]['parameters'][0][choice]
                    jaString = jaString.replace(' 。', '.')

                    # Need to remove outside code and put it back later
                    startString = re.search(r'^[^一-龠ぁ-ゔァ-ヴー【】（）Ａ-Ｚ０-９]+', jaString)
                    jaString = re.sub(r'^[^一-龠ぁ-ゔァ-ヴー【】（）Ａ-Ｚ０-９]+', '', jaString)
                    endString = re.search(r'[^一-龠ぁ-ゔァ-ヴー【】（）Ａ-Ｚ０-９ 。！？]+$', jaString)
                    jaString = re.sub(r'[^一-龠ぁ-ゔァ-ヴー【】（）Ａ-Ｚ０-９ 。！？]+$', '', jaString)
                    if startString is None: startString = ''
                    else:  startString = startString.group()
                    if endString is None: endString = ''
                    else: endString = endString.group()

                    if len(textHistory) > 0:
                        response = translateGPT(jaString, 'Previous text for context: ' + textHistory[len(textHistory)-1], False)
                        translatedText = response[0]
                    else:
                        response = translateGPT(jaString, '', False)
                        translatedText = response[0]

                    # Remove characters that may break scripts
                    charList = ['.', '\"', '\\n']
                    for char in charList:
                        translatedText = translatedText.replace(char, '')

                    # Set Data
                    tokens += response[1]
                    page['list'][i]['parameters'][0][choice] = startString + translatedText + endString

            ### Event Code: 111 Script
            if page['list'][i]['code'] == 111 and CODE111 == True:
                for j in range(len(page['list'][i]['parameters'])):
                    jaString = page['list'][i]['parameters'][j]

                    # Check if String
                    if type(jaString) != str:
                        continue

                    # Need to remove outside code and put it back later
                    startString = re.search(r'^[^一-龠ぁ-ゔァ-ヴー\<\>【】]+', jaString)
                    jaString = re.sub(r'^[^一-龠ぁ-ゔァ-ヴー\<\>【】]+', '', jaString)
                    endString = re.search(r'[^一-龠ぁ-ゔァ-ヴー【】 。！？]+$', jaString)
                    jaString = re.sub(r'[^一-龠ぁ-ゔァ-ヴー【】 。！？]+$', '', jaString)
                    if startString is None: startString = ''
                    else:  startString = startString.group()
                    if endString is None: endString = ''
                    else: endString = endString.group()

                    response = translateGPT(jaString, 'Reply with only the english translation.', True)
                    translatedText = response[0]

                    # Remove characters that may break scripts
                    charList = ['.', '\"', '\\n']
                    for char in charList:
                        translatedText = translatedText.replace(char, '')

                    # Set Data
                    tokens += response[1]
                    page['list'][i]['parameters'][j] = startString + translatedText + endString

            ### Event Code: 320 Set Variable
            if page['list'][i]['code'] == 320 and CODE320 == True or page['list'][i]['code'] == 324 and CODE324 == True:
                jaString = page['list'][i]['parameters'][1]

                # Need to remove outside code and put it back later
                startString = re.search(r'^[^一-龠ぁ-ゔァ-ヴー【】a-zA-Z\\]+', jaString)
                jaString = re.sub(r'^[^一-龠ぁ-ゔァ-ヴー【】a-zA-Z\\]+', '', jaString)
                endString = re.search(r'[^一-龠ぁ-ゔァ-ヴー【】。！？]+$', jaString)
                jaString = re.sub(r'[^一-龠ぁ-ゔァ-ヴー【】。！？]+$', '', jaString)
                if startString is None: startString = ''
                else:  startString = startString.group()
                if endString is None: endString = ''
                else: endString = endString.group()

                response = translateGPT(jaString, 'Reply with only the english translation of the npc nickname.', False)
                translatedText = response[0]

                # Remove characters that may break scripts
                charList = ['\"']
                for char in charList:
                    translatedText = translatedText.replace(char, '')

                translatedText = translatedText.strip('.')

                # Set Data
                tokens += response[1]
                page['list'][i]['parameters'][1] = startString + translatedText + endString

    except IndexError:
        # This is part of the logic so we just pass it.
        pass
    except Exception as e:
        tracebackLineNo = str(traceback.extract_tb(sys.exc_info()[2])[-1].lineno)
        raise Exception(str(e) + '|Line:' + tracebackLineNo + '| Failed to translate: ' + oldjaString)  
                
    # Append leftover groups in 401
    if len(currentGroup) > 0:
        # Translate
        response = translateGPT(finalJAString, 'Previous Translated Text for Context: ' + '\n\n'.join(textHistory), True)
        tokens += response[1]
        translatedText = response[0]

        # TextHistory is what we use to give GPT Context, so thats appended here.
        # rawTranslatedText = re.sub(r'[\\<>]+[a-zA-Z]+\[[a-zA-Z0-9]+\]', '', translatedText)
        textHistory.append('\"' + translatedText + '\"')

        # if speakerCaught == True:
        #     translatedText = speakerRaw + ':\n' + translatedText
        #     speakerCaught = False

        # Textwrap
        translatedText = textwrap.fill(translatedText, width=WIDTH)

        # Resub start and end
        translatedText = startString + translatedText

        # Set Data
        translatedText = translatedText.replace('ッ', '')
        translatedText = translatedText.replace('っ', '')
        translatedText = translatedText.replace('\"', '')
        page['list'][i]['parameters'][0] = translatedText
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
    responseList = [0] * 7

    responseList[0] = (translateGPT(state['message1'], 'reply with only the english translation of the text.', False))
    responseList[1] = (translateGPT(state['message2'], 'reply with only the english translation of the text.', False))
    responseList[2] = (translateGPT(state.get('message3', ''), 'reply with only the english translation of the text.', False))
    responseList[3] = (translateGPT(state.get('message4', ''), 'reply with only the english translation of the text.', False))
    responseList[4] = (translateGPT(state['name'], 'Reply with only the english translation of the RPG item name.', False))
    if 'description' in state:
        responseList[6] = (translateGPT(state['description'], 'reply with only the english translation of the description.', False))

    # if 'note' in state:
    #     if 'raceDesc' in state['note']:
    #         tokens += translateNote(state, r'<raceDesc:([^>]*)>')

    # Put all our translations in a list
    for i in range(len(responseList)):
        if responseList[i] != 0:
            tokens += responseList[i][1]
            responseList[i] = responseList[i][0].strip('.\"')
    
    # Set Data
    if responseList[0] != '':
        if responseList[0][0] != ' ':
            state['message1'] = ' ' + responseList[0][0].lower() + responseList[0][1:]
    state['message2'] = responseList[1]
    if responseList[2] != '':
        state['message3'] = responseList[2]
    if responseList[3] != '':
        state['message4'] = responseList[3]
    state['name'] = responseList[4].strip('.')
    # state['note'] = responseList[5]
    if responseList[6] != 0:
        responseList[6] = textwrap.fill(responseList[6], LISTWIDTH)
        state['description'] = responseList[6].strip('\"')


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

    # Variables
    for i in range(len(data['variables'])):
        response = translateGPT(data['variables'][i], 'Reply with only the english translation of the variable name.', False)
        tokens += response[1]
        data['variables'][i] = response[0].strip('.\"')
        pbar.update(1)

    # Messages
    messages = (data['terms']['messages'])
    for key, value in messages.items():
        response = translateGPT(value, 'Reply with only the english translation of the text.', False)
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
    varRegex = r'\\+[a-zA-Z]+\[[0-9a-zA-Z\\\[\]]+\]|[\\]+[#a-zA-Z]'
    count = 0

    varList = re.findall(varRegex, jaString)
    if len(varList) != 0:
        for var in varList:
            jaString = jaString.replace(var, '[' + str(count) + ']')
            count += 1

    return [jaString, varList]

def resubVars(translatedText, varList):
    count = 0
    
    if len(varList) != 0:
        for var in varList:
            translatedText = translatedText.replace('[' + str(count) + ']', var)
            count += 1

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
    if fullPromptFlag:
        system = PROMPT 
        user = 'Reply with only the English Translation of this text maintaining any code: ' + subbedT
    else:
        system = 'Reply with only the English translation of the text.' 
        user = 'Reply with only the English Translation of this dialogue menu option: ' + subbedT
    response = openai.ChatCompletion.create(
        temperature=0,
        model="gpt-3.5-turbo-16k",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": history},
            {"role": "user", "content": user}
        ],
        request_timeout=30,
    )

    translatedText = response.choices[0].message.content
    tokens = response.usage.total_tokens

    # Make sure translation didn't wonk out
    mlen=len(response.choices[0].message.content)
    elnt=10*len(subbedT)

    #Resub Vars
    translatedText = resubVars(translatedText, varResponse[1])

    if len(response.choices[0].message.content) > 10 * len(t):
        return [t, response.usage.total_tokens]
    else:
        return [translatedText, tokens]
    