"""
File Manager - Handle input and output files
"""

from pathlib import Path
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QPushButton, QLabel, QFileDialog, QMessageBox, QGroupBox,
    QSplitter, QTextEdit, QProgressBar, QCheckBox
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
import json


class FileManager(QWidget):
    """Widget for managing input and output files."""
    
    files_changed = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self.input_files = []
        self.output_directory = Path("translated")
        self.init_ui()
        self.refresh_files()
        
    def init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout()
        
        # Create splitter for input and output sections
        splitter = QSplitter(Qt.Horizontal)
        
        # Input files section
        input_group = self.create_input_section()
        splitter.addWidget(input_group)
        
        # Output files section
        output_group = self.create_output_section()
        splitter.addWidget(output_group)
        
        splitter.setSizes([400, 400])
        layout.addWidget(splitter)
        
        # Progress section
        progress_group = self.create_progress_section()
        layout.addWidget(progress_group)
        
        self.setLayout(layout)
        
    def create_input_section(self):
        """Create the input files section."""
        group = QGroupBox("Input Files")
        layout = QVBoxLayout()
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.add_files_button = QPushButton("Add Files")
        self.add_files_button.clicked.connect(self.add_input_files)
        
        self.add_folder_button = QPushButton("Add Folder")
        self.add_folder_button.clicked.connect(self.add_input_folder)
        
        self.remove_files_button = QPushButton("Remove Selected")
        self.remove_files_button.clicked.connect(self.remove_selected_files)
        
        self.clear_files_button = QPushButton("Clear All")
        self.clear_files_button.clicked.connect(self.clear_input_files)
        
        button_layout.addWidget(self.add_files_button)
        button_layout.addWidget(self.add_folder_button)
        button_layout.addWidget(self.remove_files_button)
        button_layout.addWidget(self.clear_files_button)
        
        layout.addLayout(button_layout)
        
        # File tree
        self.input_tree = QTreeWidget()
        self.input_tree.setHeaderLabels(["File", "Size", "Type"])
        self.input_tree.itemSelectionChanged.connect(self.on_input_selection_changed)
        layout.addWidget(self.input_tree)
        
        # File info
        self.input_info = QTextEdit()
        self.input_info.setMaximumHeight(100)
        self.input_info.setReadOnly(True)
        layout.addWidget(self.input_info)
        
        group.setLayout(layout)
        return group
        
    def create_output_section(self):
        """Create the output files section."""
        group = QGroupBox("Output Files")
        layout = QVBoxLayout()
        
        # Output directory selection
        dir_layout = QHBoxLayout()
        
        self.output_dir_label = QLabel(str(self.output_directory))
        self.output_dir_label.setStyleSheet("border: 1px solid #555; padding: 5px;")
        
        self.browse_output_button = QPushButton("Browse")
        self.browse_output_button.clicked.connect(self.browse_output_directory)
        
        dir_layout.addWidget(QLabel("Output Directory:"))
        dir_layout.addWidget(self.output_dir_label)
        dir_layout.addWidget(self.browse_output_button)
        
        layout.addLayout(dir_layout)
        
        # Output file tree
        self.output_tree = QTreeWidget()
        self.output_tree.setHeaderLabels(["File", "Size", "Modified"])
        self.output_tree.itemSelectionChanged.connect(self.on_output_selection_changed)
        layout.addWidget(self.output_tree)
        
        # Output file preview
        self.output_preview = QTextEdit()
        self.output_preview.setMaximumHeight(100)
        self.output_preview.setReadOnly(True)
        layout.addWidget(self.output_preview)
        
        # Output buttons
        output_button_layout = QHBoxLayout()
        
        self.open_output_button = QPushButton("Open in Editor")
        self.open_output_button.clicked.connect(self.open_output_file)
        
        self.delete_output_button = QPushButton("Delete Selected")
        self.delete_output_button.clicked.connect(self.delete_output_file)
        
        output_button_layout.addWidget(self.open_output_button)
        output_button_layout.addWidget(self.delete_output_button)
        output_button_layout.addStretch()
        
        layout.addLayout(output_button_layout)
        
        group.setLayout(layout)
        return group
        
    def create_progress_section(self):
        """Create the progress monitoring section."""
        group = QGroupBox("Translation Progress")
        layout = QVBoxLayout()
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        # Status and options
        status_layout = QHBoxLayout()
        
        self.status_label = QLabel("Ready")
        self.backup_cb = QCheckBox("Create Backups")
        self.backup_cb.setChecked(True)
        
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        status_layout.addWidget(self.backup_cb)
        
        layout.addLayout(status_layout)
        
        group.setLayout(layout)
        return group
        
    def add_input_files(self):
        """Add input files via dialog."""
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Input Files",
            "",
            "JSON Files (*.json);;All Files (*)"
        )
        
        for file_path in files:
            if file_path not in self.input_files:
                self.input_files.append(file_path)
                
        self.refresh_input_files()
        
    def add_input_folder(self):
        """Add all files from a folder."""
        folder = QFileDialog.getExistingDirectory(self, "Select Input Folder")
        
        if folder:
            folder_path = Path(folder)
            for file_path in folder_path.rglob("*.json"):
                file_str = str(file_path)
                if file_str not in self.input_files:
                    self.input_files.append(file_str)
                    
        self.refresh_input_files()
        
    def remove_selected_files(self):
        """Remove selected input files."""
        selected_items = self.input_tree.selectedItems()
        for item in selected_items:
            file_path = item.text(0)
            if file_path in self.input_files:
                self.input_files.remove(file_path)
                
        self.refresh_input_files()
        
    def clear_input_files(self):
        """Clear all input files."""
        self.input_files.clear()
        self.refresh_input_files()
        
    def refresh_input_files(self):
        """Refresh the input files display."""
        self.input_tree.clear()
        
        for file_path in self.input_files:
            path_obj = Path(file_path)
            if path_obj.exists():
                size = path_obj.stat().st_size
                file_type = path_obj.suffix
                
                item = QTreeWidgetItem([
                    path_obj.name,
                    f"{size:,} bytes",
                    file_type
                ])
                item.setToolTip(0, str(path_obj))
                self.input_tree.addTopLevelItem(item)
            else:
                # File doesn't exist - show in red
                item = QTreeWidgetItem([
                    f"{path_obj.name} (Missing)",
                    "0 bytes",
                    "N/A"
                ])
                item.setBackground(0, Qt.red)
                self.input_tree.addTopLevelItem(item)
                
        # Update info
        self.update_input_info()
        
    def refresh_output_files(self):
        """Refresh the output files display."""
        self.output_tree.clear()
        
        if self.output_directory.exists():
            for file_path in self.output_directory.iterdir():
                if file_path.is_file():
                    size = file_path.stat().st_size
                    modified = file_path.stat().st_mtime
                    
                    import datetime
                    modified_str = datetime.datetime.fromtimestamp(modified).strftime("%Y-%m-%d %H:%M")
                    
                    item = QTreeWidgetItem([
                        file_path.name,
                        f"{size:,} bytes",
                        modified_str
                    ])
                    item.setToolTip(0, str(file_path))
                    self.output_tree.addTopLevelItem(item)
                    
    def browse_output_directory(self):
        """Browse for output directory."""
        directory = QFileDialog.getExistingDirectory(
            self, "Select Output Directory", str(self.output_directory)
        )
        
        if directory:
            self.output_directory = Path(directory)
            self.output_dir_label.setText(str(self.output_directory))
            self.refresh_output_files()
            
    def refresh_files(self):
        """Refresh both input and output file displays."""
        self.refresh_input_files()
        self.refresh_output_files()
        
    def on_input_selection_changed(self):
        """Handle input file selection change."""
        selected_items = self.input_tree.selectedItems()
        if selected_items:
            item = selected_items[0]
            file_name = item.text(0)
            
            # Find the full path
            full_path = None
            for file_path in self.input_files:
                if Path(file_path).name == file_name:
                    full_path = file_path
                    break
                    
            if full_path and Path(full_path).exists():
                try:
                    with open(full_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        
                    # Show preview of file structure
                    if full_path.endswith('.json'):
                        data = json.loads(content)
                        if isinstance(data, dict):
                            keys = list(data.keys())[:10]  # Show first 10 keys
                            preview = f"JSON Object with {len(data)} keys:\n"
                            preview += "\n".join(keys)
                            if len(data) > 10:
                                preview += f"\n... and {len(data) - 10} more"
                        elif isinstance(data, list):
                            preview = f"JSON Array with {len(data)} items"
                        else:
                            preview = f"JSON: {type(data).__name__}"
                    else:
                        preview = content[:500] + "..." if len(content) > 500 else content
                        
                    self.input_info.setPlainText(preview)
                except Exception as e:
                    self.input_info.setPlainText(f"Error reading file: {str(e)}")
                    
    def on_output_selection_changed(self):
        """Handle output file selection change."""
        selected_items = self.output_tree.selectedItems()
        if selected_items:
            item = selected_items[0]
            file_name = item.text(0)
            file_path = self.output_directory / file_name
            
            if file_path.exists():
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        
                    preview = content[:500] + "..." if len(content) > 500 else content
                    self.output_preview.setPlainText(preview)
                except Exception as e:
                    self.output_preview.setPlainText(f"Error reading file: {str(e)}")
                    
    def open_output_file(self):
        """Open selected output file in external editor."""
        selected_items = self.output_tree.selectedItems()
        if selected_items:
            item = selected_items[0]
            file_name = item.text(0)
            file_path = self.output_directory / file_name
            
            if file_path.exists():
                import subprocess
                try:
                    subprocess.run(['notepad.exe', str(file_path)], check=True)
                except subprocess.CalledProcessError:
                    QMessageBox.warning(self, "Warning", "Could not open file in external editor")
                    
    def delete_output_file(self):
        """Delete selected output file."""
        selected_items = self.output_tree.selectedItems()
        if selected_items:
            item = selected_items[0]
            file_name = item.text(0)
            file_path = self.output_directory / file_name
            
            reply = QMessageBox.question(
                self,
                "Confirm Deletion",
                f"Are you sure you want to delete '{file_name}'?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes and file_path.exists():
                try:
                    file_path.unlink()
                    self.refresh_output_files()
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Failed to delete file:\n{str(e)}")
                    
    def update_input_info(self):
        """Update the input files information."""
        total_files = len(self.input_files)
        total_size = 0
        
        for file_path in self.input_files:
            path_obj = Path(file_path)
            if path_obj.exists():
                total_size += path_obj.stat().st_size
                
        info = f"Total Files: {total_files}\nTotal Size: {total_size:,} bytes"
        
        # Count by file type
        extensions = {}
        for file_path in self.input_files:
            ext = Path(file_path).suffix
            extensions[ext] = extensions.get(ext, 0) + 1
            
        if extensions:
            info += "\n\nFile Types:"
            for ext, count in sorted(extensions.items()):
                info += f"\n{ext or 'No extension'}: {count}"
                
        self.input_info.setPlainText(info)
        
    def get_input_files(self):
        """Get list of input files."""
        return self.input_files.copy()
        
    def get_output_directory(self):
        """Get output directory path."""
        return self.output_directory
