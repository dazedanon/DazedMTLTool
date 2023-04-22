from concurrent.futures import ThreadPoolExecutor
from colorama import Fore
import os

from rpgmakermvmz import handleMVMZ
from rpgmakerace import handleACE

THREADS = 20

# Info Message
print(Fore.LIGHTYELLOW_EX + "Do not close while translation is in progress. If a file fails or gets stuck, \
Translated lines will remain translated so you don't have to worry about being charged \
twice. You can simply copy the file generated in /translations back over to /files and \
start the script again. It will skip over any translated text." + Fore.RESET, end='\n\n')

def main():
    estimate = ''
    while estimate == '':
        estimate = input('Select Translation or Cost Estimation:\n\n1. Translate\n2. Estimate\n')
        match estimate:
            case '1': estimate = False
            case '2': estimate = True
            case _: estimate = ''
    
    version = input('Select the RPGMaker Version:\n\n1. MV/MZ\n2. ACE\n')

    totalCost = 0
    match version:
        case '1':
            # Open File (Threads)
            with ThreadPoolExecutor(max_workers=THREADS) as executor:
                for filename in os.listdir("files"):
                    if filename.endswith('json'):
                        future = executor.submit(handleMVMZ, filename, estimate)

                        try:
                            totalCost = future.result()
                        except Exception as e:
                            print(Fore.RED + str(e))

        case '2':
             # Open File (Threads)
            with ThreadPoolExecutor(max_workers=THREADS) as executor:
                for filename in os.listdir("files"):
                    if filename.endswith('json'):
                        future = executor.submit(handleACE, filename, estimate)

                        try:
                            totalCost = future.result()
                        except Exception as e:
                            print(Fore.RED + str(e))
        
    if estimate == False:
        # This is to encourage people to grab what's in /translated instead
        deleteFolderFiles('files')

    # Prevent immediately closing of CLI
    print(totalCost)
    input('Done! Press Enter to close.')

def deleteFolderFiles(folderPath):
    for filename in os.listdir(folderPath):
        file_path = os.path.join(folderPath, filename)
        if file_path.endswith('.json'):
            os.remove(file_path)   
    
main()
