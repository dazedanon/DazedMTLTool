import sys, os, traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from colorama import Fore
from tqdm import tqdm
from dotenv import load_dotenv

# This needs to be before the module imports as some of them currently try to read and use some of these values
# upon import, in which case if they are unset the script will crash before we can output these messages.
envMissing = False
load_dotenv()
for env in ['api','key','organization','model','language','timeout','fileThreads','threads','width','listWidth']:
    if os.getenv(env) is None or str(os.getenv(env))[:1] == '<':
        tqdm.write(Fore.RED + f'Environment variable {env} is not set!')
        envMissing = True
if envMissing:
    tqdm.write(Fore.RED + f'Some of the required environment values may not be set correctly. You can set \
these values using an .env file, for an example see .env.example')

from modules.rpgmakermvmz import handleMVMZ
from modules.rpgmakerace import handleACE
from modules.csv import handleCSV
from modules.eushully import handleEushully
from modules.alice import handleAlice
from modules.tyrano import handleTyrano
from modules.json import handleJSON
from modules.kansen import handleKansen
from modules.lune import handleLune
from modules.atelier import handleAtelier
from modules.anim import handleAnim
from modules.nscript import handleOnscripter
from modules.wolf import handleWOLF
from modules.wolf2 import handleWOLF2
from modules.javascript import handleJavascript
from modules.irissoft import handleIris
from modules.regex import handleRegex

# For GPT4 rate limit will be hit if you have more than 1 thread.
# 1 Thread for each file. Controls how many files are worked on at once.
THREADS = int(os.getenv('fileThreads'))

# [Display name, file extension, handle function]
MODULES = [
    ["RPGMaker MV/MZ", "json", handleMVMZ],
    ["RPGMaker ACE", "yaml", handleACE],
    ["CSV (From Translator++)", "csv", handleCSV],
    ["Eushully", "txt", handleEushully],
    ["Alice", "txt", handleAlice],
    ["Tyrano", "ks", handleTyrano],
    ["JSON", "json", handleJSON],
    ["Kansen", "ks", handleKansen],
    ["Lune", "json", handleLune],
    ["Atelier", "txt", handleAtelier],
    ["Anim", "json", handleAnim],
    ["NScript", "txt", handleOnscripter],
    ["Wolf", "json", handleWOLF],
    ["Wolf", "txt", handleWOLF2],
    ["Javascript", "js", handleJavascript],
    ["Iris", "txt", handleIris],
    ["Regex", "txt", handleRegex],
]

# Info Message
tqdm.write(Fore.LIGHTYELLOW_EX + "WARNING: Once the translation starts do not close it unless you want to lose your \
translated data. If a file fails or gets stuck, translated lines will remain translated so you don't have \
to worry about being charged twice. You can simply copy the file generated in /translations back over to \
/files and start the script again. It will skip over any translated text." + Fore.RESET, end='\n\n')

def main():
    estimate = ''
    while estimate == '':
        estimate = input('Select Translation or Cost Estimation:\n\n 1. Translate\n 2. Estimate\n')
        match estimate:
            case '1':
                estimate = False
            case '2':
                estimate = True
            case _:
                estimate = ''
    
    version = ''
    while True:
        tqdm.write("Select game engine:\n")
        for position, module in enumerate(MODULES):
            tqdm.write(f'{str(position + 1).rjust(2)}. {module[0]} (.{module[1]})')
        version = input()
        try:
            version = int(version) - 1
        except:
            continue
        if version in range(len(MODULES)):
            break    

    totalCost = Fore.RED + 'Translation module didn\'t return the total cost. Make sure the \
files to translate are in the /files folder and that you picked the right game engine.'

    # Open File (Threads)
    with ThreadPoolExecutor(max_workers=THREADS) as executor:
        futures = [executor.submit(MODULES[version][2], filename, estimate) \
                    for filename in os.listdir("files") if filename.endswith(MODULES[version][1])]
                    
        for future in as_completed(futures):
            try:
                totalCost = future.result()
            except Exception as e:
                tracebackLineNo = str(traceback.extract_tb(sys.exc_info()[2])[-1].lineno)
                tqdm.write(Fore.RED + str(e) + '|' + tracebackLineNo + Fore.RESET)

    if totalCost != 'Fail':
        if estimate is False:
            # This is to encourage people to grab what's in /translated instead
            deleteFolderFiles('files')

        tqdm.write(str(totalCost))

def deleteFolderFiles(folderPath):
    for filename in os.listdir(folderPath):
        file_path = os.path.join(folderPath, filename)
        if file_path.endswith(('.json', '.yaml', '.ks')):
            os.remove(file_path)   
