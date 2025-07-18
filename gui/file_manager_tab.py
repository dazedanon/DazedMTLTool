#!/usr/bin/env python3
"""
File Manager Tab for DazedMTLTool GUI

Manages input files from 'files' directory and output to 'translated' directory.
Users can add files through GUI or by copying them to the files folder.
"""

import os
import shutil
from pathlib import Path
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem,
    QPushButton, QGroupBox, QSplitter, QTextEdit, QFileDialog, QMessageBox,
    QProgressBar, QFrame, QHeaderView
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont


class FileManagerTab(QWidget):
    """File Manager tab for managing input and output files."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.project_root = Path(__file__).parent.parent
        self.files_dir = self.project_root / "files"
        self.translated_dir = self.project_root / "translated"
        
        # Ensure directories exist
        self.files_dir.mkdir(exist_ok=True)
        self.translated_dir.mkdir(exist_ok=True)
        
        self.setup_ui()
        self.refresh_file_lists()
        
        # Auto-refresh timer
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.refresh_file_lists)
        self.refresh_timer.start(3000)  # Refresh every 3 seconds
        
    def setup_ui(self):
        """Set up the user interface."""
        layout = QVBoxLayout()
        
        # Title
        title_label = QLabel("File Manager")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #007acc;")
        layout.addWidget(title_label)
        
        # Description
        desc_label = QLabel(
            "Input files are loaded from the 'files' directory. "
            "Translated files will be saved to the 'translated' directory. "
            "You can add files using the GUI or by copying them to the files folder."
        )
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: #cccccc; margin-bottom: 10px;")
        layout.addWidget(desc_label)
        
        # Main splitter
        splitter = QSplitter(Qt.Horizontal)
        
        # Input files section
        input_group = self.create_input_files_section()
        splitter.addWidget(input_group)
        
        # Output files section
        output_group = self.create_output_files_section()
        splitter.addWidget(output_group)
        
        # Set equal sizes
        splitter.setSizes([400, 400])
        layout.addWidget(splitter)
        
        # Action buttons
        button_layout = self.create_action_buttons()
        layout.addLayout(button_layout)
        
        # Status bar
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #cccccc; padding: 5px;")
        layout.addWidget(self.status_label)
        
        self.setLayout(layout)
        
    def create_input_files_section(self):
        """Create the input files section."""
        group = QGroupBox("Input Files (files directory)")
        layout = QVBoxLayout()
        
        # File tree
        self.input_tree = QTreeWidget()
        self.input_tree.setHeaderLabels(["Filename", "Size", "Modified"])
        self.input_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.input_tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.input_tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.input_tree.itemSelectionChanged.connect(self.on_input_file_selected)
        layout.addWidget(self.input_tree)
        
        # Input buttons
        input_button_layout = QHBoxLayout()
        
        self.add_file_btn = QPushButton("Add Files")
        self.add_file_btn.clicked.connect(self.add_files)
        input_button_layout.addWidget(self.add_file_btn)
        
        self.remove_file_btn = QPushButton("Remove Selected")
        self.remove_file_btn.clicked.connect(self.remove_input_file)
        self.remove_file_btn.setEnabled(False)
        input_button_layout.addWidget(self.remove_file_btn)
        
        self.open_files_folder_btn = QPushButton("Open Files Folder")
        self.open_files_folder_btn.clicked.connect(self.open_files_folder)
        input_button_layout.addWidget(self.open_files_folder_btn)
        
        input_button_layout.addStretch()
        layout.addLayout(input_button_layout)
        
        group.setLayout(layout)
        return group
        
    def create_output_files_section(self):
        """Create the output files section."""
        group = QGroupBox("Output Files (translated directory)")
        layout = QVBoxLayout()
        
        # File tree
        self.output_tree = QTreeWidget()
        self.output_tree.setHeaderLabels(["Filename", "Size", "Modified"])
        self.output_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.output_tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.output_tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.output_tree.itemSelectionChanged.connect(self.on_output_file_selected)
        layout.addWidget(self.output_tree)
        
        # Output buttons
        output_button_layout = QHBoxLayout()
        
        self.view_output_btn = QPushButton("View Selected")
        self.view_output_btn.clicked.connect(self.view_output_file)
        self.view_output_btn.setEnabled(False)
        output_button_layout.addWidget(self.view_output_btn)
        
        self.delete_output_btn = QPushButton("Delete Selected")
        self.delete_output_btn.clicked.connect(self.delete_output_file)
        self.delete_output_btn.setEnabled(False)
        output_button_layout.addWidget(self.delete_output_btn)
        
        self.open_translated_folder_btn = QPushButton("Open Translated Folder")
        self.open_translated_folder_btn.clicked.connect(self.open_translated_folder)
        output_button_layout.addWidget(self.open_translated_folder_btn)
        
        output_button_layout.addStretch()
        layout.addLayout(output_button_layout)
        
        group.setLayout(layout)
        return group
        
    def create_action_buttons(self):
        """Create main action buttons."""
        layout = QHBoxLayout()
        
        self.refresh_btn = QPushButton("Refresh File Lists")
        self.refresh_btn.clicked.connect(self.refresh_file_lists)
        layout.addWidget(self.refresh_btn)
        
        self.clear_translated_btn = QPushButton("Clear All Translated Files")
        self.clear_translated_btn.clicked.connect(self.clear_translated_files)
        layout.addWidget(self.clear_translated_btn)
        
        layout.addStretch()
        
        # Auto-refresh indicator
        self.auto_refresh_label = QLabel("Auto-refresh: ON")
        self.auto_refresh_label.setStyleSheet("color: #00aa00; font-size: 10px;")
        layout.addWidget(self.auto_refresh_label)
        
        return layout
        
    def refresh_file_lists(self):
        """Refresh both input and output file lists."""
        self.refresh_input_files()
        self.refresh_output_files()
        self.update_status()
        
    def refresh_input_files(self):
        """Refresh the input files tree."""
        self.input_tree.clear()
        
        if not self.files_dir.exists():
            return
            
        supported_extensions = {'.json', '.txt', '.csv', '.js', '.py', '.xml', '.html', '.md'}
        
        for file_path in self.files_dir.iterdir():
            if (file_path.is_file() and 
                file_path.suffix.lower() in supported_extensions and 
                file_path.name != '.gitkeep'):
                item = QTreeWidgetItem()
                item.setText(0, file_path.name)
                
                # File size
                size = file_path.stat().st_size
                if size < 1024:
                    size_str = f"{size} B"
                elif size < 1024 * 1024:
                    size_str = f"{size / 1024:.1f} KB"
                else:
                    size_str = f"{size / (1024 * 1024):.1f} MB"
                item.setText(1, size_str)
                
                # Modified time
                import datetime
                mtime = datetime.datetime.fromtimestamp(file_path.stat().st_mtime)
                item.setText(2, mtime.strftime("%Y-%m-%d %H:%M"))
                
                # Store file path
                item.setData(0, Qt.UserRole, str(file_path))
                
                self.input_tree.addTopLevelItem(item)
                
    def refresh_output_files(self):
        """Refresh the output files tree."""
        self.output_tree.clear()
        
        if not self.translated_dir.exists():
            return
            
        for file_path in self.translated_dir.iterdir():
            if file_path.is_file() and file_path.name != '.gitkeep':
                item = QTreeWidgetItem()
                item.setText(0, file_path.name)
                
                # File size
                size = file_path.stat().st_size
                if size < 1024:
                    size_str = f"{size} B"
                elif size < 1024 * 1024:
                    size_str = f"{size / 1024:.1f} KB"
                else:
                    size_str = f"{size / (1024 * 1024):.1f} MB"
                item.setText(1, size_str)
                
                # Modified time
                import datetime
                mtime = datetime.datetime.fromtimestamp(file_path.stat().st_mtime)
                item.setText(2, mtime.strftime("%Y-%m-%d %H:%M"))
                
                # Store file path
                item.setData(0, Qt.UserRole, str(file_path))
                
                self.output_tree.addTopLevelItem(item)
                
    def update_status(self):
        """Update the status label."""
        input_count = self.input_tree.topLevelItemCount()
        output_count = self.output_tree.topLevelItemCount()
        self.status_label.setText(f"Input files: {input_count} | Output files: {output_count}")
        
    def on_input_file_selected(self):
        """Handle input file selection."""
        selected = self.input_tree.selectedItems()
        self.remove_file_btn.setEnabled(len(selected) > 0)
        
    def on_output_file_selected(self):
        """Handle output file selection."""
        selected = self.output_tree.selectedItems()
        self.view_output_btn.setEnabled(len(selected) > 0)
        self.delete_output_btn.setEnabled(len(selected) > 0)
        
    def add_files(self):
        """Add files to the input directory."""
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Files to Add",
            "",
            "All Supported Files (*.json *.txt *.csv *.js *.py *.xml *.html *.md);;All Files (*.*)"
        )
        
        if not file_paths:
            return
            
        copied_count = 0
        for file_path in file_paths:
            source_path = Path(file_path)
            dest_path = self.files_dir / source_path.name
            
            try:
                # Check if file already exists
                if dest_path.exists():
                    reply = QMessageBox.question(
                        self,
                        "File Exists",
                        f"'{source_path.name}' already exists. Overwrite?",
                        QMessageBox.Yes | QMessageBox.No
                    )
                    if reply != QMessageBox.Yes:
                        continue
                        
                shutil.copy2(source_path, dest_path)
                copied_count += 1
                
            except Exception as e:
                QMessageBox.warning(
                    self,
                    "Copy Error",
                    f"Failed to copy '{source_path.name}':\n{str(e)}"
                )
                
        if copied_count > 0:
            QMessageBox.information(
                self,
                "Files Added",
                f"Successfully added {copied_count} file(s) to the input directory."
            )
            self.refresh_input_files()
            
    def remove_input_file(self):
        """Remove selected input file."""
        selected = self.input_tree.selectedItems()
        if not selected:
            return
            
        item = selected[0]
        file_path = Path(item.data(0, Qt.UserRole))
        
        reply = QMessageBox.question(
            self,
            "Confirm Removal",
            f"Are you sure you want to remove '{file_path.name}' from the input directory?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                file_path.unlink()
                self.refresh_input_files()
                QMessageBox.information(self, "File Removed", f"'{file_path.name}' has been removed.")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to remove file:\n{str(e)}")
                
    def view_output_file(self):
        """View selected output file."""
        selected = self.output_tree.selectedItems()
        if not selected:
            return
            
        item = selected[0]
        file_path = Path(item.data(0, Qt.UserRole))
        
        try:
            # Open file with default system application
            import subprocess
            import platform
            
            if platform.system() == 'Windows':
                os.startfile(str(file_path))
            elif platform.system() == 'Darwin':  # macOS
                subprocess.run(['open', str(file_path)])
            else:  # Linux
                subprocess.run(['xdg-open', str(file_path)])
                
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to open file:\n{str(e)}")
            
    def delete_output_file(self):
        """Delete selected output file."""
        selected = self.output_tree.selectedItems()
        if not selected:
            return
            
        item = selected[0]
        file_path = Path(item.data(0, Qt.UserRole))
        
        reply = QMessageBox.question(
            self,
            "Confirm Deletion",
            f"Are you sure you want to delete '{file_path.name}' from the output directory?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                file_path.unlink()
                self.refresh_output_files()
                QMessageBox.information(self, "File Deleted", f"'{file_path.name}' has been deleted.")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to delete file:\n{str(e)}")
                
    def clear_translated_files(self):
        """Clear all files from the translated directory."""
        if self.output_tree.topLevelItemCount() == 0:
            QMessageBox.information(self, "No Files", "There are no files to clear.")
            return
            
        reply = QMessageBox.question(
            self,
            "Confirm Clear All",
            "Are you sure you want to delete ALL files from the translated directory?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                deleted_count = 0
                for file_path in self.translated_dir.iterdir():
                    if file_path.is_file() and file_path.name != '.gitkeep':
                        file_path.unlink()
                        deleted_count += 1
                        
                self.refresh_output_files()
                QMessageBox.information(
                    self, 
                    "Files Cleared", 
                    f"Successfully deleted {deleted_count} file(s) from the translated directory."
                )
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to clear files:\n{str(e)}")
                
    def open_files_folder(self):
        """Open the files folder in the system file manager."""
        try:
            import subprocess
            import platform
            
            if platform.system() == 'Windows':
                subprocess.run(['explorer', str(self.files_dir)])
            elif platform.system() == 'Darwin':  # macOS
                subprocess.run(['open', str(self.files_dir)])
            else:  # Linux
                subprocess.run(['xdg-open', str(self.files_dir)])
                
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to open folder:\n{str(e)}")
            
    def open_translated_folder(self):
        """Open the translated folder in the system file manager."""
        try:
            import subprocess
            import platform
            
            if platform.system() == 'Windows':
                subprocess.run(['explorer', str(self.translated_dir)])
            elif platform.system() == 'Darwin':  # macOS
                subprocess.run(['open', str(self.translated_dir)])
            else:  # Linux
                subprocess.run(['xdg-open', str(self.translated_dir)])
                
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to open folder:\n{str(e)}")
            
    def get_input_files(self):
        """Get list of input files for processing."""
        input_files = []
        for i in range(self.input_tree.topLevelItemCount()):
            item = self.input_tree.topLevelItem(i)
            file_path = item.data(0, Qt.UserRole)
            input_files.append(Path(file_path))
        return input_files
        
    def closeEvent(self, event):
        """Handle widget close event."""
        if hasattr(self, 'refresh_timer'):
            self.refresh_timer.stop()
        event.accept()
