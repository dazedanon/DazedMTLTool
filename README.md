# DazedMTLTool - A script that translates RPGMaker MV JSON files using ChatGPT API



Currently in development. Goal is to eventually have ChatGPT nicely translate all dialogue when given an RPGMaker JSON file. Right now its only tested on MV but hopeful to add more engines in the future.

## Required:
 * API Key: https://platform.openai.com/account/api-keys
 * Organization Key: https://platform.openai.com/account/org-settings
 * Python3: https://www.python.org/downloads/

## Setup:
1. Add you API key and Organization Key to a .env file. An example can be found in the repo.
2. Edit the prompt.example to prompt.txt. (See ChatGPT Prompt Section)
2. Untranslated JSON files go in `/files`. Anything translated will end up in `/translated`
3. Run the script either with VSCode or by running .\main.py in a CLI.

## ChatGPT Prompt:

`prompt.txt` will decide what and how ChatGPT translates the text. This is where you can customize it's output. This is extremely useful for when ChatGPT gives you a translation that you don't want. You can use this to tell him what to do, give examples of how you want things translated, etc. The example included is what I use currently, but you should tailor it to the game you are trying to translate.

Note that the bigger the prompt, the more $$$ its going to cost to translate.
