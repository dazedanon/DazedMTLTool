"""
Subprocess runner for translation modules.
This script runs in a separate process to execute translation modules
and reports progress back to the GUI.
"""

import sys
import os
from pathlib import Path
import io
import threading
from dotenv import load_dotenv

# Load environment variables from .env with override=True to ensure
# we always use the latest saved config, not inherited/stale values
load_dotenv(override=True)

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
    
    # Start progress monitoring thread
    monitor_thread = threading.Thread(target=monitor_progress, daemon=True)
    monitor_thread.start()
    
    try:
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
        elif "NScript" in module_name:
            from modules.nscript import handleOnscripter
            handler = handleOnscripter
        elif "Wolf RPG 2" in module_name:
            from modules.wolf2 import handleWOLF2
            handler = handleWOLF2
        elif "Wolf RPG" in module_name:
            from modules.wolf import handleWOLF
            handler = handleWOLF
        elif "Regex" in module_name:
            from modules.regex import handleRegex
            handler = handleRegex
        elif "Text" in module_name:
            from modules.text import handleText
            handler = handleText
        elif "RenPy" in module_name:
            from modules.renpy import handleRenpy
            handler = handleRenpy
        elif "Unity" in module_name:
            from modules.unity import handleUnity
            handler = handleUnity
        elif "Images" in module_name:
            from modules.images import handleImages
            handler = handleImages
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
        
        # Run the handler
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
