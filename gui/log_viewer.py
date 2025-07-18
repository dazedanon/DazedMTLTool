"""
Log Viewer - Real-time log display and monitoring
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton,
    QLabel, QCheckBox, QComboBox, QGroupBox, QSplitter
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QTextCursor, QFont
from pathlib import Path
import datetime


class LogViewer(QWidget):
    """Widget for viewing translation logs and monitoring progress."""
    
    log_updated = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.log_files = {
            "Translation History": "log/translationHistory.txt",
            "Mismatch History": "log/mismatchHistory.txt"
        }
        self.auto_refresh_timer = QTimer()
        self.auto_refresh_timer.timeout.connect(self.refresh_logs)
        self.init_ui()
        
    def init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout()
        
        # Control panel
        control_group = QGroupBox("Log Controls")
        control_layout = QHBoxLayout()
        
        # Log file selector
        self.log_selector = QComboBox()
        self.log_selector.addItems(list(self.log_files.keys()))
        self.log_selector.currentTextChanged.connect(self.load_selected_log)
        control_layout.addWidget(QLabel("Log File:"))
        control_layout.addWidget(self.log_selector)
        
        # Auto-refresh checkbox
        self.auto_refresh_cb = QCheckBox("Auto Refresh")
        self.auto_refresh_cb.toggled.connect(self.toggle_auto_refresh)
        control_layout.addWidget(self.auto_refresh_cb)
        
        # Manual refresh button
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh_logs)
        control_layout.addWidget(self.refresh_button)
        
        # Clear button
        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self.clear_log)
        control_layout.addWidget(self.clear_button)
        
        control_layout.addStretch()
        control_group.setLayout(control_layout)
        layout.addWidget(control_group)
        
        # Log display area
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setFont(QFont("Consolas", 10))
        self.log_display.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #ffffff;
                border: 1px solid #555555;
            }
        """)
        layout.addWidget(self.log_display)
        
        # Status bar
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #cccccc; padding: 5px;")
        layout.addWidget(self.status_label)
        
        self.setLayout(layout)
        
        # Initial load
        self.load_selected_log()
        
    def toggle_auto_refresh(self, enabled):
        """Toggle auto-refresh functionality."""
        if enabled:
            self.auto_refresh_timer.start(2000)  # Refresh every 2 seconds
            self.status_label.setText("Auto-refresh enabled")
        else:
            self.auto_refresh_timer.stop()
            self.status_label.setText("Auto-refresh disabled")
            
    def load_selected_log(self):
        """Load the currently selected log file."""
        selected_log = self.log_selector.currentText()
        if selected_log in self.log_files:
            self.load_log_file(self.log_files[selected_log])
            
    def load_log_file(self, file_path):
        """Load content from a specific log file."""
        try:
            log_path = Path(file_path)
            if log_path.exists():
                with open(log_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.log_display.setPlainText(content)
                
                # Scroll to bottom
                cursor = self.log_display.textCursor()
                cursor.movePosition(QTextCursor.End)
                self.log_display.setTextCursor(cursor)
                
                # Update status
                file_size = log_path.stat().st_size
                self.status_label.setText(f"Loaded {log_path.name} ({file_size} bytes)")
            else:
                self.log_display.setPlainText(f"Log file not found: {file_path}")
                self.status_label.setText("Log file not found")
        except Exception as e:
            self.log_display.setPlainText(f"Error loading log file: {str(e)}")
            self.status_label.setText(f"Error: {str(e)}")
            
    def refresh_logs(self):
        """Refresh the current log display."""
        self.load_selected_log()
        
    def clear_log(self):
        """Clear the log display."""
        self.log_display.clear()
        self.status_label.setText("Log cleared")
        
    def append_log_message(self, message):
        """Append a message to the log display."""
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] {message}"
        
        self.log_display.append(formatted_message)
        
        # Scroll to bottom
        cursor = self.log_display.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_display.setTextCursor(cursor)
        
    def get_current_log_content(self):
        """Get the current log content."""
        return self.log_display.toPlainText()
