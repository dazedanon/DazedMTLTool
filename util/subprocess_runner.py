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
    # The job workspace may be separate from the installed engine code.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
        
        # Share the same exact engine registry as both interfaces.
        from util.translation_task import translation_module

        handler = translation_module(module_name)[2]

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

        filenames = list(filename) if isinstance(filename, (list, tuple)) else [filename]
        multi_file = isinstance(filename, (list, tuple))

        # A persistent RPG Maker batch worker holds these scopes across every
        # file in the phase. Consume loads fetched results/cache once; collect
        # collect/estimate snapshot cache reads and coalesce durable queue fragments.
        cache_scope = nullcontext()
        queue_scope = nullcontext()
        batch_phase = os.getenv("BATCH_PHASE", "").strip().lower()
        if batch_phase == "consume":
            from util.translation import deferred_translation_cache_writes

            cache_scope = deferred_translation_cache_writes()
        elif batch_phase in {"collect", "estimate"}:
            from util.translation import (
                batch_collect_snapshot_reads,
                buffered_batch_queue_writes,
            )

            cache_scope = batch_collect_snapshot_reads()
            if "RPG Maker MV/MZ" in module_name:
                queue_scope = buffered_batch_queue_writes()

        # Multi-file mode reports an isolated result marker after each file so
        # the GUI retains per-file completion, mismatch, and error behavior.
        handler_result = None
        with cache_scope, queue_scope:
            rpgmakermvmz = None
            try:
                if "RPG Maker MV/MZ" in module_name:
                    from modules import rpgmakermvmz

                    if multi_file and batch_phase in {
                        "collect", "estimate", "consume"
                    }:
                        rpgmakermvmz.configureBatchMapNames(filenames)

                for current_filename in filenames:
                    try:
                        if rpgmakermvmz is not None:
                            # Separate subprocesses used to provide fresh totals for
                            # every file. Preserve that behavior in a reused worker.
                            rpgmakermvmz.TOKENS[:] = [0, 0]
                            rpgmakermvmz.TIMETOTAL = 0
                        handler_result = handler(current_filename, estimate_only)
                        if multi_file:
                            mismatch_count = 0
                            if rpgmakermvmz is not None:
                                mismatch_count = len(rpgmakermvmz.MISMATCH)
                            print(
                                "FILE_RESULT:"
                                + json.dumps(
                                    {
                                        "filename": current_filename,
                                        "result": handler_result or "Fail",
                                        "mismatch_count": mismatch_count,
                                    },
                                    ensure_ascii=False,
                                ),
                                flush=True,
                            )
                    except Exception as exc:
                        if multi_file:
                            print(
                                "FILE_ERROR:"
                                + json.dumps(
                                    {
                                        "filename": current_filename,
                                        "error": str(exc),
                                    },
                                    ensure_ascii=False,
                                ),
                                flush=True,
                            )
                        raise
            finally:
                if rpgmakermvmz is not None:
                    rpgmakermvmz.resetBatchMapNames()
        
        # Stop progress monitoring
        progress_active = False
        # Wake monitor thread if it's waiting so it can exit promptly
        try:
            progress_event.set()
        except Exception:
            pass
        
        # Print the result
        if multi_file:
            print("RESULT:Success", flush=True)
        elif handler_result:
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
    if filename == "--files-from-stdin":
        filename = json.load(sys.stdin)
        if not isinstance(filename, list) or not filename or not all(
            isinstance(item, str) and item for item in filename
        ):
            print("ERROR:Invalid multi-file input")
            sys.exit(1)
    estimate_only = sys.argv[4].lower() == 'true'
    
    run_handler(project_root, module_name, filename, estimate_only)
