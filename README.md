# GPT4-TL

Currently in development. Goal is to eventually have ChatGPT nicely translate all dialogue when given an RPGMaker JSON file.

### Required:
 * API Key: https://platform.openai.com/account/api-keys
 * Organization Key: https://platform.openai.com/account/org-settings
 * Python3: https://www.python.org/downloads/

### Setup:
1. Add you API key and Organization Key to a .env file. An example can be found in the repo.
2. Untranslated JSON files go in `/files`. Anything translated will end up in `/translated`
3. Run the script either with VSCode or by running .\main.py in a CLI.
