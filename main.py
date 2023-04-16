from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import sys
import threading
from colorama import Fore
from dotenv import load_dotenv
from tqdm import tqdm
from retry import retry
import traceback
import os
import re
import textwrap
import json
import time
import openai

#Globals
load_dotenv()
openai.organization = os.getenv('org')
openai.api_key = os.getenv('key')
THREADS = 20
COST = .002 # Depends on the model https://openai.com/pricing
LOCK = threading.Lock()
PROMPT = Path('prompt.txt').read_text(encoding='utf-8')
WIDTH = 60

#tqdm Globals
BAR_FORMAT='{l_bar}{bar:10}{r_bar}{bar:-10b}'
POSITION=0
LEAVE=False

# Info Message
print(Fore.BLUE + "Do not close while translation is in progress. If a file fails or gets stuck, \
Translated lines will remain translated so you don't have to worry about being charged \
twice. You can simply copy the file generated in /translations back over to /files and \
start the script again. It will skip over any translated text." + Fore.RESET, end='\n\n')

# Flags
CODE401 = True
CODE102 = True
CODE122 = False
CODE101 = False
CODE355655 = False
CODE357 = False

def main():
    # Open File (Threads)
    with ThreadPoolExecutor(max_workers=THREADS) as executor:
        for filename in os.listdir("files"):
            if filename.endswith('json'):
                executor.submit(handleFiles, filename)
    
    # This is to encourage people to grab what's in /translated instead
    deleteFolderFiles('files')

    # Prevent immediately closing of CLI
    input('Done! Press Enter to close.')

def deleteFolderFiles(folderPath):
    for filename in os.listdir(folderPath):
        file_path = os.path.join(folderPath, filename)
        if file_path.endswith('.json'):
            os.remove(file_path)

def handleFiles(filename):
    with open('translated/' + filename, 'w', encoding='UTF-8') as outFile:
        with open('files/' + filename, 'r', encoding='UTF-8') as f:
            data = json.load(f)

            # Map Files
            if 'Map' in filename and filename != 'MapInfos.json':
                start = time.time()
                translatedData = parseMap(data, filename)

            # CommonEvents Files
            if 'CommonEvents' in filename:
                start = time.time()
                translatedData = parseCommonEvents(data, filename)

            # Actor File
            if 'Actors' in filename:
                start = time.time()
                translatedData = parseNames(data, filename, 'Actors')

            # Armor File
            if 'Actors' in filename:
                start = time.time()
                translatedData = parseThings(data, filename, 'Armor')
            
            # Classes File
            if 'Classes' in filename:
                start = time.time()
                translatedData = parseNames(data, filename, 'Classes')

            # Items File
            if 'Items' in filename:
                start = time.time()
                translatedData = parseThings(data, filename, 'Items')

            # MapInfo File
            if 'MapInfos' in filename:
                start = time.time()
                translatedData = parseNames(data, filename, 'MapInfos')

            # Skills File
            if 'Skills' in filename:
                start = time.time()
                translatedData = parseSS(data, filename)

            # States File
            if 'States' in filename:
                start = time.time()
                translatedData = parseSS(data, filename)

            # System File
            if 'System' in filename:
                start = time.time()
                translatedData = parseSystem(data, filename)

        end = time.time()
        json.dump(translatedData[0], outFile, ensure_ascii=False)
        printString(translatedData, end - start, f)

def printString(translatedData, translationTime, f):
    # Strings
    tokenString = Fore.YELLOW + '[' + str(translatedData[1]) + \
        ' Tokens/${:,.4f}'.format(translatedData[1] * .001 * COST) + ']'
    timeString = Fore.BLUE + '[' + str(round(translationTime, 1)) + 's]'

    if translatedData[2] == None:
        # Success
        tqdm.write(f.name + ': ' + tokenString + timeString + Fore.GREEN + u' \u2713 ' + Fore.RESET)
    else:
        # Fail
        try:
            raise translatedData[2]
        except Exception as e:
            errorString = str(e) + Fore.RED
            tqdm.write(f.name + ': ' + tokenString + timeString + Fore.RED + u' \u2717 ' +\
                errorString + Fore.RESET)

def parseMap(data, filename):
    totalTokens = 0
    totalLines = 0
    events = data['events']
    global LOCK

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
                    futures = [executor.submit(searchCodes, page, pbar) for page in event['pages'] if page is not None]
                    for future in as_completed(futures):
                        try:
                            totalTokens += future.result()
                        except Exception as e:
                            return [data, totalTokens, e]
    return [data, totalTokens, None]

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

def parseThings(data, filename, context):
    totalTokens = 0
    totalLines = 0
    totalLines += len(data)
                
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
            pbar.desc=filename
            pbar.total=totalLines
            for name in data:
                if name is not None:
                    try:
                        result = searchThings(name, pbar, context)       
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
                
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
        pbar.desc=filename
        pbar.total=totalLines
        try:
            result = searchSystem(data, pbar)       
            totalTokens += result
        except Exception as e:
            return [data, totalTokens, e]
    return [data, totalTokens, None]

def searchThings(name, pbar, context):
    tokens = 0

    # Set the context of what we are translating
    responseList = []
    responseList.append(translateGPT(name['name'], 'Reply with only the menu item name.'))
    responseList.append(translateGPT(name['description'], 'Reply with only the description.'))
    responseList.append(translateGPT(name['note'], 'Reply with only the note.'))

    # Extract all our translations in a list from response
    for i in range(len(responseList)):
        tokens += responseList[i][1]
        responseList[i] = responseList[i][0]

    # Set Data
    name['name'] = responseList[0].strip('.')
    name['description'] = responseList[1]
    name['note'] = responseList[2]
    pbar.update(1)

    return tokens

def searchNames(name, pbar, context):
    tokens = 0

    # Set the context of what we are translating
    if 'Actors' in context:
        context = 'Reply with only the actor name'
    if 'Classes' in context:
        context = 'Reply with only the class name'
    if 'MapInfos' in context:
        context = 'Reply with only the map name'

    responseList = []
    responseList[0].append(translateGPT(name['name'], context))
    responseList[1].append(translateGPT(name['description'], context))
    responseList[2].append(translateGPT(name['note'], context))

    # Extract all our translations in a list from response
    for i in range(len(responseList)):
        tokens += responseList[i][1]
        responseList[i] = responseList[i][0]

    # Set Data
    name['name'] = responseList[0].strip('.')
    name['description'] = responseList[1]
    name['note'] = responseList[2]
    pbar.update(1)

    return tokens

def searchCodes(page, pbar):
    text = ''
    translatedText = ''
    currentGroup = []
    textHistory = []
    maxHistory = 20 # The higher this number is, the better the translation, the more money you are going to pay :)
    tokens = 0
    global LOCK

    try:
        for i in range(len(page['list'])):
            with LOCK:
                pbar.update(1)

            ### All the codes are here which translate specific functions in the MAP files.
            ### IF these crash or fail your game will do the same. Just comment out anything not needed.

            ## Event Code: 401 Show Text
            if page['list'][i]['code'] == 401 and CODE401 == True:    
                jaString = page['list'][i]['parameters'][0]

                # Remove repeating characters because it confuses ChatGPT
                jaString = re.sub(r'(.)\1{2,}', r'\1\1', jaString)
                   
                # Using this to keep track of 401's in a row. Throws IndexError at EndOfList (Expected Behavior)
                currentGroup.append(jaString)
                while (page['list'][i+1]['code'] == 401):
                    del page['list'][i]  
                    jaString = page['list'][i]['parameters'][0]
                    jaString = re.sub(r'(.)\1{2,}', r'\1\1', jaString)
                    currentGroup.append(jaString)

                # Join up 401 groups for better translation.
                if len(currentGroup) > 0:
                    finalJAString = ''.join(currentGroup)

                    # Improves translation but may break certain games
                    finalJAString = finalJAString.replace('\\n', '') 
                    finalJAString = finalJAString.replace('”', '')

                    # Sub Vars
                    finalJAString = re.sub(r'(\\+[a-zA-Z]+)\[([0-9]+)\]', r'[\1\2]', finalJAString)

                    # Translate
                    response = translateGPT(finalJAString, 'Previous text for context: ' + ' '.join(textHistory))
                    tokens += response[1]
                    translatedText = response[0]

                    # ReSub Vars
                    translatedText = re.sub(r'\[([\\a-zA-Z]+)([0-9]+)]', r'\1[\2]', translatedText)

                    # TextHistory is what we use to give GPT Context, so thats appended here.
                    textHistory.append(translatedText)

                    # Textwrap
                    translatedText = textwrap.fill(translatedText, width=WIDTH)

                    # Set Data
                    page['list'][i]['parameters'][0] = translatedText

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
                if '_' in jaString:
                    continue

                # If there isn't any Japanese in the text just skip
                if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', jaString):
                    continue

                # Remove repeating characters because it confuses ChatGPT
                jaString = re.sub(r'(.)\1{2,}', r'\1\1', jaString)

                # Sub Vars
                jaString = re.sub(r'\\+([a-zA-Z]+)\[([0-9]+)\]', r'[\1\2]', jaString)

                # Translate
                response = translateGPT(jaString, '')
                tokens += response[1]
                translatedText = response[0]

                # Remove characters that may break scripts
                charList = ['.', '\"', '\\n', '\\']
                for char in charList:
                    translatedText = translatedText.replace(char, '')

                # ReSub Vars
                translatedText = re.sub(r'\[([a-zA-Z]+)([0-9]+)]', r'\\\\\1[\2]', translatedText)

                # Set Data
                page['list'][i]['parameters'][4] = '\"' + translatedText + '\"'

        ## Event Code: 357 [Picture Text] [Optional]
            if page['list'][i]['code'] == 357 and CODE357 == True:    
                if 'text' in page['list'][i]['parameters'][3]:
                    jaString = page['list'][i]['parameters'][3]['text']
                    if type(jaString) != str:
                        continue
                    
                    # Definitely don't want to mess with files
                    if '_' in jaString:
                        continue

                    # If there isn't any Japanese in the text just skip
                    if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', jaString):
                        continue

                    # Need to remove outside non-japanese text and put it back later
                    startString = re.search(r'^[^ぁ-んァ-ン一-龯\<\>【】]+', jaString)
                    jaString = re.sub(r'^[^ぁ-んァ-ン一-龯\<\>【】]+', '', jaString)
                    if startString is None: startString = ''
                    else:  startString = startString.group()

                    # Remove repeating characters because it confuses ChatGPT
                    jaString = re.sub(r'(.)\1{2,}', r'\1\1', jaString)

                    # Sub Vars
                    jaString = re.sub(r'\\+([a-zA-Z]+)\[([0-9]+)\]', r'[\1\2]', jaString)

                    # Translate
                    response = translateGPT(jaString, '')
                    tokens += response[1]
                    translatedText = response[0]

                    # Remove characters that may break scripts
                    charList = ['\"', '\\', '\\n']
                    for char in charList:
                        translatedText = translatedText.replace(char, '')

                    # Textwrap
                    translatedText = textwrap.fill(translatedText, width=50)

                    # ReSub Vars
                    translatedText = re.sub(r'\[([a-zA-Z]+)([0-9]+)]', r'\\\\\1[\2]', translatedText)

                    # Set Data
                    page['list'][i]['parameters'][3]['text'] = startString + translatedText

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
                    continue

                # Remove repeating characters because it confuses ChatGPT
                jaString = re.sub(r'(.)\1{2,}', r'\1\1', jaString)

                # Translate
                response = translateGPT(jaString, 'Reply with only the english translated name')
                tokens += response[1]
                translatedText = response[0]

                # Remove characters that may break scripts
                charList = ['.', '\"', '\\n']
                for char in charList:
                    translatedText = translatedText.replace(char, '')

                # Set Data
                page['list'][i]['parameters'][4] = translatedText

            ## Event Code: 355 or 655 Scripts [Optional]
            if (page['list'][i]['code'] == 355 or page['list'][i]['code'] == 655) and CODE355655 == True:
                jaString = page['list'][i]['parameters'][0]

                # If there isn't any Japanese in the text just skip
                if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', jaString):
                    continue

                # Want to translate this script
                if page['list'][i]['code'] == 355 and 'this.BLogAdd' not in jaString:
                    continue

                # Don't want to touch certain scripts
                if page['list'][i]['code'] == 655 and 'this.' in jaString:
                    continue

                # Need to remove outside code and put it back later
                startString = re.search(r'^[^ぁ-んァ-ン一-龯\<\>【】]+', jaString)
                jaString = re.sub(r'^[^ぁ-んァ-ン一-龯\<\>【】]+', '', jaString)
                endString = re.search(r'[^ぁ-んァ-ン一-龯\<\>【】]+$', jaString)
                jaString = re.sub(r'[^ぁ-んァ-ン一-龯\<\>【】]+$', '', jaString)
                if startString is None: startString = ''
                else:  startString = startString.group()
                if endString is None: endString = ''
                else: endString = endString.group()

                # Translate
                response = translateGPT(jaString, '')
                tokens += response[1]
                translatedText = response[0]

                # Remove characters that may break scripts
                charList = ['.', '\"', '\\n']
                for char in charList:
                    translatedText = translatedText.replace(char, '')

                # Set Data
                page['list'][i]['parameters'][0] = startString + translatedText + endString

            ### Event Code: 102 Show Choice
            if page['list'][i]['code'] == 102 and CODE102 == True:
                for choice in range(len(page['list'][i]['parameters'][0])):
                    choiceText = page['list'][i]['parameters'][0][choice]
                    translatedText = translatedText.replace(' 。', '.')

                    # Need to remove outside non-japanese text and put it back later
                    startString = re.search(r'^[^ぁ-んァ-ン一-龯\<\>【】]+', choiceText)
                    choiceText = re.sub(r'^[^ぁ-んァ-ン一-龯\<\>【】]+', '', choiceText)
                    if startString is None: startString = ''
                    else:  startString = startString.group()
    
                    response = translateGPT(choiceText, 'Reply with the english translation for the answer to this question: ' + textHistory[-1])
                    translatedText = response[0]

                    # Remove characters that may break scripts
                    charList = ['.', '\"', '\\n']
                    for char in charList:
                        translatedText = translatedText.replace(char, '')

                    # Set Data
                    tokens += response[1]
                    page['list'][i]['parameters'][0][choice] = startString + translatedText

    except IndexError:
        # This is part of the logic so we just pass it.
        pass
    except Exception as e:
        tracebackLineNo = str(traceback.extract_tb(sys.exc_info()[2])[-1].lineno)
        raise Exception(str(e) + '|Line:' + tracebackLineNo + '| Failed to translate: ' + jaString)  
                
    # Append leftover groups in 401
    if len(currentGroup) > 0:
        response = translateGPT(''.join(currentGroup), ' '.join(textHistory))
        tokens += response[1]
        translatedText = response[0]

        #Cleanup
        # TextHistory is what we use to give GPT Context, so thats appended here.
        textHistory.append(translatedText)

        # Textwrap
        if page['list'][i]['code'] == 401:
            translatedText = textwrap.fill(translatedText, width=WIDTH)

        # Set Data
        page['list'][i]['parameters'][0] = translatedText

        # Keep textHistory list at length maxHistory
        if len(textHistory) > maxHistory:
            textHistory.pop(0)
        currentGroup = []
        page['list'][i]['parameters'][0] = translatedText
        currentGroup = []

    return tokens

def searchSS(state, pbar):
    '''Searches skills and states json files'''
    tokens = 0
    responseList = [0] * 6

    responseList[0] = (translateGPT(state['message1'], 'Reply with only the message.'))
    responseList[1] = (translateGPT(state['message2'], 'Reply with only the message.'))
    responseList[2] = (translateGPT(state.get('message3', ''), 'Reply with only the message.'))
    responseList[3] = (translateGPT(state.get('message4', ''), 'Reply with only the message.'))
    responseList[4] = (translateGPT(state['name'], 'Reply with only the state name.'))
    responseList[5] = (translateGPT(state['note'], 'Reply with only the note.'))

    # Put all our translations in a list
    for i in range(len(responseList)):
        tokens += responseList[i][1]
        responseList[i] = responseList[i][0]
    
    # Set Data
    state['message1'] = responseList[0]
    state['message2'] = responseList[1]
    if responseList[2] != '':
        state['message3'] = responseList[2]
    if responseList[3] != '':
        state['message4'] = responseList[3]
    state['name'] = responseList[4].strip('.')
    state['note'] = responseList[5]

    pbar.update(1)
    return tokens

def searchSystem(data, pbar):
    tokens = 0
    context = 'Reply with only the menu item.'

    # Title
    response = translateGPT(data['gameTitle'], context)
    tokens += response[1]
    data['gameTitle'] = response[0].strip('.')
    pbar.update(1)
    
    # Terms
    for term in data['terms']:
        if term != 'messages':
            termList = data['terms'][term]
            for i in range(len(termList)):  # Last item is a messages object
                if termList[i] is not None:
                    response = translateGPT(termList[i], context)
                    tokens += response[1]
                    termList[i] = response[0].strip('.\"')
                    pbar.update(1)

    # Messages
    messages = (data['terms']['messages'])
    for key, value in messages.items():
        response = translateGPT(value, 'Reply with only the english translated answer')
        translatedText = response[0]

        # Remove characters that may break scripts
        charList = ['.', '\"', '\\n']
        for char in charList:
            translatedText = translatedText.replace(char, '')

        tokens += response[1]
        messages[key] = translatedText
        pbar.update(1)
    
    return tokens
    

@retry(exceptions=Exception, tries=5, delay=5)
def translateGPT(t, history):
    # If there isn't any Japanese in the text just skip
    if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴ]+', t):
        return(t, 0)

    """Translate text using GPT"""
    system = PROMPT + history 
    response = openai.ChatCompletion.create(
        temperature=0,
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": t}
        ],
        request_timeout=30,
    )

    return [response.choices[0].message.content, response.usage.total_tokens]   
    
main()
