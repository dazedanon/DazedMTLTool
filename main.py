import os
import re
import textwrap
from googletrans import Translator
from pathlib import Path
import json
import time
from dotenv import load_dotenv
import openai

load_dotenv()
openai.organization = os.getenv('org')
openai.api_key = os.getenv('key')

def main():
    # Load JSON file into a Python dictionary
    with open('Map013.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
        parse401(data)

def parse401(data):
    """
    Extracts the first parameter of all commands with code 401 from a dictionary of events.

    Args:
        data (list): A list of events.

    Returns:
        list: A list of strings containing the first parameter of all commands with code 401.
    """
    # Extract 401 Text
    events = data['events']
    untranslatedTextList = []
    for event in events:
        if event is not None:
            for page in event['pages']:
                for command in page['list']:
                    if command['code'] == 401:
                        untranslatedTextList.append(command['parameters'][0])

    batchList = splitIntoBatches(untranslatedTextList, 3500)  

    # Translate Batches
    translatedBatchList = []
    for batch in batchList:
        translatedBatchList.append(translateGPT(batch))
    translatedText = ''.join(translatedBatchList)
    translatedTextList = translatedText.split('/p')
    translatedTextList = wordwrapList(translatedTextList)
    translatedTextList = matchListSize(untranslatedTextList, translatedTextList)
    
    # Write to new json file
    i = 0
    for event in events:
        if event is not None:
            for page in event['pages']:
                for command in page['list']:
                    if command['code'] == 401:
                        if command['parameters'][0] == '':
                            del command['parameters'][0]
                        else:
                            command['parameters'][0] = translatedTextList[i]
                            i += 1

    with open('file.json', 'w') as f:
        json.dump(data, f)

def splitIntoBatches(textList, n):
    """This function takes a piece of text and sorts it into batches based on set token length."""
    # Initialize the batch list
    batches = []
    
    # Initialize the current batch
    current_batch = []
    
    # Loop through each word in the text
    for line in textList:
        # If adding the current word to the current batch would exceed the max length,
        # add the current batch to the list of batches and start a new batch
        if len(' '.join(current_batch + [line])) > n:
            batches.append(current_batch)
            current_batch = [line]
        # Otherwise, add the current word to the current batch
        else:
            current_batch.append(line)
    
    # Add any remaining words to the final batch
    if len(current_batch) > 0:
        batches.append(current_batch)
    
    return batches

def translateGPT(t):
    """Translate text using GPT"""
    system = "You are a professional Japanese visual novel translator. \
    You always manages to translate all of the little nuances of the original \
    Japanese text to your output, while still making it a prose masterpiece, \
    and localizing it in a way that an average American would understand. \
    You always include the '/p' from the original text in your translation."

    # Convert to text
    pipe = '/p'
    t = pipe.join(t)

    response = openai.ChatCompletion.create(
        temperature=0,
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": t}
        ]
    )
    return response.choices[0].message.content

def matchListSize(list1, list2):
    """Make list2 the same size as list1"""
    list2 += [""] * (len(list1) - len(list2))
    for i in range(len(list2)):
        list2[i] = list2[i].strip()

    return list2

def wordwrapList(list):
    wrappedList = []

    for item in list:
        wrappedList.append(textwrap.fill(item, width=50))

    return wrappedList

main()
