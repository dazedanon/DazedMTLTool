"""Tests for LogViewer tail shutdown behavior."""

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt5.QtWidgets import QApplication

from gui.log_viewer import LogViewer

APP = QApplication.instance() or QApplication(sys.argv)


class LogViewerStopTailTests(unittest.TestCase):
    def test_stop_tail_without_active_tail_is_instant(self):
        viewer = LogViewer()
        history = Path("log/history/translationHistory_20260703_175433.txt")
        if history.exists():
            viewer._tail_path = history

        t0 = time.perf_counter()
        viewer.stop_tail(drain=False)
        elapsed = time.perf_counter() - t0

        self.assertLess(elapsed, 0.2)
        self.assertIsNone(viewer._tail_f)

    def test_stop_tail_drain_skips_ui_when_not_tailing(self):
        viewer = LogViewer()
        with patch.object(viewer, "append_log_message") as append_mock:
            viewer.stop_tail(drain=True)
        append_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
