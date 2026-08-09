import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt5.QtCore import QSettings, Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QMainWindow,
    QMessageBox,
)

from gui.image_manager import ImageManager
from gui.workflow_tab import _inspect_image_workflow
from util.image_manager import PROFILE_AUTO, PROFILE_GENERIC, PROFILE_RPGMAKER_MVMZ


class ImageManagerSelectionTests(unittest.TestCase):
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
        self.settings_path = root / "settings.ini"
        settings = QSettings(str(self.settings_path), QSettings.IniFormat)
        self.manager = ImageManager(self.game_root, settings=settings)
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

    def test_plain_click_replaces_selection_and_ctrl_click_adds(self):
        self._click(0)
        self._click(1)
        self.assertEqual(len(self.manager.image_list.selectedItems()), 1)
        self.assertEqual(len(self.manager.selected_ids), 1)

        self._click(2, Qt.ControlModifier)
        self.assertEqual(len(self.manager.image_list.selectedItems()), 2)
        self.assertEqual(len(self.manager.selected_ids), 2)

    def test_workspace_images_are_selected_after_manager_reopens(self):
        self._click(0)
        self._click(2, Qt.ControlModifier)
        expected = set(self.manager.selected_ids)
        for asset_id in expected:
            asset = self.manager.assets_by_id[asset_id]
            asset.plain_path.parent.mkdir(parents=True, exist_ok=True)
            asset.plain_path.write_bytes(asset.runtime_plain_path.read_bytes())
        manifest = self.game_root / ".dazedtl" / "image_selection.json"
        manifest.write_text("not used", encoding="utf-8")

        settings = QSettings(str(self.settings_path), QSettings.IniFormat)
        reopened = ImageManager(self.game_root, settings=settings)
        reopened.resize(1100, 760)
        reopened.show()
        reopened._scan_worker.wait(5000)
        self.app.processEvents()
        try:
            self.assertEqual(reopened.selected_ids, set())
            self.assertEqual(reopened.image_list.selectedItems(), [])
            self.assertEqual(manifest.read_text(encoding="utf-8"), "not used")

            reopened.folder_combo.setCurrentIndex(
                reopened.folder_combo.findData("img/pictures")
            )
            reopened.state_combo.setCurrentIndex(
                reopened.state_combo.findData("editable")
            )
            self.app.processEvents()
            self.assertEqual(reopened.image_list.count(), len(expected))
            self.assertEqual(reopened.image_list.selectedItems(), [])
        finally:
            for worker in list(reopened._thumbnail_workers):
                worker.wait(5000)
            reopened.close()
            self.app.processEvents()

    def test_highlights_clear_when_filter_or_page_changes(self):
        with patch("gui.image_manager._PAGE_SIZE", 2):
            self.manager._apply_filters()
            self._click(0)
            self._click(1, Qt.ControlModifier)
            self.assertEqual(len(self.manager.selected_ids), 2)

            self.manager.search_edit.setText("image0")
            self.app.processEvents()
            self.assertEqual(self.manager.selected_ids, set())
            self.assertEqual(self.manager.image_list.selectedItems(), [])
            self.assertIn("0 highlighted", self.manager.status_label.text())

            self.manager.search_edit.clear()
            self.app.processEvents()
            self._click(0)
            self.assertEqual(len(self.manager.selected_ids), 1)

            self.manager._change_page(1)
            self.app.processEvents()
            self.assertEqual(self.manager.selected_ids, set())
            self.assertEqual(self.manager.image_list.selectedItems(), [])
            self.assertIn("0 highlighted", self.manager.status_label.text())

            self.manager._change_page(-1)
            self.app.processEvents()
            self.assertEqual(self.manager.image_list.selectedItems(), [])

    def test_delete_key_removes_only_highlighted_workspace_copy(self):
        asset = self.manager.assets[0]
        asset.plain_path.parent.mkdir(parents=True, exist_ok=True)
        edited = asset.runtime_plain_path.read_bytes()
        asset.plain_path.write_bytes(edited)
        self.manager.state_combo.setCurrentIndex(
            self.manager.state_combo.findData("editable")
        )
        self.app.processEvents()
        self.assertEqual(self.manager.image_list.count(), 1)
        self._click(0)

        with (
            patch.object(QMessageBox, "question", return_value=QMessageBox.Yes),
            patch.object(QMessageBox, "information"),
        ):
            QTest.keyClick(self.manager.image_list, Qt.Key_Delete)
            action_worker = self.manager._action_worker
            self.assertIsNotNone(action_worker)
            action_worker.wait(5000)
            self.app.processEvents()
            self.manager._scan_worker.wait(5000)
            self.app.processEvents()

        self.assertFalse(asset.plain_path.exists())
        self.assertTrue(asset.runtime_plain_path.exists())
        self.assertEqual(self.manager.image_list.count(), 0)

    def test_prepare_uses_only_highlighted_editable_images(self):
        highlighted = self.manager.assets[0]
        not_highlighted = self.manager.assets[1]
        for asset in (highlighted, not_highlighted):
            asset.plain_path.parent.mkdir(parents=True, exist_ok=True)
            asset.plain_path.write_bytes(asset.runtime_plain_path.read_bytes())
        self._click(0)

        with (
            patch.object(QMessageBox, "question", return_value=QMessageBox.Yes),
            patch.object(self.manager, "_start_action") as start_action,
        ):
            self.manager._prepare_checked()

        action, assets = start_action.call_args.args
        self.assertEqual(action, "prepare")
        self.assertEqual(assets, [highlighted])
        self.assertTrue(highlighted.plain_path.exists())
        self.assertTrue(not_highlighted.plain_path.exists())

    def test_prepare_uses_all_editable_images_without_highlights(self):
        editable = self.manager.assets[:2]
        for asset in editable:
            asset.plain_path.parent.mkdir(parents=True, exist_ok=True)
            asset.plain_path.write_bytes(asset.runtime_plain_path.read_bytes())

        with (
            patch.object(QMessageBox, "question", return_value=QMessageBox.Yes),
            patch.object(self.manager, "_start_action") as start_action,
        ):
            self.manager._prepare_checked()

        action, assets = start_action.call_args.args
        self.assertEqual(action, "prepare")
        self.assertEqual(assets, editable)

    def test_translation_skill_is_enabled_only_for_editable_images(self):
        self.assertFalse(self.manager.copy_translation_button.isEnabled())

        asset = self.manager.assets[0]
        asset.plain_path.parent.mkdir(parents=True, exist_ok=True)
        asset.plain_path.write_bytes(asset.runtime_plain_path.read_bytes())
        self.manager._start_scan()
        self.manager._scan_worker.wait(5000)
        self.app.processEvents()

        self.assertTrue(self.manager.copy_translation_button.isEnabled())

    def test_loading_and_scanning_project_is_read_only(self):
        self.assertEqual(self.manager.engine_combo.currentData(), PROFILE_AUTO)
        self.assertEqual(self.manager.engine_id, PROFILE_RPGMAKER_MVMZ)
        self.assertFalse((self.game_root / ".dazedtl").exists())
        self.assertFalse((self.game_root / ".gitignore").exists())

    def test_translation_skill_copies_project_specific_editable_folder(self):
        asset = self.manager.assets[0]
        asset.plain_path.parent.mkdir(parents=True, exist_ok=True)
        asset.plain_path.write_bytes(asset.runtime_plain_path.read_bytes())
        self.manager._start_scan()
        self.manager._scan_worker.wait(5000)
        self.app.processEvents()

        QApplication.clipboard().clear()
        self.manager.copy_translation_button.click()
        prompt = QApplication.clipboard().text()

        self.assertIn(str(self.game_root), prompt)
        self.assertIn(str(self.game_root / ".dazedtl" / "images" / "img"), prompt)
        self.assertIn(str(self.game_root / ".dazedtl" / "glossary.txt"), prompt)
        self.assertIn("RPG Maker MV/MZ image profile", prompt)
        self.assertIn("image_translation_log.md", prompt)
        self.assertNotIn("{{GAME_ROOT}}", prompt)
        self.assertNotIn("{{EDITABLE_IMAGES_FOLDER}}", prompt)
        self.assertNotIn("{{VOCAB_FILE}}", prompt)
        self.assertNotIn("{{ENGINE_NAME}}", prompt)
        self.assertNotIn("{{ENGINE_CONTEXT}}", prompt)
        self.assertIn(
            "Copied image translation skill for 1 editable PNG",
            self.manager.status_label.text(),
        )

        conflict = Path(self.temp.name) / "Conflict Game"
        conflict.joinpath("skills").mkdir(parents=True)
        conflict.joinpath(".dazedtl", "skills").mkdir(parents=True)
        legacy_glossary = conflict / "glossary.txt"
        legacy_glossary.write_text("Legacy (Legacy)\n", encoding="utf-8")
        self.manager.game_root = conflict
        QApplication.clipboard().setText("unchanged")
        with patch.object(QMessageBox, "warning") as warning:
            self.manager._copy_translation_skill()
        warning.assert_called_once()
        self.assertEqual(QApplication.clipboard().text(), "unchanged")
        self.assertTrue(legacy_glossary.is_file())
        self.assertFalse(conflict.joinpath(".dazedtl", "glossary.txt").exists())

    def test_workflow_readiness_detects_editable_and_misplaced_pngs(self):
        asset = self.manager.assets[0]
        asset.plain_path.parent.mkdir(parents=True, exist_ok=True)
        asset.plain_path.write_bytes(asset.runtime_plain_path.read_bytes())
        self.game_root.joinpath("glossary.txt").write_text("Menu (Menu)\n", encoding="utf-8")
        misplaced = self.game_root / ".dazedtl" / "images" / "img (2)" / "pictures"
        misplaced.mkdir(parents=True)
        misplaced.joinpath("menu.png").write_bytes(asset.runtime_plain_path.read_bytes())

        report = _inspect_image_workflow(self.game_root)

        self.assertTrue(report["ok"])
        self.assertEqual(report["runtime"], 4)
        self.assertEqual(report["editable"], 1)
        self.assertEqual(report["misplaced"], 1)
        self.assertEqual(
            report["vocab"], self.game_root / ".dazedtl" / "glossary.txt"
        )
        self.assertTrue(self.game_root.joinpath("glossary.txt").is_file())
        self.assertFalse(report["vocab"].exists())
        self.assertFalse(self.game_root.joinpath(".gitignore").exists())

    def test_open_folder_uses_highlighted_images_editable_parent(self):
        self._click(0)
        asset_id = self.manager.image_list.currentItem().data(Qt.UserRole + 1)
        expected = self.manager.assets_by_id[asset_id].plain_path.parent
        self.manager.image_list.setCurrentItem(None)

        with patch(
            "gui.image_manager.QDesktopServices.openUrl",
            return_value=True,
        ) as open_url:
            self.manager._open_editable_folder()

        opened_url = open_url.call_args.args[0]
        self.assertEqual(Path(opened_url.toLocalFile()), expected)
        self.assertTrue(expected.is_dir())

    def test_open_folder_ignores_current_item_without_highlights(self):
        self.manager.image_list.setCurrentRow(0)
        self.manager.selected_ids.clear()
        expected = self.game_root / ".dazedtl" / "images" / "img"

        with patch(
            "gui.image_manager.QDesktopServices.openUrl",
            return_value=True,
        ) as open_url:
            self.manager._open_editable_folder()

        opened_url = open_url.call_args.args[0]
        self.assertEqual(Path(opened_url.toLocalFile()), expected)
        self.assertTrue(expected.is_dir())

    def test_thumbnail_batch_keeps_one_loaded_icon_per_asset(self):
        for worker in list(self.manager._thumbnail_workers):
            worker.wait(5000)
        self.app.processEvents()

        image_list = self.manager.image_list
        self.assertEqual(image_list.count(), 4)
        self.assertTrue(
            all(not image_list.item(index).icon().isNull() for index in range(4))
        )
        asset_ids = [
            image_list.item(index).data(Qt.UserRole + 1)
            for index in range(image_list.count())
        ]
        self.assertEqual(len(asset_ids), len(set(asset_ids)))


class GenericImageManagerUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_auto_detects_generic_root_and_uses_make_editable_actions(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            game_root = root / "Game"
            image_root = game_root / "assets" / "images" / "ui"
            image_root.mkdir(parents=True)
            Image.new("RGBA", (20, 12), "green").save(image_root / "menu.png")
            settings = QSettings(str(root / "settings.ini"), QSettings.IniFormat)
            manager = ImageManager(game_root, settings=settings)
            manager.resize(1000, 700)
            manager.show()
            manager._scan_worker.wait(5000)
            self.app.processEvents()
            try:
                self.assertEqual(manager.engine_combo.currentData(), PROFILE_AUTO)
                self.assertEqual(manager.engine_id, PROFILE_GENERIC)
                self.assertTrue(manager.generic_root_host.isVisible())
                self.assertEqual(manager.image_list.count(), 1)
                self.assertEqual(manager.assets[0].asset_id, "assets/images/ui/menu.png")
                self.assertFalse((game_root / ".dazedtl").exists())

                asset = manager.assets[0]
                asset.plain_path.parent.mkdir(parents=True)
                asset.plain_path.write_bytes(asset.runtime_plain_path.read_bytes())
                manager._start_scan()
                manager._scan_worker.wait(5000)
                self.app.processEvents()
                QApplication.clipboard().clear()
                manager.copy_translation_button.click()
                prompt = QApplication.clipboard().text()

                self.assertIn("Generic / Loose Images image profile", prompt)
                self.assertNotIn("RPG Maker", prompt)
                self.assertNotIn(".rpgmvp", prompt)
                self.assertNotIn("{{ENGINE_NAME}}", prompt)
                self.assertNotIn("{{ENGINE_CONTEXT}}", prompt)
            finally:
                for worker in list(manager._thumbnail_workers):
                    worker.wait(5000)
                manager.close()
                self.app.processEvents()


class RPGMakerWorkflowImageStepTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_images_step_checks_setup_and_opens_existing_manager(self):
        from gui.workflow_tab import WorkflowTab

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            game_root = root / "Game"
            image_root = game_root / "img" / "pictures"
            data_root = game_root / "data"
            image_root.mkdir(parents=True)
            data_root.mkdir(parents=True)
            Image.new("RGBA", (12, 12), "purple").save(image_root / "menu.png")
            data_root.joinpath("System.json").write_text("{}", encoding="utf-8")
            game_root.joinpath("glossary.txt").write_text("Menu (Menu)\n", encoding="utf-8")
            portable_glossary = game_root / ".dazedtl" / "glossary.txt"
            portable_glossary.parent.mkdir()
            portable_glossary.write_text("Portable (Portable)\n", encoding="utf-8")

            settings = QSettings(str(root / "settings.ini"), QSettings.IniFormat)

            class Host(QMainWindow):
                PAGE_IMAGES = 2

                def __init__(self):
                    super().__init__()
                    self.switched_to = None

                def switch_page(self, index):
                    self.switched_to = index

            host = Host()
            with patch("gui.workflow_tab.QSettings", return_value=settings):
                workflow = WorkflowTab(host)
            try:
                workflow.folder_edit.setText(str(game_root))
                workflow._goto_step(7)
                workflow._refresh_image_workflow_status()

                self.assertEqual(workflow._step_tabs.count(), 9)
                self.assertEqual(workflow._step_tabs.currentIndex(), 7)
                self.assertIn("Runtime images:</span> 1", workflow._image_workflow_status.text())
                self.assertIn("Glossary:</span>", workflow._image_workflow_status.text())
                self.assertTrue(game_root.joinpath("glossary.txt").is_file())
                self.assertTrue(portable_glossary.is_file())
                self.assertFalse(game_root.joinpath(".gitignore").exists())

                workflow._open_image_manager()

                self.assertEqual(host.switched_to, host.PAGE_IMAGES)
                self.assertEqual(
                    settings.value("workflow/last_game_folder"), str(game_root.resolve())
                )
            finally:
                workflow.close()
                host.close()


class RPGMakerWorkflowRewrapStepTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_rewrap_scope_reads_detected_game_data_not_tool_workspace(self):
        from gui.workflow_tab import WorkflowTab

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            game_data = root / "Game" / "data"
            game_data.mkdir(parents=True)
            game_data.joinpath("Map123.json").write_text("{}", encoding="utf-8")
            game_data.joinpath("Items.json").write_text("[]", encoding="utf-8")
            settings = QSettings(str(root / "settings.ini"), QSettings.IniFormat)

            with patch("gui.workflow_tab.QSettings", return_value=settings):
                workflow = WorkflowTab()
            try:
                workflow.folder_edit.setText(str(game_data.parent))
                self.assertTrue(workflow.setup_editors.reload_all())
                workflow._prepared_game_root = str(game_data.parent)
                workflow._data_path = str(game_data)
                workflow._refresh_rewrap_files()
                names = {
                    workflow.rewrap_file_list.item(index).text()
                    for index in range(workflow.rewrap_file_list.count())
                }
                self.assertEqual(names, {"Items.json", "Map123.json"})
                self.assertIn(str(game_data.resolve()), workflow.rewrap_scope_title.text())
            finally:
                workflow.close()


if __name__ == "__main__":
    unittest.main()
