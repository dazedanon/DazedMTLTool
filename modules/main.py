import sys
import os
import traceback
import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from colorama import Fore
from tqdm import tqdm
from dotenv import load_dotenv

# This needs to be before the module imports as some of them currently try to read and use some of these values
# upon import, in which case if they are unset the script will crash before we can output these messages.
envMissing = False
load_dotenv()
for env in [
    "api",
    "key",
    "model",
    "language",
    "timeout",
    "fileThreads",
    "threads",
    "width",
    "listWidth",
]:
    if os.getenv(env) is None or str(os.getenv(env))[:1] == "<":
        tqdm.write(Fore.RED + f"Environment variable {env} is not set!")
        envMissing = True
if envMissing:
    tqdm.write(
        Fore.RED
        + "Some of the required environment values may not be set correctly. You can set \
these values using an .env file, for an example see .env.example"
    )

from modules.rpgmakermvmz import handleMVMZ, setSpeakerParseMode as setSpeakerParseMVMZ, finalizeSpeakerParse as finalizeSpeakerParseMVMZ
from modules.csv import handleCSV
from modules.tyrano import handleTyrano
from modules.kirikiri import handleKirikiri
from modules.json import handleJSON
from modules.lune import handleLune
from modules.nscript import handleOnscripter
from modules.wolf import handleWOLF
from modules.wolf2 import handleWOLF2
from modules.regex import handleRegex
from modules.text import handleText
from modules.renpy import handleRenpy
from modules.unity import handleUnity
from modules.images import handleImages
from modules.rpgmakerplugin import handlePlugin
from modules.srpg import handleSRPG
from modules.aquedi4 import handleAquedi4

# For GPT4 rate limit will be hit if you have more than 1 thread.
# 1 Thread for each file. Controls how many files are worked on at once.
THREADS = int(os.getenv("fileThreads"))

# [Display name, file extension, handle function]
MODULES = [
    ["RPGMaker MV/MZ", ["json"], handleMVMZ],
    ["RPGMaker Plugins", ["js", "rb"], handlePlugin],
    ["CSV (From Translator++)", ["csv"], handleCSV],
    ["Tyrano", ["ks"], handleTyrano],
    ["Kirikiri", ["ks", "tjs", "ssd", "asd"], handleKirikiri],
    ["JSON", ["json"], handleJSON],
    ["Lune", ["json"], handleLune],
    ["NScript", ["txt"], handleOnscripter],
    ["Wolf", ["json"], handleWOLF],
    ["Wolf", ["txt"], handleWOLF2],
    ["Regex", ["txt", "json", "script", "csv"], handleRegex],
    ["Text", ["txt", "srt"], handleText],
    ["Renpy", ["rpy"], handleRenpy],
    ["Unity", ["txt"], handleUnity],
    ["SRPG Studio", ["json"], handleSRPG],
    ["Images", [""], handleImages],
    ["Aquedi4 Prepared JSON", [".json"], handleAquedi4],
]

# Info Message
tqdm.write(
    Fore.CYAN
    + "-Dazed MTL Tool -"
    + Fore.RESET,
    end="\n\n",
)


def main():
    # Clear the translation cache at the start of the run
    from util.translation import clear_cache
    clear_cache()
    
    estimate = ""
    speaker_parse = False  # Deferred until after engine select
    while estimate == "":
        estimate = input("Select Mode:\n\n 1. Translate\n 2. Estimate\n")
        match estimate:
            case "1":
                estimate = False
            case "2":
                estimate = True
            case _:
                estimate = ""

    version = ""
    while True:
        tqdm.write("Select game engine:\n")
        for position, module in enumerate(MODULES):
            tqdm.write(f"{str(position + 1).rjust(2)}. {module[0]} (.{module[1]})")
        version = input()
        try:
            version = int(version) - 1
        except:
            continue
        if version in range(len(MODULES)):
            break

    totalCost = (
        Fore.RED
        + "Translation module didn't return the total cost. Make sure the \
files to translate are in the /files folder and that you picked the right game engine."
    )

    # If translating RPGMaker MV/MZ, prompt for speaker parse mode
    speaker_parse = False
    if version == 0 and not estimate:
        sub = ""
        while sub == "":
            sub = input("RPGMaker MV/MZ options:\n\n 1. Standard Translate\n 2. Parse Speakers (collect speaker names only)\n")
            match sub:
                case "1":
                    speaker_parse = False
                case "2":
                    speaker_parse = True
                case _:
                    sub = ""
        if speaker_parse:
            setSpeakerParseMVMZ(True)

    # Open File (Threads) - recursively walk 'files' and preserve directory structure
    # Prepare per-run log file so CLI runs also write to a run-specific history file
    try:
        hist_dir = Path("log") / "history"
        hist_dir.mkdir(parents=True, exist_ok=True)
        
        # Clean up old log files, keeping only the 10 most recent
        try:
            log_files = sorted(hist_dir.glob("translationHistory_*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
            # Keep only the 10 most recent, delete the rest
            for old_log in log_files[10:]:
                try:
                    old_log.unlink()
                except Exception:
                    pass
        except Exception:
            pass
        
        fname = datetime.datetime.now().strftime("translationHistory_%Y%m%d_%H%M%S.txt")
        run_log_path = hist_dir / fname
        # Don't create the file yet - it will be created when first log is written
        # Store the path in environment variable
        try:
            os.environ['TRANSLATION_RUN_LOG'] = str(run_log_path)
        except Exception:
            pass

        # Try to create a hard link from legacy path to this run file for compatibility
        # This will be created when the run_log_path file is first written to
        legacy = Path("log") / "translationHistory.txt"
        try:
            if legacy.exists():
                try:
                    legacy.unlink()
                except Exception:
                    pass
        except Exception:
            pass
    except Exception:
        pass
    
    # Use single worker for estimate mode to prevent race conditions
    max_workers = 1 if estimate else THREADS
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        files_root = "files"

        # Special-case: Images engine expects a folder, not a file; schedule per directory containing assets
        if MODULES[version][0] == "Images":
            for root, dirs, filenames in os.walk(files_root):
                # Skip hidden/system directories
                dirs[:] = [d for d in dirs if d not in {".git", "__pycache__"}]

                # Skip the root 'files' itself to avoid processing everything twice
                # We'll still allow scheduling for root if it contains assets

                # Only schedule directories that contain potential assets
                has_assets = any(fn.lower().endswith((".png", ".txt")) for fn in filenames)
                if not has_assets:
                    continue

                # Compute relative directory path and ensure translated mirror exists
                rel_dir = os.path.relpath(root, files_root).replace(os.sep, "/")
                if rel_dir == ".":
                    # Represent root as empty string so handler creates files under translated/ directly
                    rel_dir = ""
                try:
                    target_dir = os.path.join("translated", rel_dir.replace("/", os.sep)) if rel_dir else "translated"
                    os.makedirs(target_dir, exist_ok=True)
                except Exception:
                    pass

                futures.append(
                    executor.submit(MODULES[version][2], rel_dir, estimate)
                )
        else:
            # Gather all candidate files recursively
            for root, dirs, filenames in os.walk(files_root):
                # Skip hidden/system directories if any
                dirs[:] = [d for d in dirs if d not in {".git", "__pycache__"}]

                for fname in filenames:
                    if fname == ".gitkeep":
                        continue

                    abs_path = os.path.join(root, fname)
                    # Build relative path from 'files' root using POSIX-style separators so handlers can do 'files/' + rel
                    rel_path = os.path.relpath(abs_path, files_root)
                    rel_path_posix = rel_path.replace(os.sep, "/")

                    # Check extension match for the selected module version
                    for m in MODULES[version][1]:
                        if rel_path_posix.endswith(m):
                            # Ensure the corresponding directory exists under 'translated'
                            rel_dir = os.path.dirname(rel_path_posix)
                            if rel_dir:
                                try:
                                    os.makedirs(os.path.join("translated", rel_dir.replace("/", os.sep)), exist_ok=True)
                                except Exception:
                                    # Best-effort; handler may attempt write and fail if permissions are insufficient
                                    pass

                            futures.append(
                                executor.submit(MODULES[version][2], rel_path_posix, estimate)
                            )
                            break  # Avoid double-adding if multiple ext entries match

        for future in as_completed(futures):
            try:
                totalCost = future.result()
            except Exception as e:
                tracebackLineNo = str(traceback.extract_tb(sys.exc_info()[2])[-1].lineno)
                tqdm.write(Fore.RED + str(e) + "|" + tracebackLineNo + Fore.RESET)

    # Finalize speaker parse mode by writing collected speakers to vocab
    if speaker_parse:
        finalizeSpeakerParseMVMZ()

    # Delete Tmp Files
    if os.path.isfile("csv.tmp"):
        os.remove("csv.tmp")

    # Sweep any leftover temp files in translated/
    try:
        translated_dir = os.path.join("translated")
        if os.path.isdir(translated_dir):
            for fname in os.listdir(translated_dir):
                if fname.endswith(".tmp"):
                    fpath = os.path.join(translated_dir, fname)
                    try:
                        os.remove(fpath)
                    except Exception:
                        # Best-effort cleanup; ignore files locked by other processes
                        pass
    except Exception:
        pass

    # Finish
    if totalCost != "Fail":
        # if estimate is False:
        # This is to encourage people to grab what's in /translated instead
        # deleteFolderFiles("files")

        tqdm.write(str(totalCost))


def deleteFolderFiles(folderPath):
    for filename in os.listdir(folderPath):
        file_path = os.path.join(folderPath, filename)
        if file_path.endswith((".json", ".ks")):
            os.remove(file_path)