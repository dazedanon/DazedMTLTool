from concurrent.futures import ThreadPoolExecutor
import sys
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
THREADS = 20
COST = .002 # Depends on the model https://openai.com/pricing

def main():
    print(Fore.BLUE + "If a file fails or gets stuck, Translated lines will remain \
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

                # Strings
                tokenString = Fore.YELLOW + '[' + str(translatedData[1]) + \
                    ' Tokens/${:,.4f}'.format(translatedData[1] * .001 * COST) + ']'
                timeString = Fore.BLUE + '[' + str(round(end - start, 1)) + 's]'

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
    
    with tqdm(total = totalLines, leave=False, desc=filename, bar_format='{l_bar}{bar:10}{r_bar}{bar:-10b}', position=0) as pbar:
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

def searchCodes(page, pbar):
    translatedText = ''
    currentGroup = []
    textHistory = []
    maxHistory = 20 # The higher this number is, the better the translation, the more money you are going to pay :)
    tokens = 0
    try:
        for i in range(len(page['list'])):
            pbar.update(1)
            # Translating Code: 401
            if page['list'][i]['code'] == 401:
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
                    response = translateGPT(text, ' '.join(textHistory))

                    # Check if we got an object back or plain string
                    if type(response) != str:
                        tokens += response.usage.total_tokens
                        translatedText = response.choices[0].message.content
                    else:
                        translatedText = response

                    # TextHistory is what we use to give GPT Context, so thats appended here.
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
    
@retry(tries=5, delay=2)
def translateGPT(t, history):

    # If there isn't any Japanese in the text just return it
    pattern = r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+'
    if not re.search(pattern, t):
        return t

    """Translate text using GPT"""

    system = "Context: " + history + "\n\n###\n\n You are a professional Japanese visual novel translator,\
editor, and localizer. You always manages to carry all of the little nuances of the original Japanese text to your output,\
while still making it a prose masterpiece, and localizing it in a way that an average American would understand.\
The 'Context' at the top is previously translated text for the work.\
You translate Onomatopoeia literally.\
When I give you something to translate, answer with just the translation.\
Translation Examples:\
\\n<ルイ>そう、私はルイよ。= \\n<Rui> Yes, I'm Rui.\
\\nそう、私はルイよ。= \\nYes, I'm Rui.\
\\n<瑠唯>イヤァァァ\"ァ\"ァ\"ァ\"ァ\"っ！！？ = \\n<Rui> Iyaaa\"a\"a\"a\"a\!!?\
\\nイグぅぅぅぅぅぅぅゥゥゥゥゥゥっ！！！♡♡♡ = \\nIguuuuuuuuuuuuu!!!♡♡♡"
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
