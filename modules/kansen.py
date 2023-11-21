from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from pathlib import Path
import re
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
THREADS = int(os.getenv('threads')) # For GPT4 rate limit will be hit if you have more than 1 thread.
LOCK = threading.Lock()
WIDTH = int(os.getenv('width'))
LISTWIDTH = int(os.getenv('listWidth'))
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
FIXTEXTWRAP = True
IGNORETLTEXT = True

def handleKansen(filename, estimate):
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
            with open('translated/' + filename, 'w', encoding='shift_jis', errors='ignore') as outFile:
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
    with open('files/' + filename, 'r', encoding='cp932') as readFile:
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
        if '[ns]' in data[i]:
            matchList = re.findall(r'\[ns\](.+?)\[', data[i])
            if len(matchList) != 0:
                response = translateGPT(matchList[0], 'Reply with only the '+ LANGUAGE +' translation of the NPC name', True)
                speaker = response[0]
                tokens += response[1]
                data[i] = '[ns]' + speaker + '[nse]\n'
            else:
                speaker = ''

        # Choices
        elif '[eval exp="f.seltext' in data[i]:
            matchList = re.findall(r'\[eval exp=.+?\'(.+)\'', data[i])
            if len(matchList) != 0:
                if len(textHistory) > 0:
                    originalText = matchList[0]
                    response = translateGPT(matchList[0], 'Past Translated Text: ' + textHistory[len(textHistory)-1] + '\n\nReply in the style of a dialogue option.', True)
                else:
                    response = translateGPT(matchList[0], '', False)
                translatedText = response[0]
                tokens += response[1]

                # Remove characters that may break scripts
                charList = ['.', '\"', '\\n']
                for char in charList:
                    translatedText = translatedText.replace(char, '')

                # Escape all '
                translatedText = translatedText.replace('\\', '')
                translatedText = translatedText.replace("'", "\\\'")

                # Set Data
                translatedText = data[i].replace(originalText, translatedText)
                data[i] = translatedText                

        # Lines
        matchList = re.findall(r'(.+?)\[r\]$', data[i])
        if len(matchList) > 0:
            matchList[0] = matchList[0].replace('「', '')
            matchList[0] = matchList[0].replace('」', '')
            currentGroup.append(matchList[0])
            if len(data) > i+1:
                while '[r]' in data[i+1]:
                    data[i] = '\d\n'    # \d Marks line for deletion
                    i += 1
                    matchList = re.findall(r'(.+?)\[r\]', data[i])
                    if len(matchList) > 0:
                        matchList[0] = matchList[0].replace('「', '')
                        matchList[0] = matchList[0].replace('」', '')
                        currentGroup.append(matchList[0])
                while '[pcms]' in data[i+1]:
                    data[i] = '\d\n'
                    i += 1
                    matchList = re.findall(r'(.+?)\[pcms\]', data[i])
                    if len(matchList) > 0:
                        matchList[0] = matchList[0].replace('「', '')
                        matchList[0] = matchList[0].replace('」', '')
                        currentGroup.append(matchList[0])
            # Join up 401 groups for better translation.
            if len(currentGroup) > 0:
                finalJAString = ''.join(currentGroup)
                oldjaString = finalJAString

            # Remove any textwrap
            if FIXTEXTWRAP == True:
                finalJAString = re.sub(r'[r]', ' ', finalJAString)

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
            translatedText = translatedText.replace('[', '')
            translatedText = translatedText.replace(']', '')

            # Format Text
            matchList = re.findall(r'(.+?[)\.\?\!）。・]+)', translatedText)
            translatedText = re.sub(r'(.+?[)\.\?\!）。・]+)', '', translatedText)

            # Combine Lists
            for k in range(len(matchList)):
                matchList[k] = matchList[k].strip()
            j=0
            while(len(matchList) > j+1):
                while len(matchList[j]) < 30 and len(matchList) > j:
                    matchList[j:j+2] = [' '.join(matchList[j:j+2])]
                    if len(matchList) == j+1:
                        matchList[j] = matchList[j] + ' ' + translatedText
                        translatedText = ''
                        break
                j+=1
                
            if len(matchList) > 0:
                data[i] = '\d\n'
                for line in matchList:
                    # Wordwrap Text
                    if '[r]' not in line:
                        line = textwrap.fill(line, width=WIDTH)
                        line = line.replace('\n', '[r]')
                    
                    # Set
                    data.insert(i, line.strip() + '[l][er]\n')
                    i+=1
                data[i-1] = data[i-1].replace('[l][er]', '[pcms]')
            # else:
                # print ('No Matches')
            if translatedText != '':
                # Wordwrap Text
                if '[r]' not in translatedText:
                    translatedText = textwrap.fill(translatedText, width=WIDTH)
                    translatedText = translatedText.replace('\n', '[r]')

                # Set Backup
                data[i] = translatedText.strip() + '[l][er]\n'

            # Keep textHistory list at length maxHistory
            if len(textHistory) > maxHistory:
                textHistory.pop(0)
            currentGroup = [] 
            speaker = ''
        
        matchList = re.findall(r'(.+?)\[pcms\]$', data[i])
        if len(matchList) > 0:
            matchList[0] = matchList[0].replace('「', '')
            matchList[0] = matchList[0].replace('」', '')
            finalJAString = matchList[0]

            # Remove any textwrap
            if FIXTEXTWRAP == True:
                finalJAString = finalJAString.replace('[r]', ' ')
            
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
            translatedText = translatedText.replace('[', '')
            translatedText = translatedText.replace(']', '')

            # Format Text
            matchList = re.findall(r'(.+?[)\.\?\!）。・]+)', translatedText)
            translatedText = re.sub(r'(.+?[)\.\?\!）。・]+)', '', translatedText)

            # Get rid of whitespace for each item and add wordwrap
            for k in range(len(matchList)):
                matchList[k] = matchList[k].strip()

            # Combine Sentences with a max limit (Wordwrap basically)
            j=0
            while(len(matchList) > j+1):
                while len(matchList[j]) < 30 and len(matchList) > j:
                    matchList[j:j+2] = [' '.join(matchList[j:j+2])]
                    if len(matchList) == j+1:
                        matchList[j] = matchList[j] + ' ' + translatedText
                        translatedText = ''
                        break
                j+=1
                
            # Set Data
            if len(matchList) > 0:
                data[i] = '\d\n'
                for line in matchList:
                    # Wordwrap Text
                    if '[r]' not in line:
                        line = textwrap.fill(line, width=WIDTH)
                        line = line.replace('\n', '[r]')
                    
                    # Set
                    data.insert(i, line.strip() + '[l][er]\n')
                    i+=1
                # Set last line as [pcms] instead of [r]
                data[i-1] = data[i-1].replace('[l][er]', '[pcms]')
            # else:
                # print ('No Matches')
            if translatedText != '':
                # Wordwrap Text
                if '[r]' not in translatedText:
                    translatedText = textwrap.fill(translatedText, width=WIDTH)
                    translatedText = translatedText.replace('\n', '[r]')

                # Set Backup
                data[i] = translatedText.strip() + '[l][er]\n'

            # Keep textHistory list at length maxHistory
            if len(textHistory) > maxHistory:
                textHistory.pop(0)
            currentGroup = [] 
            speaker = ''

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
    iconList = re.findall(r'[\\]+[iIkKwW]+\[[0-9]+\]', jaString)
    iconList = set(iconList)
    if len(iconList) != 0:
        for icon in iconList:
            jaString = jaString.replace(icon, '[Icon' + str(count) + ']')
            count += 1

    # Colors
    count = 0
    colorList = re.findall(r'[\\]+[cC]\[[0-9]+\]', jaString)
    colorList = set(colorList)
    if len(colorList) != 0:
        for color in colorList:
            jaString = jaString.replace(color, '[Color' + str(count) + ']')
            count += 1

    # Names
    count = 0
    nameList = re.findall(r'[\\]+[nN]\[[0-9]+\]', jaString)
    nameList = set(nameList)
    if len(nameList) != 0:
        for name in nameList:
            jaString = jaString.replace(name, '[Name' + str(count) + ']')
            count += 1

    # Variables
    count = 0
    varList = re.findall(r'[\\]+[vV]\[[0-9]+\]', jaString)
    varList = set(varList)
    if len(varList) != 0:
        for var in varList:
            jaString = jaString.replace(var, '[Var' + str(count) + ']')
            count += 1

    # Put all lists in list and return
    allList = [iconList, colorList, nameList, varList]
    return [jaString, allList]

def resubVars(translatedText, allList):
    # Fix Spacing and ChatGPT Nonsense
    matchList = re.findall(r'\[\s?.+?\s?\]', translatedText)
    if len(matchList) > 0:
        for match in matchList:
            text = match.strip()
            translatedText = translatedText.replace(match, text)

    # Icons
    count = 0
    if len(allList[0]) != 0:
        for var in allList[0]:
            translatedText = translatedText.replace('[Icon' + str(count) + ']', var)
            count += 1

    # Colors
    count = 0
    if len(allList[1]) != 0:
        for var in allList[1]:
            translatedText = translatedText.replace('[Color' + str(count) + ']', var)
            count += 1

    # Names
    count = 0
    if len(allList[2]) != 0:
        for var in allList[2]:
            translatedText = translatedText.replace('[Name' + str(count) + ']', var)
            count += 1

    # Vars
    count = 0
    if len(allList[3]) != 0:
        for var in allList[3]:
            translatedText = translatedText.replace('[Var' + str(count) + ']', var)
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
