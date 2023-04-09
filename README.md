# DazedMTLTool - A script that translates RPGMaker MV JSON files using ChatGPT API

Currently in development. Goal is to eventually have ChatGPT nicely translate all dialogue when given an RPGMaker JSON file. Right now its only tested on MV but hopeful to add more engines in the future.

### Required:
 * API Key: https://platform.openai.com/account/api-keys
 * Organization Key: https://platform.openai.com/account/org-settings
 * Python3: https://www.python.org/downloads/

### Setup:
1. Add you API key and Organization Key to a .env file. An example can be found in the repo.
2. Untranslated JSON files go in `/files`. Anything translated will end up in `/translated`
3. Run the script either with VSCode or by running .\main.py in a CLI.
