"""
Other Modules Tab - Configuration for other translation modules
"""

from pathlib import Path
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QCheckBox, QPushButton, 
    QGroupBox, QLabel, QScrollArea, QListWidget, QListWidgetItem,
    QMessageBox, QTextEdit, QFrame
)
from PyQt5.QtCore import Qt, pyqtSignal


class OtherModulesTab(QWidget):
    """Tab for configuring other translation modules."""
    
    config_changed = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self.modules_info = self.get_modules_info()
        self.init_ui()
        
    def init_ui(self):
        """Initialize the user interface."""
        main_layout = QVBoxLayout()
        
        # Create scroll area
        scroll_area = QScrollArea()
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout()
        
        # Title
        title_label = QLabel("Other Translation Modules")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #007acc;")
        scroll_layout.addWidget(title_label)
        
        # Description
        description_label = QLabel(
            "Configure settings for other game engines and file formats supported by DazedMTLTool."
        )
        description_label.setWordWrap(True)
        description_label.setStyleSheet("color: #cccccc; margin-bottom: 10px;")
        scroll_layout.addWidget(description_label)
        
        # Create module groups
        for category, modules in self.modules_info.items():
            group = self.create_module_group(category, modules)
            scroll_layout.addWidget(group)
            
        # Buttons
        button_layout = QHBoxLayout()
        
        self.refresh_button = QPushButton("Refresh Modules")
        self.refresh_button.clicked.connect(self.refresh_modules)
        
        self.enable_all_button = QPushButton("Enable All")
        self.enable_all_button.clicked.connect(self.enable_all_modules)
        
        self.disable_all_button = QPushButton("Disable All")
        self.disable_all_button.clicked.connect(self.disable_all_modules)
        
        button_layout.addWidget(self.refresh_button)
        button_layout.addWidget(self.enable_all_button)
        button_layout.addWidget(self.disable_all_button)
        button_layout.addStretch()
        
        scroll_layout.addLayout(button_layout)
        
        scroll_content.setLayout(scroll_layout)
        scroll_area.setWidget(scroll_content)
        scroll_area.setWidgetResizable(True)
        
        main_layout.addWidget(scroll_area)
        self.setLayout(main_layout)
        
    def get_modules_info(self):
        """Get information about available modules."""
        return {
            "Visual Novel Engines": {
                "kirikiri": "Kirikiri engine games (.ks, .tjs files)",
                "renpy": "Ren'Py visual novels (.rpy files)",
                "tyrano": "TyranoBuilder games",
                "nscript": "NScripter games",
                "lune": "Lune engine games"
            },
            "RPG Engines": {
                "rpgmakerace": "RPG Maker Ace (legacy)",
                "rpgmakerplugin": "RPG Maker plugins",
                "unity": "Unity engine games",
                "wolf": "Wolf RPG Editor games",
                "wolf2": "Wolf RPG Editor 2 games"
            },
            "File Formats": {
                "json": "Generic JSON files",
                "csv": "CSV/Excel files",
                "text": "Plain text files",
                "regex": "Custom regex patterns",
                "images": "Image text extraction"
            }
        }
        
    def create_module_group(self, category, modules):
        """Create a group for a category of modules."""
        group = QGroupBox(category)
        layout = QVBoxLayout()
        
        for module_name, description in modules.items():
            # Check if module file exists
            module_path = Path(f"modules/{module_name}.py")
            exists = module_path.exists()
            
            checkbox = QCheckBox(f"{module_name.upper()}")
            checkbox.setEnabled(exists)
            checkbox.setToolTip(description)
            
            if not exists:
                checkbox.setText(f"{module_name.upper()} (Not Found)")
                checkbox.setStyleSheet("color: #ff6b6b;")
            
            # Add description label
            desc_label = QLabel(description)
            desc_label.setStyleSheet("color: #aaaaaa; font-size: 11px; margin-left: 20px;")
            desc_label.setWordWrap(True)
            
            layout.addWidget(checkbox)
            layout.addWidget(desc_label)
            
            # Store reference for later use
            setattr(self, f"{module_name}_cb", checkbox)
            
        group.setLayout(layout)
        return group
        
    def refresh_modules(self):
        """Refresh the modules list."""
        # Clear current layout and rebuild
        self.modules_info = self.get_modules_info()
        
        # Find all Python files in modules directory
        modules_dir = Path("modules")
        if modules_dir.exists():
            found_modules = [f.stem for f in modules_dir.glob("*.py") if f.stem != "__init__"]
            
            info_text = f"Found {len(found_modules)} module files:\n"
            info_text += ", ".join(sorted(found_modules))
            
            QMessageBox.information(self, "Modules Refreshed", info_text)
        else:
            QMessageBox.warning(self, "Warning", "Modules directory not found!")
            
    def enable_all_modules(self):
        """Enable all available modules."""
        for category, modules in self.modules_info.items():
            for module_name in modules.keys():
                checkbox = getattr(self, f"{module_name}_cb", None)
                if checkbox and checkbox.isEnabled():
                    checkbox.setChecked(True)
                    
    def disable_all_modules(self):
        """Disable all modules."""
        for category, modules in self.modules_info.items():
            for module_name in modules.keys():
                checkbox = getattr(self, f"{module_name}_cb", None)
                if checkbox:
                    checkbox.setChecked(False)
                    
    def get_enabled_modules(self):
        """Get list of enabled modules."""
        enabled = []
        for category, modules in self.modules_info.items():
            for module_name in modules.keys():
                checkbox = getattr(self, f"{module_name}_cb", None)
                if checkbox and checkbox.isChecked():
                    enabled.append(module_name)
        return enabled
        
    def get_config(self):
        """Get current configuration."""
        return {
            "enabled_modules": self.get_enabled_modules()
        }
