from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from pathlib import Path
import re
import sys
import textwrap
import threading
import time
import traceback
import tiktoken
import csv

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
MAXHISTORY = 10
ESTIMATE = ''
TOTALCOST = 0
TOKENS = 0
TOTALTOKENS = 0

#tqdm Globals
BAR_FORMAT='{l_bar}{bar:10}{r_bar}{bar:-10b}'
POSITION=0
LEAVE=False

def handleCSV(filename, estimate):
    global ESTIMATE, TOKENS, TOTALTOKENS, TOTALCOST
    ESTIMATE = estimate
    
    with open('translated/' + filename, 'w+t', newline='', encoding='utf-8') as writeFile:
        start = time.time()
        translatedData = openFiles(filename, writeFile)
        
        # Print Result
        end = time.time()
        tqdm.write(getResultString(translatedData, end - start, filename))
        TOTALCOST += translatedData[1] * .001 * APICOST
        TOTALTOKENS += translatedData[1]

    return getResultString(['', TOTALTOKENS, None], end - start, 'TOTAL')

def openFiles(filename, writeFile):
    with open('files/' + filename, 'r', encoding='utf-8') as readFile, writeFile:
        translatedData = parseCSV(readFile, writeFile, filename)

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
            errorString = str(e) + '|' + translatedData[3] + Fore.RED
            return filename + ': ' + tokenString + timeString + Fore.RED + u' \u2717 ' +\
                errorString + Fore.RESET
        
def parseCSV(readFile, writeFile, filename):
    totalTokens = 0
    totalLines = 0
    textHistory = []
    global LOCK

    format = ''
    while format == '':
        format = input('\n\nSelect the CSV Format:\n\n1. Translator++\n2. Translate All\n')
        match format:
            case '1':
                format = '1'
            case '2':
                format = '2'

    # Get total for progress bar
    totalLines = len(readFile.readlines())
    readFile.seek(0)

    reader = csv.reader(readFile, delimiter=',',)
    writer = csv.writer(writeFile, delimiter=',', quotechar='\"')

    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
        pbar.desc=filename
        pbar.total=totalLines

        for row in reader:
            try:
                totalTokens += translateCSV(row, pbar, writer, textHistory, format)
            except Exception as e:
                tracebackLineNo = str(traceback.extract_tb(sys.exc_info()[2])[-1].lineno)
                return [reader, totalTokens, e, tracebackLineNo]
    return [reader, totalTokens, None]

def translateCSV(row, pbar, writer, textHistory, format):
    translatedText = ''
    maxHistory = MAXHISTORY
    tokens = 0
    global LOCK, ESTIMATE

    try:
        match format:
            # Japanese Text on column 1. English on Column 2
            case '1':
                # Skip already translated lines
                if row[1] == '' or re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴ]+|[\uFF00-\uFFEF]', row[1]):
                    jaString = row[0]

                    # Remove repeating characters because it confuses ChatGPT
                    jaString = re.sub(r'([\u3000-\uffef])\1{2,}', r'\1\1', jaString)

                    # Translate
                    response = translateGPT(jaString, 'Previous text for context: ' + ' '.join(textHistory), True)

                    # Check if there is an actual difference first
                    if response[0] != row[0]:
                        translatedText = response[0]
                    else:
                        translatedText = row[1]
                    tokens += response[1]

                    # Textwrap
                    translatedText = textwrap.fill(translatedText, width=WIDTH)

                    # Set Data
                    row[1] = translatedText

                    # Keep textHistory list at length maxHistory
                    with LOCK:
                        if len(textHistory) > maxHistory:
                            textHistory.pop(0)
                        if not ESTIMATE:
                            writer.writerow(row)
                        pbar.update(1)

                    # TextHistory is what we use to give GPT Context, so thats appended here.
                    textHistory.append('\"' + translatedText + '\"')
                
            # Translate Everything
            case '2':
                for i in range(len(row)):
                    # This will allow you to ignore certain columns
                    if i not in [1]:
                        continue
                    jaString = row[i]
                    matchList = re.findall(r':name\[(.+?),.+?\](.+?[」）\"。]+)', jaString)

                    # Start Translation
                    for match in matchList:
                        speaker = match[0]
                        text = match[1]

                        # Translate Speaker
                        response = translateGPT (speaker, 'Reply with the '+ LANGUAGE +' translation of the NPC name.', True)
                        translatedSpeaker = response[0]
                        tokens += response[1]

                        # Translate Line
                        jaText = re.sub(r'([\u3000-\uffef])\1{3,}', r'\1\1\1', text)
                        response = translateGPT(translatedSpeaker + ': ' + jaText, 'Previous Translated Text: ' + '|'.join(textHistory), True)
                        translatedText = response[0]
                        tokens += response[1]

                        # TextHistory is what we use to give GPT Context, so thats appended here.
                        textHistory.append(translatedText)

                        # Remove Speaker from translated text
                        translatedText = re.sub(r'.+?: ', '', translatedText)

                        # Set Data
                        translatedSpeaker = translatedSpeaker.replace('\"', '')
                        translatedText = translatedText.replace('\"', '')
                        translatedText = translatedText.replace('「', '')
                        translatedText = translatedText.replace('」', '')
                        row[i] = row[i].replace('\n', ' ')

                        # Textwrap
                        translatedText = textwrap.fill(translatedText, width=WIDTH)

                        translatedText = '「' + translatedText + '」'
                        row[i] = re.sub(rf':name\[({re.escape(speaker)}),', f':name[{translatedSpeaker},', row[i])
                        row[i] = row[i].replace(text, translatedText)

                        # Keep History at fixed length.
                        with LOCK:
                            if len(textHistory) > maxHistory:
                                textHistory.pop(0)

                    with LOCK:
                        if not ESTIMATE:
                            writer.writerow(row)
                pbar.update(1)

    except Exception as e:
        traceback.print_exc()
        tracebackLineNo = str(traceback.extract_tb(sys.exc_info()[2])[-1].lineno)
        raise Exception(str(e) + '|Line:' + tracebackLineNo + '| Failed to translate: ' + text) 
    
    return tokens
    

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
