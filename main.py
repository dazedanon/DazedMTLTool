from concurrent.futures import ThreadPoolExecutor
from colorama import Fore
from dotenv import load_dotenv
from tqdm import tqdm
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
pipe = '###'
THREADS = 5

def main():
    # Open File (Threads)
    with ThreadPoolExecutor(max_workers=THREADS, thread_name_prefix='handle') as executor:
        for filename in os.listdir("files"):
            if filename.endswith('json'):
                executor.submit(handle, filename)

def handle(filename):
    with open('translated/' + filename, 'w', encoding='UTF-8') as outFile:
        with open('files/' + filename, 'r', encoding='UTF-8') as f:
            try:
                # Map Files
                if 'Map' in filename:
                    # Start Timer
                    start = time.time()

                    # Start Translation
                    translatedData = parseMap(json.load(f), filename)
                    json.dump(translatedData, outFile, ensure_ascii=False)

                    # Print Results
                    end = time.time()
                    print(f.name + ':', end=' ')
                    print(Fore.GREEN + str(round(end - start, 1)) + 's ' + u'\u2713' + Fore.RESET)
            except Exception as e:
                end = time.time()
                print(f.name + ':', end=' ')
                print(Fore.RED + str(round(end - start, 1)) + 's ' + u'\u2717 ' + str(e) + Fore.RESET)

def parseMap(data, filename):
    with ThreadPoolExecutor(max_workers=THREADS, thread_name_prefix='parseMap') as executor:
        events = data['events']
        for event in events:
            if event is not None:
                for page in event['pages']:
                    future = executor.submit(searchCodes, page, filename)
                
                # Verify if an exception was thrown
                try:
                    future.result()
                except Exception as e:
                    raise e

    return data

def searchCodes(page, filename):
    translatedText = ''
    currentGroup = []
    textHistory = []
    try:
        for i in tqdm(range(len(page['list'])), leave=False, position=0, desc=filename):
            time.sleep(0.001)
            if page['list'][i]['code'] == 401:
                currentGroup.append(page['list'][i]['parameters'][0])

                while (page['list'][i+1]['code'] == 401):
                    del page['list'][i]  
                    currentGroup.append(page['list'][i]['parameters'][0])
            else:
                if len(currentGroup) > 0:
                    text = ''.join(currentGroup)
                    text = text.replace('\\n', '')
                    translatedText = translateGPT(text, ' '.join(textHistory))
                    textHistory.append(translatedText)
                    translatedText = textwrap.fill(translatedText, width=50)
                    page['list'][i-1]['parameters'][0] = translatedText
                    if len(textHistory) > 10:
                        textHistory.pop(0)
                    currentGroup = []
    except IndexError:

        pass     
                
    # Append leftover groups
    if len(currentGroup) > 0:
        translatedText = translateGPT(''.join(currentGroup), ' '.join(textHistory))
        translatedText = textwrap.fill(translatedText, width=50)
        page['list'][i]['parameters'][0] = translatedText
        currentGroup = []
    
def translateGPT(t, history):

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
\\nそう、私はルイよ。= \\nYes, I'm Rui."

    response = openai.ChatCompletion.create(
        temperature=0,
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": t}
        ]
    )
    return response.choices[0].message.content
    
main()
