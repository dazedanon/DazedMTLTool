[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/A0A7KP6Z5)
# DazedMTLTool - A script that translates RPGMaker JSON files using ChatGPT API

![image](https://user-images.githubusercontent.com/96628874/230908699-adacb5e1-1548-4116-a0ea-a33297cdafa4.png)

Currently in development. Goal is to eventually have ChatGPT nicely translate all dialogue when given a specific file or list of files.

## Currently Supported:
* RPGMaker MV & MZ
* CSV Files

## Required:
 * API Key: https://platform.openai.com/account/api-keys
 * Organization Key: https://platform.openai.com/account/org-settings
 * Python3: https://www.python.org/downloads/

## Setup:
1. `cd` to the project folder and install the dependencies with `pip install -r requirements.txt`
2. Add your API key and Organization Key to a .env file. An example can be found in the repo.
3. Add a prompt.txt file using prompt.example as a template. (See ChatGPT Prompt Section)
4. Untranslated JSON files go in `/files`. Anything translated will end up in `/translated`
5. Run `start.py` script either with VSCode or by running `python .\start.py` in a CLI.

## ChatGPT Prompt:

`prompt.txt` will decide what and how ChatGPT translates the text. This is where you can customize it's output. This is extremely useful for when ChatGPT gives you a translation that you don't want. You can use this to tell him what to do, give examples of how you want things translated, etc. The example included is what I use currently, but you should tailor it to the game you are trying to translate.

Note that the bigger the prompt, the more $$$ its going to cost to translate.

## Troubleshooting Errors:
In its current state, you will very likely run into errors. There hasn't been enough testing with enough games to get it in a stable state. Often ChatGPT won't know how to translate something and will timeout. Currently the timeout is pretty long so the program may hang for a while. NEVER CLOSE THE PROGRAM FORCEFULLY unless you wish to lose your translation data, which might as well be you losing money. 

If the ChatGPT times out or hits any other error, what has already been translated will always be saved as long as you let it fail on its own. The file will still be placed in /translated on success or fail. That way you don't have to worry about the program failing and you wasting money on bugs.

### Common Errors:
#### ChatGPT timing out due to not knowing how to translate something 
1. Go into ChatGPT Playground https://platform.openai.com/playground?mode=chat and enter the text it failed on. If it comes out clean, likely the prompt may just need some adjusting or the string may need to be formatted in some way.
2. Create an example for that specific text. At the bottom of prompt.txt are examples you can enter which will give the AI training data on how to translate. This pretty much works 100% of the time but the downside is it will make your prompt.txt file bigger and your translation more expensive.

#### ChatGPT randomly hangs
1. Unsure what causes this. I recommend you just let it fail on its own and give you the error message. The error handler will tell you what line of text threw the error and what error it received.

### General Debugging:
You'll need VSCode or something similar:

#### See what text is being translated
* Place a breakpoint on this line `return [response.choices[0].message.content, response.usage.total_tokens]` and run the code in debugging mode. Everytime a request comes back you should be able to view the response object to see what text got translated and what the response was.

## How I Translate Games
The goal of this section is to get you learnt and ready to translate the game of your choice. I'll be walking you through every step of my process so that you can get an idea of what I do to get things working. First a couple of requirements.

* [VSCode](https://code.visualstudio.com/) (It's going to be be your main tool for running the scripts. When installing make sure you enable the context menu options)
* [Python 3](https://www.python.org/downloads/)
* [API Key](https://platform.openai.com/account/api-keys)

1. First download the repository. You can do this by just downloading the zip on the main page or using Git to clone it, either works.
2. Right click on the project folder and click `Open with Code`.

![image](https://github.com/dazedanon/DazedMTLTool/assets/96628874/df6adca7-1d6f-44a2-aab7-dfffeab91b02)

3. Here is where the magic happens. This will be your main workspace which you can use to do everything you need to MTL a game.

![image](https://github.com/dazedanon/DazedMTLTool/assets/96628874/68aedaf7-c915-4531-b76b-291a5d1487ff)

A breakdown of what all the different files are, this is important.
* /files - Where you place files that need to be translated.
* /translated - Where files go after they are translated.
* /scripts - ignore
* /src - The script files, the cogs of the machine, what creates the translation.
  * main.py - Responsible for determining what engine gets run based on user choices
  * rpgmakermvmz.py - Translation Script for the RPGMaker MV/MZ Engine.
  * rpgmakerace.py - Translation Script for the RPGMaker MV/MZ Engine. (WIP)
  * csvtl.py - Translation Script for CSV Files. Requires at least 2 columns to work.
  * textfile.py - Translation Script for Other game engines. (More of a custom script I change depending on the game)





