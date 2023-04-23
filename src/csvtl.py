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

    with open('translated/' + filename, 'w+t', newline='', encoding='UTF-8') as writeFile:
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
    with open('files/' + filename, 'r', encoding='UTF-8') as readFile, writeFile:
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

    # Get total for progress bar
    totalLines = len(readFile.readlines())
    readFile.seek(0)

    reader = csv.reader(readFile, delimiter=',')
    writer = csv.writer(writeFile, delimiter=',', quoting=csv.QUOTE_NONNUMERIC)

    with tqdm(bar_format=BAR_FORMAT, position=POSITION, total=totalLines, leave=LEAVE) as pbar:
        pbar.desc=filename
        pbar.total=totalLines

        for row in reader:
            try:
                totalTokens += translateCSV(row, pbar, writer, textHistory)
            except Exception as e:
                tracebackLineNo = str(traceback.extract_tb(sys.exc_info()[2])[-1].lineno)
                return [reader, totalTokens, e, tracebackLineNo]
    return [reader, totalTokens, None]

def translateCSV(row, pbar, writer, textHistory):
    translatedText = ''
    maxHistory = MAXHISTORY
    tokens = 0
    global LOCK, ESTIMATE

    try:
        jaString = row[0]

        # Remove repeating characters because it confuses ChatGPT
        jaString = re.sub(r'([\u3000-\uffef])\1{2,}', r'\1\1', jaString)

        # Sub Vars
        jaString = re.sub(r'(\\+[a-zA-Z]+)\[([a-zA-Z0-9]+)\]', r'[\1|\2]', jaString)

        # Translate
        response = translateGPT(jaString, 'Previous text for context: ' + ' '.join(textHistory))

        # Check if there is an actual difference first
        if response[0] != row[0]:
            translatedText = response[0]
        else:
            translatedText = row[1]
        tokens += response[1]

        # ReSub Vars
        translatedText = re.sub(r'\[([\\a-zA-Z]+)\|([a-zA-Z0-9]+)]', r'\1[\2]', translatedText)
        translatedText = re.sub('"', "'", translatedText)

        # TextHistory is what we use to give GPT Context, so thats appended here.
        textHistory.append(': ' + translatedText)

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

    except Exception as e:
        tracebackLineNo = str(traceback.extract_tb(sys.exc_info()[2])[-1].lineno)
        raise Exception(str(e) + '|Line:' + tracebackLineNo + '| Failed to translate: ' + jaString) 
    
    return tokens
    

@retry(exceptions=Exception, tries=5, delay=5)
def translateGPT(t, history):
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