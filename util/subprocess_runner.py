"""
Subprocess runner for translation modules.
This script runs in a separate process to execute translation modules
and reports progress back to the GUI.
"""

import sys
import os
from pathlib import Path
import io
import json
import threading
from contextlib import nullcontext

# Set UTF-8 encoding for stdout to handle Unicode characters
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Progress monitoring thread
progress_active = True
last_reported = {'state': None}
progress_event = threading.Event()


def monitor_progress():
    """Monitor module PBAR and report progress."""
    global progress_active
    while progress_active:
        try:
            # Try to get PBAR from any loaded module
            for module_name in list(sys.modules.keys()):
                if module_name.startswith('modules.'):
                    module = sys.modules[module_name]
                    if hasattr(module, 'PBAR') and module.PBAR is not None:
                        pbar = module.PBAR
                        desc = getattr(pbar, 'desc', '') or ''
                        n = getattr(pbar, 'n', 0)
                        total = getattr(pbar, 'total', 0)
                        
                        current_state = (desc, n, total)
                        if current_state != last_reported['state']:
                            print(f"PROGRESS:{desc}:{n}:{total}", flush=True)
                            last_reported['state'] = current_state
                        break
        except Exception:
            pass
        # Wait with timeout so we don't busy-wait. Using an Event allows
        # the main thread to wake this monitor immediately when stopping
        # instead of waiting for the full timeout.
        progress_event.wait(0.1)


def run_handler(project_root, module_name, filename, estimate_only):
    """Run a translation module handler."""
    global progress_active
    
    # Add project root to path
    project_root = Path(project_root)
    sys.path.insert(0, str(project_root))

    try:
        # Refresh global config first, then restore the active game's portable
        # widths before importing any engine-level constants.
        from util.game_settings import load_translation_runtime_environment

        load_translation_runtime_environment(project_root / ".env")

        # Start progress monitoring only after environment preparation succeeds.
        monitor_thread = threading.Thread(target=monitor_progress, daemon=True)
        monitor_thread.start()

        # Change to project directory
        os.chdir(str(project_root))
        
        # Import the appropriate module and get handler
        handler = None
        if "RPG Maker MV/MZ" in module_name:
            from modules.rpgmakermvmz import handleMVMZ
            handler = handleMVMZ
        elif "CSV" in module_name:
            from modules.csv import handleCSV
            handler = handleCSV
        elif "Tyrano" in module_name:
            from modules.tyrano import handleTyrano
            handler = handleTyrano
        elif "Kirikiri" in module_name:
            from modules.kirikiri import handleKirikiri
            handler = handleKirikiri
        elif "JSON" in module_name:
            from modules.json import handleJSON
            handler = handleJSON
        elif "Lune" in module_name:
            from modules.lune import handleLune
            handler = handleLune
        elif "Yuris" in module_name:
            from modules.yuris import handleYuris
            handler = handleYuris
        elif "NScript" in module_name:
            from modules.nscript import handleOnscripter
            handler = handleOnscripter
        elif "WolfDawn" in module_name:
            from modules.wolfdawn import handleWolfDawn
            handler = handleWolfDawn
        elif "Wolf RPG 2" in module_name:
            from modules.wolf2 import handleWOLF2
            handler = handleWOLF2
        elif "Wolf RPG" in module_name:
            from modules.wolf import handleWOLF
            handler = handleWOLF
        elif "Regex" in module_name:
            from modules.regex import handleRegex
            handler = handleRegex
        # Must stay above the "Text" branch: this chain matches on substrings,
        # and "Text" is inside "Image Text". Below it, image_text.json would be
        # handed to the plain-text engine, which translates a JSON file line by
        # line and destroys it.
        elif "Image Text" in module_name:
            from modules.imagetext import handleImageText
            handler = handleImageText
        elif "Text" in module_name:
            from modules.text import handleText
            handler = handleText
        elif "RenPy" in module_name:
            from modules.renpy import handleRenpy
            handler = handleRenpy
        elif "Unity" in module_name:
            from modules.unity import handleUnity
            handler = handleUnity
        elif "Plugin" in module_name:
            from modules.rpgmakerplugin import handlePlugin
            handler = handlePlugin
        elif "Aquedi4" in module_name:
            from modules.aquedi4 import handleAquedi4
            handler = handleAquedi4
        elif "SRPG" in module_name:
            from modules.srpg import handleSRPG
            handler = handleSRPG
        else:
            print(f"ERROR:Unknown module: {module_name}")
            sys.exit(1)

        runtime_profile_json = os.getenv("DAZED_BATCH_RUNTIME_PROFILE", "").strip()
        if runtime_profile_json:
            if "RPG Maker MV/MZ" not in module_name:
                raise ValueError(
                    "A batch runtime profile was supplied for the wrong translation module"
                )
            from modules import rpgmakermvmz
            from util.runtime_profile import apply_batch_runtime_profile

            apply_batch_runtime_profile(
                rpgmakermvmz,
                json.loads(runtime_profile_json),
            )

        # A consume pass only applies already-fetched results. Buffer translation
        # cache mutations for this file and commit them once when the handler
        # exits instead of rewriting the complete cache for every result.
        cache_scope = nullcontext()
        if os.getenv("BATCH_PHASE", "").strip().lower() == "consume":
            from util.translation import deferred_translation_cache_writes

            cache_scope = deferred_translation_cache_writes()

        # Run the handler
        with cache_scope:
            handler_result = handler(filename, estimate_only)
        
        # Stop progress monitoring
        progress_active = False
        # Wake monitor thread if it's waiting so it can exit promptly
        try:
            progress_event.set()
        except Exception:
            pass
        
        # Print the result
        if handler_result:
            print(f"RESULT:{handler_result}")
        else:
            print("RESULT:Fail")
        
    except Exception as e:
        progress_active = False
        # Wake monitor thread if it's waiting so it can exit promptly
        try:
            progress_event.set()
        except Exception:
            pass
        import traceback
        error_msg = str(e).encode('ascii', 'ignore').decode('ascii')
        print(f"ERROR:{error_msg}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print("ERROR:Invalid arguments")
        sys.exit(1)
    
    project_root = sys.argv[1]
    module_name = sys.argv[2]
    filename = sys.argv[3]
    estimate_only = sys.argv[4].lower() == 'true'
    
    run_handler(project_root, module_name, filename, estimate_only)
