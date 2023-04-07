from concurrent.futures import ThreadPoolExecutor, as_completed
import random
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
PROMPT = os.getenv('prompt')
THREADS = 20
COST = .002 # Depends on the model https://openai.com/pricing
LOCK = threading.Lock()

def main():
    print(Fore.BLUE + "Do not close while translation is in progress. If a file fails or gets stuck, \
Translated lines will remain \
translated so you don't have to worry about being charged \
twice. You can simply copy the file generated in /translations back over to /files and \
start the script again. It will skip over any translated text." + Fore.RESET)

    # Open File (Threads)
    with ThreadPoolExecutor(max_workers=THREADS) as executor:
        for filename in os.listdir("files"):
            if filename.endswith('json'):
                executor.submit(handle, filename)
    
    # This is to encourage people to grab what's in /translated instead
    deleteFolderFiles('files')

def deleteFolderFiles(folderPath):
    for filename in os.listdir(folderPath):
        file_path = os.path.join(folderPath, filename)
        if file_path.endswith('.json'):
            os.remove(file_path)

def handle(filename):
    with open('translated/' + filename, 'w', encoding='UTF-8') as outFile:
        with open('files/' + filename, 'r', encoding='UTF-8') as f:
            data = json.load(f)

            # Map Files
            if 'Map' in filename:
                # Start Timer
                start = time.time()

                # Start Translation
                translatedData = parseMap(data, filename)
                end = time.time()
                json.dump(translatedData[0], outFile, ensure_ascii=False)
                printString(translatedData, end - start, f)

            # CommonEvents Files
            if 'CommonEvents' in filename:
                # Start Timer
                start = time.time()

                 # Start Translation
                translatedData = parseCommonEvents(data, filename)
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
        print(f.name + ': ' + tokenString + timeString + Fore.GREEN + u' \u2713 ' + Fore.RESET)
    else:
        # Fail
        try:
            raise translatedData[2]
        except Exception as e:
            errorString = str(e) + Fore.RED + ' Line: ' + str(traceback.extract_tb(sys.exc_info()[2])[-1].lineno)
            print(f.name + ': ' + tokenString + timeString + Fore.RED + u' \u2717 ' +\
                errorString + Fore.RESET)

def parseMap(data, filename):
    totalTokens = 0
    totalLines = 0
    events = data['events']

    # Get total for progress bar
    for event in events:
        if event is not None:
            for page in event['pages']:
                totalLines += len(page['list'])
    
    with tqdm(total = totalLines, leave=False, desc=filename, bar_format='{l_bar}{bar:10}{r_bar}{bar:-10b}', position=1, mininterval=1) as pbar:
        for event in events:
            if event is not None:
                with ThreadPoolExecutor(max_workers=THREADS) as executor:
                    for page in event['pages']:
                        future = executor.submit(searchCodes, page, pbar)   
                     
                        # Verify if an exception was thrown
                        try:
                            totalTokens += future.result()
                        except Exception as e:
                            return [data, totalTokens, e]

    return [data, totalTokens, None]

def parseCommonEvents(data, filename):
    totalTokens = 0
    totalLines = 0

    # Get total for progress bar
    for page in data:
        if page is not None:
            totalLines += len(page['list'])

    with tqdm(total = totalLines, leave=False, desc=filename, bar_format='{l_bar}{bar:10}{r_bar}{bar:-10b}', position=0,) as pbar:
        with ThreadPoolExecutor(max_workers=THREADS) as executor:
            futures = [executor.submit(searchCodes, page, pbar) for page in data if page is not None]
            for future in as_completed(futures):
                try:
                    totalTokens += future.result()
                except Exception as e:
                    return [data, totalTokens, e]
                

    return [data, totalTokens, None]

def searchCodes(page, pbar):
    translatedText = ''
    currentGroup = []
    textHistory = []
    maxHistory = 20 # The higher this number is, the better the translation, the more money you are going to pay :)
    tokens = 0
    global LOCK

    try:
        for i in range(len(page['list'])):
            LOCK.acquire()
            pbar.update(1)
            LOCK.release()

            # Translating Code: 401
            if page['list'][i]['code'] == 401:
                # Remove repeating characters because it confuses ChatGPT
                page['list'][i]['parameters'][0] = re.sub(r'(.)\1{2,}', r'\1\1\1\1', page['list'][i]['parameters'][0])    # Remove repeating characters
                currentGroup.append(page['list'][i]['parameters'][0])
                
                while (page['list'][i+1]['code'] == 401):
                    del page['list'][i]  
                    currentGroup.append(page['list'][i]['parameters'][0])
            else:
                # Here we will need to take the current group of 401's and translate it all at once
                # This leads to a much much better translation
                if len(currentGroup) > 0:
                    # Translation
                    text = ''.join(currentGroup)
                    text = text.replace('\\n', '') # Improves translation but may break certain games
                    text = text.replace('”', '')
                    response = translateGPT(text, ' '.join(textHistory))

                    # Check if we got an object back or plain string
                    if type(response) != str:
                        tokens += response.usage.total_tokens
                        translatedText = response.choices[0].message.content
                    else:
                        translatedText = response

                    # TextHistory is what we use to give GPT Context, so thats appended here.
                    # translatedText = startString + translatedText + endString
                    textHistory.append(translatedText)
                    translatedText = textwrap.fill(translatedText, width=50)
                    page['list'][i-1]['parameters'][0] = translatedText
                    if len(textHistory) > maxHistory:
                        textHistory.pop(0)
                    currentGroup = []

    except IndexError:
        # This is part of the logic so we just pass it.
        pass
    except Exception:
        raise TimeoutError('Failed to translate: ' + text)  
                
    # Append leftover groups
    if len(currentGroup) > 0:
        response = translateGPT(''.join(currentGroup), ' '.join(textHistory))
        # Check if we got an object back or plain string
        if type(response) != str:
            tokens += response.usage.total_tokens
            translatedText = response.choices[0].message.content
        else:
            translatedText = response
        
        #Cleanup
        translatedText = textwrap.fill(translatedText, width=50)
        page['list'][i]['parameters'][0] = translatedText
        currentGroup = []

    return tokens
    
def translateGPT(t, history):
    global LOCK

    # If there isn't any Japanese in the text just return it
    pattern = r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+'
    if not re.search(pattern, t):
        return t

    """Translate text using GPT"""
    system = "Context: " + history + PROMPT
    response = openai.ChatCompletion.create(
        temperature=0,
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": t}
        ],
        request_timeout=60,
    )
    return response
    
main()
