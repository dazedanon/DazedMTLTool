from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEventLoop
from PyQt5.QtWidgets import QApplication

from gui.batch_tab import BatchTab


class BatchTabWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_completion_callback_runs_after_worker_is_cleared(self):
        tab = BatchTab()
        observed = {}
        loop = QEventLoop()

        def done(ok, message, payload):
            observed.update(
                ok=ok,
                message=message,
                payload=payload,
                worker=tab._worker,
                refresh_enabled=tab.refresh_btn.isEnabled(),
            )

        tab._run_task(
            lambda _log: (True, "finished", {"value": 1}),
            on_done=done,
        )
        tab._worker.finished.connect(loop.quit)
        loop.exec_()
        self.app.processEvents()

        self.assertTrue(observed["ok"])
        self.assertEqual(observed["message"], "finished")
        self.assertEqual(observed["payload"], {"value": 1})
        self.assertIsNone(observed["worker"])
        self.assertTrue(observed["refresh_enabled"])
        tab.close()


if __name__ == "__main__":
    unittest.main()
