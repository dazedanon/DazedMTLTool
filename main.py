from concurrent.futures import ThreadPoolExecutor
import os
import re
import textwrap
import json
from dotenv import load_dotenv
import openai

#Globals
load_dotenv()
openai.organization = os.getenv('org')
openai.api_key = os.getenv('key')
pipe = '###'
THREADS = 5

def main():
    # Open File (Threads)
    test = 0
    with ThreadPoolExecutor(max_workers=THREADS, thread_name_prefix='handle') as executor:
        for filename in os.listdir("files"):
            if filename.endswith('json'):
                executor.submit(handle, filename)

def handle(filename):
    with open('translated/' + filename, 'w', encoding='UTF-8') as outFile:
        with open('files/' + filename, 'r', encoding='UTF-8') as f:
            # Map Files
            if 'Map' in filename:
                translatedData = parseMap(json.load(f))
                json.dump(translatedData, outFile, ensure_ascii=False)
                print('Translated: {0}'.format(filename))
            

def parseMap(data):
    test = 0
    with ThreadPoolExecutor(max_workers=THREADS, thread_name_prefix='parseMap') as executor:
        events = data['events']
        for event in events:
            if event is not None:
                executor.submit(handleParseMap, event, test)    
    return data

def handleParseMap(event, test):
    print(test)
    test = test+1
    for page in event['pages']:
        searchCodes(page)
    return page

def searchCodes(page):
    translatedText = ''
    currentGroup = []
    textHistory = []
    try:
        for i in range(len(page['list'])):
            if page['list'][i]['code'] == 401:
                currentGroup.append(page['list'][i]['parameters'][0])

                while (page['list'][i+1]['code'] == 401):
                    del page['list'][i]  
                    currentGroup.append(page['list'][i]['parameters'][0])
            else:
                if len(currentGroup) > 0:
                    text = ''.join(currentGroup)
                    text = text.replace('\\n', '')
                    print('Translating' + text)
                    translatedText = translateGPT(text, ' '.join(textHistory))
                    textHistory.append(translatedText)
                    translatedText = textwrap.fill(translatedText, width=50)
                    page['list'][i-1]['parameters'][0] = translatedText
                    if len(textHistory) > 1:
                        textHistory.pop(0)
                    currentGroup = []
    except IndexError:
        print('End of List')     
                
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
    editor, and localizer. You always manage to convey the original meaning of the Japanese text to your output,\
    and localize it in a way that an average American would understand.\
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
