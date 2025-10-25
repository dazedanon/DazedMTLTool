#!/usr/bin/env python3
"""
Simple Translation Tab for DazedMTLTool GUI

Simple file management and translation execution with console log display.
"""

import os
import subprocess
import threading
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
import traceback
import signal
import multiprocessing
from colorama import Fore
from tqdm import tqdm
from dotenv import load_dotenv
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGroupBox,
    QTextEdit, QMessageBox, QListWidget, QListWidgetItem, 
    QSplitter, QFileDialog, QComboBox, QCheckBox, QProgressBar, QFrame, QFormLayout
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread, QMutex, QProcess
from PyQt5.QtGui import QFont
from gui.log_viewer import LogViewer


def create_section_header(title):
    """Create a clean section header without boxes."""
    label = QLabel(title)
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


class TranslationWorker(QThread):
    """Worker thread for running translations without blocking the UI."""
    
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int, str)  # current_file, total_files, filename
    item_progress_signal = pyqtSignal(int, int)  # current_item, total_items (for tqdm within file)
    finished_signal = pyqtSignal(bool, str)
    
    def __init__(self, project_root, module_info, estimate_only=False, selected_files=None):
        super().__init__()
        self.project_root = project_root
        self.module_info = module_info  # [name, extensions, handler_function]
        self.estimate_only = estimate_only
        self.selected_files = selected_files  # List of files to process
        self.should_stop = False
        self.mutex = QMutex()  # For thread safety
        self.executor = None  # Store reference to executor for proper shutdown
        self.running_processes = []  # Track running processes for termination
        
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
        
    def run_module_in_process(self, filename, estimate_only):
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
                                self.item_progress_signal.emit(int(current), int(total))
                                # Update translating label with filename
                                if desc:
                                    self.emit_log(f"📝 Translating: {desc} ({current}/{total})")
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
                error_msg = stderr.strip() if stderr.strip() else "Unknown error"
                # Handle potential Unicode errors in error messages
                try:
                    clean_error = error_msg.encode('ascii', 'ignore').decode('ascii')
                except:
                    clean_error = "Unicode encoding error in process output"
                self.emit_log(f"❌ Process error: {clean_error}")
                return "Fail"
                
        except Exception as e:
            self.emit_log(f"❌ Failed to run module process: {str(e)}")
            return "Fail"
        
    def run(self):
        """Run the translation process."""
        try:
            # Load environment variables
            load_dotenv()
            
            # Check for required environment variables
            required_envs = ["api", "key", "organization", "model", "language", "timeout", "fileThreads", "threads", "width", "listWidth"]
            env_missing = False
            
            for env in required_envs:
                if os.getenv(env) is None or str(os.getenv(env))[:1] == "<":
                    self.emit_log(f"❌ Environment variable {env} is not set!")
                    env_missing = True
                    
            if env_missing:
                self.emit_log("❌ Some required environment variables are not set. Check your .env file.")
                self.finished_signal.emit(False, "Environment variables missing")
                return
                
            # Get files to process
            files_dir = self.project_root / "files"
            if not files_dir.exists():
                self.emit_log("❌ Files directory does not exist!")
                self.finished_signal.emit(False, "Files directory missing")
                return
                
            # Use selected files or find all matching files
            if self.selected_files:
                matching_files = self.selected_files
            else:
                # Find files matching the selected module's extensions
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
            self.emit_log(f"📊 Estimate only: {'Yes' if self.estimate_only else 'No'}")
            self.emit_log("")
            
            # Process files
            threads = int(os.getenv("fileThreads", "1"))
            total_cost = "Fail"
            
            # Change to project directory for module execution
            old_cwd = os.getcwd()
            os.chdir(str(self.project_root))
            
            try:
                # Use a simpler approach with limited parallelism
                # to have better control over stopping
                max_workers = min(threads, 2)  # Limit to 2 concurrent processes max
                self.executor = ThreadPoolExecutor(max_workers=max_workers)
                
                # Submit tasks to run modules in separate processes
                future_to_filename = {
                    self.executor.submit(self.run_module_in_process, filename, self.estimate_only): filename
                    for filename in matching_files
                }
                
                completed_count = 0
                total_files = len(matching_files)
                
                for future in as_completed(future_to_filename):
                    if self.should_stop:
                        # Don't log here, the stop() method already logged
                        # Cancel remaining futures
                        for remaining_future in future_to_filename:
                            if not remaining_future.done():
                                remaining_future.cancel()
                        break
                        
                    filename = future_to_filename[future]
                    completed_count += 1
                    
                    # Emit progress signal (less frequent updates)
                    self.emit_progress(completed_count, total_files, filename)
                    
                    try:
                        result = future.result()
                        if result and result != "Fail" and result != "Stopped":
                            total_cost = result
                            # Don't log completion here since the module already logged the detailed cost info
                        elif result == "Stopped":
                            # Don't log here, already handled
                            break
                        else:
                            self.emit_log(f"❌ Failed processing {filename}")
                    except Exception as e:
                        tb_line = str(traceback.extract_tb(sys.exc_info()[2])[-1].lineno)
                        error_msg = f"❌ Error processing {filename}: {str(e)} | Line: {tb_line}"
                        self.emit_log(error_msg)
                        
            finally:
                # Properly shutdown the executor
                if self.executor:
                    try:
                        # Try to use cancel_futures parameter (Python 3.9+)
                        self.executor.shutdown(wait=False, cancel_futures=True)
                    except TypeError:
                        # Fallback for older Python versions
                        self.executor.shutdown(wait=False)
                    self.executor = None
                # Change back to original directory
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
                self.emit_log("")
                self.emit_log(f"💰 {total_cost}")
                if not self.estimate_only:
                    self.emit_log("✅ Translation completed successfully!")
                else:
                    self.emit_log("✅ Estimation completed!")
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
        
        self.setup_ui()
        self.setup_module_list()
        self.refresh_file_lists()
        
    def setup_ui(self):
        """Set up the user interface."""
        # Create main splitter to separate translation controls from log viewer
        main_splitter = QSplitter(Qt.Horizontal)
        
        # Left side - translation controls
        left_widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(15, 15, 15, 15)

        # Files Section (at the top)
        layout.addWidget(create_section_header("📁 Input Files"))
        
        # Files Section with side buttons
        files_container = QHBoxLayout()
        files_container.setSpacing(5)  # Add spacing between list and buttons
        
        # File list with checkboxes
        self.file_list = QListWidget()
        self.file_list.setMinimumHeight(350)
        # No max height - let it expand
        self.file_list.setSelectionMode(QListWidget.NoSelection)  # Disable selection highlighting
        self.file_list.itemClicked.connect(self._toggle_file_checkbox)
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
        files_container.addWidget(self.file_list)
        
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
        
        add_files_btn = QPushButton("➕")
        add_files_btn.setToolTip("Add files to translate")
        add_files_btn.clicked.connect(self.add_input_files)
        add_files_btn.setStyleSheet(icon_button_style)
        file_buttons.addWidget(add_files_btn)
        
        remove_files_btn = QPushButton("🗑️")
        remove_files_btn.setToolTip("Remove selected files")
        remove_files_btn.clicked.connect(self.remove_selected_files)
        remove_files_btn.setStyleSheet(icon_button_style)
        file_buttons.addWidget(remove_files_btn)
        
        open_folder_btn = QPushButton("📁")
        open_folder_btn.setToolTip("Open files folder in explorer")
        open_folder_btn.clicked.connect(self.open_input_folder)
        open_folder_btn.setStyleSheet(icon_button_style)
        file_buttons.addWidget(open_folder_btn)
        
        refresh_btn = QPushButton("🔄")
        refresh_btn.setToolTip("Refresh file list")
        refresh_btn.clicked.connect(self.refresh_file_lists)
        refresh_btn.setStyleSheet(icon_button_style)
        file_buttons.addWidget(refresh_btn)
        
        # Add stretch to push buttons to top
        file_buttons.addStretch()
        
        # Add button column to the container
        files_container.addLayout(file_buttons)
        
        # Add the entire container to main layout
        layout.addLayout(files_container)
        layout.addWidget(create_horizontal_line())
        
        # Translation Settings Section (in the middle)
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
        self.mode_combo.setFixedWidth(300)
        self.mode_combo.currentTextChanged.connect(self._on_mode_changed)
        trans_form.addRow(mode_label, self.mode_combo)
        
        layout.addLayout(trans_form)
        layout.addWidget(create_horizontal_line())
        
        # Spacer to push progress and buttons to bottom
        layout.addStretch()
        
        # Progress Section (at the bottom, right above buttons)
        layout.addWidget(create_section_header("📊 Translation Progress"))
        
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
        
        layout.addLayout(progress_layout)

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
        self.stop_button = QPushButton("Stop Translation")
        self.stop_button.clicked.connect(self.stop_translation)
        self.stop_button.setVisible(False)  # Hidden by default
        self.stop_button.setStyleSheet("""
            QPushButton {
                background-color: #cc0000;
                color: white;
                font-weight: bold;
                padding: 10px 20px;
                font-size: 14px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #aa0000;
            }
        """)
        button_layout.addWidget(self.stop_button)
        button_layout.addStretch()
        layout.addLayout(button_layout)
        left_widget.setLayout(layout)
        
        # Right side - translation history log viewer
        self.translation_log_viewer = LogViewer()
        
        # Add both to splitter
        main_splitter.addWidget(left_widget)
        main_splitter.addWidget(self.translation_log_viewer)
        
        # Set proportional sizes (translation controls: 60%, log viewer: 40%)
        main_splitter.setStretchFactor(0, 3)
        main_splitter.setStretchFactor(1, 2)
        
        # Set main layout for this tab
        tab_layout = QVBoxLayout()
        tab_layout.addWidget(main_splitter)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(tab_layout)
        
    def setup_module_list(self):
        """Set up the module selection list."""
        # Import modules to get the list
        try:
            sys.path.append(str(self.project_root))
            from modules.rpgmakermvmz import handleMVMZ
            from modules.rpgmakerace import handleACE
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
            
            self.modules = [
                ["RPG Maker MV/MZ", [".json"], handleMVMZ],
                ["RPG Maker Ace", [".yaml"], handleACE],
                ["CSV", [".csv"], handleCSV],
                ["Tyrano", [".ks"], handleTyrano],
                ["Kirikiri", [".ks"], handleKirikiri],
                ["JSON", [".json"], handleJSON],
                ["Lune", [".l"], handleLune],
                ["NScript", [".nscript"], handleOnscripter],
                ["Wolf RPG", [".txt"], handleWOLF],
                ["Wolf RPG 2", [".txt"], handleWOLF2],
                ["Regex", [".txt"], handleRegex],
                ["Text", [".txt"], handleText],
                ["RenPy", [".rpy"], handleRenpy],
                ["Unity", [".unity"], handleUnity],
                ["Images", [".png", ".jpg", ".jpeg"], handleImages],
                ["RPG Maker Plugin", [".js"], handlePlugin],
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
        if "ace" in lowered:
            self.engine_changed.emit("ace")
        elif "wolf" in lowered and "wolf rpg 2" not in lowered:
            self.engine_changed.emit("wolf")
        elif "mv/mz" in lowered:
            self.engine_changed.emit("mvmz")
        
        # Update mode dropdown based on engine
        current_mode = self.mode_combo.currentText()
        self.mode_combo.clear()
        self.mode_combo.addItem("Translate")
        self.mode_combo.addItem("Estimate")
        
        # Add Parse Speakers for RPG Maker MV/MZ
        if "mv/mz" in lowered:
            self.mode_combo.addItem("Parse Speakers")
        
        # Restore previous selection if it still exists
        index = self.mode_combo.findText(current_mode)
        if index >= 0:
            self.mode_combo.setCurrentIndex(index)
        else:
            self.mode_combo.setCurrentIndex(0)
    
    def _toggle_file_checkbox(self, item):
        """Toggle checkbox when clicking anywhere on the item."""
        if item.checkState() == Qt.Checked:
            item.setCheckState(Qt.Unchecked)
        else:
            item.setCheckState(Qt.Checked)
    
    def _on_mode_changed(self, mode_text):
        """Update the translate button text based on selected mode."""
        if mode_text == "Translate":
            self.translate_button.setText("Start Translation")
        elif mode_text == "Estimate":
            self.translate_button.setText("Start Estimation")
        elif mode_text == "Parse Speakers":
            self.translate_button.setText("Parse Speakers")
        
    def refresh_file_lists(self):
        """Refresh the file list with checkboxes, preserving checked states."""
        # Save current check states
        checked_files = set()
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item.checkState() == Qt.Checked:
                checked_files.add(item.text())
        
        # Rebuild the list
        self.file_list.clear()
        if self.files_dir.exists():
            for file_path in self.files_dir.iterdir():
                if file_path.is_file() and file_path.name != '.gitkeep':
                    item = QListWidgetItem(file_path.name)
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
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
            item.setCheckState(Qt.Checked)
    
    def deselect_all_files(self):
        """Deselect all files in the list."""
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            item.setCheckState(Qt.Unchecked)
    
    def get_selected_files(self):
        """Get list of checked files."""
        selected = []
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item.checkState() == Qt.Checked:
                selected.append(item.text())
        return selected
    
    def add_input_files(self):
        """Add files to the input directory."""
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select files to add",
            "",
            "All Files (*)"
        )
        
        if file_paths:
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
            
    def start_translation(self):
        """Start the translation process."""
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
        
        # Confirm start
        action = mode.lower()
        reply = QMessageBox.question(
            self,
            f"Start {mode}",
            f"Start {action} for {len(selected_files)} file(s) using {selected_module[0]}?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # Toggle button visibility
            self.translate_button.setVisible(False)
            self.stop_button.setVisible(True)
            
            # Initialize progress tracking
            self.files_completed = 0
            self.files_total = len(selected_files)
            self.files_translated_label.setText(f"0/{self.files_total}")
            self.translating_label.setText("Starting...")
            self.item_progress_label.setText("0/0")
            self.item_progress_bar.setValue(0)
            self.item_progress_bar.setMaximum(100)
            
            # Create and start translation worker
            self.translation_worker = TranslationWorker(
                self.project_root, 
                selected_module, 
                estimate_only,
                selected_files  # Pass selected files
            )
            
            # Connect signals
            self.translation_worker.log_signal.connect(self.append_log)
            self.translation_worker.progress_signal.connect(self.update_file_progress)
            self.translation_worker.item_progress_signal.connect(self.update_item_progress)
            self.translation_worker.finished_signal.connect(self.on_translation_finished)
            
            # Start the worker
            self.translation_worker.start()
            
    def append_log(self, message):
        """Append a message to the log - now just for internal tracking."""
        # We no longer display logs in the UI, but we can keep this for debugging
        # or future use with the log viewer
        pass
    
    def update_file_progress(self, current_file, total_files, filename):
        """Update the file-level progress."""
        self.files_completed = current_file
        self.files_translated_label.setText(f"{current_file}/{total_files}")
        self.translating_label.setText(filename)
    
    def update_item_progress(self, current_item, total_items):
        """Update the item-level progress (from tqdm)."""
        self.item_progress_label.setText(f"{current_item}/{total_items}")
        self.item_progress_bar.setMaximum(total_items if total_items > 0 else 100)
        self.item_progress_bar.setValue(current_item)
            
    def flush_log_buffer(self):
        """No longer needed - kept for compatibility."""
        self.log_buffer.clear()
        self.log_timer.stop()
        
    def update_progress(self, current_file, total_files, filename):
        """Legacy method - redirect to new method."""
        self.update_file_progress(current_file, total_files, filename)
        
    def on_translation_finished(self, success, message):
        """Handle translation completion."""
        # Toggle button visibility
        self.translate_button.setVisible(True)
        self.stop_button.setVisible(False)
        
        # Update progress display
        if success:
            self.translating_label.setText("Completed!")
        else:
            self.translating_label.setText(f"Failed: {message}")
        
        # Refresh file list to show any new translated files
        self.refresh_file_lists()
            
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
