from concurrent.futures import ThreadPoolExecutor, as_completed
import sys
import traceback
from colorama import Fore
import os
from tqdm import tqdm

from modules.rpgmakermvmz import handleMVMZ
from modules.rpgmakerace import handleACE
from modules.csv import handleCSV
from modules.alice import handleAlice
from modules.tyrano import handleTyrano
from modules.json import handleJSON
from modules.kansen import handleKansen
from modules.lune2 import handleLuneTxt
from modules.atelier import handleAtelier
from modules.anim import handleAnim

# For GPT4 rate limit will be hit if you have more than 1 thread.
# 1 Thread for each file. Controls how many files are worked on at once.
THREADS = int(os.getenv('fileThreads'))

# [Display name, file extension, handle function]
MODULES = [
    ["RPGMaker MV/MZ", "json", handleMVMZ],
    ["RPGMaker ACE", "yaml", handleACE],
    ["CSV (From Translator++)", "csv", handleCSV],
    ["Alice", "txt", handleAlice],
    ["Tyrano", "ks", handleTyrano],
    ["JSON", "json", handleJSON],
    ["Kansen", "ks", handleKansen],
    ["Lune", "txt", handleLuneTxt],
    ["Atelier", "txt", handleAtelier],
    ["Anim", "json", handleAnim],
]

# Info Message
tqdm.write(Fore.LIGHTYELLOW_EX + "WARNING: Once a translation starts do not close it unless you want to lose your\
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

    totalCost = 0

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

        # Prevent immediately closing of CLI
        tqdm.write(str(totalCost))
        # input('Done! Press Enter to close.')

def deleteFolderFiles(folderPath):
    for filename in os.listdir(folderPath):
        file_path = os.path.join(folderPath, filename)
        if file_path.endswith(('.json', '.yaml', '.ks')):
            os.remove(file_path)   
