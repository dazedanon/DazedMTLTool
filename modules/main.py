import sys
import os
import time
import traceback
import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from colorama import Fore
from tqdm import tqdm
from dotenv import load_dotenv

# This needs to be before the module imports as some of them currently try to read and use some of these values
# upon import, in which case if they are unset the script will crash before we can output these messages.
load_dotenv()
from util.paths import migrate_root_data_files

migrate_root_data_files()
_missing_envs = [
    env for env in [
        "api",
        "key",
        "model",
        "language",
        "timeout",
        "fileThreads",
        "threads",
        "width",
        "listWidth",
    ]
    if os.getenv(env) is None or str(os.getenv(env))[:1] == "<"
]
if _missing_envs:
    names = ", ".join(_missing_envs)
    tqdm.write(
        Fore.RED
        + f"Missing required environment variable(s): {names}. "
        + "Set them in a .env file (see .env.example)."
    )

from modules.rpgmakermvmz import handleMVMZ, setSpeakerParseMode as setSpeakerParseMVMZ, finalizeSpeakerParse as finalizeSpeakerParseMVMZ
from modules.csv import handleCSV
from modules.tyrano import handleTyrano
from modules.kirikiri import handleKirikiri
from modules.json import handleJSON
from modules.lune import handleLune
from modules.yuris import handleYuris
from modules.nscript import handleOnscripter
from modules.wolf import handleWOLF
from modules.wolf2 import handleWOLF2
from modules.wolfdawn import handleWolfDawn
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
    ["Yuris", ["json"], handleYuris],
    ["NScript", ["txt"], handleOnscripter],
    ["Wolf RPG (WolfDawn)", ["json"], handleWolfDawn],
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
    from util.translation import clear_cache

    estimate = ""
    batch_mode = False
    speaker_parse = False  # Deferred until after engine select
    while estimate == "":
        estimate = input("Select Mode:\n\n 1. Translate\n 2. Estimate\n 3. Batch Translate (Anthropic Batches API, 50% off)\n")
        match estimate:
            case "1":
                estimate = False
            case "2":
                estimate = True
            case "3":
                estimate = False
                batch_mode = True
            case _:
                estimate = ""

    resume_state = None
    if batch_mode:
        from util.translation import isClaudeNative, batchRunState
        if not isClaudeNative(os.getenv("model", "")):
            tqdm.write(
                Fore.RED
                + "Batch Translate requires a Claude model with the 'api' env var unset or pointing at anthropic.com."
                + Fore.RESET
            )
            return
        # An interrupted batch run can be resumed instead of re-collecting
        # (a second submission would be billed again).
        resume_state = batchRunState()
        if resume_state:
            confirm = ""
            while confirm not in ("y", "n"):
                if resume_state == "queued":
                    prompt = (
                        "A previous collect finished but was not submitted (queued). "
                        "Resume and submit that queue? (y/n)\n"
                        "(n discards the queue and re-collects - live collect charges again)\n"
                    )
                else:
                    prompt = (
                        f"A previous batch run was interrupted ({resume_state}). Resume it? (y/n)\n"
                        "(n discards it and can bill again)\n"
                    )
                confirm = input(prompt).strip().lower()
            if confirm == "n":
                resume_state = None

    # Clear the translation cache at the start of the run. Kept when resuming a
    # batch so names translated during collect stay consistent with the queued
    # payloads in the consume pass.
    if not resume_state:
        clear_cache()

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
    if version == 0 and not estimate and not batch_mode:
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
    
    def runFiles(estimate):
        runCost = totalCost
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
                    runCost = future.result()
                except Exception as e:
                    tracebackLineNo = str(traceback.extract_tb(sys.exc_info()[2])[-1].lineno)
                    tqdm.write(Fore.RED + str(e) + "|" + tracebackLineNo + Fore.RESET)
        return runCost

    if batch_mode:
        from util.translation import (
            set_batch_phase,
            clearBatchFiles,
            pendingBatchRequests,
            estimateBatchCost,
            runTranslationBatches,
        )
        poll = int(os.getenv("batchPollInterval", "60") or 60)
        run_consume = True

        if resume_state is None:
            clearBatchFiles()

            # Pass 1 — queue dialogue for the batch. Unresolved dynamic speakers
            # are deferred until consume; some other short variables may still be live.
            tqdm.write(Fore.CYAN + "[BATCH] Pass 1/2: collecting requests..." + Fore.RESET)
            tqdm.write(
                Fore.YELLOW
                + "[BATCH] Note: unresolved dynamic speakers are deferred until after "
                "submission approval; some other short variables may still translate live."
                + Fore.RESET
            )
            set_batch_phase("collect")
            try:
                totalCost = runFiles(False)
            finally:
                set_batch_phase(None)

            if pendingBatchRequests() == 0:
                tqdm.write("[BATCH] No requests queued — nothing needed the API.")
                run_consume = False
            else:
                est = estimateBatchCost()
                confirm = ""
                while confirm not in ("y", "n"):
                    confirm = input("Submit batch? (y/n)\n").strip().lower()
                if confirm == "n":
                    tqdm.write(
                        "[BATCH] Not submitted. The queue is kept in log/batch_requests.json "
                        "(resume Batch Translate later to submit without re-collecting)."
                    )
                    return
                from util.translation import submitTranslationBatches, checkTranslationBatches, fetchTranslationBatches
                if not submitTranslationBatches(cost_estimate=est):
                    run_consume = False
                else:
                    tqdm.write(
                        f"[BATCH] polling every {poll}s (Ctrl-C is safe - resume later)..."
                    )
                    while not checkTranslationBatches():
                        time.sleep(poll)
                    fetchTranslationBatches()
        elif resume_state == "queued":
            tqdm.write(
                Fore.CYAN
                + "[BATCH] Resuming queued requests (skipping re-collect)..."
                + Fore.RESET
            )
            if pendingBatchRequests() == 0:
                tqdm.write("[BATCH] Queue is empty - nothing to submit.")
                run_consume = False
            else:
                est = estimateBatchCost()
                confirm = ""
                while confirm not in ("y", "n"):
                    confirm = input("Submit batch? (y/n)\n").strip().lower()
                if confirm == "n":
                    tqdm.write("[BATCH] Not submitted. Queue kept.")
                    return
                from util.translation import submitTranslationBatches, checkTranslationBatches, fetchTranslationBatches
                if not submitTranslationBatches(cost_estimate=est):
                    run_consume = False
                else:
                    tqdm.write(
                        f"[BATCH] polling every {poll}s (Ctrl-C is safe - resume later)..."
                    )
                    while not checkTranslationBatches():
                        time.sleep(poll)
                    fetchTranslationBatches()
        elif resume_state == "submitted":
            tqdm.write(Fore.CYAN + "[BATCH] Resuming the submitted batch..." + Fore.RESET)
            runTranslationBatches(poll)
        else:  # "fetched" - results already downloaded, just write the files
            tqdm.write(Fore.CYAN + "[BATCH] Resuming from fetched results..." + Fore.RESET)

        if run_consume:
            try:
                from util.batch_history import missing_result_count
                present, expected = missing_result_count()
                if expected and present < expected:
                    tqdm.write(
                        Fore.YELLOW
                        + f"[BATCH] WARNING: only {present}/{expected} results present. "
                        "Missing keys fall back to the live API (full price)."
                        + Fore.RESET
                    )
            except Exception:
                pass
            # Pass 2 — write the translated files from the fetched results.
            # Anything the batch missed falls back to the live API.
            tqdm.write(Fore.CYAN + "[BATCH] Pass 2/2: writing translated files..." + Fore.RESET)
            set_batch_phase("consume")
            try:
                totalCost = runFiles(False)
            finally:
                set_batch_phase(None)
            if totalCost != "Fail":
                clearBatchFiles()
    else:
        totalCost = runFiles(estimate)

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
