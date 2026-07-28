from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QListWidgetItem

from gui.ui_components import CheckableFileList


class CheckableFileListTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.file_list = CheckableFileList()
        for index in range(6):
            item = QListWidgetItem(f"File{index}.json")
            item.setFlags(
                item.flags()
                | Qt.ItemIsEnabled
                | Qt.ItemIsSelectable
                | Qt.ItemIsUserCheckable
            )
            item.setCheckState(Qt.Unchecked)
            self.file_list.addItem(item)
        self.file_list.resize(420, 320)
        self.file_list.show()
        self.app.processEvents()

    def tearDown(self) -> None:
        self.file_list.close()
        self.app.processEvents()

    def _click(self, row: int, modifiers=Qt.NoModifier) -> None:
        item = self.file_list.item(row)
        QTest.mouseClick(
            self.file_list.viewport(),
            Qt.LeftButton,
            modifiers,
            self.file_list.visualItemRect(item).center(),
        )
        self.app.processEvents()

    def _checked_rows(self) -> set[int]:
        return {
            row
            for row in range(self.file_list.count())
            if self.file_list.item(row).checkState() == Qt.Checked
        }

    def _selected_rows(self) -> set[int]:
        return {self.file_list.row(item) for item in self.file_list.selectedItems()}

    def test_ctrl_and_shift_update_visible_and_checked_scope(self) -> None:
        self._click(1)
        self._click(3, Qt.ControlModifier)
        self.assertEqual(self._checked_rows(), {1, 3})
        self.assertEqual(self._selected_rows(), {1, 3})

        self._click(5, Qt.ShiftModifier)
        self.assertEqual(self._checked_rows(), {1, 3, 4, 5})
        self.assertEqual(self._selected_rows(), {3, 4, 5})

        self._click(4, Qt.ControlModifier)
        self.assertEqual(self._checked_rows(), {1, 3, 5})
        self.assertEqual(self._selected_rows(), {3, 5})

    def test_ctrl_a_checks_and_selects_every_visible_file(self) -> None:
        self.file_list.setFocus()
        QTest.keyClick(self.file_list, Qt.Key_A, Qt.ControlModifier)
        self.app.processEvents()
        self.assertEqual(self._checked_rows(), set(range(6)))
        self.assertEqual(self._selected_rows(), set(range(6)))


if __name__ == "__main__":
    unittest.main()
