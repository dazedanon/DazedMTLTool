#!/usr/bin/env python3
"""
DazedMTLTool GUI - Main Application
A PyQt-based graphical user interface for the DazedMTLTool translation system.
"""

import re
import sys
import os
import json
import urllib.request
import zipfile
import shutil
import tempfile
from pathlib import Path
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QVBoxLayout, QHBoxLayout,
    QWidget, QPushButton, QLabel, QFileDialog, QMessageBox, QProgressBar,
    QTextEdit, QSplitter, QGroupBox, QStatusBar, QStackedWidget, QToolButton,
    QDialog
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QSettings
from PyQt5.QtGui import QIcon, QFont, QPixmap, QScreen


def _project_root() -> Path:
    """Directory containing start_gui.py / requirements.txt (parent of gui/)."""
    return Path(__file__).resolve().parent.parent


def load_application_icon() -> QIcon:
    """Prefer ICO on Windows; PNG is fine for all platforms. Empty if missing."""
    root = _project_root()
    for rel in ("assets/icon.ico", "assets/icon.png"):
        path = root / rel
        if path.is_file():
            icon = QIcon(str(path))
            if not icon.isNull():
                return icon
    return QIcon()


class UpdateThread(QThread):
    """Downloads and applies a tool update from the GitGud repository."""

    REPO_USER   = "DazedAnon"
    REPO_NAME   = "DazedMTLTool"
    REPO_BRANCH = "main"
    SHA_FILE    = "last_update_sha.txt"

    # Paths (relative, top-level) that should never be touched during update
    PROTECTED = {".env", "venv", "log", "files", "translated",
                 "vocab.txt", "last_update_sha.txt"}

    progress  = pyqtSignal(str)           # status message
    finished  = pyqtSignal(bool, str)     # (success, message)

    def __init__(self, check_only=False, parent=None):
        super().__init__(parent)
        self.check_only = check_only

    # ------------------------------------------------------------------ #

    def run(self):
        try:
            latest_sha = self._fetch_latest_sha()
            current_sha = self._read_stored_sha()

            if latest_sha == current_sha:
                self.finished.emit(True, "already_up_to_date")
                return

            if self.check_only:
                self.finished.emit(True, f"update_available:{latest_sha}")
                return

            self._download_and_apply(latest_sha)

        except Exception as exc:
            self.finished.emit(False, str(exc))

    # ------------------------------------------------------------------ #

    def _fetch_latest_sha(self):
        api = (
            f"https://gitgud.io/api/v4/projects/"
            f"{self.REPO_USER}%2F{self.REPO_NAME}"
            f"/repository/branches/{self.REPO_BRANCH}"
        )
        req = urllib.request.Request(api, headers={"User-Agent": "DazedMTLTool"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())["commit"]["id"]

    def _read_stored_sha(self):
        p = Path(self.SHA_FILE)
        return p.read_text().strip() if p.exists() else ""

    def _download_and_apply(self, latest_sha):
        zip_url = (
            f"https://gitgud.io/{self.REPO_USER}/{self.REPO_NAME}/-/archive/"
            f"{self.REPO_BRANCH}/{self.REPO_NAME}-{self.REPO_BRANCH}.zip"
        )

        self.progress.emit("Downloading update…")
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp     = Path(tmp_dir)
            zip_path = tmp / "update.zip"

            req = urllib.request.Request(zip_url, headers={"User-Agent": "DazedMTLTool"})
            with urllib.request.urlopen(req, timeout=120) as resp, \
                 open(zip_path, "wb") as fh:
                shutil.copyfileobj(resp, fh)

            self.progress.emit("Extracting…")
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(tmp)

            extracted = tmp / f"{self.REPO_NAME}-{self.REPO_BRANCH}"
            root      = Path(".").resolve()

            self.progress.emit("Applying update…")
            for src in extracted.rglob("*"):
                rel   = src.relative_to(extracted)
                parts = rel.parts
                if not parts or parts[0] in self.PROTECTED:
                    continue
                dst = root / rel
                if src.is_dir():
                    dst.mkdir(parents=True, exist_ok=True)
                else:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)

        Path(self.SHA_FILE).write_text(latest_sha)
        self.finished.emit(True, f"updated:{latest_sha[:8]}")


class UpdateDialog(QDialog):
    """Modal dialog that shows update progress and result."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tool Update")
        self.setMinimumWidth(420)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        self.status_label = QLabel("Checking for updates…")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)   # indeterminate
        layout.addWidget(self.progress_bar)

        self.close_btn = QPushButton("Cancel")
        self.close_btn.clicked.connect(self.reject)
        layout.addWidget(self.close_btn)

        self._thread = None

    def start(self, check_only=False):
        self._thread = UpdateThread(check_only=check_only, parent=self)
        self._thread.progress.connect(self.status_label.setText)
        self._thread.finished.connect(self._on_finished)
        self._thread.start()

    def _on_finished(self, success, message):
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1)
        self.close_btn.setText("Close")

        if not success:
            self.status_label.setText(f"❌ Update failed:\n{message}")
            return

        if message == "already_up_to_date":
            self.status_label.setText("✅ Already up to date.")
        elif message.startswith("update_available:"):
            sha = message.split(":", 1)[1]
            self.status_label.setText(
                f"🆕 Update available ({sha[:8]}).\nClick 'Update Now' to install."
            )
            self.close_btn.setText("Cancel")
            update_btn = QPushButton("Update Now")
            update_btn.clicked.connect(self._do_update)
            self.layout().insertWidget(self.layout().count() - 1, update_btn)
        elif message.startswith("updated:"):
            sha = message.split(":", 1)[1]
            self.status_label.setText(
                f"✅ Updated to {sha}.\n\nPlease restart the tool for changes to take effect."
            )

    def _do_update(self):
        # Remove any extra buttons so only the close button remains
        for i in reversed(range(self.layout().count())):
            item = self.layout().itemAt(i)
            if item and item.widget() and item.widget() is not self.close_btn:
                w = item.widget()
                if isinstance(w, QPushButton) and w.text() in ("Update Now", "Cancel"):
                    if w.text() != "Close":
                        self.layout().removeWidget(w)
                        w.deleteLater()
        self.progress_bar.setRange(0, 0)
        self.status_label.setText("Downloading update…")
        self.start(check_only=False)

# Import configuration widgets
from gui.config_tab import ConfigTab
from gui.translation_tab import TranslationTab
from gui.workflow_tab import WorkflowTab
from gui.rewrite_tab import RewriteTab

class DazedMTLGUI(QMainWindow):
    """Main GUI window for the DazedMTLTool."""
    
    def __init__(self):
        super().__init__()
        self.settings = QSettings("DazedTranslations", "DazedMTLTool")
        self.init_ui()
        self.setup_status_bar()
        self.setup_font_scaling()
        self.restore_window_state()
        
    def restore_window_state(self):
        """Restore window geometry and state from settings."""
        try:
            # Restore window geometry
            geometry = self.settings.value("geometry")
            if geometry:
                self.restoreGeometry(geometry)
            
            # Restore window state (maximized, etc.)
            window_state = self.settings.value("windowState")
            if window_state:
                self.restoreState(window_state)
                
        except Exception as e:
            print(f"Warning: Could not restore window state: {e}")
            
    def save_window_state(self):
        """Save window geometry and state to settings."""
        try:
            self.settings.setValue("geometry", self.saveGeometry())
            self.settings.setValue("windowState", self.saveState())
        except Exception as e:
            print(f"Warning: Could not save window state: {e}")
            
    def closeEvent(self, event):
        """Handle application close event."""
        # Save window geometry/state
        try:
            self.save_window_state()
        except Exception:
            pass

        # Attempt to stop any running translation worker to ensure
        # ThreadPoolExecutors and subprocesses are shut down so the
        # Python process can exit cleanly.
        try:
            if hasattr(self, 'translation_tab') and self.translation_tab:
                tt = self.translation_tab
                # Stop log tailing first (if active)
                try:
                    if hasattr(tt, 'translation_log_viewer') and tt.translation_log_viewer:
                        tt.translation_log_viewer.stop_tail()
                except Exception:
                    pass

                # If a worker exists and is running, request it to stop and wait
                try:
                    if hasattr(tt, 'translation_worker') and tt.translation_worker and tt.translation_worker.isRunning():
                        tt.translation_worker.stop()
                        # Wait up to 5s for graceful stop, otherwise terminate
                        if not tt.translation_worker.wait(5000):
                            try:
                                tt.translation_worker.terminate()
                                tt.translation_worker.wait(2000)
                            except Exception:
                                pass
                except Exception:
                    pass
        except Exception:
            pass

        event.accept()
        
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
            if not app:
                return

            # Scale the application default font (affects widgets without inline font-size)
            font = app.font()
            font.setPointSize(max(6, int(9 * scale_factor)))
            app.setFont(font)

            # Scale inline font-size values in every widget's individual stylesheet.
            # We store the *original* stylesheet on each widget (using a Qt property)
            # so that re-scaling always starts from the unmodified values.
            for widget in app.allWidgets():
                original = widget.property("_orig_stylesheet")
                if original is None:
                    ss = widget.styleSheet()
                    if not ss or 'font-size' not in ss:
                        continue
                    widget.setProperty("_orig_stylesheet", ss)
                    original = ss

                scaled = re.sub(
                    r'font-size:\s*(\d+(?:\.\d+)?)px',
                    lambda m: f'font-size: {max(6, round(float(m.group(1)) * scale_factor))}px',
                    original
                )
                widget.setStyleSheet(scaled)

            # Update window title only when non-default scale is active
            if scale_factor != 1.0:
                self.setWindowTitle(f"DazedMTLTool - Visual Translation Interface (Font: {scale_factor:.1f}x)")
            else:
                self.setWindowTitle("DazedMTLTool - Visual Translation Interface")

        except Exception as e:
            print(f"Warning: Could not apply font scaling: {e}")
        
    def init_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle("DazedMTLTool - Visual Translation Interface")
        
        # Get screen geometry and set window size more responsively
        screen = QApplication.primaryScreen()
        screen_geometry = screen.availableGeometry()
        
        # Set window size to 80% of screen size, with reasonable minimums
        window_width = max(1200, int(screen_geometry.width() * 0.8))
        window_height = max(800, int(screen_geometry.height() * 0.8))
        
        # Center the window on screen
        x = (screen_geometry.width() - window_width) // 2
        y = (screen_geometry.height() - window_height) // 2
        
        self.setGeometry(x, y, window_width, window_height)
        
        # Set minimum size to prevent the window from becoming too small
        self.setMinimumSize(1000, 600)
        
        app_icon = load_application_icon()
        if not app_icon.isNull():
            self.setWindowIcon(app_icon)
        
        # Create central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Create main layout with VSCode-style sidebar
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Create sidebar for navigation
        sidebar = QWidget()
        sidebar.setFixedWidth(60)
        sidebar.setStyleSheet("""
            QWidget {
                background-color: #2d2d30;
            }
        """)
        sidebar_layout = QVBoxLayout()
        sidebar_layout.setContentsMargins(0, 10, 0, 10)
        sidebar_layout.setSpacing(2)
        
        # Create navigation buttons
        self.nav_buttons = []
        
        # Translation button (first)
        btn_translation = self.create_nav_button("🌐", "Translation")
        btn_translation.clicked.connect(lambda: self.switch_page(0))
        sidebar_layout.addWidget(btn_translation)
        self.nav_buttons.append(btn_translation)

        # Workflow / Automation button (second)
        btn_workflow = self.create_nav_button("⚡", "Workflow")
        btn_workflow.setToolTip("Workflow — automated translation pipeline")
        btn_workflow.clicked.connect(lambda: self.switch_page(1))
        sidebar_layout.addWidget(btn_workflow)
        self.nav_buttons.append(btn_workflow)

        # Configuration button (third)
        btn_config = self.create_nav_button("⚙️", "Configuration")
        btn_config.clicked.connect(lambda: self.switch_page(2))
        sidebar_layout.addWidget(btn_config)
        self.nav_buttons.append(btn_config)

        # Rewrite button (fourth)
        btn_rewrite = self.create_nav_button("✏️", "Rewrite")
        btn_rewrite.setToolTip("Rewrite — fix over-limit dialogue messages")
        btn_rewrite.clicked.connect(lambda: self.switch_page(3))
        sidebar_layout.addWidget(btn_rewrite)
        self.nav_buttons.append(btn_rewrite)
        
        sidebar_layout.addStretch()

        # Update button at the bottom of the sidebar
        btn_update = self.create_nav_button("🔄", "Check for Updates")
        btn_update.setCheckable(False)
        btn_update.clicked.connect(self.show_update_dialog)
        sidebar_layout.addWidget(btn_update)

        sidebar.setLayout(sidebar_layout)
        
        # Create stacked widget for content pages
        self.content_stack = QStackedWidget()
        
        # Add tabs to stacked widget
        self.setup_tabs()
        
        # Add sidebar and content to main layout
        main_layout.addWidget(sidebar)
        main_layout.addWidget(self.content_stack)
        central_widget.setLayout(main_layout)
        
        # Create menu bar
        self.create_menu_bar()
        
        # Select first page by default
        self.switch_page(0)
    
    def create_nav_button(self, icon_text, tooltip):
        """Create a navigation button for the sidebar."""
        btn = QToolButton()
        btn.setText(icon_text)
        btn.setToolTip(tooltip)
        btn.setFixedSize(60, 50)
        btn.setCheckable(True)
        btn.setStyleSheet("""
            QToolButton {
                background-color: transparent;
                border: none;
                border-left: 3px solid transparent;
                color: #cccccc;
                font-size: 24px;
                padding: 5px;
            }
            QToolButton:hover {
                background-color: #3e3e42;
            }
            QToolButton:checked {
                background-color: #37373d;
                border-left: 3px solid #007acc;
                color: #ffffff;
            }
        """)
        return btn
    
    def switch_page(self, index):
        """Switch to the specified page and update button states."""
        self.content_stack.setCurrentIndex(index)
        
        # Update button checked states
        for i, btn in enumerate(self.nav_buttons):
            btn.setChecked(i == index)
        
    def setup_tabs(self):
        """Set up all the tabs in the interface."""
        # Translation Execution Tab (index 0)
        self.translation_tab = TranslationTab(self)
        self.content_stack.addWidget(self.translation_tab)

        # Workflow / Automation Tab (index 1)
        self.workflow_tab = WorkflowTab(self)
        self.content_stack.addWidget(self.workflow_tab)

        # Configuration Tab (index 2)
        self.config_tab = ConfigTab()
        self.config_tab.config_changed.connect(self.on_config_changed)
        self.content_stack.addWidget(self.config_tab)

        # Rewrite Tab (index 3)
        self.rewrite_tab = RewriteTab(self)
        self.content_stack.addWidget(self.rewrite_tab)
        
    def show_update_dialog(self):
        """Open the update dialog and check for a newer version."""
        dlg = UpdateDialog(self)
        dlg.start(check_only=True)
        dlg.exec_()

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
            
            # Update the configuration tab if it provides a font_scale widget
            try:
                if hasattr(self.config_tab, "font_scale_spin"):
                    self.config_tab.font_scale_spin.setValue(scale_factor)
            except Exception:
                # If the widget isn't present or fails to update, continue silently
                pass

            # Save to .env file if the config tab provides save functionality
            try:
                if hasattr(self.config_tab, "save_to_env"):
                    self.config_tab.save_to_env()
            except Exception:
                pass
            
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
        
    # Font Size submenu removed — font scaling menu was unreliable and has been removed
        
        tools_menu.addSeparator()

        # Check for updates
        update_action = tools_menu.addAction('Check for Updates')
        update_action.triggered.connect(self.show_update_dialog)

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
        """Set up the status bar (removed to save space)."""
        # Status bar removed to maximize space for content
        pass
        
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
                config_data = self.config_tab.get_config()
                
                import json
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(config_data, f, indent=2, ensure_ascii=False)
                    
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
            
    def validate_configuration(self):
        """Validate the current configuration."""
        try:
            # Validate configuration settings
            config_valid = self.config_tab.validate()
            
            if config_valid:
                QMessageBox.information(self, "Validation", "Configuration is valid!")
            else:
                QMessageBox.warning(self, "Validation", "Configuration has issues. Check the warnings.")
                
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
        """Update the status bar message (removed to save space)."""
        pass
        
    def show_progress(self, show=True):
        """Show or hide the progress bar (removed to save space)."""
        pass
        
    def set_progress(self, value):
        """Set the progress bar value (removed to save space)."""
        pass


def main():
    """Main entry point for the GUI application."""
    try:
        # Enable high DPI scaling before creating QApplication
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        
        # Additional DPI handling for better compatibility
        if hasattr(Qt, 'AA_DisableWindowContextHelpButton'):
            QApplication.setAttribute(Qt.AA_DisableWindowContextHelpButton, True)
            
        # Set high DPI scale factor policy
        if hasattr(QApplication, 'setHighDpiScaleFactorRoundingPolicy'):
            QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
        
        app = QApplication(sys.argv)

        # Windows taskbar groups by executable (python.exe) unless we set an explicit
        # AppUserModelID; combine with QApplication window icon so the pinned icon
        # matches the window instead of the Python launcher.
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    "DazedTranslations.DazedMTLTool.1"
                )
            except Exception:
                pass

        app_icon = load_application_icon()
        if not app_icon.isNull():
            app.setWindowIcon(app_icon)
        
        # Additional screen-aware settings
        screen = app.primaryScreen()
        if screen:
            dpi = screen.logicalDotsPerInch()
            print(f"Screen DPI: {dpi}")
            
    except Exception as e:
        print(f"Failed to create QApplication: {e}")
        print("Make sure PyQt5 is properly installed:")
        print("  pip install PyQt5>=5.15.0")
        return 1
    
    # Set application properties
    app.setApplicationName("DazedMTLTool")
    app.setApplicationVersion("1.0")
    app.setOrganizationName("DazedTranslations")
    
    # Apply dark theme with cleaner, more compact styling
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
            padding: 5px;
        }
        QTabBar::tab {
            background-color: #555555;
            color: #ffffff;
            padding: 8px 16px;
            margin-right: 2px;
            border: 1px solid #666666;
            border-bottom: none;
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
            font-weight: normal;
            border: 1px solid #444444;
            border-radius: 3px;
            margin-top: 8px;
            padding: 8px;
            color: #ffffff;
            background-color: transparent;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 8px;
            padding: 2px 5px;
            color: #007acc;
            background-color: #2b2b2b;
            font-weight: bold;
        }
        QPushButton {
            background-color: #0078d4;
            color: white;
            border: none;
            padding: 7px 14px;
            border-radius: 3px;
            font-weight: bold;
        }
        QPushButton:hover {
            background-color: #106ebe;
        }
        QPushButton:pressed {
            background-color: #005a9e;
        }
        QPushButton:disabled {
            background-color: #404040;
            color: #888888;
        }
        QCheckBox {
            color: #ffffff;
            spacing: 6px;
            background-color: transparent;
            padding: 2px;
        }
        QCheckBox::indicator {
            width: 16px;
            height: 16px;
        }
        QCheckBox::indicator:unchecked {
            background-color: #404040;
            border: 1px solid #555555;
            border-radius: 2px;
        }
        QCheckBox::indicator:checked {
            background-color: #0078d4;
            border: 1px solid #0078d4;
            border-radius: 2px;
        }
        QLabel {
            color: #ffffff;
            background-color: transparent;
            padding: 2px;
        }
        QLineEdit {
            background-color: #404040;
            color: #ffffff;
            border: 1px solid #555555;
            padding: 5px 8px;
            border-radius: 2px;
            selection-background-color: #007acc;
        }
        QLineEdit:focus {
            border: 1px solid #007acc;
        }
        QSpinBox, QDoubleSpinBox {
            background-color: #404040;
            color: #ffffff;
            border: 1px solid #555555;
            padding: 5px 8px;
            border-radius: 2px;
        }
        QSpinBox:focus, QDoubleSpinBox:focus {
            border: 1px solid #007acc;
        }
        QSpinBox::up-button, QDoubleSpinBox::up-button {
            background-color: #555555;
            border: none;
            border-radius: 0;
        }
        QSpinBox::down-button, QDoubleSpinBox::down-button {
            background-color: #555555;
            border: none;
            border-radius: 0;
        }
        QComboBox {
            background-color: #404040;
            color: #ffffff;
            border: 1px solid #555555;
            padding: 5px;
            padding-right: 30px;
            border-radius: 2px;
        }
        QComboBox:focus {
            border: 1px solid #007acc;
        }
        QComboBox::drop-down {
            subcontrol-origin: padding;
            subcontrol-position: center right;
            width: 25px;
            border-left: 1px solid #555555;
            background-color: #555555;
        }
        QComboBox::drop-down:hover {
            background-color: #007acc;
        }
        QComboBox::down-arrow {
            width: 0;
            height: 0;
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
            border-top: 6px solid #ffffff;
        }
        QComboBox QAbstractItemView {
            background-color: #404040;
            color: #ffffff;
            selection-background-color: #007acc;
            border: 1px solid #555555;
            padding: 3px;
        }
        QTextEdit {
            background-color: #1e1e1e;
            color: #ffffff;
            border: 1px solid #555555;
            selection-background-color: #007acc;
            padding: 5px;
        }
        QTextEdit:focus {
            border: 1px solid #007acc;
        }
        QScrollArea {
            background-color: transparent;
            border: none;
        }
        QScrollBar:vertical {
            background-color: #2b2b2b;
            width: 12px;
            border: none;
        }
        QScrollBar::handle:vertical {
            background-color: #555555;
            border-radius: 6px;
            min-height: 20px;
            margin: 2px;
        }
        QScrollBar::handle:vertical:hover {
            background-color: #007acc;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0px;
        }
        QScrollBar:horizontal {
            background-color: #2b2b2b;
            height: 12px;
            border: none;
        }
        QScrollBar::handle:horizontal {
            background-color: #555555;
            border-radius: 6px;
            min-width: 20px;
            margin: 2px;
        }
        QScrollBar::handle:horizontal:hover {
            background-color: #007acc;
        }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
            width: 0px;
        }
        QListWidget {
            background-color: #1e1e1e;
            color: #ffffff;
            border: 1px solid #555555;
            selection-background-color: #007acc;
            padding: 3px;
        }
        QListWidget::item {
            padding: 5px;
            border-bottom: 1px solid #333333;
        }
        QListWidget::item:selected {
            background-color: #007acc;
            color: #ffffff;
        }
        QListWidget::item:hover {
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
            height: 20px;
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
            padding: 6px 20px;
        }
        QMenu::item:selected {
            background-color: #007acc;
        }
        QFrame[frameShape="4"], QFrame[frameShape="5"] {
            color: #555555;
        }
        QSplitter::handle {
            background-color: #555555;
        }
        QSplitter::handle:hover {
            background-color: #007acc;
        }
    """)
    
    try:
        # Create and show the main window
        window = DazedMTLGUI()
        window.show()

        # Safety: ensure any running translation worker is stopped when the
        # application is quitting (aboutToQuit). This helps guarantee the
        # ThreadPoolExecutor threads and subprocesses are shut down so the
        # Python interpreter can exit cleanly.
        def _on_about_to_quit():
            try:
                if hasattr(window, 'translation_tab') and window.translation_tab:
                    tt = window.translation_tab
                    try:
                        if hasattr(tt, 'translation_log_viewer') and tt.translation_log_viewer:
                            tt.translation_log_viewer.stop_tail()
                    except Exception:
                        pass

                    try:
                        if hasattr(tt, 'translation_worker') and tt.translation_worker and tt.translation_worker.isRunning():
                            tt.translation_worker.stop()
                            # Wait briefly for graceful shutdown
                            if not tt.translation_worker.wait(3000):
                                try:
                                    tt.translation_worker.terminate()
                                    tt.translation_worker.wait(2000)
                                except Exception:
                                    pass
                    except Exception:
                        pass
            except Exception:
                pass

        try:
            app.aboutToQuit.connect(_on_about_to_quit)
        except Exception:
            pass
        
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
