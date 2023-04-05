import os
import re
import textwrap
import json
from dotenv import load_dotenv
import openai

load_dotenv()
openai.organization = os.getenv('org')
openai.api_key = os.getenv('key')
pipe = '###'

def main():
    # Load JSON file into a Python dictionary
    with open('Map013.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
        parse401(data)

def count401Groups(data):
    """
    Counts the number of groups of 401 in a dictionary of events.

    Args:
        data (list): A list of events.

    Returns:
        int: The number of groups of 401.
    """
    # Count 401 Groups
    events = data['events']
    groupCount = 0
    currentGroupCount = 0
    for event in events:
        if event is not None:
            for page in event['pages']:
                for command in page['list']:
                    if command['code'] == 401:
                        currentGroupCount += 1
                    else:
                        if currentGroupCount > 0:
                            groupCount += 1
                        currentGroupCount = 0
                if currentGroupCount > 1:
                    groupCount += 1
                currentGroupCount = 0
    return groupCount

def parse401(data):
    """
    Extracts the first parameter of all commands with code 401 from a dictionary of events.

    Args:
        data (list): A list of events.

    Returns:
        list: A list of strings containing the first parameter of all commands with code 401.
    """
    # Extract 401 Text (Needed for Context)
    translatedText = ''
    untranslatedTextList = []
    currentGroup = []
    textHistory = []

    events = data['events']
    for event in events:
        if event is not None:
            for page in event['pages']:
                try:
                    for i in range(len(page['list'])):
                        if page['list'][i]['code'] == 401:
                            currentGroup.append(page['list'][i]['parameters'][0])
                            textHistory.append(page['list'][i]['parameters'][0])

                            while page['list'][i+1]['code'] == 401:
                                del page['list'][i]  
                                currentGroup.append(page['list'][i]['parameters'][0])
                                textHistory.append(page['list'][i]['parameters'][0])    
                        else:
                            if len(currentGroup) > 0:
                                text = ''.join(currentGroup)
                                print('Translating' + text)
                                translatedText = translateGPT(text, ''.join(textHistory))
                                page['list'][i-1]['parameters'][0] = translatedText
                                if len(textHistory) > 50:
                                    for i in range(len(currentGroup)):
                                        textHistory.pop(0)
                                currentGroup = []
                except IndexError:
                    print('End of List')     
                
                # Append leftover groups
                if len(currentGroup) > 0:
                    translatedText = translateGPT(''.join(currentGroup), ' '.join(textHistory))
                    page['list'][i]['parameters'][0] = translatedText
                    currentGroup = []
    
    with open('file.json', 'w', encoding='utf-8') as f:
        json.dump(data, f)

def translateGPT(t, history):

    pattern = r'[一-龠]+|[ぁ-ゔ]+|[ァ-ヴー]+'
    if not re.search(pattern, t):
        return t

    """Translate text using GPT"""

    system = "Context: " + history + "\n\n###\n\n You are a professional Japanese visual novel translator, editor, and localizer, \
    with a writing style could only be described as being a mixture of \
    John Steinbeck's, Oscar Wilde's, and Vladimir Nabokov's writing styles. \
    You always manage to carry all of the little nuances of the original Japanese text to your output, \
    while still making it a prose masterpiece, and localizing it in a way that an average American would understand. \
    You read and understand the 'Context' \
    You translate only what I give you. \
    You include line breaks in your translation. \
    You translate sound effects and Onomatopoeia in their romanji form. \
    You translate anything inside '<>' as a name"

    response = openai.ChatCompletion.create(
        temperature=0,
        max_tokens = 3000,
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": t}
        ]
    )
    return response.choices[0].message.content
    
main()
