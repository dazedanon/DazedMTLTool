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
THREADS = 10 # For GPT4 rate limit will be hit if you have more than 1 thread.
LOCK = threading.Lock()
WIDTH = 60
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
NAMES = False    # Output a list of all the character names found
BRFLAG = False   # If the game uses <br> instead
FIXTEXTWRAP = False

def handleTyrano(filename, estimate):
    global ESTIMATE, TOKENS, TOTALTOKENS, TOTALCOST
    ESTIMATE = estimate

    if estimate:
        start = time.time()
        translatedData = openFiles(filename)

        # Print Result
        end = time.time()
        tqdm.write(getResultString(translatedData, end - start, filename))
        with LOCK:
            TOTALCOST += translatedData[1] * .001 * APICOST
            TOTALTOKENS += translatedData[1]

        return getResultString(['', TOTALTOKENS, None], end - start, 'TOTAL')
    
    else:
        try:
            with open('translated/' + filename, 'w', encoding='UTF-8') as outFile:
                start = time.time()
                translatedData = openFiles(filename)

                # Print Result
                outFile.writelines(translatedData[0])
                end = time.time()
                tqdm.write(getResultString(translatedData, end - start, filename))
                with LOCK:
                    TOTALCOST += translatedData[1] * .001 * APICOST
                    TOTALTOKENS += translatedData[1]
        except Exception as e:
            traceback.print_exc()
            return 'Fail'

    return getResultString(['', TOTALTOKENS, None], end - start, 'TOTAL')

def openFiles(filename):
    with open('files/' + filename, 'r', encoding='utf-8') as readFile:
        translatedData = parseTyrano(readFile, filename)

        # Delete lines marked for deletion
        finalData = []
        for line in translatedData[0]:
            if line != '\\d\n':
                finalData.append(line)
        translatedData[0] = finalData
    
    return translatedData

def parseTyrano(readFile, filename):
    totalTokens = 0
    totalLines = 0

    # Get total for progress bar
    data = readFile.readlines()
    totalLines = len(data)

    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
        pbar.desc=filename
        pbar.total=totalLines

        try:
            totalTokens += translateTyrano(data, pbar)
        except Exception as e:
            traceback.print_exc()
            return [data, totalTokens, e]
    return [data, totalTokens, None]

def translateTyrano(data, pbar):
    textHistory = []
    maxHistory = MAXHISTORY
    tokens = 0
    currentGroup = []
    syncIndex = 0
    speaker = ''
    global LOCK, ESTIMATE

    for i in range(len(data)):
        if syncIndex > i:
            i = syncIndex

        # Speaker
        if '#' in data[i]:
            matchList = re.findall(r'#(.+)', data[i])
            if len(matchList) != 0:
                response = translateGPT(matchList[0], 'Reply with only the english translation of the NPC name', True)
                speaker = response[0]
                tokens += response[1]
                data[i] = '#' + speaker + '\n'
            else:
                speaker = ''

        # Choices
        elif 'glink' in data[i]:
            matchList = re.findall(r'text=\"(.+?)\"', data[i])
            if len(matchList) != 0:
                if len(textHistory) > 0:
                    response = translateGPT(matchList[0], 'Past Translated Text: ' + textHistory[len(textHistory)-1] + '\n\nReply in the style of a dialogue option.', True)
                else:
                    response = translateGPT(matchList[0], '', False)
                translatedText = response[0]
                tokens += response[1]

                # Remove characters that may break scripts
                charList = ['.', '\"', '\\n']
                for char in charList:
                    translatedText = translatedText.replace(char, '')

                # Set Data
                translatedText = 'text=\"' + translatedText.replace(' ', ' ') + '\"'
                data[i] = re.sub(r'text=\"(.+?)\"', translatedText, data[i])                

        # Lines
        elif '[p]' in data[i]:
            matchList = re.findall(r'(.+?)\[p\]', data[i])
            if len(matchList) > 0:
                matchList[0] = matchList[0].replace('「', '')
                matchList[0] = matchList[0].replace('」', '')
                currentGroup.append(matchList[0])
                if len(data) > i+1:
                    while '[p]' in data[i+1]:
                        data[i] = '\d\n'
                        i += 1
                        matchList = re.findall(r'(.+?)\[p\]', data[i])
                        if len(matchList) > 0:
                            matchList[0] = matchList[0].replace('「', '')
                            matchList[0] = matchList[0].replace('」', '')
                            currentGroup.append(matchList[0])
            # Join up 401 groups for better translation.
            if len(currentGroup) > 0:
                finalJAString = ''.join(currentGroup)
                oldjaString = finalJAString

            #Check Speaker
            if speaker == '':
                response = translateGPT(finalJAString, 'Previous Dialogue: ' + '\n\n'.join(textHistory), True)
                tokens += response[1]
                translatedText = response[0]
                textHistory.append('\"' + translatedText + '\"')
            else:
                response = translateGPT(speaker + ': ' + finalJAString, 'Previous Dialogue: ' + '\n\n'.join(textHistory), True)
                tokens += response[1]
                translatedText = response[0]
                textHistory.append('\"' + translatedText + '\"')

                # Remove added speaker
                translatedText = re.sub(r'^.+:\s?', '', translatedText)

            # Set Data
            translatedText = translatedText.replace('ッ', '')
            translatedText = translatedText.replace('っ', '')
            translatedText = translatedText.replace('ー', '')
            translatedText = translatedText.replace('\"', '')

            # Format Text
            matchList = re.findall(r'(.+?[)\.\?\!）。・]+)', translatedText)
            translatedText = re.sub(r'(.+?[)\.\?\!）。・]+)', '', translatedText)

            # Combine Lists
            for k in range(len(matchList)):
                matchList[k] = matchList[k].strip()
            j=0
            while(len(matchList) > j+1):
                while len(matchList[j]) < 100 and len(matchList) > j:
                    matchList[j:j+2] = [' '.join(matchList[j:j+2])]
                    if len(matchList) == j+1:
                        matchList[j] = matchList[j] + ' ' + translatedText
                        translatedText = ''
                        break
                j+=1
                
            if len(matchList) > 0:
                data[i] = '\d\n'
                for line in matchList:
                    data.insert(i, line.strip() + '[p]\n')
                    i+=1
            # else:
                # print ('No Matches')
            if translatedText != '':
                data[i] = translatedText.strip() + '[p]\n'

            # Keep textHistory list at length maxHistory
            if len(textHistory) > maxHistory:
                textHistory.pop(0)
            currentGroup = [] 

        currentGroup = [] 
        pbar.update(1)
        if len(data) > i+1:
            syncIndex = i+1
        else:
            break

    return tokens
            
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
            traceback.print_exc()
            errorString = str(e) + Fore.RED
            return filename + ': ' + tokenString + timeString + Fore.RED + u' \u2717 ' +\
                errorString + Fore.RESET
        
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
    if len(iconList) != 0:
        for color in colorList:
            jaString = jaString.replace(color, '<C' + str(count) + '>')
            count += 1

    # Names
    count = 0
    nameList = re.findall(r'[\\]+[nN]\[[0-9]+\]', jaString)
    nameList = set(nameList)
    if len(iconList) != 0:
        for name in nameList:
            jaString = jaString.replace(name, '<N' + str(count) + '>')
            count += 1

    # Variables
    count = 0
    varList = re.findall(r'[\\]+[vV]\[[0-9]+\]', jaString)
    varList = set(varList)
    if len(iconList) != 0:
        for var in varList:
            jaString = jaString.replace(var, '<V' + str(count) + '>')
            count += 1

    # Put all lists in list and return
    allList = [iconList, colorList, nameList, varList]
    return [jaString, allList]

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

    # Put all lists in list and return
    allList = [iconList, colorList, nameList, varList]
    return [jaString, allList]

@retry(exceptions=Exception, tries=5, delay=5)
def translateGPT(t, history, fullPromptFlag):
    global LOCK, TOKENS
    with LOCK:
        # If ESTIMATE is True just count this as an execution and return.
        if ESTIMATE:
            enc = tiktoken.encoding_for_model("gpt-3.5-turbo")
            tokens = len(enc.encode(t)) * 2 + len(enc.encode(history)) + len(enc.encode(PROMPT))
            return (t, tokens)
    
    # Sub Vars
    varResponse = subVars(t)
    subbedT = varResponse[0]

    # If there isn't any Japanese in the text just skip
    if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', subbedT):
        return(t, 0)

    """Translate text using GPT"""
    context = 'Eroge Names Context: 桐嶋 香織 == Kaori Kirishima | Female, 肉山 猛 == Takeshi Nikuyama'
    if fullPromptFlag:
        system = PROMPT 
        user = 'Line to Translate: ' + subbedT
    else:
        system = 'You are an expert translator who translates everything to English. Reply with only the English Translation of the text.' 
        user = 'Line to Translate: ' + subbedT
    response = openai.ChatCompletion.create(
        temperature=0,
        frequency_penalty=0.2,
        presence_penalty=0.2,
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
    translatedText = re.sub(r'\n\nPast Translated Text:.*', '', translatedText, 0, re.DOTALL)
    translatedText = re.sub(r'Note:.*', '', translatedText)

    # Return Translation
    if len(translatedText) > 15 * len(t) or "I'm sorry, but I'm unable to assist with that translation" in translatedText:
        return [t, response.usage.total_tokens]
    else:

        return [translatedText, tokens]