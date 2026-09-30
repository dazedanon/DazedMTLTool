"""
Log Viewer - Real-time log display and monitoring
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QTextEdit, QLabel, QSizePolicy, QTabWidget
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QTextCursor, QFont, QTextCharFormat
from pathlib import Path
import datetime
import html
import os


def _parse_mismatch_log_line(message, in_block):
    """Return display text, whether this starts an issue, and next block state."""
    body = message.split("[MISMATCH]", 1)[1].lstrip()
    if body == "End mismatch":
        return body, False, False
    starts_block = body.startswith(
        ("Validation mismatch:", "Failed after retries:")
    ) or not in_block
    return body, starts_block, True


class LogViewer(QWidget):
    """Widget for viewing translation logs and monitoring progress."""
    
    log_updated = pyqtSignal(str)
    mismatch_detected = pyqtSignal()  # Emitted each time a [MISMATCH] header line is seen
    
    def __init__(self, *, show_header: bool = True):
        super().__init__()
        # Lightweight append-only log viewer. Logs are provided by the
        # translation worker via signals so we don't poll files or provide
        # controls here. This keeps the UI responsive.
        self._error_count = 0
        self._mismatch_count = 0
        self._in_mismatch_block = False
        self._show_header = show_header
        self.init_ui()
        
    def init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout()
        # Remove internal margins so header aligns with the left column's header
        layout.setContentsMargins(0, 0, 0, 0)

        # Simple header to match left-side styling (use same look as create_section_header)
        from gui.qt_icons import make_section_header

        if self._show_header:
            header = make_section_header(
                "📝 Translation Log",
                "QLabel {"
                "font-size: 13px;"
                "font-weight: bold;"
                "color: #007acc;"
                "padding: 8px 0px 5px 0px;"
                "background-color: transparent;"
                "}",
            )
            layout.addWidget(header, 0)

        # Match spacing used in left column so the gap between header and
        # content lines up visually.
        layout.setSpacing(8)

        # Tab widget for All / Issues views
        self._tab_widget = QTabWidget()
        self._tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #555555;
                background-color: #1e1e1e;
            }
            QTabBar::tab {
                background-color: #2d2d2d;
                color: #cccccc;
                padding: 5px 12px;
                border: 1px solid #555555;
                border-bottom: none;
            }
            QTabBar::tab:selected {
                background-color: #1e1e1e;
                color: #ffffff;
            }
            QTabBar::tab:hover {
                background-color: #3a3a3a;
            }
        """)
        self._tab_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        _log_font = QFont("Consolas", 10)
        _text_edit_style = """
            QTextEdit {
                background-color: #1e1e1e;
                color: #ffffff;
                border: none;
            }
        """

        # --- All tab ---
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setFont(_log_font)
        self.log_display.setStyleSheet(_text_edit_style)
        self.log_display.document().setDocumentMargin(8.0)
        self.log_display.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._tab_widget.addTab(self.log_display, "All")

        # --- Issues tab (validation mismatches + hard errors) ---
        self.error_display = QTextEdit()
        self.error_display.setReadOnly(True)
        self.error_display.setFont(_log_font)
        self.error_display.setStyleSheet(_text_edit_style)
        self.error_display.document().setDocumentMargin(8.0)
        self.error_display.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._tab_widget.addTab(self.error_display, "Issues")

        layout.addWidget(self._tab_widget, 1)

        # Lightweight status label
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #cccccc; padding: 8px;")
        layout.addWidget(self.status_label, 0)

        self.setLayout(layout)
        # Tail-related fields
        self._tail_timer = QTimer(self)
        self._tail_timer.timeout.connect(self._poll_tail)
        self._tail_interval = 300  # ms
        self._tail_f = None
        self._tail_buffer = ""  # Buffer for incomplete lines
        self._tailing = False
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
        # Reset the char format so the red color from previous [MISMATCH]
        # HTML spans doesn't bleed into new plain-text appends.
        self.log_display.setCurrentCharFormat(QTextCharFormat())
        self.error_display.clear()
        self.error_display.setCurrentCharFormat(QTextCharFormat())
        self._error_count = 0
        self._mismatch_count = 0
        self._in_mismatch_block = False
        self._update_issue_tab_text()
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

        self._tailing = True

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

    def stop_tail(self, *, drain: bool = True):
        """Stop tailing the log file and close internal file handle.

        When *drain* is True and tailing was active, performs one final read so
        lines written just before shutdown are not lost. On application exit,
        pass ``drain=False`` so a large history file is not loaded into the UI.
        """
        self._tailing = False
        try:
            self._tail_timer.stop()
        except Exception:
            pass
        if drain and self._tail_f is not None:
            try:
                self._poll_tail()
            except Exception:
                pass
            if self._tail_buffer and self._tail_buffer.strip():
                try:
                    self.append_log_message(self._tail_buffer)
                except Exception:
                    pass
                self._tail_buffer = ""
        else:
            self._tail_buffer = ""
        if self._tail_f:
            try:
                self._tail_f.close()
            except Exception:
                pass
            self._tail_f = None

    def _poll_tail(self):
        """Timer callback: read any new data from the tailed file and append it."""
        if not self._tailing:
            return
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

    @staticmethod
    def _plural(count, singular):
        if count == 1:
            return singular
        if singular.endswith(("ch", "sh", "s", "x", "z")):
            return f"{singular}es"
        return f"{singular}s"

    def _update_issue_tab_text(self):
        parts = []
        if self._mismatch_count:
            parts.append(
                f"{self._mismatch_count} "
                f"{self._plural(self._mismatch_count, 'mismatch')}"
            )
        if self._error_count:
            parts.append(
                f"{self._error_count} {self._plural(self._error_count, 'error')}"
            )
        suffix = f" ({', '.join(parts)})" if parts else ""
        self._tab_widget.setTabText(1, f"Issues{suffix}")

    def _append_mismatch_message(self, message):
        body, starts_block, self._in_mismatch_block = _parse_mismatch_log_line(
            message, self._in_mismatch_block
        )
        if starts_block:
            self._mismatch_count += 1
            filename = body.split(":", 1)[1].strip() if ":" in body else body
            rendered = (
                '<p style="color: #e5b84b; margin-top: 10px; margin-bottom: 2px;">'
                f'<b>⚠ Validation mismatch #{self._mismatch_count}</b>'
                f' — {html.escape(filename)}</p>'
            )
        elif body == "End mismatch":
            self._in_mismatch_block = False
            rendered = '<p style="margin: 3px 0px;"></p>'
        elif body in ("Input:", "Final Output:", "Provider output:"):
            label = "Provider output:" if body == "Final Output:" else body
            rendered = (
                '<p style="color: #9cdcfe; margin: 5px 0px 1px 14px;">'
                f'<b>{html.escape(label)}</b></p>'
            )
        elif body.startswith("Original text kept"):
            rendered = (
                '<p style="color: #d7ba7d; margin: 1px 0px 3px 14px;">'
                f'{html.escape(body)}</p>'
            )
        else:
            rendered = (
                '<p style="color: #dddddd; margin: 0px 0px 0px 28px;">'
                f'{html.escape(body)}</p>'
            )

        self.log_display.append(rendered)
        self.error_display.append(rendered)
        self._update_issue_tab_text()

    def append_log_message(self, message):
        """Append a message to the log display.
        
        Lines containing '[MISMATCH]' or '[API_ERROR]' are also routed to the
        Issues filter tab so they are never lost in a fast-scrolling log.
        """
        if "[MISMATCH]" in message:
            self._append_mismatch_message(message)
        elif "[API_ERROR]" in message:
            self._in_mismatch_block = False
            escaped = html.escape(message)
            html_msg = f'<span style="color: #ffaa00;">{escaped}</span>'
            self.log_display.append(html_msg)
            self.error_display.append(html_msg)
            self._error_count += 1
            self._update_issue_tab_text()
        elif '\u274c' in message:
            self._in_mismatch_block = False
            escaped = html.escape(message)
            # Worker-level error (❌ prefix) — show in both All and Errors tabs.
            html_msg = f'<span style="color: #ff6666;">{escaped}</span>'
            self.log_display.append(html_msg)
            self.error_display.append(html_msg)
            self._error_count += 1
            self._update_issue_tab_text()
        else:
            self._in_mismatch_block = False
            escaped = html.escape(message)
            # Explicitly wrap in a white span so Qt doesn't inherit red from
            # a preceding [MISMATCH] HTML append.
            self.log_display.append(f'<span style="color: #ffffff;">{escaped}</span>')

        # Scroll to bottom of whichever tab is active; always scroll the
        # background error display too so it stays at the latest entry.
        for display in (self.log_display, self.error_display):
            cursor = display.textCursor()
            cursor.movePosition(QTextCursor.End)
            display.setTextCursor(cursor)
        
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
