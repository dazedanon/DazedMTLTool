import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt5.QtCore import QItemSelectionModel, QSettings, Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QAbstractItemView

from gui.rpgmaker_image_manager import RPGMakerImageManager


class RPGMakerImageManagerSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.game_root = root / "Game"
        image_dir = self.game_root / "img" / "pictures"
        data_dir = self.game_root / "data"
        image_dir.mkdir(parents=True)
        data_dir.mkdir(parents=True)
        data_dir.joinpath("System.json").write_text(
            '{"encryptionKey":"00112233445566778899aabbccddeeff"}',
            encoding="utf-8",
        )
        for index in range(4):
            Image.new("RGBA", (24, 24), (index * 40, 10, 20, 255)).save(
                image_dir / f"image{index}.png"
            )
        settings = QSettings(str(root / "settings.ini"), QSettings.IniFormat)
        self.manager = RPGMakerImageManager(self.game_root, settings=settings)
        self.manager.resize(1100, 760)
        self.manager.show()
        self.manager._scan_worker.wait(5000)
        self.app.processEvents()

    def tearDown(self):
        for worker in list(self.manager._thumbnail_workers):
            worker.wait(5000)
        self.manager.close()
        self.app.processEvents()
        self.temp.cleanup()

    def _click(self, index: int, modifiers=Qt.NoModifier):
        item = self.manager.image_list.item(index)
        rect = self.manager.image_list.visualItemRect(item)
        QTest.mouseClick(
            self.manager.image_list.viewport(),
            Qt.LeftButton,
            modifiers,
            rect.center(),
        )
        self.app.processEvents()

    def test_ctrl_shift_and_ctrl_a_use_standard_extended_selection(self):
        image_list = self.manager.image_list
        self.assertEqual(
            image_list.selectionMode(), QAbstractItemView.ExtendedSelection
        )

        self._click(0)
        self._click(2, Qt.ControlModifier)
        self.assertEqual(len(image_list.selectedItems()), 2)
        self.assertEqual(len(self.manager.selected_ids), 2)

        self._click(3, Qt.ShiftModifier)
        selected_names = {item.text() for item in image_list.selectedItems()}
        self.assertIn("image2.png", selected_names)
        self.assertIn("image3.png", selected_names)

        image_list.clearSelection()
        image_list.setFocus()
        QTest.keyClick(image_list, Qt.Key_A, Qt.ControlModifier)
        self.app.processEvents()
        self.assertEqual(len(image_list.selectedItems()), 4)
        self.assertEqual(len(self.manager.selected_ids), 4)

    def test_selected_tiles_are_restored_after_filtering(self):
        selection = self.manager.image_list.selectionModel()
        selection.select(
            self.manager.image_list.model().index(1, 0),
            QItemSelectionModel.Select,
        )
        selection.select(
            self.manager.image_list.model().index(3, 0),
            QItemSelectionModel.Select,
        )
        self.app.processEvents()
        selected_before = set(self.manager.selected_ids)
        self.assertEqual(len(selected_before), 2)

        self.manager.search_edit.setText("image0")
        self.app.processEvents()
        self.manager.search_edit.clear()
        self.app.processEvents()

        self.assertEqual(self.manager.selected_ids, selected_before)
        self.assertEqual(len(self.manager.image_list.selectedItems()), 2)

    def test_thumbnail_batch_keeps_one_stable_tile_per_asset(self):
        for worker in list(self.manager._thumbnail_workers):
            worker.wait(5000)
        self.app.processEvents()

        image_list = self.manager.image_list
        self.assertTrue(image_list.uniformItemSizes())
        self.assertNotIn("border-bottom", image_list.styleSheet())
        self.assertEqual(image_list.count(), 4)
        self.assertTrue(
            all(not image_list.item(index).icon().isNull() for index in range(4))
        )
        rects = [image_list.visualItemRect(image_list.item(index)) for index in range(4)]
        self.assertEqual(len({(rect.x(), rect.y()) for rect in rects}), 4)


class RPGMakerImageManagerNavigationTests(unittest.TestCase):
    def test_image_manager_is_a_dedicated_sidebar_page(self):
        root = Path(__file__).resolve().parents[1]
        main_source = (root / "gui" / "main.py").read_text(encoding="utf-8")
        workflow_source = (root / "gui" / "workflow_tab.py").read_text(encoding="utf-8")
        self.assertIn("PAGE_IMAGES = 2", main_source)
        self.assertIn("self.image_manager_tab = RPGMakerImageManager", main_source)
        self.assertIn('create_nav_button("🖼", "Images")', main_source)
        self.assertNotIn("Open Image Manager", workflow_source)


if __name__ == "__main__":
    unittest.main()
