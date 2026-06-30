#!/usr/bin/env python3
"""
Simple Translation Tab for DazedMTLTool GUI

Simple file management and translation execution with console log display.
"""

import os
import datetime
import subprocess
import threading
import sys
import io
import time
from contextlib import redirect_stdout
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
import traceback
import signal
import multiprocessing
import re
from colorama import Fore
from tqdm import tqdm
from dotenv import load_dotenv
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGroupBox,
    QTextEdit, QMessageBox, QListWidget, QListWidgetItem, 
    QSplitter, QFileDialog, QComboBox, QCheckBox, QProgressBar, QFrame, QFormLayout, QStackedWidget
)
from PyQt5.QtWidgets import QSizePolicy
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread, QMutex, QProcess, QEvent, QRect, QSettings
from PyQt5.QtGui import QFont
from gui.log_viewer import LogViewer
from gui.platform_glyph import platform_glyph


def _strip_ansi(text):
    if not isinstance(text, str) or not text:
        return text
    return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)


def create_section_header(title):
    """Create a clean section header without boxes."""
    label = QLabel(platform_glyph(title))
    label.setStyleSheet("""
        QLabel {
            font-size: 13px;
            font-weight: bold;
            color: #007acc;
            padding: 8px 0px 5px 0px;
            background-color: transparent;
        }
    """)
    return label

def create_horizontal_line():
    """Create a horizontal separator line."""
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setFrameShadow(QFrame.Sunken)
    line.setStyleSheet("QFrame { color: #555555; margin: 5px 0px; }")
    return line


BATCH_MODE_LABEL = "Batch Translate"
BATCH_MODE_BENEFIT_NOTE = (
    "Anthropic Batches API — 50% or more cheaper than live translate (Claude only)."
)
BATCH_COLLECT_LIVE_CHARGE_NOTE = (
    "During Pass 1, speaker names and similar short strings are translated at live "
    "API rates right away (not batched). Dialogue is queued for the batch and billed "
    "only after you confirm the estimate."
)


class TranslationWorker(QThread):
    """Worker thread for running translations without blocking the UI."""
    
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int, str)  # current_file, total_files, filename
    item_progress_signal = pyqtSignal(str, int, int)  # filename, current_item, total_items (for tqdm within file)
    file_error_signal = pyqtSignal(str, str)  # filename, error_message
    finished_signal = pyqtSignal(bool, str)
    batch_phase_signal = pyqtSignal(str, object)  # phase name, optional payload
    
    def __init__(self, project_root, module_info, estimate_only=False, selected_files=None,
                 parse_speakers=False, batch_mode=False, batch_resume_state=None):
        super().__init__()
        self.project_root = project_root
        self.module_info = module_info  # [name, extensions, handler_function]
        self.estimate_only = estimate_only
        self.selected_files = selected_files  # List of files to process
        # Whether we should run in speaker-parse mode (special-case for MV/MZ)
        self.parse_speakers = parse_speakers
        self.batch_mode = batch_mode
        self.batch_resume_state = batch_resume_state
        self._batch_submit_event = threading.Event()
        self._batch_submit_approved = False
        self.should_stop = False
        self.mutex = QMutex()  # For thread safety
        self.executor = None  # Store reference to executor for proper shutdown
        self.running_processes = []  # Track running processes for termination

    def set_batch_submit_response(self, approved):
        """Called from the UI thread after the submit-batch confirmation dialog."""
        self._batch_submit_approved = approved
        self._batch_submit_event.set()

    def _wait_batch_submit(self, estimate):
        self._batch_submit_event.clear()
        self.batch_phase_signal.emit("submit", estimate)
        self._batch_submit_event.wait()
        return self._batch_submit_approved

    def _emit_batch_phase(self, phase, payload=None):
        self.batch_phase_signal.emit(phase, payload)

    def _emit_batch_output(self, fn, *args, **kwargs):
        """Run a batch helper that prints status lines; forward them to the log."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = fn(*args, **kwargs)
        for line in buf.getvalue().splitlines():
            if line.strip():
                self.emit_log(line)
        return result

    def _run_batch_poll_fetch(self):
        """Submit (if needed), poll until ended, fetch results. None if stopped while polling."""
        from util.translation import (
            submitTranslationBatches,
            checkTranslationBatches,
            fetchTranslationBatches,
            _read_batch_file,
            BATCH_STATE_FILE,
            _batch_file_lock,
        )

        with _batch_file_lock():
            state = _read_batch_file(BATCH_STATE_FILE)
        if not state.get("batches"):
            if not self._emit_batch_output(submitTranslationBatches):
                return 0, 0

        poll = int(os.getenv("batchPollInterval", "60") or 60)
        self._emit_batch_phase("polling")
        self.emit_log(
            f"[BATCH] polling every {poll}s (stop is safe — resume later with Batch Translate mode)..."
        )
        while True:
            if self.should_stop:
                self.emit_log("[BATCH] Stopped while polling. Batch keeps processing — resume later.")
                return None
            buf = io.StringIO()
            with redirect_stdout(buf):
                ended = checkTranslationBatches()
            for line in buf.getvalue().splitlines():
                if line.strip():
                    self.emit_log(line)
                    self._emit_batch_phase("poll_status", line.strip())
            if ended:
                break
            for _ in range(poll * 10):
                if self.should_stop:
                    self.emit_log("[BATCH] Stopped while polling. Batch keeps processing — resume later.")
                    return None
                time.sleep(0.1)

        fetched, errored = self._emit_batch_output(fetchTranslationBatches)
        return fetched, errored
        
    def stop(self):
        """Stop the translation process."""
        self.mutex.lock()
        try:
            if self.should_stop:
                # Already stopping, don't log again
                return
                
            self.should_stop = True
            self.emit_log("🛑 Stopping translation worker and canceling pending tasks...")
            
            # Shutdown the executor if it exists
            if self.executor:
                # For older Python versions compatibility, use shutdown(wait=False)
                # and manually cancel futures
                try:
                    # Try to use cancel_futures parameter (Python 3.9+)
                    self.executor.shutdown(wait=False, cancel_futures=True)
                except TypeError:
                    # Fallback for older Python versions
                    self.executor.shutdown(wait=False)
            
            # Terminate any running processes
            if self.running_processes:
                self.emit_log("🛑 Terminating running translation processes...")
                for process in self.running_processes:
                    try:
                        if process.poll() is None:  # Process is still running
                            process.terminate()
                            # Give it a moment to terminate gracefully
                            try:
                                process.wait(timeout=2)
                            except subprocess.TimeoutExpired:
                                # Force kill if it doesn't terminate
                                process.kill()
                                process.wait()
                    except Exception as e:
                        self.emit_log(f"⚠️ Warning: Could not terminate process: {e}")
                self.running_processes.clear()
        finally:
            self.mutex.unlock()
        
    def emit_log(self, message):
        """Thread-safe log emission."""
        self.log_signal.emit(message)
        
    def emit_progress(self, current, total, filename):
        """Thread-safe progress emission."""
        self.progress_signal.emit(current, total, filename)
        
    def run_module_in_process(self, filename, estimate_only, batch_phase=None):
        """Run a module handler in a separate process for better control."""
        try:
            # Use the external subprocess runner script
            runner_script = self.project_root / "util" / "subprocess_runner.py"
            if not runner_script.exists():
                self.emit_log(f"❌ Subprocess runner script not found: {runner_script}")
                return "Fail"
            
            # Run the script in a separate process
            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'  # Force UTF-8 encoding
            if batch_phase in ("collect", "consume"):
                env["BATCH_PHASE"] = batch_phase
            else:
                env.pop("BATCH_PHASE", None)
            
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(runner_script),
                    str(self.project_root),
                    self.module_info[0],  # module name
                    filename,
                    str(estimate_only)
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
                cwd=str(self.project_root),
                env=env,
                bufsize=1  # Line buffered
            )
            
            # Track the process for potential termination
            self.running_processes.append(process)
            
            # Read output in real-time to capture progress
            stdout_lines = []
            stderr_lines = []
            
            def read_stdout():
                """Read stdout line by line."""
                for line in iter(process.stdout.readline, ''):
                    if not line:
                        break
                    line = line.strip()
                    if line.startswith('PROGRESS:'):
                        # Parse progress: PROGRESS:filename:current:total
                        try:
                            parts = line.split(':', 3)
                            if len(parts) == 4:
                                _, desc, current, total = parts
                                # Emit with filename included
                                self.item_progress_signal.emit(desc, int(current), int(total))
                        except Exception:
                            pass  # Ignore malformed progress lines
                    else:
                        stdout_lines.append(line)
                process.stdout.close()
            
            def read_stderr():
                """Read stderr line by line."""
                for line in iter(process.stderr.readline, ''):
                    if not line:
                        break
                    stderr_lines.append(line.strip())
                process.stderr.close()
            
            # Start reader threads
            stdout_thread = threading.Thread(target=read_stdout, daemon=True)
            stderr_thread = threading.Thread(target=read_stderr, daemon=True)
            stdout_thread.start()
            stderr_thread.start()
            
            # Wait for process completion
            process.wait()
            
            # Wait for reader threads to finish
            stdout_thread.join(timeout=1.0)
            stderr_thread.join(timeout=1.0)
            
            # Combine output
            stdout = '\n'.join(stdout_lines)
            stderr = '\n'.join(stderr_lines)
            
            # Remove from tracking
            if process in self.running_processes:
                self.running_processes.remove(process)
            
            # Check if process was terminated by stop signal
            if self.should_stop:
                return "Stopped"
            
            # Forward all stdout output to log (this includes cost information)
            for line in stdout.strip().split('\n'):
                if line.strip() and not line.startswith('RESULT:'):
                    self.emit_log(line)
            
            # Parse result
            if process.returncode == 0:
                for line in stdout.strip().split('\n'):
                    if line.startswith('RESULT:'):
                        result_text = line[7:]  # Remove 'RESULT:' prefix
                        # Clean up any Unicode issues in the result
                        try:
                            return result_text
                        except UnicodeError:
                            return result_text.encode('ascii', 'ignore').decode('ascii')
                return "Success"
            else:
                # Extract error message from stderr
                error_msg = stderr.strip() if stderr.strip() else "Unknown error"
                # Handle potential Unicode errors in error messages
                try:
                    clean_error = error_msg.encode('ascii', 'ignore').decode('ascii')
                except:
                    clean_error = "Unicode encoding error in process output"
                
                # Check if stderr contains the actual exception message
                # Format from subprocess_runner.py: "ERROR:actual error message"
                actual_error = clean_error
                for line in clean_error.split('\n'):
                    if line.startswith('ERROR:'):
                        actual_error = line[6:]  # Remove 'ERROR:' prefix
                        break
                    # Check for exception lines in traceback
                    if 'NameError:' in line or 'Error:' in line:
                        # Extract just the error message part
                        if ':' in line:
                            actual_error = line.split(':', 1)[1].strip()
                            break
                
                self.emit_log(f"❌ Process error: {actual_error}")
                # Return the actual error so it can be used to determine if file is unsupported
                return ("SUBPROCESS_ERROR", actual_error)
                
        except Exception as e:
            self.emit_log(f"❌ Failed to run module process: {str(e)}")
            return "Fail"

    def _run_files(self, matching_files, estimate_only, batch_phase=None):
        """Process matching files; return last cost string or 'Fail'."""
        threads = int(os.getenv("fileThreads", "1"))
        total_cost = "Fail"
        module_name_lower = self.module_info[0].lower() if isinstance(self.module_info[0], str) else ""
        is_mvmz = "mv/mz" in module_name_lower

        if self.parse_speakers and is_mvmz:
            try:
                from modules.rpgmakermvmz import (
                    handleMVMZ as handler, setSpeakerParseMode, finalizeSpeakerParse,
                    resetSpeakerState, TOKENS, calculateCost, MODEL,
                )
            except Exception as e:
                self.emit_log(f"❌ Could not import rpgmakermvmz for speaker-parse: {e}")
                return "Fail"

            try:
                resetSpeakerState()
            except Exception:
                pass
            try:
                setSpeakerParseMode(True)
            except Exception:
                pass

            completed_count = 0
            total_files = len(matching_files)
            for filename in matching_files:
                if self.should_stop:
                    break
                try:
                    handler(filename, estimate_only)
                    completed_count += 1
                    self.emit_progress(completed_count, total_files, filename)
                except Exception as e:
                    tb_line = str(traceback.extract_tb(sys.exc_info()[2])[-1].lineno)
                    self.emit_log(f"❌ Error processing {filename}: {str(e)} | Line: {tb_line}")
                    self.file_error_signal.emit(filename, str(e))
                    completed_count += 1
                    self.emit_progress(completed_count, total_files, filename)

            try:
                before_in, before_out = (0, 0)
                try:
                    before_in, before_out = (int(TOKENS[0]), int(TOKENS[1]))
                except Exception:
                    pass
                finalizeSpeakerParse()
                after_in, after_out = (0, 0)
                try:
                    after_in, after_out = (int(TOKENS[0]), int(TOKENS[1]))
                except Exception:
                    pass
                delta_in = max(0, after_in - before_in)
                delta_out = max(0, after_out - before_out)
                if delta_in or delta_out:
                    try:
                        cost = calculateCost(delta_in, delta_out, MODEL)
                        self.emit_log(f"Speakers: [Input: {delta_in}][Output: {delta_out}][Cost: ${cost:.4f}] ✓")
                    except Exception:
                        pass
            except Exception as e:
                self.emit_log(f"❌ Failed to finalize speaker parse: {e}")

            try:
                setSpeakerParseMode(False)
            except Exception:
                pass
            return "Success"

        max_workers = 1 if estimate_only else threads
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        future_to_filename = {
            self.executor.submit(
                self.run_module_in_process, filename, estimate_only, batch_phase
            ): filename
            for filename in matching_files
        }

        completed_count = 0
        total_files = len(matching_files)
        for future in as_completed(future_to_filename):
            if self.should_stop:
                for remaining_future in future_to_filename:
                    if not remaining_future.done():
                        remaining_future.cancel()
                break

            filename = future_to_filename[future]
            completed_count += 1
            self.emit_progress(completed_count, total_files, filename)

            try:
                result = future.result()
                if isinstance(result, tuple) and len(result) == 2 and result[0] == "SUBPROCESS_ERROR":
                    self.file_error_signal.emit(filename, result[1])
                elif result and result not in ("Fail", "Stopped"):
                    total_cost = result
                elif result == "Stopped":
                    break
                else:
                    self.emit_log(f"❌ Failed processing {filename}")
                    self.file_error_signal.emit(filename, "Translation failed")
            except Exception as e:
                tb_line = str(traceback.extract_tb(sys.exc_info()[2])[-1].lineno)
                self.emit_log(f"❌ Error processing {filename}: {str(e)} | Line: {tb_line}")
                self.file_error_signal.emit(filename, str(e))

        if self.executor:
            try:
                self.executor.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                self.executor.shutdown(wait=False)
            self.executor = None

        return total_cost
        
    def run(self):
        """Run the translation process."""
        try:
            load_dotenv()
            sys.path.insert(0, str(self.project_root))

            from util.translation import clear_cache

            if not (self.batch_mode and self.batch_resume_state):
                clear_cache()

            required_envs = ["api", "key", "model", "language", "timeout", "fileThreads", "threads", "width", "listWidth"]
            missing_envs = [
                env for env in required_envs
                if os.getenv(env) is None or str(os.getenv(env))[:1] == "<"
            ]
            if missing_envs:
                names = ", ".join(missing_envs)
                self.emit_log(f"❌ Missing required environment variable(s): {names}")
                self.emit_log("   Check your .env file (see .env.example).")
                self.finished_signal.emit(False, f"Missing env: {names}")
                return

            if self.batch_mode and self.parse_speakers:
                self.emit_log("❌ Batch Translate does not support Parse Speakers mode.")
                self.finished_signal.emit(False, "Batch + Parse Speakers unsupported")
                return

            files_dir = self.project_root / "files"
            if not files_dir.exists():
                self.emit_log("❌ Files directory does not exist!")
                self.finished_signal.emit(False, "Files directory missing")
                return

            if self.selected_files:
                matching_files = self.selected_files
            else:
                matching_files = []
                for file_path in files_dir.iterdir():
                    if file_path.is_file() and file_path.name != '.gitkeep':
                        for ext in self.module_info[1]:
                            if file_path.name.endswith(ext):
                                matching_files.append(file_path.name)
                                break

            if not matching_files:
                self.emit_log(f"❌ No files found matching extensions: {', '.join(self.module_info[1])}")
                self.finished_signal.emit(False, "No matching files")
                return

            self.emit_log(f"📁 Found {len(matching_files)} files to process:")
            for filename in matching_files:
                self.emit_log(f"   • {filename}")
            self.emit_log(f"🔧 Using module: {self.module_info[0]}")
            if self.batch_mode:
                self.emit_log("📦 Batch mode: Anthropic Batches API (50% off)")
            else:
                self.emit_log(f"📊 Estimate only: {'Yes' if self.estimate_only else 'No'}")
            self.emit_log("")

            total_cost = "Fail"
            old_cwd = os.getcwd()
            os.chdir(str(self.project_root))

            if self.estimate_only:
                try:
                    from util.translation import clear_estimate_written_sizes
                    clear_estimate_written_sizes()
                except Exception:
                    pass

            try:
                if self.batch_mode:
                    from util.translation import (
                        clearBatchFiles,
                        pendingBatchRequests,
                        estimateBatchCost,
                    )

                    run_consume = True
                    if self.batch_resume_state is None:
                        clearBatchFiles()
                        self._emit_batch_phase("collect")
                        self.emit_log("[BATCH] Pass 1/2: collecting requests...")
                        self.emit_log(
                            "[BATCH] Note: speaker names and similar short strings translate at "
                            "live API rates during collect (dialogue is batched after you confirm)."
                        )
                        total_cost = self._run_files(matching_files, False, batch_phase="collect")
                        if self.should_stop:
                            self.finished_signal.emit(False, "Translation stopped")
                            return

                        if pendingBatchRequests() == 0:
                            self.emit_log("[BATCH] No requests queued — nothing needed the API.")
                            run_consume = False
                        else:
                            n_requests = pendingBatchRequests()
                            self._emit_batch_phase("collect_done", {
                                "files": len(matching_files),
                                "requests": n_requests,
                            })
                            est = self._emit_batch_output(estimateBatchCost)
                            if est is not None:
                                est = dict(est)
                                est["files"] = len(matching_files)
                            if not self._wait_batch_submit(est):
                                self.emit_log("[BATCH] Not submitted. Queue kept in log/batch_requests.json.")
                                self.finished_signal.emit(True, "Batch not submitted")
                                return
                            poll_result = self._run_batch_poll_fetch()
                            if poll_result is None:
                                self.finished_signal.emit(False, "Batch polling stopped")
                                return
                    elif self.batch_resume_state == "submitted":
                        self._emit_batch_phase("polling")
                        self.emit_log("[BATCH] Resuming submitted batch...")
                        poll_result = self._run_batch_poll_fetch()
                        if poll_result is None:
                            self.finished_signal.emit(False, "Batch polling stopped")
                            return
                    else:
                        self.emit_log("[BATCH] Resuming from fetched results...")

                    if run_consume and not self.should_stop:
                        self._emit_batch_phase("consume")
                        self.emit_log("[BATCH] Pass 2/2: writing translated files...")
                        total_cost = self._run_files(matching_files, False, batch_phase="consume")
                else:
                    total_cost = self._run_files(matching_files, self.estimate_only)
            finally:
                os.chdir(old_cwd)
                
            # Clean up temporary files
            tmp_file = self.project_root / "csv.tmp"
            if tmp_file.exists():
                tmp_file.unlink()
                
            # Clean up any remaining temporary scripts
            temp_script = self.project_root / "temp_translation_script.py"
            if temp_script.exists():
                temp_script.unlink()
                
            # Ensure all processes are terminated
            if self.running_processes:
                for process in self.running_processes:
                    try:
                        if process.poll() is None:
                            process.terminate()
                            process.wait(timeout=1)
                    except:
                        pass
                self.running_processes.clear()
                
            # Report results
            if total_cost != "Fail" and not self.should_stop:
                if self.batch_mode:
                    try:
                        from util.translation import clearBatchFiles
                        clearBatchFiles()
                    except Exception:
                        pass
                self.emit_log("")
                self.emit_log(f"💰 {total_cost}")
                if self.batch_mode:
                    self.emit_log("✅ Batch translation completed!")
                elif not self.estimate_only:
                    self.emit_log("✅ Translation completed successfully!")
                else:
                    self.emit_log("✅ Estimation completed!")
                    try:
                        from util.translation import clear_estimate_written_sizes
                        clear_estimate_written_sizes()
                    except Exception:
                        pass
                self.finished_signal.emit(True, str(total_cost))
            else:
                if not self.should_stop:
                    self.emit_log("❌ Translation failed!")
                    self.finished_signal.emit(False, "Translation failed")
                else:
                    # Only log the final stop message here
                    self.emit_log("🛑 Translation stopped by user")
                    self.finished_signal.emit(False, "Translation stopped")
                    
        except Exception as e:
            error_msg = f"❌ Unexpected error: {str(e)}"
            self.emit_log(error_msg)
            self.finished_signal.emit(False, error_msg)


class TranslationTab(QWidget):
    """Simple translation tab with file management and console log.

    Emits engine_changed(str) when the selected module implies a different
    engine configuration tab should be displayed.
    """
    engine_changed = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        # Persistent settings (remember last directory used in file dialogs)
        try:
            self.settings = QSettings("DazedTranslations", "DazedMTLTool")
        except Exception:
            self.settings = None
        # If the worker signals finished before all file progress updates
        # have been received, we queue the finalization until the last
        # file progress update arrives.
        self._finish_pending = None
        self.translation_process = None
        self.log_buffer = []  # Buffer for batching log messages
        self.log_timer = QTimer()  # Timer for flushing log buffer
        self.log_timer.timeout.connect(self.flush_log_buffer)
        
        # Set up directories
        self.project_root = Path(__file__).parent.parent
        self.files_dir = self.project_root / "files"
        self.translated_dir = self.project_root / "translated"
        
        # Ensure directories exist
        self.files_dir.mkdir(exist_ok=True)
        self.translated_dir.mkdir(exist_ok=True)
        
        # Initialize tracking variables
        self.files_completed = 0
        self.files_total = 0
        self.file_progress_items = {}  # filename -> {widget, label, progress_bar, checkbox}
        self.current_translating_file = None
        # Totals tracking
        self.totals_input_tokens = 0
        self.totals_output_tokens = 0
        self.totals_cost = 0.0
        self.totals_time = 0.0
        # Track which filenames' totals have been applied (prevents double-counting)
        self._applied_file_totals = set()
        # Filenames from the most recently completed translation run (used by post-run export)
        self._last_run_files: list = []
        # Totals widget reference
        self.totals_widget = None
        self._batch_active = False
        self._batch_ui_phase = None
        self._batch_tab_index = -1
        
        self.setup_ui()
        self.setup_module_list()
        self.refresh_file_lists()
        
    def setup_ui(self):
        """Set up the user interface."""
        # Create a fixed horizontal layout to separate translation controls from log viewer.
        # Using a layout instead of QSplitter prevents the user from resizing panes.
        main_container = QWidget()
        main_hbox = QHBoxLayout()
        # Match left side padding so headers align at the top of the boxes
        main_hbox.setContentsMargins(15, 15, 15, 15)
        main_hbox.setSpacing(8)
    # Align child widgets individually when needed; avoid setting a
    # global AlignTop on the HBox so children with Expanding size
    # policies can grow vertically to fill available space.

        # Left side - translation controls
        left_widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(8)
        # Remove the top internal margin so the left header lines up with the
        # right header (main_hbox already provides top padding).
        layout.setContentsMargins(15, 0, 15, 15)

        # Files Section (at the top)
        layout.addWidget(create_section_header("📁 Input Files"))
        
        # Create stacked widget to switch between file list and progress view
        self.file_stack = QStackedWidget()
        
        # Page 0: Normal file list with buttons
        file_list_page = QWidget()
        file_list_layout = QVBoxLayout()
        file_list_layout.setContentsMargins(0, 0, 0, 0)
        
        # Files Section with side buttons
        files_container = QHBoxLayout()
        files_container.setSpacing(5)  # Add spacing between list and buttons
        
        # File list with checkboxes
        self.file_list = QListWidget()
        # Allow the file list to expand vertically to fill available space
        # (remove fixed minimum height so it can stretch).
        self.file_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # No max height - let it expand
        self.file_list.setSelectionMode(QListWidget.NoSelection)  # Disable selection highlighting
        # Use an event filter installed on the viewport so we reliably
        # intercept mouse events that occur over the item rows and
        # checkbox indicator. Installing on the viewport is more
        # reliable cross-platform than installing on the list itself.
        self.file_list.viewport().installEventFilter(self)
        self._file_list_filter_installed = True
        self.file_list.setFocusPolicy(Qt.NoFocus)  # Remove focus outline
        self.file_list.setStyleSheet("""
            QListWidget {
                outline: none;
                border: 1px solid #555555;
            }
            QListWidget::item {
                border: none;
                outline: none;
            }
            QListWidget::item:hover {
                background-color: #3e3e42;
            }
        """)
        # Place the two main file buttons on the left and totals on the right
        # File management buttons (icon-based, vertical on the side)
        file_buttons = QVBoxLayout()
        file_buttons.setSpacing(0)
        file_buttons.setContentsMargins(0, 0, 0, 0)
        
        # Button style for all icon buttons - all same size
        icon_button_style = """
            QPushButton {
                font-size: 13px;
                padding: 0px;
                min-width: 32px;
                max-width: 32px;
                min-height: 32px;
                max-height: 32px;
                border: 1px solid #555555;
                border-top: none;
                border-radius: 0px;
                background-color: #2d2d30;
            }
            QPushButton:hover {
                background-color: #3e3e42;
                border-left-color: #007acc;
            }
            QPushButton:pressed {
                background-color: #007acc;
            }
        """
        
        # First button style - same size but with top border
        first_button_style = """
            QPushButton {
                font-size: 13px;
                padding: 0px;
                min-width: 32px;
                max-width: 32px;
                min-height: 32px;
                max-height: 32px;
                border: 1px solid #555555;
                border-radius: 0px;
                background-color: #2d2d30;
            }
            QPushButton:hover {
                background-color: #3e3e42;
                border-left-color: #007acc;
            }
            QPushButton:pressed {
                background-color: #007acc;
            }
        """
        
        select_all_btn = QPushButton("✓")
        select_all_btn.setToolTip("Select all files")
        select_all_btn.clicked.connect(self.select_all_files)
        select_all_btn.setStyleSheet(first_button_style)
        file_buttons.addWidget(select_all_btn)
        
        deselect_all_btn = QPushButton("✗")
        deselect_all_btn.setToolTip("Deselect all files")
        deselect_all_btn.clicked.connect(self.deselect_all_files)
        deselect_all_btn.setStyleSheet(icon_button_style)
        file_buttons.addWidget(deselect_all_btn)
        
        add_files_btn = QPushButton(platform_glyph("➕"))
        add_files_btn.setToolTip("Add files to translate")
        add_files_btn.clicked.connect(self.add_input_files)
        add_files_btn.setStyleSheet(icon_button_style)
        file_buttons.addWidget(add_files_btn)
        
        remove_files_btn = QPushButton("🗑️")
        remove_files_btn.setToolTip("Remove selected files")
        remove_files_btn.clicked.connect(self.remove_selected_files)
        remove_files_btn.setStyleSheet(icon_button_style)
        file_buttons.addWidget(remove_files_btn)
        
        open_folder_btn = QPushButton(platform_glyph("📁"))
        open_folder_btn.setToolTip("Open files folder in explorer")
        open_folder_btn.clicked.connect(self.open_input_folder)
        open_folder_btn.setStyleSheet(icon_button_style)
        file_buttons.addWidget(open_folder_btn)
        
        refresh_btn = QPushButton(platform_glyph("🔄"))
        refresh_btn.setToolTip("Refresh file list")
        refresh_btn.clicked.connect(self.refresh_file_lists)
        refresh_btn.setStyleSheet(icon_button_style)
        file_buttons.addWidget(refresh_btn)

        self.sidebar_export_btn = QPushButton("📤")
        self.sidebar_export_btn.setToolTip("Export selected files → Game Folder\nCopy translated files for the checked items into your game's data directory")
        self.sidebar_export_btn.clicked.connect(self._export_selected_files)
        self.sidebar_export_btn.setStyleSheet(icon_button_style)
        file_buttons.addWidget(self.sidebar_export_btn)

        pricing_test_btn = QPushButton("💰")
        pricing_test_btn.setToolTip("Check live pricing for the current model")
        pricing_test_btn.clicked.connect(self._check_model_pricing)
        pricing_test_btn.setStyleSheet(icon_button_style)
        file_buttons.addWidget(pricing_test_btn)
        
        # Add stretch to push buttons to top
        file_buttons.addStretch()

        # Add button column to the container on the LEFT
        files_container.addLayout(file_buttons)
        # Then add the file list (center)
        files_container.addWidget(self.file_list)

        # (Totals footer will be created below and shown only when translation starts)

        # Add the container to file list page and allow it to expand so
        # the file list can grow and push settings to the bottom.
        file_list_layout.addLayout(files_container, 1)
        # (Totals footer removed here; totals will be shown next to the
        # back/open buttons in the progress view as requested.)
        file_list_page.setLayout(file_list_layout)
        self.file_stack.addWidget(file_list_page)  # Index 0
        
        # Page 1: Progress view (shown during translation)
        progress_view_page = QWidget()
        progress_view_layout = QVBoxLayout()
        progress_view_layout.setContentsMargins(0, 0, 0, 0)
        progress_view_layout.setSpacing(8)

        # Batch pipeline panel (shown only during batch runs)
        self.batch_pipeline_widget = QWidget()
        self.batch_pipeline_widget.setVisible(False)
        batch_pipe_layout = QVBoxLayout()
        batch_pipe_layout.setContentsMargins(12, 12, 12, 12)
        batch_pipe_layout.setSpacing(10)

        self.batch_phase_title = QLabel("Batch Translate")
        self.batch_phase_title.setStyleSheet("color:#4ec9b0;font-weight:bold;font-size:13px;")
        batch_pipe_layout.addWidget(self.batch_phase_title)

        self.batch_overall_bar = QProgressBar()
        self.batch_overall_bar.setRange(0, 100)
        self.batch_overall_bar.setValue(0)
        self.batch_overall_bar.setFixedHeight(20)
        self.batch_overall_bar.setTextVisible(True)
        self.batch_overall_bar.setStyleSheet("""
            QProgressBar {
                border: none;
                border-radius: 3px;
                text-align: center;
                background-color: #2b2b2b;
                color: #cccccc;
            }
            QProgressBar::chunk {
                background-color: #007acc;
                border-radius: 3px;
            }
        """)
        batch_pipe_layout.addWidget(self.batch_overall_bar)

        self.batch_pipeline_stack = QStackedWidget()

        collect_page = QWidget()
        collect_layout = QVBoxLayout(collect_page)
        collect_layout.setContentsMargins(0, 0, 0, 0)
        collect_layout.setSpacing(8)
        self.batch_collect_warning = QLabel(BATCH_COLLECT_LIVE_CHARGE_NOTE)
        self.batch_collect_warning.setWordWrap(True)
        self.batch_collect_warning.setStyleSheet("color:#f0ad4e;font-size:11px;")
        collect_layout.addWidget(self.batch_collect_warning)
        self.batch_collect_status = QLabel("Pass 1/2: collecting API requests from selected files…")
        self.batch_collect_status.setWordWrap(True)
        self.batch_collect_status.setStyleSheet("color:#cccccc;font-size:12px;")
        collect_layout.addWidget(self.batch_collect_status)
        self.batch_pipeline_stack.addWidget(collect_page)

        submit_page = QWidget()
        submit_layout = QVBoxLayout(submit_page)
        submit_layout.setContentsMargins(0, 0, 0, 0)
        submit_layout.setSpacing(4)
        self.batch_submit_summary = QLabel("")
        self.batch_submit_summary.setWordWrap(True)
        self.batch_submit_summary.setAlignment(Qt.AlignTop)
        self.batch_submit_summary.setStyleSheet("color:#cccccc;font-size:12px;")
        submit_layout.addWidget(self.batch_submit_summary, 1)
        submit_btn_row = QHBoxLayout()
        submit_btn_row.addStretch()
        self.batch_submit_yes_btn = QPushButton("Submit Batch")
        self.batch_submit_yes_btn.setStyleSheet(
            "QPushButton{background-color:#007acc;color:white;font-weight:bold;padding:6px 16px;border-radius:4px;}"
            "QPushButton:hover{background-color:#106ebe;}"
        )
        self.batch_submit_yes_btn.clicked.connect(self._on_batch_submit_yes)
        self.batch_submit_no_btn = QPushButton("Cancel")
        self.batch_submit_no_btn.setStyleSheet(
            "QPushButton{background-color:#555;color:white;padding:6px 16px;border-radius:4px;}"
            "QPushButton:hover{background-color:#666;}"
        )
        self.batch_submit_no_btn.clicked.connect(self._on_batch_submit_no)
        submit_btn_row.addWidget(self.batch_submit_no_btn)
        submit_btn_row.addWidget(self.batch_submit_yes_btn)
        submit_layout.addLayout(submit_btn_row)
        self.batch_pipeline_stack.addWidget(submit_page)

        poll_page = QWidget()
        poll_layout = QVBoxLayout(poll_page)
        poll_layout.setContentsMargins(0, 0, 0, 0)
        self.batch_poll_status = QLabel("Waiting for Anthropic to finish processing the batch…")
        self.batch_poll_status.setWordWrap(True)
        self.batch_poll_status.setStyleSheet("color:#cccccc;font-size:12px;")
        poll_layout.addWidget(self.batch_poll_status)
        self.batch_poll_bar = QProgressBar()
        self.batch_poll_bar.setRange(0, 0)  # indeterminate
        self.batch_poll_bar.setFixedHeight(16)
        self.batch_poll_bar.setStyleSheet("""
            QProgressBar { border: none; background-color: #2b2b2b; border-radius: 3px; }
            QProgressBar::chunk { background-color: #007acc; border-radius: 3px; }
        """)
        poll_layout.addWidget(self.batch_poll_bar)
        self.batch_pipeline_stack.addWidget(poll_page)

        consume_page = QWidget()
        consume_layout = QVBoxLayout(consume_page)
        consume_layout.setContentsMargins(0, 0, 0, 0)
        self.batch_consume_status = QLabel("Pass 2/2: writing translated files from batch results…")
        self.batch_consume_status.setWordWrap(True)
        self.batch_consume_status.setStyleSheet("color:#cccccc;font-size:12px;")
        consume_layout.addWidget(self.batch_consume_status)
        self.batch_pipeline_stack.addWidget(consume_page)

        batch_pipe_layout.addWidget(self.batch_pipeline_stack, 1)
        self.batch_live_status = QLabel("")
        self.batch_live_status.setWordWrap(True)
        self.batch_live_status.setStyleSheet("color:#666666;font-size:11px;")
        batch_pipe_layout.addWidget(self.batch_live_status)

        self.batch_pipeline_widget.setLayout(batch_pipe_layout)
        self.batch_pipeline_widget.setObjectName("batchPipeline")
        self.batch_pipeline_widget.setStyleSheet("""
            #batchPipeline {
                background-color: #252526;
                border: 1px solid #3e3e42;
                border-radius: 4px;
            }
        """)
        self.batch_pipeline_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.batch_pipeline_stack.setStyleSheet("background: transparent;")
        self.batch_pipeline_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.progress_list = QListWidget()
        self.progress_list.setMinimumHeight(120)
        self.progress_list.setSelectionMode(QListWidget.NoSelection)
        self.progress_list.setFocusPolicy(Qt.NoFocus)
        self.progress_list.setSpacing(1)  # Minimal spacing between items
        self.progress_list.setStyleSheet("""
            QListWidget {
                outline: none;
                border: 1px solid #555555;
                border-radius: 3px;
                background-color: #1e1e1e;
                color: white;
                font-size: 13px;
            }
            QListWidget::item {
                padding: 0px;
                border-bottom: 1px solid #333333;
            }
            QListWidget::item:last {
                border-bottom: none;
            }
        """)

        self.progress_overview_page = QWidget()
        overview_layout = QVBoxLayout(self.progress_overview_page)
        overview_layout.setContentsMargins(0, 0, 0, 0)
        overview_layout.setSpacing(0)
        overview_layout.addWidget(self.batch_pipeline_widget, 1)

        self.progress_files_page = QWidget()
        files_page_layout = QVBoxLayout(self.progress_files_page)
        files_page_layout.setContentsMargins(0, 0, 0, 0)
        files_page_layout.addWidget(self.progress_list)

        progress_tab_btn_style = """
            QPushButton {
                background: #2d2d30;
                color: #aaa;
                border: 1px solid #3e3e42;
                border-radius: 4px;
                padding: 0px;
            }
            QPushButton:hover {
                background: #353538;
                color: #ddd;
            }
        """
        progress_tab_btn_active_style = """
            QPushButton {
                background: #252526;
                color: #4ec9b0;
                border: 1px solid #4a4a4f;
                border-radius: 4px;
                padding: 0px;
            }
        """
        self._progress_tab_btn_style = progress_tab_btn_style
        self._progress_tab_btn_active_style = progress_tab_btn_active_style

        self.progress_tab_row = QWidget()
        progress_tab_row_layout = QHBoxLayout(self.progress_tab_row)
        progress_tab_row_layout.setContentsMargins(0, 0, 0, 0)
        progress_tab_row_layout.setSpacing(6)
        self.batch_tab_btn = QPushButton("Batch")
        self.batch_tab_btn.setFixedSize(118, 34)
        self.batch_tab_btn.setCursor(Qt.PointingHandCursor)
        self.batch_tab_btn.clicked.connect(lambda: self._switch_progress_tab(0))
        self.files_tab_btn = QPushButton("Files")
        self.files_tab_btn.setFixedSize(118, 34)
        self.files_tab_btn.setCursor(Qt.PointingHandCursor)
        self.files_tab_btn.clicked.connect(lambda: self._switch_progress_tab(1))
        progress_tab_row_layout.addWidget(self.batch_tab_btn)
        progress_tab_row_layout.addWidget(self.files_tab_btn)
        progress_tab_row_layout.addStretch()
        self.progress_tab_row.setVisible(False)

        self.progress_content_stack = QStackedWidget()
        self.progress_content_stack.addWidget(self.progress_overview_page)
        self.progress_content_stack.addWidget(self.progress_files_page)
        self.progress_content_stack.setCurrentIndex(1)

        progress_view_layout.addWidget(self.progress_tab_row)
        progress_view_layout.addWidget(self.progress_content_stack, 1)

        # Summary button (shown after completion) - icon-only
        # Use a simple left-arrow for the back action and place it on the left
        self.reset_view_button = QPushButton("←")
        self.reset_view_button.setToolTip("Back to File Selection")
        self.reset_view_button.clicked.connect(self.reset_to_file_view)
        self.reset_view_button.setVisible(False)
        # Button to open the translations (translated) folder - icon-only
        self.open_translations_button = QPushButton(platform_glyph("📂"))
        self.open_translations_button.setToolTip("Open the translated files folder")
        self.open_translations_button.clicked.connect(self.open_output_folder)
        self.open_translations_button.setVisible(False)
        # Sync translated/ → files/ (RPG Maker only)
        self.sync_translated_button = QPushButton(platform_glyph("🔄"))
        self.sync_translated_button.setToolTip("Sync translated/ → files/\nCopy translated files back into files/ so the next phase starts from the latest state")
        self.sync_translated_button.clicked.connect(self._sync_translated_to_files)
        self.sync_translated_button.setVisible(False)
        # Export active files → game folder (RPG Maker only)
        self.export_active_button = QPushButton("📤")
        self.export_active_button.setToolTip("Export translated files → Game Folder\nCopy the files from this translation run into your game's data directory")
        self.export_active_button.clicked.connect(self._export_last_run_files)
        self.export_active_button.setVisible(False)

        # Make both buttons the same fixed size and style (icon-only)
        icon_btn_style = """
            QPushButton {
                background-color: #2d2d30;
                color: white;
                font-weight: bold;
                font-size: 16px;
                border: 1px solid #555555;
                border-radius: 4px;
                min-width: 40px;
                max-width: 40px;
                min-height: 36px;
                max-height: 36px;
            }
            QPushButton:hover {
                background-color: #3e3e42;
                border-left-color: #007acc;
            }
            QPushButton:pressed {
                background-color: #007acc;
            }
        """

        self.reset_view_button.setStyleSheet(icon_btn_style)
        self.open_translations_button.setStyleSheet(icon_btn_style)
        self.sync_translated_button.setStyleSheet(icon_btn_style)
        self.export_active_button.setStyleSheet(icon_btn_style)
        # Ensure emoji/icons are readable
        self.reset_view_button.setFont(QFont('Segoe UI', 12))
        self.open_translations_button.setFont(QFont('Segoe UI', 12))
        self.sync_translated_button.setFont(QFont('Segoe UI', 12))
        self.export_active_button.setFont(QFont('Segoe UI', 12))

        # Create the stop button here so it sits in the same row as the
        # back/open buttons. Use a compact icon style to match them but
        # make it visually distinct (red) to indicate a destructive action.
        stop_button_style = """
            QPushButton {
                background-color: #c0392b; /* red */
                color: white;
                font-weight: bold;
                font-size: 16px;
                border: 1px solid #7f2e28;
                border-radius: 4px;
                min-width: 40px;
                max-width: 40px;
                min-height: 36px;
                max-height: 36px;
            }
            QPushButton:hover {
                background-color: #e04b43;
                border-left-color: #ff6b60;
            }
            QPushButton:pressed {
                background-color: #a82a20;
            }
        """

        # Use a clear stop-sign emoji so the glyph is rendered as a stop icon
        # and not as a colored square on some platforms.
        self.stop_button = QPushButton(platform_glyph("🛑"))
        self.stop_button.setToolTip("Stop Translation")
        self.stop_button.clicked.connect(self.stop_translation)
        self.stop_button.setStyleSheet(stop_button_style)
        # Slightly larger font for the emoji to make it visually clear
        self.stop_button.setFont(QFont('Segoe UI', 14))
        self.stop_button.setVisible(False)

        # Place both buttons on the left and totals on the right
        buttons_container = QWidget()
        # Prevent the buttons row from changing the file list box size when
        # buttons/totals are shown — use minimum height that can grow if needed.
        buttons_container.setMinimumHeight(64)
        buttons_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        buttons_hbox = QHBoxLayout()
        buttons_hbox.setContentsMargins(0, 0, 0, 0)
        buttons_hbox.setSpacing(8)
        # Back/Open/Stop buttons on the left (stop shown while running)
        buttons_hbox.addWidget(self.stop_button)
        buttons_hbox.addWidget(self.reset_view_button)
        buttons_hbox.addWidget(self.open_translations_button)
        buttons_hbox.addWidget(self.sync_translated_button)
        buttons_hbox.addWidget(self.export_active_button)
        # Spacer between buttons and totals
        buttons_hbox.addStretch()
        # Totals widget on the right (hidden until start)
        self.totals_widget = QWidget()
        # Let the totals widget size naturally; the mismatch label starts hidden
        # so it won't take extra space until a mismatch occurs.
        self.totals_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        totals_layout = QVBoxLayout()
        totals_layout.setContentsMargins(6, 2, 6, 2)
        totals_layout.setSpacing(2)
        self.totals_tokens_label = QLabel("Tokens: 0 in / 0 out")
        self.totals_tokens_label.setStyleSheet("color: #f1c40f; font-weight: bold;")
        totals_layout.addWidget(self.totals_tokens_label)
        self.totals_cost_label = QLabel("Cost: $0.0000")
        self.totals_cost_label.setStyleSheet("color: #4ec9b0; font-weight: bold;")
        totals_layout.addWidget(self.totals_cost_label)
        self.totals_time_label = QLabel("Time: 0.0s")
        self.totals_time_label.setStyleSheet("color: #4da6ff; font-weight: bold;")
        totals_layout.addWidget(self.totals_time_label)
        self.totals_mismatch_label = QLabel("")
        self.totals_mismatch_label.setStyleSheet("color: #ff4444; font-weight: bold;")
        self.totals_mismatch_label.setVisible(False)
        totals_layout.addWidget(self.totals_mismatch_label)
        self.totals_widget.setLayout(totals_layout)
        self.totals_widget.setVisible(False)
        buttons_hbox.addWidget(self.totals_widget)
        buttons_container.setLayout(buttons_hbox)
        progress_view_layout.addWidget(buttons_container)
        
        progress_view_page.setLayout(progress_view_layout)
        self.file_stack.addWidget(progress_view_page)  # Index 1
        
        # Add stacked widget to main layout and allow it to stretch
        # so the input files area can take up available vertical space.
        layout.addWidget(self.file_stack, 1)
            
        # Progress Section (removed from UI)
        # The visible progress UI was removed per user request. We keep the
        # underlying widgets as attributes so existing logic can update them
        # without raising AttributeError, but we do not add them to the
        # layout so they are not shown.
        
        progress_layout = QVBoxLayout()
        progress_layout.setSpacing(8)
        progress_layout.setContentsMargins(0, 0, 0, 12)
        
        # Files Translated counter
        files_layout = QHBoxLayout()
        files_layout.addWidget(QLabel("Files Translated:"))
        self.files_translated_label = QLabel("0/0")
        self.files_translated_label.setStyleSheet("font-weight: bold; color: #007acc;")
        files_layout.addWidget(self.files_translated_label)
        files_layout.addStretch()
        progress_layout.addLayout(files_layout)
        
        # Currently translating
        translating_layout = QHBoxLayout()
        translating_layout.addWidget(QLabel("Translating:"))
        self.translating_label = QLabel("—")
        self.translating_label.setStyleSheet("font-weight: bold; color: #cccccc;")
        translating_layout.addWidget(self.translating_label)
        translating_layout.addStretch()
        progress_layout.addLayout(translating_layout)
        
        # Progress bar with label
        item_progress_layout = QHBoxLayout()
        item_progress_layout.addWidget(QLabel("Progress:"))
        self.item_progress_label = QLabel("0/0")
        self.item_progress_label.setStyleSheet("font-weight: bold; color: #cccccc;")
        item_progress_layout.addWidget(self.item_progress_label)
        item_progress_layout.addStretch()
        progress_layout.addLayout(item_progress_layout)
        
        self.item_progress_bar = QProgressBar()
        self.item_progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #555555;
                border-radius: 3px;
                text-align: center;
                background-color: #2b2b2b;
                color: white;
                height: 20px;
            }
            QProgressBar::chunk {
                background-color: #007acc;
                border-radius: 2px;
            }
        """)
        progress_layout.addWidget(self.item_progress_bar)
        
        # NOTE: Do not add progress_layout to the UI. Kept in memory only.

        # Ensure any remaining space is consumed above the settings so
        # the Translation Settings block stays anchored to the bottom.
        layout.addStretch()

        # Translation Settings Section (moved to bottom)
        layout.addWidget(create_horizontal_line())
        layout.addWidget(create_section_header("🌐 Translation Settings"))

        trans_form = QFormLayout()
        trans_form.setSpacing(6)
        trans_form.setContentsMargins(0, 0, 0, 12)
        trans_form.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        trans_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        engine_label = QLabel("Game Engine:")
        engine_label.setFixedWidth(100)
        engine_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.module_combo = QComboBox()
        self.module_combo.currentTextChanged.connect(self._on_module_changed)
        self.module_combo.setFixedWidth(300)
        trans_form.addRow(engine_label, self.module_combo)

        mode_label = QLabel("Mode:")
        mode_label.setFixedWidth(100)
        mode_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Translate")
        self.mode_combo.addItem("Estimate")
        self.mode_combo.addItem(BATCH_MODE_LABEL)
        self.mode_combo.setFixedWidth(300)
        self.mode_combo.currentTextChanged.connect(self._on_mode_changed)
        trans_form.addRow(mode_label, self.mode_combo)

        self.batch_mode_note = QLabel(
            BATCH_MODE_BENEFIT_NOTE + "\n" + BATCH_COLLECT_LIVE_CHARGE_NOTE
        )
        self.batch_mode_note.setWordWrap(True)
        self.batch_mode_note.setStyleSheet("color:#8fbc8f;font-size:12px;padding-left:4px;")
        self.batch_mode_note.setVisible(False)
        trans_form.addRow("", self.batch_mode_note)

        layout.addLayout(trans_form)
        layout.addWidget(create_horizontal_line())

        # Buttons (right below progress section)
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        self.translate_button = QPushButton("Start Translation")
        self.translate_button.clicked.connect(self.start_translation)
        self.translate_button.setStyleSheet("""
            QPushButton {
                background-color: #007acc;
                color: white;
                font-weight: bold;
                padding: 10px 20px;
                font-size: 14px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #106ebe;
            }
        """)
        button_layout.addWidget(self.translate_button)
        button_layout.addStretch()
        layout.addLayout(button_layout)

        self.mode_combo.setCurrentIndex(self.mode_combo.findText(BATCH_MODE_LABEL))
        left_widget.setLayout(layout)
        
        # Right side - translation history log viewer
        self.translation_log_viewer = LogViewer()
        # Mismatch counting is driven by MISMATCH_EVENT stdout markers
        # detected in append_log. The log_viewer signal is kept as a
        # fallback for in-process mode (e.g. speaker-parse).
        self.translation_log_viewer.mismatch_detected.connect(self.on_mismatch_detected)

        # Allow both left and right widgets to expand vertically so the
        # log viewer fills the full height to the bottom of the tab.
        left_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.translation_log_viewer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Add both widgets to the fixed HBox with stretch factors (left 40%, right 60%).
        # Keep the left column top-aligned so its header stays at the top,
        # but allow the right-hand log viewer to expand vertically to the
        # bottom of the tab so it fills available space.
        # Let the left widget expand vertically (do not force AlignTop)
        # so its internal stretch can push the settings block to the bottom.
        main_hbox.addWidget(left_widget, 2)
        # Do NOT force AlignTop on the log viewer; with an Expanding
        # vertical size policy it will grow to fill the available height.
        main_hbox.addWidget(self.translation_log_viewer, 3)

        main_container.setLayout(main_hbox)

        # Ensure main container will expand to fill the tab vertically
        main_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Set main layout for this tab
        tab_layout = QVBoxLayout()
        # Add with stretch so the container expands to fill available space
        tab_layout.addWidget(main_container, 1)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(tab_layout)
        
    def setup_module_list(self):
        """Set up the module selection list."""
        # Import modules to get the list
        try:
            sys.path.append(str(self.project_root))
            from modules.rpgmakermvmz import handleMVMZ
            from modules.csv import handleCSV
            from modules.tyrano import handleTyrano
            from modules.kirikiri import handleKirikiri
            from modules.json import handleJSON
            from modules.lune import handleLune
            from modules.yuris import handleYuris
            from modules.nscript import handleOnscripter
            from modules.wolf import handleWOLF
            from modules.wolf2 import handleWOLF2
            from modules.regex import handleRegex
            from modules.text import handleText
            from modules.renpy import handleRenpy
            from modules.unity import handleUnity
            from modules.images import handleImages
            from modules.rpgmakerplugin import handlePlugin
            from modules.aquedi4 import handleAquedi4
            from modules.srpg import handleSRPG
            
            self.modules = [
                ["RPG Maker MV/MZ", [".json"], handleMVMZ],
                ["CSV", [".csv"], handleCSV],
                ["Tyrano", [".ks"], handleTyrano],
                ["Kirikiri", [".ks"], handleKirikiri],
                ["JSON", [".json"], handleJSON],
                ["Lune", [".l"], handleLune],
                ["Yuris", [".json"], handleYuris],
                ["NScript", [".nscript"], handleOnscripter],
                ["Wolf RPG", [".json"], handleWOLF],
                ["Wolf RPG 2", [".txt"], handleWOLF2],
                ["Regex", [".txt", ".json", ".script", ".csv"], handleRegex],
                ["Text", [".txt", ".srt"], handleText],
                ["RenPy", [".rpy"], handleRenpy],
                ["Unity", [".unity"], handleUnity],
                ["Images", [".png", ".jpg", ".jpeg"], handleImages],
                ["RPG Maker Plugin", [".js"], handlePlugin],
                ["Aquedi4 Prepared JSON", [".json"], handleAquedi4],
                ["SRPG Studio", [".json"], handleSRPG],
            ]
            
            for module in self.modules:
                extensions = ", ".join(module[1])
                self.module_combo.addItem(f"{module[0]} ({extensions})")
            if self.module_combo.count():
                self._on_module_changed(self.module_combo.currentText())
                
        except Exception as e:
            # Store error for later logging since log_display might not exist yet
            self.module_load_error = f"Warning: Could not load modules: {str(e)}"
            # Add a default option
            self.module_combo.addItem("RPG Maker MV/MZ (.json)")
            self.modules = [["RPG Maker MV/MZ", [".json"], None]]
            self._on_module_changed(self.module_combo.currentText())

    def _on_module_changed(self, text: str):
        lowered = text.lower()
        if "wolf" in lowered and "wolf rpg 2" not in lowered:
            self.engine_changed.emit("wolf")
        elif "mv/mz" in lowered:
            self.engine_changed.emit("mvmz")
        elif "srpg" in lowered:
            self.engine_changed.emit("srpg")
        
        # Update mode dropdown based on engine
        current_mode = self.mode_combo.currentText()
        self.mode_combo.clear()
        self.mode_combo.addItem("Translate")
        self.mode_combo.addItem("Estimate")
        self.mode_combo.addItem(BATCH_MODE_LABEL)

        # Add Parse Speakers for RPG Maker MV/MZ
        if "mv/mz" in lowered:
            self.mode_combo.addItem("Parse Speakers")
        
        # Restore previous selection if it still exists
        index = self.mode_combo.findText(current_mode)
        if index >= 0:
            self.mode_combo.setCurrentIndex(index)
        else:
            batch_idx = self.mode_combo.findText(BATCH_MODE_LABEL)
            self.mode_combo.setCurrentIndex(batch_idx if batch_idx >= 0 else 0)
        
        # Refresh file list to show only files matching the selected module's extensions
        self.refresh_file_lists()
    
    def _toggle_file_checkbox(self, item):
        """Toggle checkbox when clicking anywhere on the item."""
        # Toggle the built-in QListWidgetItem checkbox state
        try:
            if item.checkState() == Qt.Checked:
                item.setCheckState(Qt.Unchecked)
            else:
                item.setCheckState(Qt.Checked)
        except Exception:
            pass

    def _remove_file_list_event_filter(self):
        if not getattr(self, "_file_list_filter_installed", False):
            return
        try:
            self.file_list.viewport().removeEventFilter(self)
        except RuntimeError:
            pass
        self._file_list_filter_installed = False

    def closeEvent(self, event):
        self._remove_file_list_event_filter()
        super().closeEvent(event)

    def eventFilter(self, obj, event):
        """Intercept mouse presses on the file list.

        If the click is inside the checkbox indicator area, allow the
        default Qt handling to toggle the checkbox. If the click is
        on the rest of the row, manually toggle the item's check state
        and consume the event to prevent further handling (avoids
        double toggles).
        """
        try:
            file_list = self.file_list
            viewport = file_list.viewport()
        except RuntimeError:
            return False

        # We install the filter on the QListWidget viewport, so the
        # obj will be the viewport widget when mouse events arrive.
        if (obj is viewport or obj is file_list) and event.type() == QEvent.MouseButtonPress:
            pos = event.pos()
            index = file_list.indexAt(pos)
            if not index.isValid():
                return False

            rect = file_list.visualRect(index)
            # Approximate checkbox indicator rectangle (style may vary).
            # Use a small left inset and a ~20x20 indicator area vertically centered.
            indicator_w = 20
            indicator_h = 20
            indicator_x = rect.left() + 4
            indicator_y = rect.top() + (rect.height() - indicator_h) // 2
            indicator_rect = QRect(indicator_x, indicator_y, indicator_w, indicator_h)

            # If the click is inside the indicator area, let Qt handle it
            # (it will toggle the check state). Otherwise toggle manually
            # and consume the event.
            if indicator_rect.contains(pos):
                return False

            # Toggle the item and consume the event
            item = file_list.item(index.row())
            try:
                if item.checkState() == Qt.Checked:
                    item.setCheckState(Qt.Unchecked)
                else:
                    item.setCheckState(Qt.Checked)
            except Exception:
                pass
            return True

        try:
            return super().eventFilter(obj, event)
        except RuntimeError:
            return False
    
    def _on_mode_changed(self, mode_text):
        """Update the translate button text based on selected mode."""
        if hasattr(self, "batch_mode_note"):
            self.batch_mode_note.setVisible(mode_text == BATCH_MODE_LABEL)
        if not hasattr(self, "translate_button"):
            return
        if mode_text == "Translate":
            self.translate_button.setText("Start Translation")
        elif mode_text == "Estimate":
            self.translate_button.setText("Start Estimation")
        elif mode_text == BATCH_MODE_LABEL:
            self.translate_button.setText("Start Batch Translation")
        elif mode_text == "Parse Speakers":
            self.translate_button.setText("Parse Speakers")

    def _switch_progress_tab(self, index):
        """Switch Batch/Files views; index 0 = batch overview, 1 = per-file list."""
        self._batch_tab_index = index if self.progress_tab_row.isVisible() else -1
        self.progress_content_stack.setCurrentIndex(index)
        self.batch_tab_btn.setStyleSheet(
            self._progress_tab_btn_active_style if index == 0 else self._progress_tab_btn_style
        )
        self.files_tab_btn.setStyleSheet(
            self._progress_tab_btn_active_style if index == 1 else self._progress_tab_btn_style
        )

    def _set_progress_view_mode(self, batch_mode, file_count=0):
        """Batch runs use a Batch tab for the pipeline; Files tab holds the per-file list."""
        if batch_mode:
            self.progress_tab_row.setVisible(True)
            self.batch_pipeline_widget.setVisible(True)
            self.files_tab_btn.setText(f"Files ({file_count})" if file_count else "Files")
            self._switch_progress_tab(0)
        else:
            self.progress_tab_row.setVisible(False)
            self.batch_pipeline_widget.setVisible(False)
            self.files_tab_btn.setText("Files")
            self._batch_tab_index = -1
            self.progress_content_stack.setCurrentIndex(1)

    def _on_batch_submit_yes(self):
        if hasattr(self, "translation_worker") and self.translation_worker:
            self.translation_worker.set_batch_submit_response(True)

    def _on_batch_submit_no(self):
        if hasattr(self, "translation_worker") and self.translation_worker:
            self.translation_worker.set_batch_submit_response(False)

    def _update_batch_stop_button(self):
        """Show stop only while batch is collecting; hide after that."""
        if not getattr(self, "_batch_active", False):
            return
        try:
            self.stop_button.setVisible(self._batch_ui_phase == "collect")
        except Exception:
            pass

    def _on_batch_phase(self, phase, payload):
        """Update the inline batch pipeline panel for the current phase."""
        self._batch_ui_phase = phase
        self.batch_pipeline_widget.setVisible(True)

        if phase == "collect":
            self.batch_phase_title.setText("Batch Translate — Pass 1/2: Collect")
            self.batch_overall_bar.setRange(0, 100)
            self.batch_overall_bar.setValue(15)
            self.batch_pipeline_stack.setCurrentIndex(0)
            self.batch_submit_yes_btn.setText("Submit Batch")
            self.batch_collect_status.setText(
                "Scanning files and queueing dialogue for the batch…"
            )
        elif phase == "collect_done":
            info = payload or {}
            n_files = info.get("files", "?")
            n_req = info.get("requests", "?")
            self.batch_phase_title.setText("Batch Translate — Collect complete")
            self.batch_overall_bar.setValue(30)
            self.batch_pipeline_stack.setCurrentIndex(0)
            self.batch_collect_status.setText(
                f"Finished scanning {n_files} file(s) — {n_req} API request(s) queued.\n"
                "Review the total cost below, then submit once for the whole batch."
            )
            self.batch_live_status.setText(
                f"All {n_files} files collected. Switch to the Files tab to inspect individual rows."
            )
        elif phase == "submit":
            est = payload or {}
            n_files = est.get("files", "?")
            n_req = est.get("requests", "?")
            self.batch_phase_title.setText("Batch Translate — Review & Submit (once)")
            self.batch_overall_bar.setValue(35)
            self.batch_pipeline_stack.setCurrentIndex(1)
            self.batch_submit_summary.setText(
                f"All {n_files} file(s) scanned — {n_req} request(s) queued total.\n\n"
                f"Submit everything in one Anthropic batch?\n\n"
                f"Estimated cost: ${est.get('batch_cached_cost', 0):.2f} (batch + prompt cache)\n"
                f"Worst case: ${est.get('batch_nocache_cost', 0):.2f} (batch, no cache hits)\n"
                f"Live API would be: ${est.get('live_cost', 0):.2f}\n\n"
                "One submission covers all files. The batch usually finishes within an hour. "
                "You can stop safely and resume later."
            )
            self.batch_submit_yes_btn.setText(f"Submit All ({n_req} requests)")
        elif phase == "polling":
            self.batch_phase_title.setText("Batch Translate — Processing")
            self.batch_overall_bar.setRange(0, 100)
            self.batch_overall_bar.setValue(55)
            self.batch_pipeline_stack.setCurrentIndex(2)
            self.batch_poll_status.setText("Submitted — waiting for Anthropic to process the batch…")
        elif phase == "poll_status":
            if isinstance(payload, str) and payload.strip():
                self.batch_poll_status.setText(payload.strip())
                self.batch_overall_bar.setValue(min(75, self.batch_overall_bar.value() + 2))
        elif phase == "consume":
            self.batch_phase_title.setText("Batch Translate — Pass 2/2: Write")
            self.batch_overall_bar.setValue(80)
            self.batch_pipeline_stack.setCurrentIndex(3)
            self._reset_files_for_consume()
            if self.progress_tab_row.isVisible():
                self._switch_progress_tab(0)
        elif phase == "done":
            self.batch_overall_bar.setValue(100)
            self.batch_phase_title.setText("Batch Translate — Complete")

        self._update_batch_stop_button()

    def _reset_batch_pipeline_ui(self):
        self._batch_active = False
        self._batch_ui_phase = None
        if hasattr(self, "batch_pipeline_widget"):
            self.batch_pipeline_widget.setVisible(False)
        if hasattr(self, "batch_live_status"):
            self.batch_live_status.setText("")
        if hasattr(self, "progress_content_stack"):
            self._set_progress_view_mode(False)
        elif hasattr(self, "batch_overall_bar"):
            self.batch_overall_bar.setRange(0, 100)
            self.batch_overall_bar.setValue(0)

    def _reset_files_for_consume(self):
        """Clear collect-pass row state before the consume pass writes translations."""
        self.files_completed = 0
        self.files_translated_label.setText(f"0/{self.files_total}")
        for filename, item in self.file_progress_items.items():
            try:
                item["checkbox"].setChecked(False)
                item["label"].setText("Waiting...")
                item["label"].setStyleSheet("color: #888888; font-size: 10px;")
                item["progress_bar"].setVisible(True)
                item["progress_bar"].setValue(0)
                item["progress_bar"].setMaximum(100)
                item["progress_bar"].setTextVisible(True)
                item["progress_bar"].setStyleSheet("""
                    QProgressBar {
                        border: 1px solid #555555;
                        border-radius: 2px;
                        text-align: center;
                        background-color: #2b2b2b;
                        color: white;
                    }
                    QProgressBar::chunk {
                        background-color: #007acc;
                        border-radius: 1px;
                    }
                """)
                item["tokens_label"].setVisible(False)
                item["tokens_label"].setText("")
                item["cost_label"].setVisible(False)
                item["cost_label"].setText("")
                item["time_label"].setVisible(False)
                item["time_label"].setText("")
                item["status_label"].setVisible(False)
                item["status_label"].setText("")
                item.pop("_skip_reason", None)
            except Exception:
                pass
        if hasattr(self, "_applied_file_totals"):
            self._applied_file_totals.clear()
        self.totals_input_tokens = 0
        self.totals_output_tokens = 0
        self.totals_cost = 0.0
        self.totals_time = 0.0
        try:
            if hasattr(self, "totals_tokens_label"):
                self.totals_tokens_label.setText("Tokens: 0 in / 0 out")
            if hasattr(self, "totals_cost_label"):
                self.totals_cost_label.setText("Cost: $0.0000")
            if hasattr(self, "totals_time_label"):
                self.totals_time_label.setText("Time: 0.0s")
        except Exception:
            pass

    def mark_file_queued(self, filename):
        """Collect pass finished for a file — queued for batch, not translated yet."""
        if filename not in self.file_progress_items:
            return
        item = self.file_progress_items[filename]
        try:
            item["label"].setText("Collected")
            item["label"].setStyleSheet("color: #d4a017; font-weight: bold; font-size: 10px;")
            item["progress_bar"].setVisible(True)
            item["progress_bar"].setMaximum(100)
            item["progress_bar"].setValue(100)
            item["progress_bar"].setTextVisible(False)
            item["progress_bar"].setStyleSheet("""
                QProgressBar {
                    border: 1px solid #555555;
                    border-radius: 2px;
                    background-color: #2b2b2b;
                }
                QProgressBar::chunk {
                    background-color: #6a5a20;
                    border-radius: 1px;
                }
            """)
            item["checkbox"].setChecked(False)
            item["status_label"].setVisible(False)
            item["tokens_label"].setVisible(False)
            item["cost_label"].setVisible(False)
            item["time_label"].setVisible(False)
        except Exception:
            pass

    def _check_model_pricing(self):
        """Fetch live pricing for the current model and print it to the log."""
        from dotenv import dotenv_values
        from pathlib import Path as _Path

        # Read model from .env file directly so we always get the saved value
        env = dotenv_values(_Path(".env")) if _Path(".env").exists() else {}
        model = env.get("model") or os.getenv("model", "").strip()

        log = self.translation_log_viewer

        if not model:
            log.append_log_message("💰 [PRICING] No model configured — set a model in Settings first.")
            return

        log.append_log_message(f"💰 [PRICING] Checking pricing for: {model}")

        try:
            from util.translation import _lookup_model_price, _load_litellm_pricing
        except Exception as e:
            log.append_log_message(f"💰 [PRICING] Could not import pricing module: {e}")
            return

        # Force a fresh fetch attempt (bypasses the in-memory TTL check by
        # temporarily clearing the in-memory cache timestamp)
        try:
            import util.translation as _tmod
            _tmod._pricing_db_fetched_at = 0.0
            _tmod._pricing_fetch_warned = False
        except Exception:
            pass

        db = _load_litellm_pricing()
        if db is None:
            log.append_log_message(
                "💰 [PRICING] Could not reach LiteLLM pricing DB — no internet or cache available. "
                "Falling back to built-in prices."
            )
        else:
            log.append_log_message(f"💰 [PRICING] LiteLLM DB loaded ({len(db):,} entries).")

        result = _lookup_model_price(model)
        if result:
            inp, out = result
            source = "LiteLLM" if db else "built-in fallback"
            log.append_log_message(
                f"💰 [PRICING] {model}  —  "
                f"Input: ${inp:.4f} / 1M tokens  |  "
                f"Output: ${out:.4f} / 1M tokens  "
                f"(source: {source})"
            )
        else:
            # Fall back to getPricingConfig for the hardcoded table result
            try:
                from util.translation import getPricingConfig
                cfg = getPricingConfig(model)
                log.append_log_message(
                    f"💰 [PRICING] {model} not found in LiteLLM DB — using built-in fallback:  "
                    f"Input: ${cfg['inputAPICost']:.4f} / 1M tokens  |  "
                    f"Output: ${cfg['outputAPICost']:.4f} / 1M tokens"
                )
            except Exception as e:
                log.append_log_message(f"💰 [PRICING] Could not determine pricing for '{model}': {e}")

    def refresh_file_lists(self):
        """Refresh the file list with checkboxes, preserving checked states."""
        # Save current check states from existing QListWidgetItems
        checked_files = set()
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            try:
                if item.checkState() == Qt.Checked:
                    checked_files.add(item.text())
            except Exception:
                pass

        # Get accepted extensions for the currently selected module
        accepted_extensions = []
        try:
            selected_index = self.module_combo.currentIndex()
            if 0 <= selected_index < len(self.modules):
                accepted_extensions = self.modules[selected_index][1]  # List of extensions like [".json"]
        except Exception:
            pass

        # Rebuild the list using simple QListWidgetItems with checkboxes
        self.file_list.clear()
        if self.files_dir.exists():
            for file_path in sorted(self.files_dir.iterdir()):
                if file_path.is_file() and file_path.name != '.gitkeep':
                    # Filter by accepted extensions if any are defined
                    if accepted_extensions:
                        file_ext = file_path.suffix.lower()
                        # Skip files that don't match any accepted extension
                        if not any(file_ext == ext.lower() for ext in accepted_extensions):
                            continue
                    
                    item = QListWidgetItem(file_path.name)
                    # Ensure the item is enabled, selectable, and user-checkable
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                    # Restore checked state if it was previously checked
                    if file_path.name in checked_files:
                        item.setCheckState(Qt.Checked)
                    else:
                        item.setCheckState(Qt.Unchecked)
                    self.file_list.addItem(item)
    
    def select_all_files(self):
        """Select all files in the list."""
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            try:
                item.setCheckState(Qt.Checked)
            except Exception:
                pass
    
    def deselect_all_files(self):
        """Deselect all files in the list."""
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            try:
                item.setCheckState(Qt.Unchecked)
            except Exception:
                pass
    
    def get_selected_files(self):
        """Get list of checked files."""
        selected = []
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            try:
                if item.checkState() == Qt.Checked:
                    selected.append(item.text())
            except Exception:
                pass
        return selected
    
    def add_input_files(self):
        """Add files to the input directory, remembering last used directory."""
        # Restore last used directory from settings if available
        start_dir = ""
        try:
            if self.settings:
                start_dir = self.settings.value("last_open_dir", "") or ""
        except Exception:
            start_dir = ""

        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select files to add",
            start_dir,
            "All Files (*)"
        )
        
        if file_paths:
            # Save the directory used so next time we open the same place
            try:
                if self.settings and len(file_paths) > 0:
                    import os
                    dir_used = os.path.dirname(file_paths[0])
                    self.settings.setValue("last_open_dir", dir_used)
            except Exception:
                pass
            try:
                import shutil
                copied_count = 0
                for file_path in file_paths:
                    source = Path(file_path)
                    dest = self.files_dir / source.name
                    
                    if dest.exists():
                        reply = QMessageBox.question(
                            self,
                            "File Exists",
                            f"File '{source.name}' already exists. Overwrite?",
                            QMessageBox.Yes | QMessageBox.No
                        )
                        if reply == QMessageBox.No:
                            continue
                    
                    shutil.copy2(source, dest)
                    copied_count += 1
                
                self.refresh_file_lists()
                if copied_count > 0:
                    QMessageBox.information(self, "Files Added", f"Successfully added {copied_count} files.")
                    
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to add files:\n{str(e)}")
                
    def remove_selected_files(self):
        """Remove selected (checked) files from the input directory."""
        selected_files = self.get_selected_files()
        
        if not selected_files:
            QMessageBox.information(self, "No Selection", "Please check files to remove.")
            return
            
        reply = QMessageBox.question(
            self,
            "Confirm Deletion",
            f"Are you sure you want to delete {len(selected_files)} file(s)?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                for filename in selected_files:
                    file_path = self.files_dir / filename
                    file_path.unlink()
                self.refresh_file_lists()
                QMessageBox.information(self, "Files Removed", f"Successfully removed {len(selected_files)} file(s).")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete files:\n{str(e)}")
    
    def open_input_folder(self):
        """Open the input directory."""
        self.open_folder(self.files_dir)
        
    def open_output_folder(self):
        """Open the output directory."""
        self.open_folder(self.translated_dir)

    def _sync_translated_to_files(self):
        """Copy translated/ files back into files/ (only matching names)."""
        import shutil
        files_dir = Path("files")
        transl_dir = Path("translated")

        if not transl_dir.exists():
            QMessageBox.warning(self, "Sync", "translated/ folder not found — nothing to sync.")
            return

        active = {fp.name for fp in files_dir.glob("*.json")} if files_dir.exists() else set()
        to_copy = [fp for fp in transl_dir.glob("*.json") if not active or fp.name in active]

        if not to_copy:
            QMessageBox.warning(self, "Sync", "No matching files found in translated/ to sync.")
            return

        files_dir.mkdir(exist_ok=True)
        copied = 0
        for src in to_copy:
            shutil.copy2(src, files_dir / src.name)
            copied += 1

        QMessageBox.information(self, "Sync Complete", f"Synced {copied} file(s) from translated/ → files/")
        self.refresh_file_lists()

    def _export_selected_files(self):
        """Export only the currently checked files in the file list."""
        selected = self.get_selected_files()
        if not selected:
            QMessageBox.warning(self, "Export", "No files are checked — select files to export first.")
            return
        self._export_active_files(filenames=selected)

    def _export_last_run_files(self):
        """Export only the files that were part of the most recent translation run."""
        if not self._last_run_files:
            QMessageBox.warning(self, "Export", "No translation run recorded — translate some files first.")
            return
        self._export_active_files(filenames=self._last_run_files)

    def _export_active_files(self, filenames: list | None = None):
        """Export translated files into the game data folder.

        filenames: if provided, only those files are exported; otherwise all
        files currently in files/ are used (the original behavior, kept for
        back-compat and used by the Workflow tab via inheritance).
        """
        files_dir = Path("files")
        if filenames is not None:
            active = [n for n in filenames if n != ".gitkeep"]
        else:
            active = sorted(
                fp.name for fp in files_dir.glob("*.json") if fp.name != ".gitkeep"
            ) if files_dir.exists() else []

        if not active:
            QMessageBox.warning(self, "Export", "No files found in files/ — import game files first.")
            return

        # For RPG Maker MV/MZ, try to reuse the project path already set in the Workflow tab
        game_data = None
        module_text = ""
        try:
            module_text = self.module_combo.currentText().lower()
        except Exception:
            pass
        is_mvmz = "mv/mz" in module_text

        if is_mvmz:
            try:
                wt = self.window().workflow_tab
                if wt and getattr(wt, "_data_path", None):
                    game_data = wt._data_path
            except Exception:
                pass

        if not game_data:
            game_data = QFileDialog.getExistingDirectory(self, "Select Game Data Folder to Export Into")
            if not game_data:
                return

        transl_dir = Path("translated")
        exportable_count = sum(1 for name in active if (transl_dir / name).exists())
        reply = QMessageBox.question(
            self,
            "Export Active Files to Game",
            f"Export {exportable_count} file(s) into:\n{game_data}\n\nMake a backup first if needed. Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        import shutil
        exported = 0
        skipped = 0
        for name in active:
            src = transl_dir / name
            if src.exists():
                shutil.copy2(src, Path(game_data) / name)
                exported += 1
            else:
                skipped += 1

        msg = f"Exported {exported} file(s) to:\n{game_data}"
        if skipped:
            msg += f"\n({skipped} file(s) not found in translated/ — skipped)"
        QMessageBox.information(self, "Export Complete", msg)

    def open_folder(self, folder_path):
        """Open a folder in the file explorer."""
        try:
            import platform
            if platform.system() == "Windows":
                subprocess.run(["explorer", str(folder_path)])
            elif platform.system() == "Darwin":  # macOS
                subprocess.run(["open", str(folder_path)])
            else:  # Linux
                subprocess.run(["xdg-open", str(folder_path)])
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to open folder:\n{str(e)}")
    
    def create_progress_item(self, filename):
        """Create a progress item widget for a file."""
        widget = QWidget()
        widget.setFixedHeight(36)  # Fixed height instead of minimum
        layout = QHBoxLayout()
        layout.setContentsMargins(6, 4, 6, 4)  # Reduced margins
        layout.setSpacing(10)
        
        # Checkbox (initially unchecked, will check when done)
        checkbox = QCheckBox()
        checkbox.setEnabled(False)  # Not interactive
        checkbox.setFixedSize(18, 18)  # Slightly smaller
        layout.addWidget(checkbox)
        
        # Filename label
        filename_label = QLabel(filename)
        filename_label.setStyleSheet("font-weight: bold; color: white; font-size: 13px;")
        filename_label.setFixedWidth(250)  # Fixed width for consistent alignment
        layout.addWidget(filename_label)
        
        # Progress label (small) shown next to filename
        progress_label = QLabel("Waiting...")
        progress_label.setStyleSheet("color: #888888; font-size: 10px;")
        progress_label.setFixedWidth(110)
        layout.addWidget(progress_label)

        # Progress bar (stretch to fill remaining space)
        progress_bar = QProgressBar()
        progress_bar.setMaximum(100)
        progress_bar.setValue(0)
        progress_bar.setFixedHeight(18)  # Fixed height instead of minimum
        progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #555555;
                border-radius: 2px;
                text-align: center;
                background-color: #2b2b2b;
                color: white;
            }
            QProgressBar::chunk {
                background-color: #007acc;
                border-radius: 1px;
            }
        """)
        layout.addWidget(progress_bar, 1)  # Stretch factor of 1 to fill remaining space

    # Inline result labels (hidden until completion) - anchored to the right
    # Order (visual): tokens | time | cost | status(check)
        tokens_label = QLabel("")
        tokens_label.setStyleSheet("color: #f1c40f; font-weight: bold; font-size: 9px;")
        tokens_label.setFixedWidth(100)
        tokens_label.setVisible(False)
        tokens_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(tokens_label)

        time_label = QLabel("")
        time_label.setStyleSheet("color: #4da6ff; font-weight: bold; font-size: 9px;")
        time_label.setFixedWidth(90)
        time_label.setVisible(False)
        time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(time_label)

        # Cost label (to the left of the status/checkmark)
        cost_label = QLabel("")
        cost_label.setStyleSheet("color: #4ec9b0; font-weight: bold; font-size: 9px;")
        cost_label.setFixedWidth(100)
        cost_label.setVisible(False)
        cost_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(cost_label)

        # Small status label (checkmark or X) placed to the right of cost
        status_label = QLabel("")
        status_label.setStyleSheet("font-weight: bold; font-size: 11px;")
        status_label.setFixedWidth(100)
        status_label.setVisible(False)
        status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(status_label)
            
        widget.setLayout(layout)
        
        # Store references
        self.file_progress_items[filename] = {
            'widget': widget,
            'checkbox': checkbox,
            'label': progress_label,
            'progress_bar': progress_bar,
            'tokens_label': tokens_label,
            'cost_label': cost_label,
            'time_label': time_label,
            'status_label': status_label
        }
        
        return widget
    
    def update_file_item_progress(self, filename, current, total):
        """Update progress for a specific file."""
        if filename in self.file_progress_items:
            item = self.file_progress_items[filename]
            item['progress_bar'].setMaximum(total if total > 0 else 100)
            item['progress_bar'].setValue(current)
            item['label'].setText(f"{current}/{total}")
            item['label'].setStyleSheet("color: #007acc; font-weight: bold;")
    
    def _apply_success_status_icon(self, item, completion_kind="normal"):
        """Green checkmark for every successful row; tooltips explain skip / idle when relevant."""
        try:
            item["status_label"].setText("✓")
            item["status_label"].setStyleSheet(
                "color: #4ec9b0; font-weight: bold; font-size: 11px;"
            )
            if completion_kind == "skip":
                reason = (item.get("_skip_reason") or "").strip()
                tip = f"Skipped: {reason}" if reason else "Whole file skipped (paths/fonts only)."
            elif completion_kind == "idle":
                tip = "No translatable lines (non-dialogue content only)."
            else:
                tip = ""
            item["status_label"].setToolTip(tip)
            item["status_label"].setVisible(True)
        except Exception:
            pass

    def mark_file_complete(self, filename, success=True, error_message=None, completion_kind="normal"):
        """Mark a file as complete or failed."""
        if filename in self.file_progress_items:
            item = self.file_progress_items[filename]
            # If we have detailed result labels already set (via append_log),
            # show them and hide the progress bar to make room.
            if success:
                item['checkbox'].setChecked(True)
                if item.get('tokens_label') and item['tokens_label'].text():
                    item['tokens_label'].setVisible(True)
                    item['cost_label'].setVisible(True)
                    item['time_label'].setVisible(True)
                    self._apply_success_status_icon(item, completion_kind)
                    try:
                        item['progress_bar'].setVisible(False)
                    except Exception:
                        pass
                    # Clear the transient progress text so completed rows don't show "x/y"
                    try:
                        item['label'].setText("")
                        item['label'].setStyleSheet("color: #888888; font-size: 11px;")
                    except Exception:
                        pass
                else:
                    # No parsed results available - show status in status_label
                    self._apply_success_status_icon(item, completion_kind)
                    try:
                        item['progress_bar'].setVisible(False)
                    except Exception:
                        pass
                    try:
                        item['label'].setText("")
                        item['label'].setStyleSheet("color: #888888; font-size: 11px;")
                    except Exception:
                        pass
            else:
                # Check if this is an unsupported file type error
                is_unsupported = False
                if error_message:
                    error_lower = error_message.lower()
                    is_unsupported = (
                        " not supported" in error_lower or
                        "not supported" == error_lower or
                        "unsupported" in error_lower or
                        "invalid file" in error_lower or
                        "wrong file type" in error_lower
                    )
                
                # Mark as failed - checkbox unchecked, red X or warning icon
                item['checkbox'].setChecked(False)
                try:
                    if is_unsupported:
                        item['status_label'].setText("⚠")
                        item['status_label'].setStyleSheet("color: #f1c40f; font-weight: bold; font-size: 13px;")
                    else:
                        item['status_label'].setText("✗")
                        item['status_label'].setStyleSheet("color: #f48771; font-weight: bold; font-size: 11px;")
                    item['status_label'].setVisible(True)
                    # Set tooltip with error message if provided
                    if error_message:
                        item['status_label'].setToolTip(f"Error: {error_message}")
                        item['widget'].setToolTip(f"Error: {error_message}")
                except Exception:
                    pass
                try:
                    if is_unsupported:
                        item['label'].setText("Not Supported")
                        item['label'].setStyleSheet("color: #f1c40f; font-weight: bold; font-size: 10px;")
                    else:
                        item['label'].setText("Failed")
                        item['label'].setStyleSheet("color: #f48771; font-weight: bold; font-size: 10px;")
                except Exception:
                    pass
                try:
                    # Hide progress bar and show error state
                    item['progress_bar'].setVisible(False)
                except Exception:
                    pass
    
    def reset_to_file_view(self):
        """Reset back to file selection view."""
        self._reset_batch_pipeline_ui()
        self.file_stack.setCurrentIndex(0)
        self.reset_view_button.setVisible(False)
        # Also hide the open translations button when returning to file view
        try:
            self.open_translations_button.setVisible(False)
        except Exception:
            pass
        try:
            self.sync_translated_button.setVisible(False)
        except Exception:
            pass
        try:
            self.export_active_button.setVisible(False)
        except Exception:
            pass
        # Hide totals when returning to file view
        try:
            if hasattr(self, 'totals_widget') and self.totals_widget:
                self.totals_widget.setVisible(False)
        except Exception:
            pass
        self.translate_button.setVisible(True)
        self.stop_button.setVisible(False)
        self.refresh_file_lists()
            
    def start_translation(self, skip_confirm: bool = False):
        """Start the translation process.

        skip_confirm: when True the confirmation dialog is bypassed (used when
        called programmatically from the Workflow tab so the user doesn't need
        an extra click to confirm what they just explicitly requested).
        """
        # Get checked files
        selected_files = self.get_selected_files()
        
        if not selected_files:
            QMessageBox.warning(self, "No Files Selected", "Please check at least one file to translate.")
            return
            
        # Get selected module
        selected_index = self.module_combo.currentIndex()
        if selected_index < 0 or selected_index >= len(self.modules):
            QMessageBox.warning(self, "No Module", "Please select a translation module.")
            return
            
        selected_module = self.modules[selected_index]
        
        # Get mode from dropdown
        mode = self.mode_combo.currentText()
        estimate_only = (mode == "Estimate")
        parse_speakers = (mode == "Parse Speakers")
        batch_mode = (mode == BATCH_MODE_LABEL)
        batch_resume_state = None

        if batch_mode:
            load_dotenv()
            sys.path.insert(0, str(self.project_root))
            try:
                from util.translation import isClaudeNative, batchRunState
            except Exception as e:
                QMessageBox.warning(self, "Batch Translate", f"Could not load batch support: {e}")
                return
            model = os.getenv("model", "")
            if not isClaudeNative(model):
                QMessageBox.warning(
                    self,
                    "Batch Translate",
                    "Batch Translate requires a Claude model with the API URL unset or "
                    "pointing at anthropic.com.\n\nChange your model/API settings and try again.",
                )
                return
            if skip_confirm:
                # Workflow auto-start: each phase is an independent batch run.
                # Never resume stale queue/results left over from a prior phase.
                from util.translation import clearBatchFiles
                clearBatchFiles()
                batch_resume_state = None
            else:
                batch_resume_state = batchRunState()
                if batch_resume_state:
                    reply = QMessageBox.question(
                        self,
                        "Resume Batch?",
                        f"A previous batch run was interrupted ({batch_resume_state}).\n\n"
                        "Resume it instead of re-collecting?\n"
                        "(Re-collecting would queue new requests and bill again.)",
                        QMessageBox.Yes | QMessageBox.No,
                    )
                    if reply != QMessageBox.Yes:
                        batch_resume_state = None
        
        # Confirm start (skipped when called programmatically from the Workflow tab)
        if not skip_confirm:
            if batch_mode and not batch_resume_state:
                reply = QMessageBox.question(
                    self,
                    "Start Batch Translate",
                    f"Start batch translation for {len(selected_files)} file(s) using {selected_module[0]}?\n\n"
                    "Pass 1 collects dialogue for the batch; you confirm the estimate, then Anthropic "
                    "processes it (50% off). Pass 2 writes translated files.\n\n"
                    f"⚠ {BATCH_COLLECT_LIVE_CHARGE_NOTE}",
                    QMessageBox.Yes | QMessageBox.No,
                )
            else:
                action = mode.lower()
                reply = QMessageBox.question(
                    self,
                    f"Start {mode}",
                    f"Start {action} for {len(selected_files)} file(s) using {selected_module[0]}?",
                    QMessageBox.Yes | QMessageBox.No,
                )
            if reply != QMessageBox.Yes:
                return
        
        if True:
            # Switch to progress view
            self.file_stack.setCurrentIndex(1)
            
            # Initialize progress list with all files
            self.progress_list.clear()
            self.file_progress_items.clear()
            
            for filename in selected_files:
                item_widget = self.create_progress_item(filename)
                list_item = QListWidgetItem(self.progress_list)
                # Set fixed size hint to match widget height
                from PyQt5.QtCore import QSize
                list_item.setSizeHint(QSize(0, 36))  # Width 0 = auto, height 36px
                self.progress_list.addItem(list_item)
                self.progress_list.setItemWidget(list_item, item_widget)
            
            # Toggle button visibility
            self.translate_button.setVisible(False)
            if batch_mode:
                # Shown during collect; hidden once collection finishes (see _on_batch_phase)
                self.stop_button.setVisible(batch_resume_state is None)
            else:
                self.stop_button.setVisible(True)
            # Show totals footer and reset totals when starting translation
            try:
                self.totals_input_tokens = 0
                self.totals_output_tokens = 0
                self.totals_cost = 0.0
                self.totals_time = 0.0
                # Reset seen filenames for this run so totals can be applied anew
                try:
                    self._applied_file_totals.clear()
                except Exception:
                    self._applied_file_totals = set()
                if hasattr(self, 'totals_tokens_label'):
                    self.totals_tokens_label.setText("Tokens: 0 in / 0 out")
                if hasattr(self, 'totals_cost_label'):
                    self.totals_cost_label.setText("Cost: $0.0000")
                if hasattr(self, 'totals_time_label'):
                    self.totals_time_label.setText("Time: 0.0s")
                if hasattr(self, 'totals_mismatch_label'):
                    self.totals_mismatch_label.setText("")
                    self.totals_mismatch_label.setVisible(False)
                self.totals_mismatch_count = 0
                if hasattr(self, 'totals_widget') and self.totals_widget:
                    self.totals_widget.setVisible(True)
            except Exception:
                pass
            # Hide all post-run buttons while a new run is in progress
            for _btn_attr in (
                "open_translations_button",
                "reset_view_button",
                "sync_translated_button",
                "export_active_button",
            ):
                try:
                    getattr(self, _btn_attr).setVisible(False)
                except Exception:
                    pass
            
            # Initialize progress tracking
            self.files_completed = 0
            self.files_total = len(selected_files)
            self._batch_active = batch_mode
            self._batch_ui_phase = None
            if batch_mode:
                self._set_progress_view_mode(True, len(selected_files))
                self.batch_overall_bar.setValue(0)
                self.batch_pipeline_stack.setCurrentIndex(0)
                self.batch_live_status.setText("")
            else:
                self._set_progress_view_mode(False, len(selected_files))
                self._batch_active = False
                self._batch_ui_phase = None
            self.files_translated_label.setText(f"0/{self.files_total}")
            self.translating_label.setText("Starting...")
            self.item_progress_label.setText("0/0")
            self.item_progress_bar.setValue(0)
            self.item_progress_bar.setMaximum(100)
            
            # Remember which files this run covers so the post-run export button
            # can export exactly those files rather than all active files.
            self._last_run_files = list(selected_files)

            # Create and start translation worker
            self.translation_worker = TranslationWorker(
                self.project_root, 
                selected_module, 
                estimate_only,
                selected_files,
                parse_speakers=parse_speakers,
                batch_mode=batch_mode,
                batch_resume_state=batch_resume_state,
            )
            
            # Connect signals
            self.translation_worker.log_signal.connect(self.append_log)
            self.translation_worker.progress_signal.connect(self.update_file_progress)
            self.translation_worker.item_progress_signal.connect(self.update_item_progress)
            self.translation_worker.file_error_signal.connect(self.on_file_error)
            self.translation_worker.finished_signal.connect(self.on_translation_finished)
            self.translation_worker.batch_phase_signal.connect(self._on_batch_phase)
            # Prepare a per-run log file in log/history and start tailing it so
            # the right-hand log panel shows only this run's new lines.
            try:
                history_dir = self.project_root / 'log' / 'history'
                history_dir.mkdir(parents=True, exist_ok=True)
                
                # Clean up old log files, keeping only the 10 most recent
                try:
                    log_files = sorted(history_dir.glob("translationHistory_*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
                    # Keep only the 10 most recent, delete the rest
                    for old_log in log_files[10:]:
                        try:
                            old_log.unlink()
                        except Exception:
                            pass
                except Exception:
                    pass
                
                # Use timestamp (safe filename) for sorting
                fname = datetime.datetime.now().strftime('translationHistory_%Y%m%d_%H%M%S.txt')
                run_log_path = history_dir / fname
                # Don't create the file yet - it will be created when first log is written
                
                # Export env var so subprocess workers inherit the path
                try:
                    os.environ['TRANSLATION_RUN_LOG'] = str(run_log_path)
                except Exception:
                    pass

                # Try to create a hard link at legacy location so modules that
                # still write to log/translationHistory.txt end up in this file.
                # This will be created when the run_log_path file is first written to
                legacy = self.project_root / 'log' / 'translationHistory.txt'
                try:
                    # Remove any existing legacy file
                    if legacy.exists():
                        try:
                            legacy.unlink()
                        except Exception:
                            pass
                except Exception:
                    pass

                # Clear UI log and start tailing the per-run file (tailer will handle non-existent files)
                self.translation_log_viewer.clear_log()
                self.translation_log_viewer.start_tail(run_log_path)
            except Exception:
                # Fallback to legacy file if anything goes wrong
                try:
                    self.translation_log_viewer.clear_log()
                    self.translation_log_viewer.start_tail(self.project_root / 'log' / 'translationHistory.txt')
                except Exception:
                    pass

            # Start the worker
            self.translation_worker.start()
            
    def append_log(self, message):
        # Detect mismatch markers emitted to stdout by translation.py.
        # This is the primary, non-racy detection path for subprocess mode.
        if isinstance(message, str) and message.startswith("MISMATCH_EVENT:"):
            self.on_mismatch_detected()
            return  # marker is internal, not displayed
        # Forward error messages to the log viewer directly. These worker-level
        # errors are not written to the log file so the tail won't capture them.
        if isinstance(message, str) and '\u274c' in message:
            try:
                if hasattr(self, 'translation_log_viewer') and self.translation_log_viewer:
                    self.translation_log_viewer.append_log_message(message)
            except Exception:
                pass
        # During batch collect/poll/submit, per-file cost lines are not final translations.
        if getattr(self, "_batch_active", False) and getattr(self, "_batch_ui_phase", None) != "consume":
            return
        try:
            stripped = _strip_ansi(message)
            pattern = (
                r'^\s*(?P<filename>[^:]+):.*?\[Input:\s*(?P<input>\d+)\].*?\[Output:\s*(?P<output>\d+)\]'
                r'.*?\[Cost:\s*\$(?P<cost>[\d,\.]+)\].*?\[(?P<time>[\d\.]+)s\]'
            )
            m = re.search(pattern, stripped)
            if not m:
                return
            filename = m.group("filename").strip()
            if filename.lower() == "total":
                return
            input_tokens = int(m.group("input"))
            output_tokens = int(m.group("output"))
            cost = float(m.group("cost").replace(",", ""))
            time_s = float(m.group("time"))
            m_skip = re.search(r"\[skipped\]\s*(.*)$", stripped)
            skip_reason = (m_skip.group(1) or "").strip() if m_skip else ""
            if skip_reason:
                completion_kind = "skip"
            elif input_tokens == 0 and output_tokens == 0:
                completion_kind = "idle"
            else:
                completion_kind = "normal"
            self._apply_file_result(
                filename,
                input_tokens,
                output_tokens,
                cost,
                time_s,
                completion_kind=completion_kind,
                skip_reason=skip_reason,
            )
        except Exception:
            # Ignore parse/logging errors
            pass
        # Do not forward this message into the LogViewer (we tail the log file separately).
        return

    def _apply_file_result(
        self,
        filename,
        input_tokens,
        output_tokens,
        cost,
        time_s,
        completion_kind="normal",
        skip_reason="",
    ):
        """Update a file's item UI with parsed result details and update totals."""
        # Update per-item display
        if filename in self.file_progress_items:
            item = self.file_progress_items[filename]
            try:
                item.pop("_skip_reason", None)
                if skip_reason:
                    item["_skip_reason"] = skip_reason
                # Distinguish "no API usage" from real token counts in the list UI
                if completion_kind in ("skip", "idle"):
                    item["tokens_label"].setText("—")
                else:
                    item["tokens_label"].setText(f"{input_tokens}/{output_tokens}")
                item['cost_label'].setText(f"${cost:.4f}")
                item['time_label'].setText(f"{time_s:.1f}s")
                item['tokens_label'].setVisible(True)
                item['cost_label'].setVisible(True)
                item['time_label'].setVisible(True)
                try:
                    item['progress_bar'].setVisible(False)
                except Exception:
                    pass
            except Exception:
                pass

        try:
            if not hasattr(self, '_applied_file_totals'):
                self._applied_file_totals = set()
            if filename not in self._applied_file_totals:
                self._applied_file_totals.add(filename)
                self.totals_input_tokens += int(input_tokens)
                self.totals_output_tokens += int(output_tokens)
                self.totals_cost += float(cost)
            # Total time should be the longest single-file time (not the sum)
            self.totals_time = max(self.totals_time, float(time_s))
            # Refresh totals labels
            if hasattr(self, 'totals_tokens_label'):
                self.totals_tokens_label.setText(f"Tokens: {self.totals_input_tokens} in / {self.totals_output_tokens} out")
            if hasattr(self, 'totals_cost_label'):
                self.totals_cost_label.setText(f"Cost: ${self.totals_cost:.4f}")
            if hasattr(self, 'totals_time_label'):
                self.totals_time_label.setText(f"Time: {self.totals_time:.1f}s")
        except Exception:
            pass
        # Mark file as complete (this will ensure checkbox and label updated)
        try:
            self.mark_file_complete(filename, success=True, completion_kind=completion_kind)
        except Exception:
            pass
    
    def update_file_progress(self, current_file, total_files, filename):
        """Update the file-level progress."""
        batch_active = getattr(self, "_batch_active", False)
        phase = getattr(self, "_batch_ui_phase", None) if batch_active else None

        if batch_active:
            if phase == "collect":
                self.files_completed = current_file
                self.files_translated_label.setText(f"{current_file}/{total_files} collected")
                self.batch_collect_status.setText(
                    f"Pass 1/2: collecting {current_file}/{total_files} files…"
                )
                self.batch_live_status.setText(f"Current file: {filename}")
                self.batch_overall_bar.setValue(15 + int(20 * current_file / max(total_files, 1)))
                self.mark_file_queued(filename)
                return
            if phase in ("submit", "polling", "poll_status"):
                return

        self.files_completed = current_file
        self.files_translated_label.setText(f"{current_file}/{total_files}")

        # Row details (tokens/cost) come from parsed stdout via append_log. If that
        # did not run (older modules / parse miss), finalize so the row is not stuck.
        if filename in self.file_progress_items:
            sl = self.file_progress_items[filename].get("status_label")
            if not sl or not sl.text():
                self.mark_file_complete(filename, success=True)

        # Clear current_translating_file if it was the same file
        if self.current_translating_file == filename:
            self.current_translating_file = None

        # Update the top-level translating label: if there are more files
        # remaining, keep it as a generic "Translating..." until the next
        # file emits item-level progress (which will set the actual
        # filename). If this was the final file, show a neutral state.
        if batch_active and phase == "consume":
            self.batch_overall_bar.setValue(80 + int(15 * current_file / max(total_files, 1)))
            self.batch_consume_status.setText(
                f"Pass 2/2: writing translations ({current_file}/{total_files})…"
            )
            self.batch_live_status.setText(f"Current file: {filename}")
        if current_file < total_files:
            self.translating_label.setText("Translating...")
        else:
            if batch_active and phase == "consume":
                self.translating_label.setText("Finishing batch…")
            else:
                self.translating_label.setText("—")
    
        # If the translation worker already signaled finished but we
        # hadn't yet shown the final UI (because the worker finished
        # before this last progress update), apply the pending finish
        # now that all files have reported completion.
        try:
            if self._finish_pending and self.files_completed >= self.files_total:
                success, message = self._finish_pending
                self._finish_pending = None
                # Finalize UI now
                self._apply_finish_ui(success, message)
        except Exception:
            pass

    def update_item_progress(self, filename, current_item, total_items):
        """Update the item-level progress (from tqdm)."""
        batch_active = getattr(self, "_batch_active", False)
        phase = getattr(self, "_batch_ui_phase", None) if batch_active else None

        self.item_progress_label.setText(f"{current_item}/{total_items}")
        self.item_progress_bar.setMaximum(total_items if total_items > 0 else 100)
        self.item_progress_bar.setValue(current_item)
        self.translating_label.setText(filename)
        
        if filename in self.file_progress_items:
            self.update_file_item_progress(filename, current_item, total_items)
            label = self.file_progress_items[filename]['label']
            if label.text() in ("Waiting...", "Queued"):
                if batch_active and phase == "collect":
                    label.setText("Scanning...")
                else:
                    label.setText("Translating...")
                label.setStyleSheet("color: #007acc; font-weight: bold;")
    
    def on_file_error(self, filename, error_message):
        """Handle a file translation error."""
        # Mark the file as failed with the error message
        self.mark_file_complete(filename, success=False, error_message=error_message)

    def on_mismatch_detected(self):
        """Increment the mismatch counter and update the totals label."""
        try:
            if not hasattr(self, 'totals_mismatch_count'):
                self.totals_mismatch_count = 0
            self.totals_mismatch_count += 1
            if hasattr(self, 'totals_mismatch_label'):
                self.totals_mismatch_label.setText(f"Mismatches: {self.totals_mismatch_count}")
                self.totals_mismatch_label.setVisible(True)
        except Exception:
            pass
            
    def flush_log_buffer(self):
        """No longer needed - kept for compatibility."""
        self.log_buffer.clear()
        self.log_timer.stop()
        
    def update_progress(self, current_file, total_files, filename):
        """Legacy method - redirect to new method."""
        self.update_file_progress(current_file, total_files, filename)
        
    def on_translation_finished(self, success, message):
        """Handle translation completion."""
        # Mark the last file as complete if needed
        if self.current_translating_file:
            self.mark_file_complete(self.current_translating_file, success=success)

        # If not all files have reported completion yet, defer final UI
        # changes until the final file progress update arrives. This
        # prevents the back/reset button from showing prematurely.
        try:
            if self.files_total and self.files_completed < self.files_total:
                self._finish_pending = (success, message)
                return
        except Exception:
            # If anything goes wrong with counts, fall through and finalize.
            pass

        # Otherwise finalize immediately
        self._apply_finish_ui(success, message)

    def _apply_finish_ui(self, success, message):
        """Apply UI changes for a finished translation run."""
        if getattr(self, "_batch_active", False):
            self._on_batch_phase("done", None)
        # Hide the stop button and show the reset/back button
        try:
            self.stop_button.setVisible(False)
        except Exception:
            pass
        try:
            self.reset_view_button.setVisible(True)
        except Exception:
            pass

        # Show the button to open the translated files folder
        try:
            self.open_translations_button.setVisible(True)
        except Exception:
            pass

        # Show sync/export buttons only for RPG Maker engines
        try:
            module_text = self.module_combo.currentText().lower()
            is_rpgmaker = "rpg maker" in module_text or "rpgmaker" in module_text
            self.sync_translated_button.setVisible(is_rpgmaker)
            self.export_active_button.setVisible(is_rpgmaker)
        except Exception:
            pass

        # Update progress display
        try:
            if success:
                self.translating_label.setText("Completed!")
            else:
                self.translating_label.setText(f"Failed: {message}")
        except Exception:
            pass

        # Refresh file list to show any new translated files
        try:
            self.refresh_file_lists()
        except Exception:
            pass

        # Stop tailing the log after a short delay so the final poll
        # can pick up any data written just before the worker finished.
        try:
            if hasattr(self, 'translation_log_viewer') and self.translation_log_viewer:
                QTimer.singleShot(600, self.translation_log_viewer.stop_tail)
        except Exception:
            pass
            
    def stop_translation(self):
        """Stop the translation process."""
        if hasattr(self, 'translation_worker') and self.translation_worker.isRunning():
            self.translation_worker.stop()
            
            # Wait for the worker to stop gracefully
            if not self.translation_worker.wait(5000):  # Wait up to 5 seconds
                self.translation_worker.terminate()
                self.translation_worker.wait(2000)  # Wait for termination
        
        # Toggle button visibility
        self.translate_button.setVisible(True)
        self.stop_button.setVisible(False)
        # If a finish was pending (worker signaled finished before
        # file progress completed), clear it and finalize UI now since
        # the user requested a stop and no further progress updates
        # are expected.
        try:
            self._finish_pending = None
        except Exception:
            pass

        try:
            # Apply final UI for stopped run
            self._apply_finish_ui(False, "Translation stopped by user")
        except Exception:
            pass
        self.translating_label.setText("Stopped")
        
    def closeEvent(self, event):
        """Handle widget close event."""
        if hasattr(self, 'log_timer'):
            self.log_timer.stop()
        if hasattr(self, 'translation_worker') and self.translation_worker.isRunning():
            self.translation_worker.stop()
            if not self.translation_worker.wait(3000):
                self.translation_worker.terminate()
                self.translation_worker.wait(1000)
        event.accept()
