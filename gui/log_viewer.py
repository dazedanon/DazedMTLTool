"""
Log Viewer - Real-time log display and monitoring
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton,
    QLabel, QCheckBox, QComboBox, QGroupBox, QSplitter, QSpinBox
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QTextCursor, QFont
from pathlib import Path
import datetime
import os


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
        
        # Performance optimization tracking
        self.file_mod_times = {}  # Track file modification times
        self.file_positions = {}  # Track file read positions for tail-only updates
        self.max_lines = 1000  # Maximum lines to display
        self.refresh_interval = 2000  # Default refresh interval in ms
        
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
        
        # Max lines control
        control_layout.addWidget(QLabel("Max Lines:"))
        self.max_lines_spinbox = QSpinBox()
        self.max_lines_spinbox.setRange(100, 10000)
        self.max_lines_spinbox.setValue(self.max_lines)
        self.max_lines_spinbox.setSingleStep(100)
        self.max_lines_spinbox.valueChanged.connect(self.update_max_lines)
        control_layout.addWidget(self.max_lines_spinbox)
        
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
            # Adjust refresh interval based on file size
            self.adjust_refresh_interval()
            self.auto_refresh_timer.start(self.refresh_interval)
            self.status_label.setText(f"Auto-refresh enabled ({self.refresh_interval/1000:.1f}s interval)")
        else:
            self.auto_refresh_timer.stop()
            self.status_label.setText("Auto-refresh disabled")
            
    def adjust_refresh_interval(self):
        """Adjust refresh interval based on current log file size."""
        selected_log = self.log_selector.currentText()
        if selected_log in self.log_files:
            log_path = Path(self.log_files[selected_log])
            if log_path.exists():
                file_size = log_path.stat().st_size
                # Increase interval for larger files
                if file_size > 500000:  # > 500KB
                    self.refresh_interval = 5000  # 5 seconds
                elif file_size > 100000:  # > 100KB
                    self.refresh_interval = 3000  # 3 seconds
                else:
                    self.refresh_interval = 2000  # 2 seconds
                    
    def update_max_lines(self, value):
        """Update maximum lines to display."""
        self.max_lines = value
        self.load_selected_log()  # Reload with new limit
            
    def load_selected_log(self):
        """Load the currently selected log file."""
        selected_log = self.log_selector.currentText()
        if selected_log in self.log_files:
            self.load_log_file(self.log_files[selected_log])
            
    def load_log_file(self, file_path):
        """Load content from a specific log file with optimization."""
        try:
            log_path = Path(file_path)
            if not log_path.exists():
                self.log_display.setPlainText(f"Log file not found: {file_path}")
                self.status_label.setText("Log file not found")
                return
                
            # Check if file has been modified since last read
            current_mod_time = log_path.stat().st_mtime
            last_mod_time = self.file_mod_times.get(file_path, 0)
            
            if current_mod_time <= last_mod_time and file_path in self.file_mod_times:
                # File hasn't changed, no need to reload
                return
                
            # Update modification time
            self.file_mod_times[file_path] = current_mod_time
            
            # Read file efficiently
            file_size = log_path.stat().st_size
            
            if file_size > 1000000:  # > 1MB, read only tail
                content = self.read_file_tail(log_path, self.max_lines)
            else:
                # For smaller files, read normally but limit lines
                with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    
                # Limit to max lines if content is too long
                lines = content.splitlines()
                if len(lines) > self.max_lines:
                    content = '\n'.join(lines[-self.max_lines:])
                    content = f"... (showing last {self.max_lines} lines) ...\n" + content
                    
            self.log_display.setPlainText(content)
            
            # Scroll to bottom
            cursor = self.log_display.textCursor()
            cursor.movePosition(QTextCursor.End)
            self.log_display.setTextCursor(cursor)
            
            # Update status
            lines_count = len(content.splitlines())
            self.status_label.setText(f"Loaded {log_path.name} ({file_size:,} bytes, {lines_count:,} lines)")
            
        except Exception as e:
            self.log_display.setPlainText(f"Error loading log file: {str(e)}")
            self.status_label.setText(f"Error: {str(e)}")
            
    def read_file_tail(self, file_path, max_lines):
        """Efficiently read the last N lines of a large file."""
        try:
            with open(file_path, 'rb') as f:
                # Start from end of file
                f.seek(0, 2)  # Seek to end
                file_size = f.tell()
                
                # Read chunks from end until we have enough lines
                lines = []
                chunk_size = min(8192, file_size)  # 8KB chunks
                pos = file_size
                
                while len(lines) < max_lines and pos > 0:
                    # Calculate chunk position
                    chunk_start = max(0, pos - chunk_size)
                    f.seek(chunk_start)
                    
                    # Read chunk
                    chunk = f.read(pos - chunk_start).decode('utf-8', errors='ignore')
                    chunk_lines = chunk.splitlines()
                    
                    # Prepend to lines list
                    if chunk_lines:
                        if lines and not chunk.endswith('\n'):
                            # Merge partial line at end of chunk with first existing line
                            chunk_lines[-1] += lines[0]
                            lines = chunk_lines + lines[1:]
                        else:
                            lines = chunk_lines + lines
                            
                    pos = chunk_start
                    
                # Return last max_lines
                if len(lines) > max_lines:
                    lines = lines[-max_lines:]
                    return f"... (showing last {max_lines} lines) ...\n" + '\n'.join(lines)
                else:
                    return '\n'.join(lines)
                    
        except Exception as e:
            return f"Error reading file tail: {str(e)}"
            
    def refresh_logs(self):
        """Refresh the current log display - only if tab is visible and file changed."""
        # Only refresh if widget is visible (optimization for when tab is not active)
        if not self.isVisible():
            return
            
        self.load_selected_log()
        
        # Readjust refresh interval if auto-refresh is enabled
        if self.auto_refresh_cb.isChecked():
            self.adjust_refresh_interval()
            if self.auto_refresh_timer.interval() != self.refresh_interval:
                self.auto_refresh_timer.stop()
                self.auto_refresh_timer.start(self.refresh_interval)
        
    def clear_log(self):
        """Clear the log display and reset tracking."""
        self.log_display.clear()
        # Reset modification time tracking to force reload on next refresh
        selected_log = self.log_selector.currentText()
        if selected_log in self.log_files:
            file_path = self.log_files[selected_log]
            if file_path in self.file_mod_times:
                del self.file_mod_times[file_path]
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
        
    def showEvent(self, event):
        """Handle widget show event - resume refresh if auto-refresh is enabled."""
        super().showEvent(event)
        if self.auto_refresh_cb.isChecked() and not self.auto_refresh_timer.isActive():
            self.auto_refresh_timer.start(self.refresh_interval)
            
    def hideEvent(self, event):
        """Handle widget hide event - pause refresh to save resources."""
        super().hideEvent(event)
        # Note: Don't stop timer completely as other parts may depend on it
        # The refresh_logs method now checks visibility anyway
