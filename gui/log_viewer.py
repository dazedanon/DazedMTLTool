"""
Log Viewer - Real-time log display and monitoring
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QTextEdit, QLabel, QSizePolicy
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QTextCursor, QFont
from pathlib import Path
import datetime
import os


class LogViewer(QWidget):
    """Widget for viewing translation logs and monitoring progress."""
    
    log_updated = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        # Lightweight append-only log viewer. Logs are provided by the
        # translation worker via signals so we don't poll files or provide
        # controls here. This keeps the UI responsive.
        self.init_ui()
        
    def init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout()
        # Remove internal margins so header aligns with the left column's header
        layout.setContentsMargins(0, 0, 0, 0)

        # Simple header to match left-side styling (use same look as create_section_header)
        header = QLabel("📝 Translation Log")
        header.setStyleSheet("""
            QLabel {
                font-size: 13px;
                font-weight: bold;
                color: #007acc;
                padding: 8px 0px 5px 0px;
                background-color: transparent;
            }
        """)
        layout.addWidget(header, 0)

        # Match spacing used in left column so the gap between header and
        # content lines up visually.
        layout.setSpacing(8)

        # Log display area (append-only)
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
        # Make the log display expand to take available vertical space
        self.log_display.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.log_display, 1)

        # Lightweight status label
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #cccccc; padding: 5px;")
        layout.addWidget(self.status_label, 0)

        self.setLayout(layout)
        # Tail-related fields
        self._tail_timer = QTimer(self)
        self._tail_timer.timeout.connect(self._poll_tail)
        self._tail_interval = 300  # ms
        self._tail_f = None
        self._tail_buffer = ""  # Buffer for incomplete lines
        # Default: prefer the most recent file in log/history, else legacy path
        try:
            latest = self._latest_history_file()
        except Exception:
            latest = None
        self._tail_path = latest or Path("log/translationHistory.txt")
        
    def toggle_auto_refresh(self, enabled):
        """Toggle auto-refresh functionality."""
        # No-op: controls removed in simplified viewer
        pass
            
    def adjust_refresh_interval(self):
        """Adjust refresh interval based on current log file size."""
        # No-op in simplified viewer
        pass

    def update_max_lines(self, value):
        """No-op in simplified viewer (controls removed)."""
        pass
            
    def load_selected_log(self):
        """Load the currently selected log file."""
        # No-op in simplified viewer
        pass
            
    def load_log_file(self, file_path):
        """Load content from a specific log file with optimization."""
        # File-based loading removed in simplified viewer
        pass
            
    def read_file_tail(self, file_path, max_lines):
        """Efficiently read the last N lines of a large file."""
        # No-op in simplified viewer
        return ""
            
    def refresh_logs(self):
        """Refresh the current log display - only if tab is visible and file changed."""
        # No-op for simplified viewer
        pass
        
    def clear_log(self):
        """Clear the log display and reset tracking."""
        self.log_display.clear()
        self.status_label.setText("Log cleared")
        # Reset tail file pointer and buffer if active
        self._tail_buffer = ""
        if self._tail_f:
            try:
                # Move pointer to end so we continue only with new lines
                self._tail_f.seek(0, os.SEEK_END)
            except Exception:
                pass

    def start_tail(self, file_path: str | Path = None, interval_ms: int = None):
        """Start tailing the given log file and append new lines as they arrive.

        By default tails the most recent file in `log/history/` (if present),
        otherwise falls back to `log/translationHistory.txt`.
        Seeks to the end so only new lines after this call are shown.
        """
        if file_path:
            self._tail_path = Path(file_path)
        if interval_ms:
            self._tail_interval = interval_ms

        # Ensure directory exists but don't create the file
        try:
            self._tail_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        # Close previous handle
        if self._tail_f:
            try:
                self._tail_f.close()
            except Exception:
                pass
            self._tail_f = None

        # Only open the file if it exists
        # If it doesn't exist yet, the timer will keep checking
        if self._tail_path.exists():
            try:
                self._tail_f = open(self._tail_path, 'r', encoding='utf-8', errors='ignore')
                # Seek to end so we only read new lines
                self._tail_f.seek(0, os.SEEK_END)
            except Exception as e:
                self.status_label.setText(f"Log error: {str(e)}")
                self._tail_f = None
                return

        self._tail_timer.start(self._tail_interval)

    def stop_tail(self):
        """Stop tailing the log file and close internal file handle."""
        try:
            self._tail_timer.stop()
        except Exception:
            pass
        if self._tail_f:
            try:
                self._tail_f.close()
            except Exception:
                pass
            self._tail_f = None

    def _poll_tail(self):
        """Timer callback: read any new data from the tailed file and append it."""
        # If file handle doesn't exist yet, try to open it if the file was created
        if not self._tail_f and self._tail_path.exists():
            try:
                self._tail_f = open(self._tail_path, 'r', encoding='utf-8', errors='ignore')
                # Read from the beginning since this is a per-run file that was
                # created after we started tailing — we want all its content.
            except Exception:
                pass  # Will try again next poll
        
        if not self._tail_f:
            return
        try:
            new_data = self._tail_f.read()
            if not new_data:
                return
            
            # Combine buffer with new data
            combined = self._tail_buffer + new_data
            
            # Split by newlines, keeping the separator info
            lines = combined.split('\n')
            
            # If the data ends with a newline, the last element will be empty
            # Otherwise, it's an incomplete line that should be buffered
            if combined.endswith('\n'):
                # All lines are complete
                self._tail_buffer = ""
                complete_lines = lines[:-1]  # Exclude the empty last element
            else:
                # Last line is incomplete, save it for next time
                self._tail_buffer = lines[-1]
                complete_lines = lines[:-1]
            
            # Append complete lines to the display
            for line in complete_lines:
                if line.strip():
                    self.append_log_message(line)
        except Exception:
            # If anything goes wrong, stop the tail to avoid repeated errors
            self.stop_tail()
        
    def append_log_message(self, message):
        """Append a message to the log display."""
        # Append raw message (worker already includes any desired context).
        # We intentionally avoid adding timestamps here so wrapped lines stay
        # readable and do not misalign JSON-like outputs.
        self.log_display.append(message)

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
        # No-op for simplified viewer
            
    def hideEvent(self, event):
        """Handle widget hide event - pause refresh to save resources."""
        super().hideEvent(event)
        # No-op for simplified viewer

    def _latest_history_file(self):
        """Return the most recent file in log/history or None if not found."""
        try:
            hist_dir = Path("log") / "history"
            # Ensure history directory exists so callers can rely on it
            hist_dir.mkdir(parents=True, exist_ok=True)
            files = [p for p in hist_dir.iterdir() if p.is_file()]
            if not files:
                return None
            return max(files, key=lambda p: p.stat().st_mtime)
        except Exception:
            return None
