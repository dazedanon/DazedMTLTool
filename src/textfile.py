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
WIDTH = 72
LISTWIDTH = 75
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
CODE102 = True
CODE122 = False
CODE101 = False
CODE355655 = False
CODE357 = False
CODE356 = False
CODE320 = False
CODE111 = False

def handleTextfile(filename, estimate):
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
            outFile.writelines(translatedData[0])
            tqdm.write(getResultString(translatedData, end - start, filename))
            with LOCK:
                TOTALCOST += translatedData[1] * .001 * APICOST
                TOTALTOKENS += translatedData[1]

    return getResultString(['', TOTALTOKENS, None], end - start, 'TOTAL')

def openFiles(filename):
    with open('files/' + filename, 'r', encoding='UTF-8') as f:
        translatedData = parseText(f, filename)
    
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
        
def parseText(data, filename):
    totalTokens = 0
    totalLines = 0
    global LOCK

    # Get total for progress bar
    linesList = data.readlines()
    totalLines = len(linesList)
    
    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
        pbar.desc=filename
        pbar.total=totalLines
        try:
            response = translateText(linesList, pbar)
        except Exception as e:
            return [linesList, 0, e]
    return [response[0], response[1], None]

def translateText(data, pbar):
    textHistory = []
    maxHistory = MAXHISTORY
    tokens = 0
    speaker = ''
    speakerFlag = False

    for i in range(len(data)):
        if '◆' in data[i]:
            jaString = data[i]

            ### Translate
            # Remove any textwrap
            jaString = re.sub(r'\\n', ' ', jaString)

            # Check if speaker
            if '◆A' in jaString:
                speakerFlag = True

            # Need to remove outside code and put it back later
            startString = re.search(r'^◆[a-zA-Z0-9]+◆', jaString)
            jaString = re.sub(r'^◆[a-zA-Z0-9]+◆', '', jaString)
            endString = re.search(r'\n$', jaString)
            jaString = re.sub(r'\n$', '', jaString)
            if startString is None: startString = ''
            else:  startString = startString.group()
            if endString is None: endString = ''
            else: endString = endString.group()

            # Remove Repeating Chars
            jaString = re.sub(r'([\u3000-\uffef])\1{1,}', r'\1', jaString)
            
            # Translate
            if speaker != '':
                response = translateGPT(jaString, 'Previous Text for Context: ' + ' '.join(textHistory) \
                                        + '\n\n\n###\n\n\nCurrent Speaker: ' + speaker, True)
            else:
                response = translateGPT(jaString, 'Previous Text for Context: ' + ' '.join(textHistory), True)
            tokens += response[1]
            translatedText = response[0]

            # TextHistory is what we use to give GPT Context, so thats appended here.
            # rawTranslatedText = re.sub(r'[\\<>]+[a-zA-Z]+\[[a-zA-Z0-9]+\]', '', translatedText)
            if speaker != '':
                textHistory.append(speaker + ': ' + translatedText)
            elif speakerFlag == False:
                textHistory.append('\"' + translatedText + '\"')

            # Keep textHistory list at length maxHistory
            if len(textHistory) > maxHistory:
                textHistory.pop(0)

            # Textwrap
            translatedText = textwrap.fill(translatedText, width=WIDTH)
            translatedText = translatedText.replace('\n','\\n')
            speaker = ''

            # Setup Speaker
            if speakerFlag == True:
            # Remove characters that may break scripts
                charList = ['.', '\"']
                for char in charList:
                    translatedText = translatedText.replace(char, '')

                speaker = translatedText
                speakerFlag = False

            # Write
            data[i] = startString + translatedText + endString
        pbar.update()
    return [data, tokens]
        
@retry(exceptions=Exception, tries=5, delay=5)
def translateGPT(t, history, fullPromptFlag):
    with LOCK:
        # If ESTIMATE is True just count this as an execution and return.
        if ESTIMATE:
            global TOKENS
            enc = tiktoken.encoding_for_model("gpt-3.5-turbo")
            TOKENS += len(enc.encode(t)) * 2 + len(enc.encode(history)) + len(enc.encode(PROMPT))
            return (t, 0)
    
    # If there isn't any Japanese in the text just skip
    if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴ]+', t):
        return(t, 0)

    """Translate text using GPT"""
    if fullPromptFlag:
        system = PROMPT + history 
    else:
        system = 'You are going to pretend to be Japanese visual novel translator, \
editor, and localizer. ' + history
    response = openai.ChatCompletion.create(
        temperature=0,
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": "Text to Translate: " + t}
        ],
        request_timeout=30,
    )

    # Make sure translation didn't wonk out
    mlen=len(response.choices[0].message.content)
    elnt=10*len(t)
    if len(response.choices[0].message.content) > 9 * len(t):
        return [t, response.usage.total_tokens]
    else:
        return [response.choices[0].message.content, response.usage.total_tokens]
 
