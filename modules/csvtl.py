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
openai.organization = os.getenv('org')
openai.api_key = os.getenv('key')

APICOST = .002 # Depends on the model https://openai.com/pricing
PROMPT = Path('prompt.txt').read_text(encoding='utf-8')
THREADS = 20
LOCK = threading.Lock()
WIDTH = 60
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

    with open('translated/' + filename, 'w+t', newline='', encoding='utf-16-le') as writeFile:
        start = time.time()
        translatedData = openFiles(filename, writeFile)

    if estimate:
        # Print Result
        end = time.time()
        tqdm.write(getResultString(['', TOKENS, None], end - start, filename))
        TOTALCOST += TOKENS * .001 * APICOST
        TOTALTOKENS += TOKENS
        TOKENS = 0
        os.remove('translated/' + filename)
    
    else:
        # Print Result
        end = time.time()
        tqdm.write(getResultString(translatedData, end - start, filename))
        TOTALCOST += translatedData[1] * .001 * APICOST
        TOTALTOKENS += translatedData[1]

    return getResultString(['', TOTALTOKENS, None], end - start, 'TOTAL')

def openFiles(filename, writeFile):
    with open('files/' + filename, 'r', encoding='utf-16-le') as readFile, writeFile:
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
                    if i not in [1]:
                        continue
                    jaString = row[i]

                    matchList = re.findall(r':name\[(.+?),.+?\](.+?[」）\"。]+)', jaString)

                    for match in matchList:
                        speaker = match[0]
                        text = match[1]

                        # Translate Speaker
                        response = translateGPT (speaker, 'Reply with the English translation of the NPC name.', True)
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
        tracebackLineNo = str(traceback.extract_tb(sys.exc_info()[2])[-1].lineno)
        raise Exception(str(e) + '|Line:' + tracebackLineNo + '| Failed to translate: ' + text) 
    
    return tokens
    

def subVars(jaString):
    varRegex = r'\\+[a-zA-Z]+\[.+?\]|[\\]+[#|]+|\\+[\\\[\]\.<>a-zA-Z0-9]+'
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
    # If ESTIMATE is True just count this as an execution and return.
    if ESTIMATE:
        enc = tiktoken.encoding_for_model("gpt-3.5-turbo-0613")
        TOKENS = len(enc.encode(t)) * 2 + len(enc.encode(history)) + len(enc.encode(PROMPT))
        return (t, 0)
    
    # Sub Vars
    varResponse = subVars(t)
    subbedT = varResponse[0]

    # If there isn't any Japanese in the text just skip
    if not re.search(r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+', subbedT):
        return(t, 0)

    """Translate text using GPT"""
    context = 'Eroge Names Context: ミカエル == Mikael | Female, ミカ == Mika | Female, ベルゼビュート == Beelzebuth | Female, ベル == Bel | Female, アズラエル == Azriel | Female, アズ == Az | Female, フレイア == Freya | Female'
    if fullPromptFlag:
        system = PROMPT 
        user = 'Current Text to Translate: ' + subbedT
    else:
        system = 'You are an expert translator who translates everything to English. Reply with only the English Translation of the text.' 
        user = 'Current Text to Translate: ' + subbedT
    response = openai.ChatCompletion.create(
        temperature=0,
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
    translatedText = translatedText.replace('Current Text to Translate: ', '')
    translatedText = translatedText.replace('English Translation:', '')
    translatedText = translatedText.replace('Translation:', '')
    translatedText = translatedText.replace('Current Text to Translate:', '')

    # Return Translation
    if len(translatedText) > 15 * len(t) or "I'm sorry, but I'm unable to assist with that translation" in translatedText:
        return [t, response.usage.total_tokens]
    else:
        return [translatedText, tokens]