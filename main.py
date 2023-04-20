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
    version = input('Select the RPGMaker Version:\n\n1. MV/MZ\n2. ACE\n')

    match version:
        case '1':
            # Open File (Threads)
            with ThreadPoolExecutor(max_workers=THREADS) as executor:
                for filename in os.listdir("files"):
                    if filename.endswith('json'):
                        future = executor.submit(handleMVMZ, filename)

                        try:
                            future.result()
                        except Exception as e:
                            print(Fore.RED + str(e))
        
            # This is to encourage people to grab what's in /translated instead
            deleteFolderFiles('files')

            # Prevent immediately closing of CLI
            input('Done! Press Enter to close.')

        case '2':
             # Open File (Threads)
            with ThreadPoolExecutor(max_workers=THREADS) as executor:
                for filename in os.listdir("files"):
                    if filename.endswith('json'):
                        future = executor.submit(handleACE, filename)

                        try:
                            future.result()
                        except Exception as e:
                            print(Fore.RED + str(e))
        
            # This is to encourage people to grab what's in /translated instead
            deleteFolderFiles('files')

            # Prevent immediately closing of CLI
            input('Done! Press Enter to close.')

def deleteFolderFiles(folderPath):
    for filename in os.listdir(folderPath):
        file_path = os.path.join(folderPath, filename)
        if file_path.endswith('.json'):
            os.remove(file_path)   
    
main()
