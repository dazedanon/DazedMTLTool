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
from concurrent.futures import ThreadPoolExecutor, as_completed
import traceback
from colorama import Fore
from tqdm import tqdm
from dotenv import load_dotenv
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGroupBox,
    QTextEdit, QMessageBox, QListWidget, QListWidgetItem, 
    QSplitter, QFileDialog, QComboBox, QCheckBox, QProgressBar
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread, QMutex
from PyQt5.QtGui import QFont


class TranslationWorker(QThread):
    """Worker thread for running translations without blocking the UI."""
    
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int, str)  # current_file, total_files, filename
    finished_signal = pyqtSignal(bool, str)
    
    def __init__(self, project_root, module_info, estimate_only=False):
        super().__init__()
        self.project_root = project_root
        self.module_info = module_info  # [name, extensions, handler_function]
        self.estimate_only = estimate_only
        self.should_stop = False
        self.mutex = QMutex()  # For thread safety
        
    def stop(self):
        """Stop the translation process."""
        self.mutex.lock()
        try:
            self.should_stop = True
        finally:
            self.mutex.unlock()
        
    def emit_log(self, message):
        """Thread-safe log emission."""
        self.log_signal.emit(message)
        
    def emit_progress(self, current, total, filename):
        """Thread-safe progress emission."""
        self.progress_signal.emit(current, total, filename)
        
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
                with ThreadPoolExecutor(max_workers=threads) as executor:
                    # Submit all tasks first
                    future_to_filename = {
                        executor.submit(self.module_info[2], filename, self.estimate_only): filename
                        for filename in matching_files
                    }
                    
                    completed_count = 0
                    total_files = len(matching_files)
                    
                    for future in as_completed(future_to_filename):
                        if self.should_stop:
                            self.emit_log("🛑 Translation stopped by user")
                            break
                            
                        filename = future_to_filename[future]
                        completed_count += 1
                        
                        # Emit progress signal (less frequent updates)
                        self.emit_progress(completed_count, total_files, filename)
                        
                        try:
                            result = future.result()
                            total_cost = result
                            # Only log every file completion, not internal progress
                            self.emit_log(f"✅ Completed {filename} ({completed_count}/{total_files})")
                        except Exception as e:
                            tb_line = str(traceback.extract_tb(sys.exc_info()[2])[-1].lineno)
                            error_msg = f"❌ Error processing {filename}: {str(e)} | Line: {tb_line}"
                            self.emit_log(error_msg)
                            
            finally:
                os.chdir(old_cwd)
                
            # Clean up temporary files
            tmp_file = self.project_root / "csv.tmp"
            if tmp_file.exists():
                tmp_file.unlink()
                
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
                    
        except Exception as e:
            error_msg = f"❌ Unexpected error: {str(e)}"
            self.emit_log(error_msg)
            self.finished_signal.emit(False, error_msg)


class TranslationTab(QWidget):
    """Simple translation tab with file management and console log."""
    
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
        
        self.setup_ui()
        self.refresh_file_lists()
        
        # Auto-refresh timer for file lists (less frequent during translation)
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.refresh_file_lists)
        self.refresh_timer.start(3000)  # Refresh every 3 seconds
        
    def setup_ui(self):
        """Set up the user interface."""
        layout = QVBoxLayout()
        layout.setSpacing(15)  # Add consistent spacing
        
        # Title
        title_label = QLabel("Translation")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #007acc; margin-bottom: 5px;")
        layout.addWidget(title_label)
        
        # Description
        desc_label = QLabel(
            "Manage your files and run translations. Add files to 'files' folder, select module, then click translate."
        )
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: #cccccc; margin-bottom: 15px;")
        layout.addWidget(desc_label)
        
        # Module selection section
        module_group = QGroupBox("Translation Settings")
        module_group.setStyleSheet("QGroupBox { font-weight: bold; color: #007acc; margin-top: 10px; }")
        module_layout = QVBoxLayout()
        
        # Module selector
        module_selector_layout = QHBoxLayout()
        module_label = QLabel("Game Engine:")
        module_selector_layout.addWidget(module_label)
        
        self.module_combo = QComboBox()
        self.setup_module_list()
        module_selector_layout.addWidget(self.module_combo)
        
        # Estimate checkbox
        self.estimate_checkbox = QCheckBox("Estimate only (don't translate)")
        module_selector_layout.addWidget(self.estimate_checkbox)
        
        module_layout.addLayout(module_selector_layout)
        module_group.setLayout(module_layout)
        layout.addWidget(module_group)
        
        # File management section at the top
        file_management_splitter = QSplitter(Qt.Horizontal)
        
        # Input files
        input_widget = self.create_input_files_widget()
        file_management_splitter.addWidget(input_widget)
        
        # Output files
        output_widget = self.create_output_files_widget()
        file_management_splitter.addWidget(output_widget)
        
        file_management_splitter.setSizes([300, 300])
        layout.addWidget(file_management_splitter)
        
        # Console log at the bottom
        log_widget = self.create_log_widget()
        layout.addWidget(log_widget)
        
        # Translation button
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
        self.stop_button.setEnabled(False)
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
        
        self.setLayout(layout)
        
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
                
        except Exception as e:
            self.log_display.append(f"Warning: Could not load modules: {str(e)}")
            # Add a default option
            self.module_combo.addItem("RPG Maker MV/MZ (.json)")
            self.modules = [["RPG Maker MV/MZ", [".json"], None]]
        
    def create_input_files_widget(self):
        """Create the input files widget."""
        input_group = QGroupBox("Input Files (files folder)")
        input_group.setStyleSheet("QGroupBox { font-weight: bold; color: #007acc; margin-top: 10px; }")
        input_layout = QVBoxLayout()
        
        self.input_list = QListWidget()
        self.input_list.setMaximumHeight(120)
        input_layout.addWidget(self.input_list)
        
        input_buttons = QHBoxLayout()
        add_input_btn = QPushButton("Add Files")
        add_input_btn.clicked.connect(self.add_input_files)
        input_buttons.addWidget(add_input_btn)
        
        remove_input_btn = QPushButton("Remove Selected")
        remove_input_btn.clicked.connect(self.remove_input_file)
        input_buttons.addWidget(remove_input_btn)
        
        open_input_btn = QPushButton("Open Folder")
        open_input_btn.clicked.connect(self.open_input_folder)
        input_buttons.addWidget(open_input_btn)
        
        input_layout.addLayout(input_buttons)
        input_group.setLayout(input_layout)
        return input_group
        
    def create_output_files_widget(self):
        """Create the output files widget."""
        output_group = QGroupBox("Output Files (translated folder)")
        output_group.setStyleSheet("QGroupBox { font-weight: bold; color: #007acc; margin-top: 10px; }")
        output_layout = QVBoxLayout()
        
        self.output_list = QListWidget()
        self.output_list.setMaximumHeight(120)
        output_layout.addWidget(self.output_list)
        
        output_buttons = QHBoxLayout()
        remove_output_btn = QPushButton("Remove Selected")
        remove_output_btn.clicked.connect(self.remove_output_file)
        output_buttons.addWidget(remove_output_btn)
        
        clear_output_btn = QPushButton("Clear All")
        clear_output_btn.clicked.connect(self.clear_output_files)
        output_buttons.addWidget(clear_output_btn)
        
        open_output_btn = QPushButton("Open Folder")
        open_output_btn.clicked.connect(self.open_output_folder)
        output_buttons.addWidget(open_output_btn)
        
        output_layout.addLayout(output_buttons)
        output_group.setLayout(output_layout)
        return output_group
        
    def create_log_widget(self):
        """Create the console log widget."""
        log_group = QGroupBox("Console Output")
        log_group.setStyleSheet("QGroupBox { font-weight: bold; color: #007acc; margin-top: 10px; }")
        layout = QVBoxLayout()
        
        # Progress bar for file translation
        progress_layout = QHBoxLayout()
        self.progress_label = QLabel("Ready")
        self.progress_label.setStyleSheet("color: #cccccc; font-weight: bold;")
        progress_layout.addWidget(self.progress_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #555555;
                border-radius: 3px;
                text-align: center;
                background-color: #2b2b2b;
                color: white;
            }
            QProgressBar::chunk {
                background-color: #007acc;
                border-radius: 2px;
            }
        """)
        progress_layout.addWidget(self.progress_bar)
        layout.addLayout(progress_layout)
        
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setFont(QFont("Consolas", 9))
        self.log_display.setMinimumHeight(200)
        self.log_display.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #ffffff;
                border: 1px solid #555555;
                font-family: 'Consolas', 'Courier New', monospace;
            }
        """)
        layout.addWidget(self.log_display)
        
        clear_log_btn = QPushButton("Clear Log")
        clear_log_btn.clicked.connect(self.clear_log)
        layout.addWidget(clear_log_btn)
        
        log_group.setLayout(layout)
        return log_group
        
    def refresh_file_lists(self):
        """Refresh both input and output file lists."""
        # Refresh input files
        self.input_list.clear()
        if self.files_dir.exists():
            for file_path in self.files_dir.iterdir():
                if file_path.is_file() and file_path.name != '.gitkeep':
                    self.input_list.addItem(file_path.name)
                    
        # Refresh output files
        self.output_list.clear()
        if self.translated_dir.exists():
            for file_path in self.translated_dir.iterdir():
                if file_path.is_file() and file_path.name != '.gitkeep':
                    self.output_list.addItem(file_path.name)
                    
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
                
    def remove_input_file(self):
        """Remove selected input file."""
        current_item = self.input_list.currentItem()
        if not current_item:
            QMessageBox.information(self, "No Selection", "Please select a file to remove.")
            return
            
        file_path = self.files_dir / current_item.text()
        
        reply = QMessageBox.question(
            self,
            "Confirm Deletion",
            f"Are you sure you want to delete '{current_item.text()}'?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                file_path.unlink()
                self.refresh_file_lists()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete file:\n{str(e)}")
                
    def remove_output_file(self):
        """Remove selected output file."""
        current_item = self.output_list.currentItem()
        if not current_item:
            QMessageBox.information(self, "No Selection", "Please select a file to remove.")
            return
            
        file_path = self.translated_dir / current_item.text()
        
        reply = QMessageBox.question(
            self,
            "Confirm Deletion",
            f"Are you sure you want to delete '{current_item.text()}'?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                file_path.unlink()
                self.refresh_file_lists()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete file:\n{str(e)}")
                
    def clear_output_files(self):
        """Clear all output files."""
        if self.output_list.count() == 0:
            QMessageBox.information(self, "No Files", "No output files to clear.")
            return
            
        reply = QMessageBox.question(
            self,
            "Confirm Clear",
            "Are you sure you want to delete ALL translated files?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                count = 0
                for file_path in self.translated_dir.iterdir():
                    if file_path.is_file() and file_path.name != '.gitkeep':
                        file_path.unlink()
                        count += 1
                        
                self.refresh_file_lists()
                QMessageBox.information(self, "Files Cleared", f"Deleted {count} files.")
                
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to clear files:\n{str(e)}")
                
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
        if self.input_list.count() == 0:
            QMessageBox.warning(self, "No Files", "No files found in the input folder to translate.")
            return
            
        # Get selected module
        selected_index = self.module_combo.currentIndex()
        if selected_index < 0 or selected_index >= len(self.modules):
            QMessageBox.warning(self, "No Module", "Please select a translation module.")
            return
            
        selected_module = self.modules[selected_index]
        estimate_only = self.estimate_checkbox.isChecked()
        
        # Confirm start
        action = "estimate" if estimate_only else "translate"
        reply = QMessageBox.question(
            self,
            f"Start {action.title()}",
            f"Start {action}ing {self.input_list.count()} files using {selected_module[0]}?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.translate_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.clear_log()
            
            # Create and start translation worker
            self.translation_worker = TranslationWorker(
                self.project_root, 
                selected_module, 
                estimate_only
            )
            
            # Connect signals
            self.translation_worker.log_signal.connect(self.append_log)
            self.translation_worker.progress_signal.connect(self.update_progress)
            self.translation_worker.finished_signal.connect(self.on_translation_finished)
            
            # Show progress bar and initialize
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)
            self.progress_label.setText("Starting...")
            
            # Reduce file refresh frequency during translation
            self.refresh_timer.stop()
            
            # Start the worker
            self.translation_worker.start()
            
    def append_log(self, message):
        """Append a message to the log buffer for batched display."""
        self.log_buffer.append(message)
        
        # Start timer if not already running
        if not self.log_timer.isActive():
            self.log_timer.start(100)  # Flush every 100ms
            
    def flush_log_buffer(self):
        """Flush the log buffer to the display."""
        if self.log_buffer:
            # Add all buffered messages at once
            for message in self.log_buffer:
                self.log_display.append(message)
            self.log_buffer.clear()
            
            # Auto-scroll to bottom
            scrollbar = self.log_display.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
            
        # Stop timer if buffer is empty
        self.log_timer.stop()
        
    def update_progress(self, current_file, total_files, filename):
        """Update the progress bar and label."""
        self.progress_bar.setMaximum(total_files)
        self.progress_bar.setValue(current_file)
        self.progress_label.setText(f"Processing {filename} ({current_file}/{total_files})")
        
    def on_translation_finished(self, success, message):
        """Handle translation completion."""
        self.translate_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.progress_label.setText("Ready")
        
        # Flush any remaining log messages
        self.flush_log_buffer()
        
        # Resume file refresh
        self.refresh_timer.start(3000)
        self.refresh_file_lists()
        
        if success:
            self.append_log("")
            self.append_log("🎉 Process completed successfully!")
        else:
            self.append_log("")
            self.append_log(f"❌ Process failed: {message}")
            
        # Force flush the final messages
        self.flush_log_buffer()
            
    def stop_translation(self):
        """Stop the translation process."""
        if hasattr(self, 'translation_worker') and self.translation_worker.isRunning():
            self.translation_worker.stop()
            self.translation_worker.wait(3000)  # Wait up to 3 seconds
            self.append_log("🛑 Translation process stopped by user.")
        
        self.translate_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.progress_label.setText("Ready")
        
        # Resume file refresh
        self.refresh_timer.start(3000)
        
        # Flush any remaining messages
        self.flush_log_buffer()
        
    def clear_log(self):
        """Clear the log display."""
        self.log_buffer.clear()  # Clear buffer too
        self.log_display.clear()
        
    def closeEvent(self, event):
        """Handle widget close event."""
        if hasattr(self, 'refresh_timer'):
            self.refresh_timer.stop()
        if hasattr(self, 'log_timer'):
            self.log_timer.stop()
        if hasattr(self, 'translation_worker') and self.translation_worker.isRunning():
            self.translation_worker.stop()
            self.translation_worker.wait(3000)
        event.accept()
