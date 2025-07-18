#!/usr/bin/env python3
"""
DazedMTLTool GUI - Main Application
A PyQt-based graphical user interface for the DazedMTLTool translation system.
"""

import sys
import os
import json
from pathlib import Path
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QVBoxLayout, QHBoxLayout,
    QWidget, QPushButton, QLabel, QFileDialog, QMessageBox, QProgressBar,
    QTextEdit, QSplitter, QGroupBox, QStatusBar
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QIcon, QFont, QPixmap

# Import configuration widgets
from gui.config_tab import ConfigTab
from gui.rpgmaker_tab import RPGMakerTab
from gui.other_modules_tab import OtherModulesTab
from gui.log_viewer import LogViewer
from gui.file_manager import FileManager
from gui.translation_tab import TranslationTab

class DazedMTLGUI(QMainWindow):
    """Main GUI window for the DazedMTLTool."""
    
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.setup_status_bar()
        self.setup_font_scaling()
        
    def setup_font_scaling(self):
        """Set up font scaling based on configuration."""
        try:
            from dotenv import load_dotenv
            import os
            
            # Load environment variables
            load_dotenv()
            
            # Get font scale setting
            font_scale = float(os.getenv("font_scale", "1.0"))
            
            # Apply font scaling
            self.apply_font_scaling(font_scale)
            
        except Exception as e:
            print(f"Warning: Could not apply font scaling: {e}")
            
    def apply_font_scaling(self, scale_factor):
        """Apply font scaling to the entire application."""
        try:
            app = QApplication.instance()
            if app:
                # Get the default font
                font = app.font()
                base_size = 9  # Base font size
                new_size = int(base_size * scale_factor)
                font.setPointSize(new_size)
                app.setFont(font)
                
                # Also update window title to show scaling
                if scale_factor != 1.0:
                    self.setWindowTitle(f"DazedMTLTool - Visual Translation Interface (Font: {scale_factor:.1f}x)")
                else:
                    self.setWindowTitle("DazedMTLTool - Visual Translation Interface")
                    
        except Exception as e:
            print(f"Warning: Could not apply font scaling: {e}")
        
    def init_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle("DazedMTLTool - Visual Translation Interface")
        self.setGeometry(100, 100, 1200, 800)
        
        # Set window icon if available
        icon_path = Path("screens/tool.png")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        
        # Create central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Create main splitter
        main_splitter = QSplitter(Qt.Horizontal)
        
        # Create tab widget
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabPosition(QTabWidget.North)
        
        # Add tabs
        self.setup_tabs()
        
        # Create log viewer
        self.log_viewer = LogViewer()
        
        # Add widgets to splitter
        main_splitter.addWidget(self.tab_widget)
        main_splitter.addWidget(self.log_viewer)
        main_splitter.setSizes([800, 400])
        
        # Set main layout
        layout = QVBoxLayout()
        layout.addWidget(main_splitter)
        central_widget.setLayout(layout)
        
        # Create menu bar
        self.create_menu_bar()
        
    def setup_tabs(self):
        """Set up all the tabs in the interface."""
        # Configuration Tab
        self.config_tab = ConfigTab()
        self.config_tab.config_changed.connect(self.on_config_changed)
        self.tab_widget.addTab(self.config_tab, "Configuration")
        
        # Translation Execution Tab (includes file management)
        self.translation_tab = TranslationTab(self)
        self.tab_widget.addTab(self.translation_tab, "Translation")
        
        # RPG Maker MV/MZ Tab
        self.rpgmaker_tab = RPGMakerTab()
        self.tab_widget.addTab(self.rpgmaker_tab, "RPG Maker MV/MZ")
        
        # Other Modules Tab
        self.other_modules_tab = OtherModulesTab()
        self.tab_widget.addTab(self.other_modules_tab, "Other Modules")
        
    def on_config_changed(self):
        """Handle configuration changes."""
        # This will be called when font scale or other settings change
        try:
            config = self.config_tab.get_config()
            font_scale = config.get("font_scale", 1.0)
            self.apply_font_scaling(font_scale)
        except Exception as e:
            print(f"Warning: Could not apply configuration changes: {e}")
            
    def set_font_scale(self, scale_factor):
        """Set the font scale and update the configuration."""
        try:
            # Apply the scaling immediately
            self.apply_font_scaling(scale_factor)
            
            # Update the configuration tab
            self.config_tab.font_scale_spin.setValue(scale_factor)
            
            # Save to .env file
            self.config_tab.save_to_env()
            
            self.status_label.setText(f"Font scale set to {scale_factor:.1f}x")
            
        except Exception as e:
            QMessageBox.warning(self, "Warning", f"Failed to set font scale: {str(e)}")
        
    def create_menu_bar(self):
        """Create the menu bar."""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu('File')
        
        # Load project action
        load_action = file_menu.addAction('Load Project')
        load_action.triggered.connect(self.load_project)
        
        # Save project action
        save_action = file_menu.addAction('Save Project')
        save_action.triggered.connect(self.save_project)
        
        file_menu.addSeparator()
        
        # Exit action
        exit_action = file_menu.addAction('Exit')
        exit_action.triggered.connect(self.close)
        
        # Tools menu
        tools_menu = menubar.addMenu('Tools')
        
        # Font Size submenu
        font_menu = tools_menu.addMenu('Font Size')
        
        # Font size actions
        small_font_action = font_menu.addAction('Small (0.8x)')
        small_font_action.triggered.connect(lambda: self.set_font_scale(0.8))
        
        normal_font_action = font_menu.addAction('Normal (1.0x)')
        normal_font_action.triggered.connect(lambda: self.set_font_scale(1.0))
        
        large_font_action = font_menu.addAction('Large (1.5x)')
        large_font_action.triggered.connect(lambda: self.set_font_scale(1.5))
        
        xlarge_font_action = font_menu.addAction('Extra Large (2.0x)')
        xlarge_font_action.triggered.connect(lambda: self.set_font_scale(2.0))
        
        tools_menu.addSeparator()
        
        # Reset to defaults
        reset_action = tools_menu.addAction('Reset to Defaults')
        reset_action.triggered.connect(self.reset_to_defaults)
        
        # Validate configuration
        validate_action = tools_menu.addAction('Validate Configuration')
        validate_action.triggered.connect(self.validate_configuration)
        
        # Help menu
        help_menu = menubar.addMenu('Help')
        
        # About action
        about_action = help_menu.addAction('About')
        about_action.triggered.connect(self.show_about)
        
    def setup_status_bar(self):
        """Set up the status bar."""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        # Add status labels
        self.status_label = QLabel("Ready")
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        
        self.status_bar.addWidget(self.status_label)
        self.status_bar.addPermanentWidget(self.progress_bar)
        
    def load_project(self):
        """Load a project configuration."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            "Load Project Configuration", 
            "", 
            "JSON Files (*.json);;All Files (*)"
        )
        
        if file_path:
            try:
                # Load configuration from file
                self.config_tab.load_from_file(file_path)
                self.rpgmaker_tab.load_from_file(file_path)
                self.status_label.setText(f"Loaded project: {Path(file_path).name}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load project:\n{str(e)}")
                
    def save_project(self):
        """Save the current project configuration."""
        file_path, _ = QFileDialog.getSaveFileName(
            self, 
            "Save Project Configuration", 
            "", 
            "JSON Files (*.json);;All Files (*)"
        )
        
        if file_path:
            try:
                # Save configuration to file
                config_data = {}
                config_data.update(self.config_tab.get_config())
                config_data.update(self.rpgmaker_tab.get_config())
                
                import json
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(config_data, f, indent=2, ensure_ascii=False)
                    
                self.status_label.setText(f"Saved project: {Path(file_path).name}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save project:\n{str(e)}")
                
    def reset_to_defaults(self):
        """Reset all configurations to default values."""
        reply = QMessageBox.question(
            self, 
            "Reset to Defaults", 
            "Are you sure you want to reset all settings to their default values?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.config_tab.reset_to_defaults()
            self.rpgmaker_tab.reset_to_defaults()
            self.status_label.setText("Reset to defaults")
            
    def validate_configuration(self):
        """Validate the current configuration."""
        try:
            # Validate configuration settings
            config_valid = self.config_tab.validate()
            rpgmaker_valid = self.rpgmaker_tab.validate()
            
            if config_valid and rpgmaker_valid:
                QMessageBox.information(self, "Validation", "Configuration is valid!")
                self.status_label.setText("Configuration validated")
            else:
                QMessageBox.warning(self, "Validation", "Configuration has issues. Check the log for details.")
                
        except Exception as e:
            QMessageBox.critical(self, "Validation Error", f"Failed to validate configuration:\n{str(e)}")
            
    def show_about(self):
        """Show the about dialog."""
        QMessageBox.about(
            self, 
            "About DazedMTLTool GUI",
            """
            <h3>DazedMTLTool GUI</h3>
            <p>A visual interface for the DazedMTLTool translation system.</p>
            <p>This tool helps translate visual novels, RPG games, and other text-based content using AI translation services.</p>
            <p><b>Features:</b></p>
            <ul>
                <li>Visual configuration management</li>
                <li>Module-specific settings</li>
                <li>Real-time translation monitoring</li>
                <li>File management and organization</li>
            </ul>
            """
        )
        
    def update_status(self, message):
        """Update the status bar message."""
        self.status_label.setText(message)
        
    def show_progress(self, show=True):
        """Show or hide the progress bar."""
        self.progress_bar.setVisible(show)
        
    def set_progress(self, value):
        """Set the progress bar value (0-100)."""
        self.progress_bar.setValue(value)


def main():
    """Main entry point for the GUI application."""
    try:
        # Enable high DPI scaling before creating QApplication
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        
        app = QApplication(sys.argv)
    except Exception as e:
        print(f"Failed to create QApplication: {e}")
        print("Make sure PyQt5 is properly installed:")
        print("  pip install PyQt5>=5.15.0")
        return 1
    
    # Set application properties
    app.setApplicationName("DazedMTLTool")
    app.setApplicationVersion("1.0")
    app.setOrganizationName("DazedTranslations")
    
    # Apply dark theme (optional)
    app.setStyleSheet("""
        QMainWindow {
            background-color: #2b2b2b;
            color: #ffffff;
        }
        QWidget {
            background-color: #2b2b2b;
            color: #ffffff;
        }
        QTabWidget::pane {
            border: 1px solid #555555;
            background-color: #3c3c3c;
        }
        QTabBar::tab {
            background-color: #555555;
            color: #ffffff;
            padding: 8px 12px;
            margin-right: 2px;
            border: 1px solid #666666;
        }
        QTabBar::tab:selected {
            background-color: #007acc;
            color: #ffffff;
        }
        QTabBar::tab:hover {
            background-color: #666666;
            color: #ffffff;
        }
        QGroupBox {
            font-weight: bold;
            border: 2px solid #555555;
            border-radius: 5px;
            margin: 10px 0px;
            padding-top: 10px;
            color: #ffffff;
            background-color: #3c3c3c;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px 0 5px;
            color: #007acc;
            background-color: transparent;
        }
        QPushButton {
            background-color: #0078d4;
            color: white;
            border: none;
            padding: 6px 12px;
            border-radius: 3px;
            font-weight: bold;
        }
        QPushButton:hover {
            background-color: #106ebe;
        }
        QPushButton:pressed {
            background-color: #005a9e;
        }
        QCheckBox {
            color: #ffffff;
            spacing: 5px;
            background-color: transparent;
        }
        QCheckBox::indicator {
            width: 16px;
            height: 16px;
        }
        QCheckBox::indicator:unchecked {
            background-color: #404040;
            border: 1px solid #555555;
        }
        QCheckBox::indicator:checked {
            background-color: #0078d4;
            border: 1px solid #0078d4;
        }
        QLabel {
            color: #ffffff;
            background-color: transparent;
        }
        QLineEdit {
            background-color: #404040;
            color: #ffffff;
            border: 1px solid #555555;
            padding: 4px;
            border-radius: 2px;
        }
        QLineEdit:focus {
            border: 2px solid #007acc;
        }
        QSpinBox, QDoubleSpinBox {
            background-color: #404040;
            color: #ffffff;
            border: 1px solid #555555;
            padding: 4px;
            border-radius: 2px;
        }
        QSpinBox:focus, QDoubleSpinBox:focus {
            border: 2px solid #007acc;
        }
        QComboBox {
            background-color: #404040;
            color: #ffffff;
            border: 1px solid #555555;
            padding: 4px;
            border-radius: 2px;
        }
        QComboBox:focus {
            border: 2px solid #007acc;
        }
        QComboBox::drop-down {
            border: none;
            background-color: #555555;
        }
        QComboBox::down-arrow {
            image: none;
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            border-top: 4px solid #ffffff;
        }
        QComboBox QAbstractItemView {
            background-color: #404040;
            color: #ffffff;
            selection-background-color: #007acc;
            border: 1px solid #555555;
        }
        QTextEdit {
            background-color: #1e1e1e;
            color: #ffffff;
            border: 1px solid #555555;
            selection-background-color: #007acc;
        }
        QScrollArea {
            background-color: #2b2b2b;
            border: none;
        }
        QScrollBar:vertical {
            background-color: #404040;
            width: 12px;
            border-radius: 6px;
        }
        QScrollBar::handle:vertical {
            background-color: #666666;
            border-radius: 6px;
            margin: 2px;
        }
        QScrollBar::handle:vertical:hover {
            background-color: #007acc;
        }
        QScrollBar:horizontal {
            background-color: #404040;
            height: 12px;
            border-radius: 6px;
        }
        QScrollBar::handle:horizontal {
            background-color: #666666;
            border-radius: 6px;
            margin: 2px;
        }
        QScrollBar::handle:horizontal:hover {
            background-color: #007acc;
        }
        QTreeWidget {
            background-color: #1e1e1e;
            color: #ffffff;
            border: 1px solid #555555;
            selection-background-color: #007acc;
        }
        QTreeWidget::item {
            padding: 4px;
            border-bottom: 1px solid #333333;
        }
        QTreeWidget::item:selected {
            background-color: #007acc;
            color: #ffffff;
        }
        QTreeWidget::item:hover {
            background-color: #404040;
        }
        QHeaderView::section {
            background-color: #555555;
            color: #ffffff;
            padding: 6px;
            border: 1px solid #666666;
        }
        QStatusBar {
            background-color: #2b2b2b;
            color: #ffffff;
            border-top: 1px solid #555555;
        }
        QProgressBar {
            background-color: #404040;
            border: 1px solid #555555;
            border-radius: 3px;
            text-align: center;
            color: #ffffff;
        }
        QProgressBar::chunk {
            background-color: #007acc;
            border-radius: 2px;
        }
        QMenuBar {
            background-color: #2b2b2b;
            color: #ffffff;
            border-bottom: 1px solid #555555;
        }
        QMenuBar::item {
            padding: 6px 12px;
            background-color: transparent;
        }
        QMenuBar::item:selected {
            background-color: #007acc;
        }
        QMenu {
            background-color: #404040;
            color: #ffffff;
            border: 1px solid #555555;
        }
        QMenu::item {
            padding: 6px 12px;
        }
        QMenu::item:selected {
            background-color: #007acc;
        }
        QFrame[frameShape="4"] {
            color: #555555;
        }
        QFrame[frameShape="5"] {
            color: #555555;
        }
    """)
    
    try:
        # Create and show the main window
        window = DazedMTLGUI()
        window.show()
        
        # Show font adjustment tip on first run (optional)
        try:
            from dotenv import load_dotenv
            load_dotenv()
            show_font_tip = os.getenv("show_font_tip", "true").lower() == "true"
            
            if show_font_tip:
                QMessageBox.information(
                    window,
                    "Font Size Adjustment",
                    "💡 Font too small?\n\n"
                    "• Use Tools → Font Size menu for quick adjustment\n"
                    "• Or go to Configuration tab → UI Settings\n"
                    "• Try 'Large (1.5x)' or 'Extra Large (2.0x)' for high DPI displays\n\n"
                    "This tip can be disabled in the Configuration tab."
                )
                
                # Set flag to not show again
                from dotenv import set_key
                set_key(".env", "show_font_tip", "false")
                
        except Exception:
            pass  # Ignore if .env operations fail
        
        # Start the application
        return app.exec_()
    except Exception as e:
        print(f"Error starting GUI: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
