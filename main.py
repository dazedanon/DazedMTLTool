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

#tqdm Globals
BAR_FORMAT='{l_bar}{bar:10}{r_bar}{bar:-10b}'
POSITION=0
LEAVE=False

# Info Message
print(Fore.BLUE + "Do not close while translation is in progress. If a file fails or gets stuck, \
Translated lines will remain translated so you don't have to worry about being charged \
twice. You can simply copy the file generated in /translations back over to /files and \
start the script again. It will skip over any translated text." + Fore.RESET, end='\n\n')

def main():
    # Open File (Threads)
    with ThreadPoolExecutor(max_workers=THREADS) as executor:
        for filename in os.listdir("files"):
            if filename.endswith('json'):
                executor.submit(handleFiles, filename)
    
    # This is to encourage people to grab what's in /translated instead
    deleteFolderFiles('files')

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
                translatedData = parseNames(data, filename, 'Armor')
            
            # Classes File
            if 'Classes' in filename:
                start = time.time()
                translatedData = parseNames(data, filename, 'Classes')

            # Classes File
            if 'Items' in filename:
                start = time.time()
                translatedData = parseNames(data, filename, 'Items')

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

def searchNames(name, pbar, context):
    translatedText = ''
    tokens = 0

    # Set the context of what we are translating
    if 'Actors' in context:
        context = 'What I give you is a Actor Name.'
    if 'Armors' in context:
        context = 'What I give you is a Armor Name.'
    if 'Classes' in context:
        context = 'What I give you is a Class Name.'
    if 'Items' in context:
        context = 'What I give you is a Item Name.'
    if 'MapInfos' in context:
        context = 'What I give you is a Map Name.'

    response = translateGPT(name['name'], context)
    tokens += response[1]
    translatedText = response[0]

    translatedText = translatedText.strip('.')   # Since GPT loves his periods
    name['name'] = translatedText
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

            # Event Code: 401 Show Text
            if page['list'][i]['code'] == 401:
                # Remove repeating characters because it confuses ChatGPT
                page['list'][i]['parameters'][0] = re.sub(r'(.)\1{2,}', r'\1\1', page['list'][i]['parameters'][0])

                if '<Charai Otoko> ちょっと待ってくれよ。媚薬でドハマりしたアヘ顔を見たいん' in page['list'][i]['parameters'][0]:
                    print('')
                
                # Using this to keep track of 401's in a row. Throws IndexError at EndOfList (Expected Behavior)
                currentGroup.append(page['list'][i]['parameters'][0])
                while (page['list'][i+1]['code'] == 401):
                    del page['list'][i]  
                    currentGroup.append(page['list'][i]['parameters'][0])

                # Join up 401 groups for better translation.
                if len(currentGroup) > 0:
                    text = ''.join(currentGroup)

                    # Improves translation but may break certain games
                    text = text.replace('\\n', '') 
                    text = text.replace('”', '')

                    # Translate
                    response = translateGPT(text, ' '.join(textHistory))
                    tokens += response[1]
                    translatedText = response[0]

                    # TextHistory is what we use to give GPT Context, so thats appended here.
                    textHistory.append(translatedText)

                    # Textwrap
                    translatedText = textwrap.fill(translatedText, width=50)

                    # Set Data
                    page['list'][i]['parameters'][0] = translatedText

                    # Keep textHistory list at length maxHistory
                    if len(textHistory) > maxHistory:
                        textHistory.pop(0)
                    currentGroup = []

            # Event Code: 102 Show Choice
            if page['list'][i]['code'] == 102:
                testList = ['']
                for choice in range(len(page['list'][i]['parameters'][0])):
                    testList.append(page['list'][i]['parameters'][0][choice])
                    response = translateGPT(page['list'][i]['parameters'][0][choice], 'Answer to the last question')

                # Set Data
                    tokens += response[1]
                    page['list'][i]['parameters'][0][choice] = response[0].strip('.')

            # Unlisted Code

    except IndexError:
        # This is part of the logic so we just pass it.
        pass
    except Exception as e:
        tracebackLineNo = str(traceback.extract_tb(sys.exc_info()[2])[-1].lineno)
        raise Exception(str(e) + '|Line:' + tracebackLineNo + '| Failed to translate: ' + text)  
                
    # Append leftover groups
    if len(currentGroup) > 0:
        response = translateGPT(''.join(currentGroup), ' '.join(textHistory))
        tokens += response[1]
        translatedText = response[0]

        #Cleanup
        translatedText = textwrap.fill(translatedText, width=50)
        page['list'][i]['parameters'][0] = translatedText
        currentGroup = []

    return tokens

def searchSS(state, pbar):
    '''Searches skills and states json files'''
    tokens = 0
    responseList = [0] * 6

    responseList[0] = (translateGPT(state['message1'], 'What I give you is a Message.'))
    responseList[1] = (translateGPT(state['message2'], 'What I give you is a Message.'))
    responseList[2] = (translateGPT(state.get('message3', ''), 'What I give you is a Message.'))
    responseList[3] = (translateGPT(state.get('message4', ''), 'What I give you is a Message.'))
    responseList[4] = (translateGPT(state['name'], 'What I give you is a State Name.'))
    responseList[5] = (translateGPT(state['note'], 'What I give you is a Note.'))

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
    context = 'What I give you is an menu item.'

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
        response = translateGPT(value, 'What I give you is a message.')
        tokens += response[1]
        messages[key] = response[0]
        pbar.update(1)
    
    return tokens
    

@retry(tries=5, delay=5)
def translateGPT(t, history):
    # If there isn't any Japanese in the text just return it
    pattern = r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+'
    if not re.search(pattern, t):
        return [t, 0]

    """Translate text using GPT"""
    system = PROMPT + "\nPrevious Text: " + history 
    response = openai.ChatCompletion.create(
        temperature=0,
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": t}
        ],
        request_timeout=60,
    )

    return [response.choices[0].message.content, response.usage.total_tokens]
    
    
main()
