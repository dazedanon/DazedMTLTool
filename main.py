import os
from googletrans import Translator
from pathlib import Path
import json
import time
from dotenv import load_dotenv
import openai

load_dotenv()
openai.organization = os.getenv('org')
openai.api_key = os.getenv('key')

# Load JSON file into a Python dictionary
with open('Map013.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# Extract 401 events text
events = data['events']
text = []
for event in events:
    if event is not None:
        for page in event['pages']:
            for command in page['list']:
                if command['code'] == 401:
                    text.append(command['parameters'][0])

# Split into batches
pipe = '/p'
script = pipe.join(text)

# Translate text using GPT
def translate(t):
    system = "You are a professional Japanese visual novel translator. \
    You always manages to translate all of the little nuances of the original \
    Japanese text to your output, while still making it a prose masterpiece, \
    and localizing it in a way that an average American would understand. \
    You always include the '/p' from the original text in your translation." \

    response = openai.ChatCompletion.create(
        temperature=0.2,
        max_tokens=500,
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": t}
        ]
    )
    return response.choices[0].message.content

# Make translated list the same size
translatedText += [""] * (len(text) - len(translatedText))
for i in range(len(translatedText)):
    translatedText[i] = translatedText[i].strip()
    
# Place translated text back in its original location in the JSON file
i = 0
for event in events:
    if event is not None:
        for page in event['pages']:
            for command in page['list']:
                if command['code'] == 401:
                    command['parameters'][0] = translatedText[i]
                    i += 1

with open('file.json', 'w') as f:
    json.dump(data, f)
