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
WIDTH = 75
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
    varRegex = r'\\+[a-zA-Z]+\[[0-9a-zA-Z\\\[\]]+\]+|[\\]+[#|]+|\\+[\\\[\]\.<>a-zA-Z0-9]+'
    count = 0

    varList = re.findall(varRegex, jaString)
    if len(varList) != 0:
        for var in varList:
            jaString = jaString.replace(var, '<x' + str(count) + '>')
            count += 1

    return [jaString, varList]

def resubVars(translatedText, varList):
    count = 0
    
    if len(varList) != 0:
        for var in varList:
            translatedText = translatedText.replace('<x' + str(count) + '>', var)
            count += 1

    # Remove Color Variables Spaces
    if '\\c' in translatedText:
        translatedText = re.sub(r'\s*(\\+c\[[1-9]+\])\s*', r'\1', translatedText)
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
    return (t,0)
    if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', subbedT):
        return(t, 0)

    """Translate text using GPT"""
    context = 'Eroge Names Context: 夏樹 明人 == Natsuki Akito | Male, 朝露 砂夜子 == Asatsuyu Sayoko | Female, 神野 藍 == Jinno Ai | Female, 神野 菫 | Jinno Sumire | Female, 夏樹 海夕里 == Natsuki Miyuri | Female, 水森 陽太 == Mizumori Youta | Male, 夏樹 和人 == Natsuki Kazuto | Male, 野崎 博也 == Nozaki Hiroya | Male, 大菊 ジュン == Oogiku Jun | Male, 酒井 絹代 == Sakai Kinuyo | Female, 酒井 豊 == Sakai Yutaka | Male, 竜生 春義 == Tatsuki Haruyoshi | Male, 竜生 潤 == Tatsuki Jun | Male, 吉沢 英玄 == Yoshizawa Eigen | Male, 吉沢 武雄 == Yoshizawa Takeo | Male'
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