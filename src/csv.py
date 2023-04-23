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

    if estimate:
        start = time.time()
        translatedData = openFiles(filename)

        # Print Result
        end = time.time()
        tqdm.write(getResultString(['', TOKENS, None], end - start, filename))
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
            json.dump(translatedData[0], outFile, ensure_ascii=False)
            tqdm.write(getResultString(translatedData, end - start, filename))
            TOTALCOST += translatedData[1] * .001 * APICOST
            TOTALTOKENS += translatedData[1]

    return getResultString(['', TOTALTOKENS, None], end - start, 'TOTAL')