#!/usr/bin/env python3
"""
Translation Execution Tab for DazedMTLTool GUI

Handles running the translation process with configured settings.
Each module has its own default settings in its folder without backups.
"""

import os
import json
from pathlib import Path
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGroupBox,
    QComboBox, QTextEdit, QProgressBar, QMessageBox, QListWidget, 
    QListWidgetItem, QSplitter, QCheckBox
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QFont, QColor


class TranslationWorker(QThread):
    """Worker thread for translation process."""
    
    progress_updated = pyqtSignal(int)
    status_updated = pyqtSignal(str)
    log_updated = pyqtSignal(str)
    finished = pyqtSignal(bool)  # True if successful
    
    def __init__(self, config, files_to_translate):
        super().__init__()
        self.config = config
        self.files_to_translate = files_to_translate
        self.is_cancelled = False
        
    def run(self):
        """Run the translation process."""
        try:
            total_files = len(self.files_to_translate)
            if total_files == 0:
                self.status_updated.emit("No files to translate")
                self.finished.emit(False)
                return
                
            self.status_updated.emit(f"Starting translation of {total_files} files...")
            
            for i, file_path in enumerate(self.files_to_translate):
                if self.is_cancelled:
                    self.status_updated.emit("Translation cancelled")
                    self.finished.emit(False)
                    return
                    
                progress = int((i / total_files) * 100)
                self.progress_updated.emit(progress)
                self.status_updated.emit(f"Translating: {file_path.name}")
                self.log_updated.emit(f"Processing file: {file_path}")
                
                # Here we would call the actual translation module
                success = self.translate_file(file_path)
                
                if not success:
                    self.log_updated.emit(f"Failed to translate: {file_path.name}")
                    self.status_updated.emit(f"Error translating {file_path.name}")
                    self.finished.emit(False)
                    return
                else:
                    self.log_updated.emit(f"Successfully translated: {file_path.name}")
                    
            self.progress_updated.emit(100)
            self.status_updated.emit(f"Translation completed successfully!")
            self.finished.emit(True)
            
        except Exception as e:
            self.log_updated.emit(f"Translation error: {str(e)}")
            self.status_updated.emit(f"Translation failed: {str(e)}")
            self.finished.emit(False)
            
    def translate_file(self, file_path):
        """Translate a single file using the appropriate module."""
        try:
            import sys
            from pathlib import Path
            
            # Add project root to path
            project_root = Path(__file__).parent.parent
            sys.path.insert(0, str(project_root))
            
            # Import the main translation module
            from modules.main import translate_file
            
            # Create module-specific config for this file
            self.create_module_config(file_path)
            
            # Call the translation function
            result = translate_file(str(file_path))
            return result
            
        except Exception as e:
            self.log_updated.emit(f"Error in translate_file: {str(e)}")
            return False
            
    def create_module_config(self, file_path):
        """Create module-specific configuration without backups."""
        try:
            # Determine the module based on file extension and content
            module_name = self.determine_module(file_path)
            
            if module_name:
                # Create module directory if it doesn't exist
                module_dir = Path(__file__).parent.parent / "modules" / module_name
                module_dir.mkdir(exist_ok=True)
                
                # Create default settings file
                settings_file = module_dir / "settings.json"
                
                # Only create if it doesn't exist (no overwriting)
                if not settings_file.exists():
                    default_settings = self.get_default_settings(module_name)
                    with open(settings_file, 'w', encoding='utf-8') as f:
                        json.dump(default_settings, f, indent=2, ensure_ascii=False)
                        
                    self.log_updated.emit(f"Created default settings for {module_name}")
                    
        except Exception as e:
            self.log_updated.emit(f"Error creating module config: {str(e)}")
            
    def determine_module(self, file_path):
        """Determine which module to use based on file type."""
        suffix = file_path.suffix.lower()
        
        if suffix == '.json':
            # Check if it's RPG Maker format
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if '"code":' in content or '"parameters":' in content:
                        return "rpgmakermvmz"
                    else:
                        return "json"
            except:
                return "json"
        elif suffix == '.txt':
            return "text"
        elif suffix == '.csv':
            return "csv"
        elif suffix in ['.js', '.py']:
            return "regex"
        else:
            return "text"  # Default fallback
            
    def get_default_settings(self, module_name):
        """Get default settings for a module."""
        base_settings = {
            "enabled": True,
            "backup": False,  # No backups as requested
            "output_directory": "translated",
            "preserve_formatting": True
        }
        
        if module_name == "rpgmakermvmz":
            # Use the same defaults as defined in RPG Maker tab
            rpg_defaults = {
                # Main dialogue codes (enabled by default)
                "CODE401": True,   # Show Text
                "CODE405": True,   # Show Text (line 4+)
                "CODE102": True,   # Show Choices
                
                # Optional codes (disabled by default)
                "CODE101": False,  # Show Text (face)
                "CODE408": False,  # Show Text (line continuation)
                
                # Variable codes (disabled by default)
                "CODE122": False,  # Control Variables
                
                # General settings
                "FIRSTLINESPEAKERS": False,
                "FACENAME101": False,
                "NAMES": False,
                "BRFLAG": False,
                "FIXTEXTWRAP": True,
                "IGNORETLTEXT": False,
                
                # All other codes disabled by default
                "translate_dialogue": True,
                "translate_choices": True,
                "translate_items": False,
                "translate_skills": False,
                "translate_states": False,
                "translate_actors": False,
                "translate_classes": False,
                "translate_weapons": False,
                "translate_armors": False,
                "translate_enemies": False,
                "event_codes": ["401", "405", "102"]  # Only main dialogue codes enabled
            }
            base_settings.update(rpg_defaults)
        elif module_name == "json":
            base_settings.update({
                "translate_strings": True,
                "skip_keys": ["id", "index", "type"],
                "nested_translation": True
            })
        elif module_name == "text":
            base_settings.update({
                "line_by_line": True,
                "skip_empty_lines": True,
                "preserve_whitespace": True
            })
        elif module_name == "csv":
            base_settings.update({
                "has_header": True,
                "delimiter": ",",
                "columns_to_translate": []  # Empty means translate all text columns
            })
            
        return base_settings
        
    def cancel(self):
        """Cancel the translation process."""
        self.is_cancelled = True


class TranslationTab(QWidget):
    """Translation execution tab."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.worker = None
        self.setup_ui()
        
    def setup_ui(self):
        """Set up the user interface."""
        layout = QVBoxLayout()
        
        # Title
        title_label = QLabel("Translation Execution")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #007acc;")
        layout.addWidget(title_label)
        
        # Description
        desc_label = QLabel(
            "Execute the translation process on selected files. "
            "Each module will use its default settings stored in its own folder."
        )
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: #cccccc; margin-bottom: 10px;")
        layout.addWidget(desc_label)
        
        # Main content
        content_splitter = QSplitter(Qt.Vertical)
        
        # File selection and controls
        controls_group = self.create_controls_section()
        content_splitter.addWidget(controls_group)
        
        # Progress and log section
        progress_group = self.create_progress_section()
        content_splitter.addWidget(progress_group)
        
        content_splitter.setSizes([300, 200])
        layout.addWidget(content_splitter)
        
        # Status bar
        self.status_label = QLabel("Ready to translate")
        self.status_label.setStyleSheet("color: #cccccc; padding: 5px;")
        layout.addWidget(self.status_label)
        
        self.setLayout(layout)
        
    def create_controls_section(self):
        """Create the controls section."""
        group = QGroupBox("Translation Controls")
        layout = QVBoxLayout()
        
        # File selection
        file_layout = QHBoxLayout()
        
        file_label = QLabel("Files to translate:")
        file_label.setStyleSheet("color: #ffffff;")
        file_layout.addWidget(file_label)
        
        self.refresh_files_btn = QPushButton("Refresh File List")
        self.refresh_files_btn.clicked.connect(self.refresh_file_list)
        file_layout.addWidget(self.refresh_files_btn)
        
        file_layout.addStretch()
        layout.addLayout(file_layout)
        
        # File list
        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QListWidget.ExtendedSelection)
        layout.addWidget(self.file_list)
        
        # Options
        options_layout = QHBoxLayout()
        
        self.select_all_cb = QCheckBox("Select All Files")
        self.select_all_cb.stateChanged.connect(self.toggle_select_all)
        options_layout.addWidget(self.select_all_cb)
        
        self.dry_run_cb = QCheckBox("Dry Run (test without translating)")
        options_layout.addWidget(self.dry_run_cb)
        
        options_layout.addStretch()
        layout.addLayout(options_layout)
        
        # Action buttons
        button_layout = QHBoxLayout()
        
        self.start_btn = QPushButton("Start Translation")
        self.start_btn.clicked.connect(self.start_translation)
        self.start_btn.setStyleSheet("QPushButton { background-color: #0a7a0a; }")
        button_layout.addWidget(self.start_btn)
        
        self.stop_btn = QPushButton("Stop Translation")
        self.stop_btn.clicked.connect(self.stop_translation)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet("QPushButton { background-color: #aa0000; }")
        button_layout.addWidget(self.stop_btn)
        
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        group.setLayout(layout)
        return group
        
    def create_progress_section(self):
        """Create the progress and log section."""
        group = QGroupBox("Translation Progress")
        layout = QVBoxLayout()
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        
        # Log output
        log_label = QLabel("Translation Log:")
        log_label.setStyleSheet("color: #ffffff; margin-top: 10px;")
        layout.addWidget(log_label)
        
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(150)
        layout.addWidget(self.log_output)
        
        # Clear log button
        clear_layout = QHBoxLayout()
        clear_layout.addStretch()
        
        self.clear_log_btn = QPushButton("Clear Log")
        self.clear_log_btn.clicked.connect(self.clear_log)
        clear_layout.addWidget(self.clear_log_btn)
        
        layout.addLayout(clear_layout)
        
        group.setLayout(layout)
        return group
        
    def refresh_file_list(self):
        """Refresh the list of available files."""
        self.file_list.clear()
        
        try:
            # Get files from the file manager tab
            if hasattr(self.parent_window, 'file_manager_tab'):
                input_files = self.parent_window.file_manager_tab.get_input_files()
                
                for file_path in input_files:
                    item = QListWidgetItem(file_path.name)
                    item.setData(Qt.UserRole, str(file_path))
                    item.setCheckState(Qt.Checked)  # Default to checked
                    self.file_list.addItem(item)
                    
                self.status_label.setText(f"Found {len(input_files)} files ready for translation")
            else:
                self.status_label.setText("File manager not available")
                
        except Exception as e:
            self.status_label.setText(f"Error loading files: {str(e)}")
            
    def toggle_select_all(self, state):
        """Toggle selection of all files."""
        check_state = Qt.Checked if state == Qt.Checked else Qt.Unchecked
        
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            item.setCheckState(check_state)
            
    def get_selected_files(self):
        """Get list of selected files."""
        selected_files = []
        
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item.checkState() == Qt.Checked:
                file_path = Path(item.data(Qt.UserRole))
                selected_files.append(file_path)
                
        return selected_files
        
    def start_translation(self):
        """Start the translation process."""
        selected_files = self.get_selected_files()
        
        if not selected_files:
            QMessageBox.warning(self, "No Files Selected", "Please select at least one file to translate.")
            return
            
        # Get configuration from other tabs
        try:
            config = {}
            if hasattr(self.parent_window, 'config_tab'):
                config.update(self.parent_window.config_tab.get_config())
            if hasattr(self.parent_window, 'rpgmaker_tab'):
                config.update(self.parent_window.rpgmaker_tab.get_config())
                
        except Exception as e:
            QMessageBox.critical(self, "Configuration Error", f"Failed to get configuration:\n{str(e)}")
            return
            
        # Confirm start
        if not self.dry_run_cb.isChecked():
            reply = QMessageBox.question(
                self,
                "Confirm Translation",
                f"Start translation of {len(selected_files)} files?\n\nThis will create translated files in the 'translated' directory.",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
                
        # Start worker thread
        self.worker = TranslationWorker(config, selected_files)
        self.worker.progress_updated.connect(self.progress_bar.setValue)
        self.worker.status_updated.connect(self.status_label.setText)
        self.worker.log_updated.connect(self.add_log_message)
        self.worker.finished.connect(self.on_translation_finished)
        
        # Update UI state
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        
        # Start translation
        self.worker.start()
        self.add_log_message(f"Starting translation of {len(selected_files)} files...")
        
    def stop_translation(self):
        """Stop the translation process."""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.add_log_message("Cancelling translation...")
            self.status_label.setText("Stopping translation...")
            
    def on_translation_finished(self, success):
        """Handle translation completion."""
        # Update UI state
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        
        if success:
            self.add_log_message("Translation completed successfully!")
            QMessageBox.information(self, "Translation Complete", "All files have been translated successfully!")
            
            # Refresh file manager if available
            if hasattr(self.parent_window, 'file_manager_tab'):
                self.parent_window.file_manager_tab.refresh_file_lists()
        else:
            self.add_log_message("Translation failed or was cancelled.")
            
        self.worker = None
        
    def add_log_message(self, message):
        """Add a message to the log output."""
        import datetime
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] {message}"
        self.log_output.append(formatted_message)
        
        # Auto-scroll to bottom
        scrollbar = self.log_output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        
    def clear_log(self):
        """Clear the log output."""
        self.log_output.clear()
        self.add_log_message("Log cleared")
