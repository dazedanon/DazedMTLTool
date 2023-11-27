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
from ruamel.yaml import YAML

from colorama import Fore
from dotenv import load_dotenv
import openai
from retry import retry
from tqdm import tqdm

#Globals
load_dotenv()
if os.getenv('api').replace(' ', '') != '':
    openai.api_base = os.getenv('api')

openai.organization = os.getenv('org')
openai.api_key = os.getenv('key')
MODEL = os.getenv('model')
TIMEOUT = int(os.getenv('timeout'))
LANGUAGE=os.getenv('language').capitalize()

INPUTAPICOST = .002 # Depends on the model https://openai.com/pricing
OUTPUTAPICOST = .002
PROMPT = Path('prompt.txt').read_text(encoding='utf-8')
THREADS = int(os.getenv('threads')) # Controls how many threads are working on a single file (May have to drop this)
LOCK = threading.Lock()
WIDTH = int(os.getenv('width'))
LISTWIDTH = int(os.getenv('listWidth'))
NOTEWIDTH = 50
MAXHISTORY = 10
ESTIMATE = ''
totalTokens = [0, 0]
NAMESLIST = []

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
CODE356 = False
CODE320 = False
CODE324 = False
CODE111 = False
CODE408 = False
CODE108 = False
NAMES = False    # Output a list of all the character names found
BRFLAG = False   # If the game uses <br> instead
FIXTEXTWRAP = True
IGNORETLTEXT = True

def handleACE(filename, estimate):
    global ESTIMATE, totalTokens
    ESTIMATE = estimate

    if estimate:
        start = time.time()
        translatedData = openFiles(filename)

        # Print Result
        end = time.time()
        tqdm.write(getResultString(translatedData, end - start, filename))
        if NAMES == True:
            tqdm.write(str(NAMESLIST))
        with LOCK:
            totalTokens[0] += translatedData[1][0]
            totalTokens[1] += translatedData[1][1]

        return getResultString(['', totalTokens, None], end - start, 'TOTAL')
    
    else:
        try:
            with open('translated/' + filename, 'w', encoding='UTF-8') as outFile:
                start = time.time()
                translatedData = openFiles(filename)

                # Print Result
                end = time.time()
                yaml=YAML(pure=True)
                yaml.width = 4096
                yaml.default_style = "'"
                yaml.dump(translatedData[0], outFile)
                tqdm.write(getResultString(translatedData, end - start, filename))
                with LOCK:
                    totalTokens[0] += translatedData[1][0]
                    totalTokens[1] += translatedData[1][1]
        except Exception as e:
            return 'Fail'

    return getResultString(['', totalTokens, None], end - start, 'TOTAL')

def openFiles(filename):
    yaml=YAML(pure=True)   # Need a yaml instance per thread.
    yaml.width = 4096
    yaml.default_style = "'"

    with open('files/' + filename, 'r', encoding='UTF-8') as f:
        data = yaml.load(f)

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
        response = translateGPT(data['display_name'], 'Reply with only the '+ LANGUAGE +' translation of the RPG location name', False)
        totalTokens[0] += response[1][0]
        totalTokens[1] += response[1][1]
        data['display_name'] = response[0].replace('\"', '')

    # Get total for progress bar
    for key in events:
        if key is not None:
            for page in events[key]['pages']:
                totalLines += len(page['list'])
    
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
        pbar.desc=filename
        pbar.total=totalLines
        with ThreadPoolExecutor(max_workers=THREADS) as executor:
            for key in events:
                if key is not None:
                    # This translates text above items on the map.
                    # if 'LB:' in event['note']:
                        # totalTokens += translateNote(event, r'(?<=LB:)[^u0000-u0080]+')

                    futures = [executor.submit(searchCodes, page, pbar) for page in events[key]['pages'] if page is not None]
                    for future in as_completed(futures):
                        try:
                            totalTokensFuture = future.result()
                            totalTokens[0] += totalTokensFuture[0]
                            totalTokens[1] += totalTokensFuture[1]
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
        response = translateGPT(jaString, 'Reply with the '+ LANGUAGE +' translation of the note.', True)
        translatedText = response[0]

        # Textwrap
        translatedText = textwrap.fill(translatedText, width=NOTEWIDTH)

        translatedText = translatedText.replace('\"', '')
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

    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
        pbar.desc=filename
        pbar.total=totalLines
        with ThreadPoolExecutor(max_workers=THREADS) as executor:
            futures = [executor.submit(searchCodes, page, pbar) for page in data if page is not None]
            for future in as_completed(futures):
                try:
                    totalTokensFuture = future.result()
                    totalTokens[0] += totalTokensFuture[0]
                    totalTokens[1] += totalTokensFuture[1]
                except Exception as e:
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

    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
        pbar.desc=filename
        pbar.total=totalLines
        for troop in data:
            if troop is not None:
                with ThreadPoolExecutor(max_workers=THREADS) as executor:
                    futures = [executor.submit(searchCodes, page, pbar) for page in troop['pages'] if page is not None]
                    for future in as_completed(futures):
                        try:
                            totalTokensFuture = future.result()
                            totalTokens[0] += totalTokensFuture[0]
                            totalTokens[1] += totalTokensFuture[1]
                        except Exception as e:
                            return [data, totalTokens, e]
    return [data, totalTokens, None]
    
def parseNames(data, filename, context):
    totalTokens = [0, 0]
    totalLines = 0
    totalLines += len(data)
                
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
            pbar.desc=filename
            pbar.total=totalLines
            for name in data:
                if name is not None:
                    try:
                        result = searchNames(name, pbar, context)       
                        totalTokens[0] += result[0]
                        totalTokens[1] += result[1]
                    except Exception as e:
                        traceback.print_exc()
                        return [data, totalTokens, e]
    return [data, totalTokens, None]

def parseThings(data, filename):
    totalTokens = [0, 0]
    totalLines = 0
    totalLines += len(data)
                
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
            pbar.desc=filename
            pbar.total=totalLines
            for name in data:
                if name is not None:
                    try:
                        result = searchThings(name, pbar)       
                        totalTokens[0] += result[0]
                        totalTokens[1] += result[1]
                    except Exception as e:
                        return [data, totalTokens, e]
    return [data, totalTokens, None]

def parseSS(data, filename):
    totalTokens = [0, 0]
    totalLines = 0
    totalLines += len(data)
                
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
            pbar.desc=filename
            pbar.total=totalLines
            for ss in data:
                if ss is not None:
                    try:
                        result = searchSS(ss, pbar)       
                        totalTokens[0] += result[0]
                        totalTokens[1] += result[1]
                    except Exception as e:
                        return [data, totalTokens, e]
    return [data, totalTokens, None]

def parseSystem(data, filename):
    totalTokens = [0, 0]
    totalLines = 0

    # Calculate Total Lines
    for term in data['terms']:
        termList = data['terms'][term]
        totalLines += len(termList)
    totalLines += len(data['game_title'])
    totalLines += len(data['weapon_types'])
    totalLines += len(data['armor_types'])
    totalLines += len(data['skill_types'])
                
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
        pbar.desc=filename
        pbar.total=totalLines
        try:
            result = searchSystem(data, pbar)       
            totalTokens[0] += result[0]
            totalTokens[1] += result[1]
        except Exception as e:
            return [data, totalTokens, e]
    return [data, totalTokens, None]

def parseScenario(data, filename):
    totalTokens = [0, 0]
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
                    totalTokensFuture = future.result()
                    totalTokens[0] += totalTokensFuture[0]
                    totalTokens[1] += totalTokensFuture[1]
                except Exception as e:
                    return [data, totalTokens, e]
    return [data, totalTokens, None]

def searchThings(name, pbar):
    totalTokens = [0, 0]

    # If there isn't any Japanese in the text just skip
    if IGNORETLTEXT == True:
        if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', name['name']) and re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', name['description']):
            pbar.update(1)
            return totalTokens

    # Name
    nameResponse = translateGPT(name['name'], 'Reply with only the '+ LANGUAGE +' translation of the RPG item name.', False) if 'name' in name else ''

    # Description
    descriptionResponse = translateGPT(name['description'], 'Reply with only the '+ LANGUAGE +' translation of the description.', False) if 'description' in name else ''

    # Note
    if '<SG説明:' in name['note']:
        totalTokens[0] += translateNote(name, r'<SG説明:(.*?)>')[0]
        totalTokens[1] += translateNote(name, r'<SG説明:(.*?)>')[1]
    if '<SGカテゴリ':
        totalTokens[0] += translateNote(name, r'<SGカテゴリ:(.*?)>')[0]
        totalTokens[1] += translateNote(name, r'<SGカテゴリ:(.*?)>')[1]

    # Count totalTokens
    totalTokens[0] += nameResponse[1][0] if nameResponse != '' else 0
    totalTokens[1] += nameResponse[1][1] if nameResponse != '' else 0
    totalTokens[0] += descriptionResponse[1][0] if descriptionResponse != '' else 0
    totalTokens[1] += descriptionResponse[1][1] if descriptionResponse != '' else 0

    # Set Data
    if 'name' in name:
        name['name'] = nameResponse[0].replace('\"', '')
    if 'description' in name:
        description = descriptionResponse[0]

        # Remove Textwrap
        description = description.replace('\n', ' ')
        description = textwrap.fill(descriptionResponse[0], LISTWIDTH)
        name['description'] = description.replace('\"', '')

    pbar.update(1)
    return totalTokens

def searchNames(name, pbar, context):
    totalTokens = [0, 0]

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

    # Extract Data
    responseList = []
    responseList.append(translateGPT(name['name'], newContext, True))
    if 'Actors' in context:
        responseList.append(translateGPT(name['description'], '', True))
        responseList.append(translateGPT(name['nickname'], 'Reply with ONLY the '+ LANGUAGE +' translation of the NPC nickname', True))

    if 'Armors' in context or 'Weapons' in context:
        if 'description' in name:
            responseList.append(translateGPT(name['description'], '', True))
        else:
            responseList.append(['', 0])
        if 'hint' in name['note']:
            totalTokens[0] += translateNote(name, r'<hint:(.*?)>')[0]
            totalTokens[1] += translateNote(name, r'<hint:(.*?)>')[1]

    if 'Enemies' in context:
        if 'variable_update_skill' in name['note']:
            totalTokens[0] += translateNote(name, r'111:(.+?)\n')[0]
            totalTokens[1] += translateNote(name, r'111:(.+?)\n')[1]

        if 'desc2' in name['note']:
            totalTokens[0] += translateNote(name, r'<desc2:([^>]*)>')[0]
            totalTokens[1] += translateNote(name, r'<desc2:([^>]*)>')[1]

        if 'desc3' in name['note']:
            totalTokens[0] += translateNote(name, r'<desc3:([^>]*)>')[0]
            totalTokens[1] += translateNote(name, r'<desc3:([^>]*)>')[1]

    # Extract all our translations in a list from response
    for i in range(len(responseList)):
        totalTokens[0] += responseList[i][1][0]
        totalTokens[1] += responseList[i][1][1]
        responseList[i] = responseList[i][0]

    # Set Data
    name['name'] = responseList[0].replace('\"', '')
    if 'Actors' in context:
        translatedText = textwrap.fill(responseList[1], LISTWIDTH)
        name['profile'] = translatedText.replace('\"', '')
        translatedText = textwrap.fill(responseList[2], LISTWIDTH)
        name['nickname'] = translatedText.replace('\"', '')
        if '<特徴1:' in name['note']:
            totalTokens[0] += translateNote(name, r'<特徴1:([^>]*)>')[0]
            totalTokens[1] += translateNote(name, r'<特徴1:([^>]*)>')[1]

    if 'Armors' in context or 'Weapons' in context:
        translatedText = textwrap.fill(responseList[1], LISTWIDTH)
        if 'description' in name:
            name['description'] = translatedText.replace('\"', '')
            if '<SG説明:' in name['note']:
                totalTokens[0] += translateNote(name, r'<Info Text Bottom>\n([\s\S]*?)\n</Info Text Bottom>')[0]
                totalTokens[1] += translateNote(name, r'<Info Text Bottom>\n([\s\S]*?)\n</Info Text Bottom>')[1]
    pbar.update(1)

    return totalTokens

def searchCodes(page, pbar):
    translatedText = ''
    currentGroup = []
    textHistory = []
    maxHistory = MAXHISTORY
    totalTokens = [0, 0]
    speaker = ''
    speakerVar = ''
    nametag = ''
    match = []
    syncIndex = 0
    CLFlag = False
    global LOCK
    global NAMESLIST

    try:
        if 'list' in page:
            codeList = page['list']
        else:
            codeList = page
        for i in range(len(codeList)):
            with LOCK:  
                if syncIndex > i:
                    i = syncIndex
                pbar.update(1)
                if len(codeList) <= i:
                    break

            ### All the codes are here which translate specific functions in the MAP files.
            ### IF these crash or fail your game will do the same. Use the flags to skip codes.

            ## Event Code: 401 Show Text
            if codeList[i]['c'] == 401 and CODE401 == True or codeList[i]['c'] == 405 and CODE405:  
                # Use this to place text later
                code = codeList[i]['c']
                j = i

                # Grab String
                if len(codeList[i]['p']) > 0:
                    jaString = codeList[i]['p'][0]
                    firstJAString = jaString
                else:
                    codeList[i]['c'] = -1
                    continue

                # If there isn't any Japanese in the text just skip
                if IGNORETLTEXT == True:
                    if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', jaString):
                        # Keep textHistory list at length maxHistory
                        textHistory.append('\"' + jaString + '\"')
                        if len(textHistory) > maxHistory:
                            textHistory.pop(0)
                        currentGroup = []  
                        continue

                # Using this to keep track of 401's in a row. Throws IndexError at EndOfList (Expected Behavior)
                currentGroup.append(jaString)

                if len(codeList) > i+1:
                    while (codeList[i+1]['c'] == 401 or codeList[i+1]['c'] == 405):
                        codeList[i]['p'] = []
                        codeList[i]['c'] = -1
                        i += 1

                        # Only add if not empty
                        if len(codeList[i]['p']) > 0:
                            jaString = codeList[i]['p'][0]
                            currentGroup.append(jaString)

                        # Make sure not the end of the list.
                        if len(codeList) <= i+1:
                            break

                # Join up 401 groups for better translation.
                if len(currentGroup) > 0:
                    finalJAString = ''.join(currentGroup)
                    oldjaString = finalJAString

                    # Color Regex: ^([\\]+[cC]\[[0-9]\]+(.+?)[\\]+[cC]\[[0]\])
                    matchList = re.findall(r'(.*?([\\]+[nN]<(.+?)>).*)', finalJAString)
                    if len(matchList) > 0:  
                        response = translateGPT(matchList[0][2], 'Reply with only the '+ LANGUAGE +' translation of the NPC name', False)
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]
                        speaker = response[0].strip('.')
                        nametag = matchList[0][1].replace(matchList[0][2], speaker)
                        finalJAString = finalJAString.replace(matchList[0][1], '')

                        # Set next item as dialogue
                        if (codeList[j + 1]['c'] == -1 and len(codeList[j + 1]['p']) > 0) or codeList[j + 1]['c'] == -1:
                            # Set name var to top of list
                            codeList[j]['p'][0] = nametag
                            codeList[j]['c'] = code

                            j += 1
                            codeList[j]['p'][0] = finalJAString
                            codeList[j]['c'] = code
                            nametag = ''
                        else:
                            # Set nametag in string
                            codeList[j]['p'][0] = nametag + finalJAString
                            codeList[j]['c'] = code
                        
                        # Put names in list
                        if speaker not in NAMESLIST:
                            with LOCK:
                                NAMESLIST.append(speaker)
                    # elif '\\kw' in finalJAString:
                    #     match = re.findall(r'\\+kw\[[0-9]+\]', finalJAString)
                    #     if len(match) != 0:
                    #         if '1' in match[0]:
                    #             speaker = 'Ayako Nagatsuki'
                    #         if '2' in match[0]:
                    #             speaker = 'Rei'
                            
                    #         # Set name var to top of list
                    #         codeList[j]['p'][0] = match[0]
                    #         codeList[j]['c'] = code

                    #         # Set next item as dialogue
                    #         j += 1
                    #         codeList[j]['p'][0] = match[0]
                    #         codeList[j]['c'] = code

                    #         # Remove nametag from final string
                    #         finalJAString = finalJAString.replace(match[0], '')  
                    elif '\\nc' in finalJAString:     
                        matchList = re.findall(r'(\\+nc<(.*?)>)(.+)?', finalJAString)    
                        if len(matchList) != 0:    
                            # Translate Speaker  
                            response = translateGPT(matchList[0][1], 'Reply with only the '+ LANGUAGE +' translation of the NPC name', True)
                            totalTokens[0] += response[1][0]
                            totalTokens[1] += response[1][1]
                            speaker = response[0].strip('.')
                            nametag = matchList[0][0].replace(matchList[0][1], speaker)
                            finalJAString = finalJAString.replace(matchList[0][0], '')

                            # Set dialogue
                            codeList[j]['p'][0] = matchList[0][2]
                            codeList[j]['c'] = 401

                            # Remove nametag from final string
                            finalJAString = finalJAString.replace(nametag, '')
                    elif '\\nw' in finalJAString or '\\NW' in finalJAString:
                        matchList = re.findall(r'([\\]+[nN][wW]\[(.+?)\]+)(.+)', finalJAString)    
                        if len(matchList) != 0:    
                            response = translateGPT(matchList[0][1], 'Reply with only the '+ LANGUAGE +' translation of the NPC name', True)
                            totalTokens[0] += response[1][0]
                            totalTokens[1] += response[1][1]
                            speaker = response[0].strip('.')

                            # Set Nametag and Remove from Final String
                            nametag = matchList[0][0].replace(matchList[0][1], speaker)
                            finalJAString = finalJAString.replace(matchList[0][0], '')

                        # Set next item as dialogue
                        # if (codeList[j + 1]['c'] == 401 and len(codeList[j + 1]['p']) > 0) or (codeList[j + 1]['c'] == 0 and len(codeList[j + 1]['p']) > 0):
                        #     # Set name var to top of list
                        #     codeList[j]['p'][0] = nametag
                        #     codeList[j]['c'] = code

                        #     j += 1
                        #     codeList[j]['p'][0] = finalJAString
                        #     codeList[j]['c'] = code
                        #     nametag = ''
                        # else:
                        # Set nametag in string
                        codeList[j]['p'][0] = nametag + finalJAString
                        codeList[j]['c'] = code
                    ### Only for Specific games where name is surrounded by brackets.
                    # elif '【' in finalJAString:
                    #     matchList = re.findall(r'(.+?【(.+?)】.+?)(「.+)', finalJAString)    
                    #     if len(matchList) != 0:    
                    #         response = translateGPT(matchList[0][1], 'Reply with only the '+ LANGUAGE +' translation of the NPC name', True)
                    #     else:
                    #         print('wtf')
                    #     totalTokens[0] += response[1][0]
                    #     totalTokens[1] += response[1][1]
                    #     speaker = response[0].strip('.')

                    #     # Set Nametag and Remove from Final String
                    #     nametag = matchList[0][0].replace(matchList[0][1], speaker)
                    #     finalJAString = finalJAString.replace(matchList[0][0], '')

                    #     # Set next item as dialogue
                    #     if (codeList[j + 1]['c'] == 401 and len(codeList[j + 1]['p']) > 0) or codeList[j + 1]['c'] == 0:
                    #         # Set name var to top of list
                    #         codeList[j]['p'][0] = nametag
                    #         codeList[j]['c'] = code

                    #         j += 1
                    #         codeList[j]['p'][0] = finalJAString
                    #         codeList[j]['c'] = code
                    #         nametag = ''
                    #     else:
                    #         # Set nametag in string
                    #         codeList[j]['p'][0] = nametag + finalJAString
                    #         codeList[j]['c'] = code

                    # Special Effects
                    soundEffectString = ''
                    matchList = re.findall(r'(.+\\SE\[.+?\])', finalJAString)    
                    if len(matchList) != 0:
                        soundEffectString = matchList[0]
                        finalJAString = finalJAString.replace(matchList[0], '')

                    # Remove any textwrap
                    if FIXTEXTWRAP == True:
                        finalJAString = re.sub(r'\n', ' ', finalJAString)
                        finalJAString = finalJAString.replace('<br>', ' ')

                    # Remove Extra Stuff
                    finalJAString = finalJAString.replace('ﾞ', '')
                    finalJAString = finalJAString.replace('。', '.')
                    finalJAString = finalJAString.replace('？', '?')
                    finalJAString = finalJAString.replace('！', '!')
                    finalJAString = finalJAString.replace('：', ':')
                    finalJAString = finalJAString.replace('・', '.')
                    finalJAString = finalJAString.replace('‶', '')
                    finalJAString = finalJAString.replace('”', '')
                    finalJAString = finalJAString.replace('―', '-')
                    finalJAString = finalJAString.replace('…', '...')
                    finalJAString = finalJAString.replace('　', '')
                    # finalJAString = finalJAString.replace('〇', '*')

                    # Remove any RPGMaker Code at start
                    ffMatchList = re.findall(r'[\\]+[fF]+\[.+?\]', finalJAString)
                    if len(ffMatchList) > 0:
                        finalJAString = finalJAString.replace(ffMatchList[0], '')
                        nametag += ffMatchList[0]

                    ### Remove format codes
                    # Furigana
                    rcodeMatch = re.findall(r'([\\]+[r][b]?\[.+?,(.+?)\])', finalJAString)
                    if len(rcodeMatch) > 0:
                        for match in rcodeMatch:
                            finalJAString = finalJAString.replace(match[0],match[1])

                    # Formatting Codes
                    formatMatch = re.findall(r'[\\]+[!><.|#^]', finalJAString)
                    if len(formatMatch) > 0:
                        for match in formatMatch:
                            finalJAString = finalJAString.replace(match, '')

                    # Center Lines
                    if '\\CL' in finalJAString:
                        finalJAString = finalJAString.replace('\\CL', '')
                        CLFlag = True

                    # Translate
                    if speaker == '' and finalJAString != '':
                        response = translateGPT(finalJAString, textHistory, True)
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]
                        translatedText = response[0]

                        # Change added speaker
                        translatedText = re.sub(r'(^.+?)\s?[|:]\s?', '\g<1>: ', translatedText)

                        # Sub Vars
                        varResponse = subVars(translatedText)
                        subbedT = varResponse[0]
                        textHistory.append('\"' + varResponse[0] + '\"')
                    elif finalJAString != '':
                        response = translateGPT(speaker + ': ' + finalJAString, textHistory, True)
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]
                        translatedText = response[0]
                        
                        # Remove added speaker
                        translatedText = re.sub(r'(^.+?)\s?[|:]\s?', '', translatedText)

                        # Sub Vars
                        varResponse = subVars(translatedText)
                        subbedT = varResponse[0]
                        textHistory.append('\"' + speaker + ': ' + varResponse[0] + '\"')   
                        speaker = ''             
                    else:
                        translatedText = finalJAString    

                    # Textwrap
                    if FIXTEXTWRAP == True:
                        translatedText = textwrap.fill(translatedText, width=WIDTH)
                        if BRFLAG == True:
                            translatedText = translatedText.replace('\n', '<br>')   

                    # Add Beginning Text
                    if CLFlag:
                        translatedText = '\\CL' + translatedText
                        CLFlag = False
                    translatedText = nametag + translatedText
                    nametag = ''
                    translatedText = soundEffectString + translatedText

                    # Set Data
                    translatedText = translatedText.replace('\"', '')
                    codeList[i]['p'] = []
                    codeList[i]['c'] = -1
                    codeList[j]['p'] = [translatedText]
                    codeList[j]['c'] = code
                    speaker = ''
                    match = []
                    syncIndex = i + 1

                    # Keep textHistory list at length maxHistory
                    if len(textHistory) > maxHistory:
                        textHistory.pop(0)
                    currentGroup = []              

            ## Event Code: 122 [Set Variables]
            if codeList[i]['c'] == 122 and CODE122 == True:  
                # This is going to be the var being set. (IMPORTANT)
                varNum = codeList[i]['p'][0]
                if varNum not in [1178]:
                    continue
                  
                jaString = codeList[i]['p'][4]
                if type(jaString) != str:
                    continue
                
                # Definitely don't want to mess with files
                if '■' in jaString or '_' in jaString:
                    continue

                # Definitely don't want to mess with files
                # if '\"' not in jaString:
                #     continue

                # Need to remove outside code and put it back later
                matchList = re.findall(r"[\'\"\`](.*)[\'\"\`]", jaString)
                
                for match in matchList:
                    # Remove Textwrap
                    match = match.replace('\\n', ' ')
                    response = translateGPT(match, 'Reply with the '+ LANGUAGE +' translation.', True)
                    translatedText = response[0]
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]

                    # Replace
                    translatedText = jaString.replace(jaString, translatedText)

                    # Remove characters that may break scripts
                    charList = ['.', '\"', '\\n']
                    for char in charList:
                        translatedText = translatedText.replace(char, '')
                
                # Textwrap
                translatedText = textwrap.fill(translatedText, width=LISTWIDTH)
                translatedText = translatedText.replace('\n', '\\n')
                # translatedText = translatedText.replace('\'', '\\\'')
                translatedText = '\"' + translatedText + '\"'

                # Set Data
                codeList[i]['p'][4] = translatedText

        ## Event Code: 357 [Picture Text] [Optional]
            if codeList[i]['c'] == 357 and CODE357 == True:    
                if 'message' in codeList[i]['p'][3]:
                    jaString = codeList[i]['p'][3]['message']
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
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]
                    translatedText = response[0]

                    # Textwrap
                    translatedText = textwrap.fill(translatedText, width=WIDTH)

                    # Set Data
                    codeList[i]['p'][3]['message'] = startString + translatedText
            
        ## Event Code: 657 [Picture Text] [Optional]
            if codeList[i]['c'] == 657 and CODE657 == True:    
                if 'text' in codeList[i]['p'][0]:
                    jaString = codeList[i]['p'][0]
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
                    if '\\' in jaString:
                        print('Hi')
                    codeList[i]['p'][0] = translatedText

        ## Event Code: 101 [Name] [Optional]
            if codeList[i]['c'] == 101 and CODE101 == True:  
                # Grab String
                jaString = ''  
                if len(codeList[i]['p']) > 4:
                    jaString = codeList[i]['p'][4]
                if type(jaString) != str:
                    continue

                # Force Speaker
                matchList = re.findall(r'(\w+)\\?', jaString)
                if len(matchList) > 0:
                    if 'エスカ' in jaString:
                        speaker = 'Esuka'
                        codeList[i]['p'][4] = jaString.replace(matchList[0], speaker)
                        continue
                    elif 'シュウ' in jaString:
                        speaker = 'Shuu'
                        codeList[i]['p'][4] = jaString.replace(matchList[0], speaker)
                        continue
                    elif 'ワルチン総統' in jaString:
                        speaker = 'President Waltin'
                        codeList[i]['p'][4] = jaString.replace(matchList[0], speaker)
                        continue
                    else:
                        speaker = ''
                
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
                response = translateGPT(jaString, 'Reply with only the '+ LANGUAGE +' translation of the NPC name.', False)
                totalTokens[0] += response[1][0]
                totalTokens[1] += response[1][1]
                translatedText = response[0]

                # Remove characters that may break scripts
                charList = ['.', '\"']
                for char in charList:
                    translatedText = translatedText.replace(char, '')

                translatedText = startString + translatedText + endString

                # Set Data
                speaker = translatedText
                codeList[i]['p'][4] = translatedText
                if speaker not in NAMESLIST:
                    with LOCK:
                        NAMESLIST.append(speaker)

            ## Event Code: 355 or 655 Scripts [Optional]
            if (codeList[i]['c'] == 355 or codeList[i]['c'] == 655) and CODE355655 == True:
                jaString = codeList[i]['p'][0]

                # If there isn't any Japanese in the text just skip
                if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', jaString):
                    continue

                if '<' in jaString:
                    continue

                # Want to translate this script
                if 'var str =' not in jaString:
                    continue

                # Need to remove outside code and put it back later
                matchList = re.findall(r'var str ="(.+)"', jaString)

                # Translate
                if len(matchList) > 0:
                    # If there isn't any Japanese in the text just skip
                    if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', matchList[0]):
                        continue

                    response = translateGPT(matchList[0], 'Reply with the '+ LANGUAGE +' translation Stat Title. Keep it brief.', True)
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]
                    translatedText = response[0]

                    # Remove characters that may break scripts
                    charList = ['.', '\"']
                    for char in charList:
                        translatedText = translatedText.replace(char, '')
                    translatedText = translatedText.replace('"', '\"')
                    translatedText = translatedText.replace("'", '\'')
                    translatedText = jaString.replace(matchList[0], translatedText)

                    # Set Data
                    codeList[i]['p'][0] = translatedText

        ## Event Code: 408 (Script)
            if (codeList[i]['c'] == 408) and CODE408 == True:
                jaString = codeList[i]['p'][0]

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
                totalTokens[0] += response[1][0]
                totalTokens[1] += response[1][1]
                translatedText = response[0]

                # Remove characters that may break scripts
                charList = ['.', '\"']
                for char in charList:
                    translatedText = translatedText.replace(char, '')

                translatedText = startString + translatedText + endString

                translatedText = translatedText.replace('"', '\"')

                # Set Data
                codeList[i]['p'][0] = translatedText

            ## Event Code: 108 (Script)
            if (codeList[i]['c'] == 108) and CODE108 == True:
                jaString = codeList[i]['p'][0]

                # If there isn't any Japanese in the text just skip
                if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', jaString):
                    continue

                # Want to translate this script
                if 'text_indicator : ' not in jaString:
                    continue

                # Need to remove outside code and put it back later
                matchList = re.findall(r'text_indicator : (.+)', jaString)

                # Translate
                if len(matchList) > 0:
                    response = translateGPT(matchList[0], 'Reply with the '+ LANGUAGE +' translation of the Location Title', True)
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
                    codeList[i]['p'][0] = translatedText

            ## Event Code: 356
            if codeList[i]['c'] == 356 and CODE356 == True:
                jaString = codeList[i]['p'][0]
                oldjaString = jaString

                # Grab Speaker
                if 'Tachie showName' in jaString:
                    matchList = re.findall(r'Tachie showName (.+)', jaString)
                    if len(matchList) > 0:
                        # Translate
                        response = translateGPT(matchList[0], 'Reply with the '+ LANGUAGE +' translation of the NPC name.', True)
                        translatedText = response[0]
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]

                        # Set Text
                        speaker = translatedText
                        speaker = speaker.replace(' ', ' ')
                        codeList[i]['p'][0] = jaString.replace(matchList[0], speaker)
                    continue

                # If there isn't any Japanese in the text just skip
                if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', jaString):
                    continue

                # Want to translate this script
                if 'D_TEXT ' in jaString:
                    # Remove any textwrap
                    jaString = re.sub(r'\n', '_', jaString)

                    # Capture Arguments and text
                    dtextList = re.findall(r'D_TEXT\s(.+)\s|D_TEXT\s(.+)', jaString)
                    if len(dtextList) > 0:
                        if dtextList[0][0] != '':
                            dtext = dtextList[0][0]
                        else:
                            dtext = dtextList[0][1]
                        originalDTEXT = dtext

                        # Using this to keep track of 401's in a row. Throws IndexError at EndOfList (Expected Behavior)
                        currentGroup.append(dtext)

                        while (codeList[i+1]['c'] == 356):
                            # Want to translate this script
                            if 'D_TEXT ' not in codeList[i+1]['p'][0]:
                                break

                            codeList[i]['p'][0] = ''
                            i += 1
                            jaString = codeList[i]['p'][0]
                            dtextList = re.findall(r'D_TEXT\s(.+)\s|D_TEXT\s(.+)', jaString)
                            if len(dtextList) > 0:
                                if dtextList[0][0] != '':
                                    dtext = dtextList[0][0]
                                else:
                                    dtext = dtextList[0][1]
                                currentGroup.append(dtext)

                        # Join up 356 groups for better translation.
                        if len(currentGroup) > 0:
                            finalJAString = ' '.join(currentGroup)
                        else:
                            finalJAString = dtext

                        # Clear Group
                        currentGroup = [] 

                        # Translate
                        response = translateGPT(finalJAString, 'Reply with the '+ LANGUAGE +' Translation.', True)
                        translatedText = response[0]
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]

                        # Textwrap
                        translatedText = textwrap.fill(translatedText, width=20, drop_whitespace=False)

                        # Remove characters that may break scripts
                        charList = ['.', '\"']
                        for char in charList:
                            translatedText = translatedText.replace(char, '')
                        
                        # Cant have spaces?
                        translatedText = translatedText.replace(' ', '_')

                        # Fix spacing after ___
                        translatedText = translatedText.replace('__\n', '__')
                    
                        # Put Args Back
                        translatedText = jaString.replace(originalDTEXT, translatedText)

                        # Set Data
                        codeList[i]['p'][0] = translatedText
                    else:
                        continue

                if 'ShowInfo ' in jaString:
                    # Remove any textwrap
                    jaString = re.sub(r'\n', '_', jaString)

                    # Capture Arguments and text
                    infoList = re.findall(r'ShowInfo (.+)', jaString)
                    if len(infoList) > 0:
                        info = infoList[0]
                        originalInfo = info

                        # Remove underscores
                        info = re.sub(r'_', ' ', info)

                        # Using this to keep track of 401's in a row. Throws IndexError at EndOfList (Expected Behavior)
                        currentGroup.append(info)

                        while (codeList[i+1]['c'] == 356):
                            # Want to translate this script
                            if 'ShowInfo ' not in codeList[i+1]['p'][0]:
                                break

                            codeList[i]['p'][0] = ''
                            i += 1
                            jaString = codeList[i]['p'][0]
                            infoList = re.findall(r'ShowInfo (.+)', jaString)
                            if len(infoList) > 0:
                                dtext = infoList[0]
                                currentGroup.append(info)

                        # Join up 356 groups for better translation.
                        if len(currentGroup) > 0:
                            finalJAString = ' '.join(currentGroup)
                        else:
                            finalJAString = info

                        # Clear Group
                        currentGroup = [] 
                    
                        # Remove any textwrap
                        jaString = re.sub(r'\n', '_', jaString)

                        # Translate
                        response = translateGPT(finalJAString, 'Reply with the '+ LANGUAGE +' Translation.', True)
                        translatedText = response[0]
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]

                        # Remove characters that may break scripts
                        charList = ['.', '\"']
                        for char in charList:
                            translatedText = translatedText.replace(char, '')
                        
                        # Cant have spaces?
                        translatedText = translatedText.replace(' ', '_')
                    
                        # Put Args Back
                        translatedText = jaString.replace(originalInfo, translatedText)

                        # Set Data
                        codeList[i]['p'][0] = translatedText
                    else:
                        continue

                if 'PushGab ' in jaString:
                    # Remove any textwrap
                    jaString = re.sub(r'\n', '_', jaString)

                    # Capture Arguments and text
                    infoList = re.findall(r'PushGab [0-9]+ (.+)', jaString)
                    if len(infoList) > 0:
                        info = infoList[0]
                        originalInfo = info

                        # Remove underscores
                        info = re.sub(r'_', ' ', info)

                        # Using this to keep track of 401's in a row. Throws IndexError at EndOfList (Expected Behavior)
                        currentGroup.append(info)

                        while (codeList[i+1]['c'] == 356):
                            # Want to translate this script
                            if 'PushGab ' not in codeList[i+1]['p'][0]:
                                break

                            codeList[i]['p'][0] = ''
                            i += 1
                            jaString = codeList[i]['p'][0]
                            infoList = re.findall(r'PushGab [0-9]+ (.+)', jaString)
                            if len(infoList) > 0:
                                dtext = infoList[0]
                                currentGroup.append(info)

                        # Join up 356 groups for better translation.
                        if len(currentGroup) > 0:
                            finalJAString = ' '.join(currentGroup)
                        else:
                            finalJAString = info

                        # Clear Group
                        currentGroup = [] 
                    
                        # Remove any textwrap
                        jaString = re.sub(r'\n', '_', jaString)

                        # Translate
                        response = translateGPT(finalJAString, 'Reply with the '+ LANGUAGE +' Translation.', True)
                        translatedText = response[0]
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]

                        # Remove characters that may break scripts
                        charList = ['.', '\"']
                        for char in charList:
                            translatedText = translatedText.replace(char, '')
                        
                        # Cant have spaces?
                        translatedText = translatedText.replace(' ', '_')
                    
                        # Put Args Back
                        translatedText = jaString.replace(originalInfo, translatedText)

                        # Set Data
                        codeList[i]['p'][0] = translatedText
                    else:
                        continue

            ### Event Code: 102 Show Choice
            if codeList[i]['c'] == 102 and CODE102 == True:
                for choice in range(len(codeList[i]['p'][0])):
                    jaString = codeList[i]['p'][0][choice]
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
                        response = translateGPT(jaString, 'Keep your translation as brief as possible. Previous text for context: ' + textHistory[len(textHistory)-1] + '\n\nReply in the style of a dialogue option.', True)
                        translatedText = response[0]
                    else:
                        response = translateGPT(jaString, 'Keep your translation as brief as possible.\n\nStyle: dialogue option.', True)
                        translatedText = response[0]

                    # Remove characters that may break scripts
                    charList = ['.', '\"', '\\n']
                    for char in charList:
                        translatedText = translatedText.replace(char, '')

                    # Set Data
                    totalTokens[0] += response[1][0]
                    totalTokens[1] += response[1][1]
                    codeList[i]['p'][0][choice] = startString + translatedText + endString

            ### Event Code: 111 Script
            if codeList[i]['c'] == 111 and CODE111 == True:
                for j in range(len(codeList[i]['p'])):
                    jaString = codeList[i]['p'][j]

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
                        totalTokens[0] += response[1][0]
                        totalTokens[1] += response[1][1]

                        # Remove characters that may break scripts
                        charList = ['.', '\"', '\'', '\\n']
                        for char in charList:
                            translatedText = translatedText.replace(char, '')

                        jaString = jaString.replace(match, translatedText)

                    # Set Data
                    translatedText = jaString
                    codeList[i]['p'][j] = translatedText

            ### Event Code: 320 Set Variable
            if codeList[i]['c'] == 320 and CODE320 == True:                
                jaString = codeList[i]['p'][1]
                if type(jaString) != str:
                    continue
                
                # Definitely don't want to mess with files
                if '■' in jaString or '_' in jaString:
                    continue

                # If there isn't any Japanese in the text just skip
                if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', jaString):
                    continue
                
                response = translateGPT(jaString, 'Reply with the '+ LANGUAGE +' translation of the NPC name.', True)
                translatedText = response[0]
                totalTokens[0] += response[1][0]
                totalTokens[1] += response[1][1]

                # Remove characters that may break scripts
                charList = ['.', '\"', '\'', '\\n']
                for char in charList:
                    translatedText = translatedText.replace(char, '')

                # Set Data
                codeList[i]['p'][1] = translatedText

        # Delete all -1 codes
        codeListFinal = []
        for i in range(len(codeList)):
            if codeList[i]['c'] != -1:
                codeListFinal.append(codeList[i])
        page['list'] = codeListFinal

    except IndexError as e:
        # This is part of the logic so we just pass it
        traceback.print_exc()
        print(len(codeList))
        print(i+1)
        # raise Exception(str(e) + '|Line:' + tracebackLineNo)  
    except Exception as e:
        traceback.print_exc()
        raise Exception(str(e) + 'Failed to translate: ' + oldjaString)  
                
    # Append leftover groups in 401
    if len(currentGroup) > 0:
        # Translate
        response = translateGPT(finalJAString, 'Previous Translated Text for Context: ' + '\n\n'.join(textHistory), True)
        totalTokens[0] += response[1][0]
        totalTokens[1] += response[1][1]
        translatedText = response[0]

        # TextHistory is what we use to give GPT Context, so thats appended here.
        textHistory.append('\"' + translatedText + '\"')

        # Textwrap
        translatedText = textwrap.fill(translatedText, width=WIDTH)

        # Set Data
        translatedText = translatedText.replace('ッ', '')
        translatedText = translatedText.replace('っ', '')
        translatedText = translatedText.replace('\"', '')
        codeList[i]['p'][0] = translatedText
        speaker = ''
        match = []

        # Keep textHistory list at length maxHistory
        if len(textHistory) > maxHistory:
            textHistory.pop(0)
        currentGroup = []    

    return totalTokens

def searchSS(state, pbar):
    '''Searches skills and states json files'''
    totalTokens = [0, 0]

    # Name
    nameResponse = translateGPT(state['name'], 'Reply with only the '+ LANGUAGE +' translation of the RPG Skill name.', True) if 'name' in state else ''

    # Description
    descriptionResponse = translateGPT(state['description'], 'Reply with only the '+ LANGUAGE +' translation of the description.', True) if 'description' in state else ''

    # Messages
    message1Response = ''
    message4Response = ''
    message2Response = ''
    message3Response = ''
    
    if 'message1' in state:
        if len(state['message1']) > 0 and state['message1'][0] in ['は', 'を', 'の', 'に', 'が']:
            message1Response = translateGPT('Taro' + state['message1'], 'reply with only the gender neutral '+ LANGUAGE +' translation of the action. Always start the sentence with Taro.', True)
        else:
            message1Response = translateGPT(state['message1'], 'reply with only the gender neutral '+ LANGUAGE +' translation', True)

    if 'message2' in state:
        if len(state['message2']) > 0 and state['message2'][0] in ['は', 'を', 'の', 'に', 'が']:
            message2Response = translateGPT('Taro' + state['message2'], 'reply with only the gender neutral '+ LANGUAGE +' translation of the action. Always start the sentence with Taro.', True)
        else:
            message2Response = translateGPT(state['message2'], 'reply with only the gender neutral '+ LANGUAGE +' translation', True)

    if 'message3' in state:
        if len(state['message3']) > 0 and state['message3'][0] in ['は', 'を', 'の', 'に', 'が']:
            message3Response = translateGPT('Taro' + state['message3'], 'reply with only the gender neutral '+ LANGUAGE +' translation of the action. Always start the sentence with Taro.', True)
        else:
            message3Response = translateGPT(state['message3'], 'reply with only the gender neutral '+ LANGUAGE +' translation', True)

    if 'message4' in state:
        if len(state['message4']) > 0 and state['message4'][0] in ['は', 'を', 'の', 'に', 'が']:
            message4Response = translateGPT('Taro' + state['message4'], 'reply with only the gender neutral '+ LANGUAGE +' translation of the action. Always start the sentence with Taro.', True)
        else:
            message4Response = translateGPT(state['message4'], 'reply with only the gender neutral '+ LANGUAGE +' translation', True)

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

    pbar.update(1)
    return totalTokens

def searchSystem(data, pbar):
    totalTokens = [0, 0]
    context = 'UI Text Items:\
    "逃げる" == "Escape"\
    "大事なもの" == "Key Items"\
    "最強装備" == "Optimize"\
    "攻撃力" == "Attack"\
    "最大ＨＰ" == "Max HP"\
    "経験値" == "EXP"\
    "購入する" == "Buy"\
    "魔力攻撃" == "M. Attack\
    "魔力防御" == "M. Defense\
    "%1 の%2を獲得！" == "Gained %1 %2"\
    "お金を %1\\G 手に入れた！" == ""\
    Reply with only the '+ LANGUAGE +' translation of the UI textbox."'

    # Title
    response = translateGPT(data['gameTitle'], ' Reply with the '+ LANGUAGE +' translation of the game title name', False)
    totalTokens[0] += response[1][0]
    totalTokens[1] += response[1][1]
    # data['gameTitle'] = response[0].strip('.')
    pbar.update(1)
    
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
                    pbar.update(1)

    # Armor Types
    for i in range(len(data['armor_types'])):
        response = translateGPT(data['armorTypes'][i], 'Reply with only the '+ LANGUAGE +' translation of the armor type', False)
        totalTokens[0] += response[1][0]
        totalTokens[1] += response[1][1]
        data['armorTypes'][i] = response[0].replace('\"', '').strip()
        pbar.update(1)

    # Skill Types
    for i in range(len(data['skill_types'])):
        response = translateGPT(data['skillTypes'][i], 'Reply with only the '+ LANGUAGE +' translation', False)
        totalTokens[0] += response[1][0]
        totalTokens[1] += response[1][1]
        data['skillTypes'][i] = response[0].replace('\"', '').strip()
        pbar.update(1)

    # Equip Types
    for i in range(len(data['equip_types'])):
        response = translateGPT(data['equipTypes'][i], 'Reply with only the '+ LANGUAGE +' translation of the equipment type. No disclaimers.', False)
        totalTokens[0] += response[1][0]
        totalTokens[1] += response[1][1]
        data['equipTypes'][i] = response[0].replace('\"', '').strip()
        pbar.update(1)

    # Variables (Optional ususally)
    # for i in range(len(data['variables'])):
    #     response = translateGPT(data['variables'][i], 'Reply with only the '+ LANGUAGE +' translation of the title', False)
    #     totalTokens[0] += response[1][0]
    #     totalTokens[1] += response[1][1]
    #     data['variables'][i] = response[0].replace('\"', '').strip()
    #     pbar.update(1)

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
        pbar.update(1)
    
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
            jaString = jaString.replace(name, '{N_' + str(count) + '}')
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
    if '笑えるよね.' in jaString:
        print('t')
    formatList = re.findall(r'[\\]+CL', jaString)
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
            translatedText = translatedText.replace('{N_' + str(count) + '}', var)
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

    # Remove Color Variables Spaces
    # if '\\c' in translatedText:
    #     translatedText = re.sub(r'\s*(\\+c\[[1-9]+\])\s*', r' \1', translatedText)
    #     translatedText = re.sub(r'\s*(\\+c\[0+\])', r'\1', translatedText)
    return translatedText

@retry(exceptions=Exception, tries=5, delay=5)
def translateGPT(t, history, fullPromptFlag):
    # If ESTIMATE is True just count this as an execution and return.
    if ESTIMATE:
        enc = tiktoken.encoding_for_model(MODEL)
        historyRaw = ''
        if isinstance(history, list):
            for line in history:
                historyRaw += line
        else:
            historyRaw = history

        inputTotalTokens = len(enc.encode(historyRaw)) + len(enc.encode(PROMPT))
        outputTotalTokens = len(enc.encode(t)) * 2   # Estimating 2x the size of the original text
        totalTokens = [inputTotalTokens, outputTotalTokens]
        return (t, totalTokens)
    
    # Sub Vars
    varResponse = subVars(t)
    subbedT = varResponse[0]

    # If there isn't any Japanese in the text just skip
    if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴ]+|[\uFF00-\uFFEF]', subbedT):
        return(t, [0,0])

    # Characters
    context = 'Game Characters:\
        Character: 莉音 == Rio - Gender: Female\
        Character: 結衣 == Yui - Gender: Female\
        Character: 美雪 == Miyuki - Gender: Female\
        Character: あかり == Akari - Gender: Female\
        Character: カガミ == Kagami - Gender: Female\
        Character: ミズキ == Mizuki - Gender: Female\
        Character: スズカ == Suzuka - Gender: Female\
        Character: シズク == Shizuku - Gender: Female'

    # Prompt
    if fullPromptFlag:
        system = PROMPT
        user = 'Line to Translate = ' + subbedT
    else:
        system = 'Output ONLY the '+ LANGUAGE +' translation in the following format: `Translation: <'+ LANGUAGE.upper() +'_TRANSLATION>`' 
        user = 'Line to Translate = ' + subbedT

    # Create Message List
    msg = []
    msg.append({"role": "system", "content": system})
    msg.append({"role": "user", "content": context})
    if isinstance(history, list):
        for line in history:
            msg.append({"role": "user", "content": line})
    else:
        msg.append({"role": "user", "content": history})
    msg.append({"role": "user", "content": user})

    response = openai.ChatCompletion.create(
        temperature=0,
        frequency_penalty=0.2,
        presence_penalty=0.2,
        model=MODEL,
        messages=msg,
        request_timeout=TIMEOUT,
    )

    # Save Translated Text
    translatedText = response.choices[0].message.content
    totalTokens = [response.usage.prompt_tokens, response.usage.completion_tokens]

    # Resub Vars
    translatedText = resubVars(translatedText, varResponse[1])

    # Remove Placeholder Text
    translatedText = translatedText.replace(LANGUAGE +' Translation: ', '')
    translatedText = translatedText.replace('Translation: ', '')
    translatedText = translatedText.replace('Line to Translate = ', '')
    translatedText = translatedText.replace('Translation = ', '')
    translatedText = translatedText.replace('Translate = ', '')
    translatedText = translatedText.replace(LANGUAGE +' Translation:', '')
    translatedText = translatedText.replace('Translation:', '')
    translatedText = translatedText.replace('Line to Translate =', '')
    translatedText = translatedText.replace('Translation =', '')
    translatedText = translatedText.replace('Translate =', '')
    translatedText = translatedText.replace('っ', '')

    # Return Translation
    if len(translatedText) > 15 * len(t) or "I'm sorry, but I'm unable to assist with that translation" in translatedText:
        raise Exception
    else:
        return [translatedText, totalTokens]
