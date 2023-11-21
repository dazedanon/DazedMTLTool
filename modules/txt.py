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
if os.getenv('api').replace(' ', '') != '':
    openai.api_base = os.getenv('api')

openai.organization = os.getenv('org')
openai.api_key = os.getenv('key')
MODEL = os.getenv('model')
TIMEOUT = int(os.getenv('timeout'))
LANGUAGE=os.getenv('language').capitalize()

APICOST = .002 # Depends on the model https://openai.com/pricing
PROMPT = Path('prompt.txt').read_text(encoding='utf-8')
THREADS = int(os.getenv('threads'))
LOCK = threading.Lock()
WIDTH = int(os.getenv('width'))
LISTWIDTH = int(os.getenv('listWidth'))
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

def handleTXT(filename, estimate):
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
            traceback.print_exc()
            return [linesList, 0, e]
    return [response[0], response[1], None]

def translateText(data, pbar):
    textHistory = []
    maxHistory = MAXHISTORY
    tokens = 0
    speaker = ''
    speakerFlag = False
    currentGroup = []
    syncIndex = 0

    for i in range(len(data)):
        if i != syncIndex:
            continue

        match = re.findall(r'm\[[0-9]+\] = \"(.*)\"', data[i])
        if len(match) > 0:
            jaString = match[0]

            ### Translate
            # Remove any textwrap
            jaString = re.sub(r'\\n', ' ', jaString)

            # Grab Speaker
            speakerMatch = re.findall(r's\[[0-9]+\] = \"(.+?)[／\"]', data[i-1])
            if len(speakerMatch) > 0:
                # If there isn't any Japanese in the text just skip
                if re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', jaString) and '_' not in speakerMatch[0]:
                    speaker = ''
                else:
                    speaker = ''
            else:
                speaker = ''

            # Grab rest of the messages
            currentGroup.append(jaString)
            start = i
            data[i] = re.sub(r'(m\[[0-9]+\]) = \"(.+)\"', rf'\1 = ""', data[i])
            while (len(data) > i+1 and re.search(r'm\[[0-9]+\] = \"(.*)\"', data[i+1]) != None):
                i+=1
                match = re.findall(r'm\[[0-9]+\] = \"(.*)\"', data[i])
                currentGroup.append(match[0])
                data[i] = re.sub(r'(m\[[0-9]+\]) = \"(.+)\"', rf'\1 = ""', data[i])
            finalJAString = ' '.join(currentGroup)
            
            # Translate
            if speaker != '':
                response = translateGPT(f'{speaker}: {finalJAString}', 'Previous Text for Context: ' + ' '.join(textHistory), True)
            else:
                response = translateGPT(finalJAString, 'Previous Text for Context: ' + ' '.join(textHistory), True)
            tokens += response[1]
            translatedText = response[0]
            
            # Remove added speaker and quotes
            translatedText = re.sub(r'^.+?:\s', '', translatedText)

            # TextHistory is what we use to give GPT Context, so thats appended here.
            # rawTranslatedText = re.sub(r'[\\<>]+[a-zA-Z]+\[[a-zA-Z0-9]+\]', '', translatedText)
            if speaker != '':
                textHistory.append(speaker + ': ' + translatedText)
            elif speakerFlag == False:
                textHistory.append('\"' + translatedText + '\"')

            # Keep textHistory list at length maxHistory
            if len(textHistory) > maxHistory:
                textHistory.pop(0)
            currentGroup = []  

            # Textwrap
            translatedText = translatedText.replace('\"', '\\"')
            translatedText = textwrap.fill(translatedText, width=WIDTH)

            # Write
            textList = translatedText.split("\n")
            for t in textList:
                data[start] = re.sub(r'(m\[[0-9]+\]) = \"(.*)\"', rf'\1 = "{t}"', data[start])
                start+=1
                
        syncIndex = i + 1
        pbar.update()
    return [data, tokens]
        
def subVars(jaString):
    jaString = jaString.replace('\u3000', ' ')

    # Icons
    count = 0
    iconList = re.findall(r'[\\]+[iI]\[[0-9]+\]', jaString)
    iconList = set(iconList)
    if len(iconList) != 0:
        for icon in iconList:
            jaString = jaString.replace(icon, '<I' + str(count) + '>')
            count += 1

    # Colors
    count = 0
    colorList = re.findall(r'[\\]+[cC]\[[0-9]+\]', jaString)
    colorList = set(colorList)
    if len(colorList) != 0:
        for color in colorList:
            jaString = jaString.replace(color, '<C' + str(count) + '>')
            count += 1

    # Names
    count = 0
    nameList = re.findall(r'[\\]+[nN]\[[0-9]+\]', jaString)
    nameList = set(nameList)
    if len(nameList) != 0:
        for name in nameList:
            jaString = jaString.replace(name, '<N' + str(count) + '>')
            count += 1

    # Variables
    count = 0
    varList = re.findall(r'[\\]+[vV]\[[0-9]+\]', jaString)
    varList = set(varList)
    if len(varList) != 0:
        for var in varList:
            jaString = jaString.replace(var, '<V' + str(count) + '>')
            count += 1

    # Formatting
    count = 0
    formatList = re.findall(r'[\\]+[!.]', jaString)
    formatList = set(formatList)
    if len(formatList) != 0:
        for format in formatList:
            jaString = jaString.replace(format, '<F' + str(count) + '>')
            count += 1

    # Put all lists in list and return
    allList = [iconList, colorList, nameList, varList, formatList]
    return [jaString, allList]

def resubVars(translatedText, allList):
    # Fix Spacing and ChatGPT Nonsense
    matchList = re.findall(r'<\s?.+?\s?>', translatedText)
    if len(matchList) > 0:
        for match in matchList:
            text = match.strip()
            translatedText = translatedText.replace(match, text)

    # Icons
    count = 0
    if len(allList[0]) != 0:
        for var in allList[0]:
            translatedText = translatedText.replace('<I' + str(count) + '>', var)
            count += 1

    # Colors
    count = 0
    if len(allList[1]) != 0:
        for var in allList[1]:
            translatedText = translatedText.replace('<C' + str(count) + '>', var)
            count += 1

    # Names
    count = 0
    if len(allList[2]) != 0:
        for var in allList[2]:
            translatedText = translatedText.replace('<N' + str(count) + '>', var)
            count += 1

    # Vars
    count = 0
    if len(allList[3]) != 0:
        for var in allList[3]:
            translatedText = translatedText.replace('<V' + str(count) + '>', var)
            count += 1
    
    # Formatting
    count = 0
    if len(allList[4]) != 0:
        for var in allList[4]:
            translatedText = translatedText.replace('<F' + str(count) + '>', var)
            count += 1

@retry(exceptions=Exception, tries=5, delay=5)
def translateGPT(t, history, fullPromptFlag):
    # If ESTIMATE is True just count this as an execution and return.
    if ESTIMATE:
        enc = tiktoken.encoding_for_model(MODEL)
        tokens = len(enc.encode(t)) * 2 + len(enc.encode(str(history))) + len(enc.encode(PROMPT))
        return (t, tokens)
    
    # Sub Vars
    varResponse = subVars(t)
    subbedT = varResponse[0]

    # If there isn't any Japanese in the text just skip
    if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴ]+|[\uFF00-\uFFEF]', subbedT):
        return(t, 0)

    # Characters
    context = '```\
        Game Characters:\
        Character: 池ノ上 拓海 == Ikenoue Takumi - Gender: Male\
        Character: 福永 こはる == Fukunaga Koharu - Gender: Female\
        Character: 神泉 理央 == Kamiizumi Rio - Gender: Female\
        Character: 吉祥寺 アリサ == Kisshouji Arisa - Gender: Female\
        Character: 久我 友里子 == Kuga Yuriko - Gender: Female\
        ```'

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
        temperature=0.1,
        frequency_penalty=0.2,
        presence_penalty=0.2,
        model=MODEL,
        messages=msg,
        request_timeout=TIMEOUT,
    )

    # Save Translated Text
    translatedText = response.choices[0].message.content
    tokens = response.usage.total_tokens

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
    translatedText = re.sub(r'Note:.*', '', translatedText)
    translatedText = translatedText.replace('っ', '')

    # Return Translation
    if len(translatedText) > 15 * len(t) or "I'm sorry, but I'm unable to assist with that translation" in translatedText:
        raise Exception
    else:
        return [translatedText, tokens]
