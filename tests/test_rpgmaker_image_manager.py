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
    QScrollArea,
    QWidget,
)

from gui.rpgmaker_image_manager import RPGMakerImageManager, _PAGE_SIZE
from gui.theme import Geometry, Spacing
from gui.workflow_tab import _inspect_image_workflow
from util.image_manager import PROFILE_AUTO, PROFILE_GENERIC, PROFILE_RPGMAKER_MVMZ


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
        self.settings_path = root / "settings.ini"
        settings = QSettings(str(self.settings_path), QSettings.IniFormat)
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
        reopened = RPGMakerImageManager(self.game_root, settings=settings)
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

    def test_highlights_survive_filters_without_refreshing_editable_view(self):
        self._click(1)
        self._click(3, Qt.ControlModifier)
        selected_before = set(self.manager.selected_ids)
        self.assertEqual(len(selected_before), 2)

        self.manager.search_edit.setText("image0")
        self.app.processEvents()
        self.manager.search_edit.clear()
        self.app.processEvents()

        self.assertEqual(self.manager.selected_ids, selected_before)
        selected_ids = {
            item.data(Qt.UserRole + 1)
            for item in self.manager.image_list.selectedItems()
        }
        self.assertEqual(selected_ids, selected_before)

        for asset_id in selected_before:
            asset = self.manager.assets_by_id[asset_id]
            asset.plain_path.parent.mkdir(parents=True, exist_ok=True)
            asset.plain_path.write_bytes(asset.runtime_plain_path.read_bytes())
        editable_filter = self.manager.state_combo.findData("editable")
        self.manager.state_combo.setCurrentIndex(editable_filter)
        QTest.qWait(20)
        self.app.processEvents()
        self.assertEqual(self.manager.image_list.count(), 2)
        self.assertEqual(self.manager.selected_ids, selected_before)

        removed_id = self.manager.image_list.item(0).data(Qt.UserRole + 1)
        self._click(0, Qt.ControlModifier)
        self.app.processEvents()
        self.assertNotIn(removed_id, self.manager.selected_ids)
        self.assertEqual(self.manager.image_list.count(), 2)

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
        self.assertEqual(self.manager.remove_button.text(), "Remove copies")

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
        self.assertEqual(self.manager.prepare_button.text(), "Patch selected")

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
        self.assertEqual(self.manager.prepare_button.text(), "Patch all")

    def test_actions_are_compact_and_pagination_belongs_to_browser(self):
        action_buttons = (
            self.manager.open_workspace_button,
            self.manager.copy_translation_button,
            self.manager.decrypt_selected_button,
            self.manager.decrypt_all_button,
            self.manager.remove_button,
            self.manager.prepare_button,
        )
        self.assertTrue(
            all(self.manager.action_host.isAncestorOf(button) for button in action_buttons)
        )
        self.assertTrue(
            self.manager.browser_host.isAncestorOf(self.manager.previous_button)
        )
        self.assertTrue(self.manager.browser_host.isAncestorOf(self.manager.next_button))
        self.assertLess(
            max(button.width() for button in action_buttons),
            self.manager.workspace_card.width() // 2,
        )
        action_rows = {
            self.manager.action_layout.getItemPosition(
                self.manager.action_layout.indexOf(button)
            )[0]
            for button in action_buttons
        }
        self.assertEqual(action_rows, {0})
        self.assertEqual({button.width() for button in action_buttons}, {
            action_buttons[0].width()
        })
        self.assertEqual(
            self.manager.previous_button.size(), self.manager.next_button.size()
        )
        for button in (self.manager.previous_button, self.manager.next_button):
            button_bottom = button.mapTo(
                self.manager.browser_host, button.rect().bottomLeft()
            ).y()
            self.assertGreaterEqual(
                self.manager.browser_host.contentsRect().bottom() - button_bottom,
                Spacing.SM,
            )
        action_right = max(
            button.mapTo(self.manager.action_host, button.rect().topRight()).x()
            for button in action_buttons
        )
        self.assertLessEqual(
            action_right, self.manager.action_host.contentsRect().right()
        )

    def test_action_bar_reflows_when_only_the_page_viewport_changes(self):
        for button in self.manager.action_buttons:
            button.setFixedWidth(260)
        self.manager.page_scroll.viewport().resize(720, 600)
        QTest.qWait(1)
        self.app.processEvents()

        action_right = max(
            button.mapTo(self.manager.action_host, button.rect().topRight()).x()
            for button in self.manager.action_buttons
        )
        self.assertLessEqual(
            action_right, self.manager.action_host.contentsRect().right()
        )
        self.assertEqual(
            {button.width() for button in self.manager.action_buttons},
            {self.manager.action_buttons[0].width()},
        )

    def test_browser_is_the_single_dominant_workspace(self):
        cards = self.manager.findChildren(QWidget, "appSectionCard")
        self.assertEqual(len(cards), 1)
        workspace = cards[0]
        self.assertIsNone(self.manager.workspace_card.title_label)
        for widget in (
            self.manager.folder_edit,
            self.manager.image_list,
            self.manager.preview_host,
            self.manager.prepare_button,
        ):
            self.assertTrue(workspace.isAncestorOf(widget))
        self.assertGreater(self.manager.image_list.height(), 240)
        self.assertGreaterEqual(self.manager.preview_host.width(), 400)
        self.assertGreaterEqual(
            self.manager.preview_host.width(),
            int(self.manager.browser_splitter.width() * 0.38),
        )

    def test_browser_and_preview_panes_share_outer_edges(self):
        browser_top = self.manager.browser_host.mapTo(
            self.manager.browser_splitter,
            self.manager.browser_host.rect().topLeft(),
        ).y()
        preview_top = self.manager.preview_host.mapTo(
            self.manager.browser_splitter,
            self.manager.preview_host.rect().topLeft(),
        ).y()
        browser_bottom = self.manager.browser_host.mapTo(
            self.manager.browser_splitter,
            self.manager.browser_host.rect().bottomLeft(),
        ).y()
        preview_bottom = self.manager.preview_host.mapTo(
            self.manager.browser_splitter,
            self.manager.preview_host.rect().bottomLeft(),
        ).y()
        self.assertEqual(browser_top, preview_top)
        self.assertEqual(browser_bottom, preview_bottom)

    def test_preview_summary_is_compact_and_full_paths_are_in_tooltip(self):
        self.manager.image_list.setCurrentRow(0)
        self.app.processEvents()
        self.assertTrue(self.manager.path_label.isVisible())
        asset = self.manager.assets[0]
        self.assertIn(asset.asset_id, self.manager.path_label.text())
        self.assertIn("PNG source", self.manager.path_label.text())
        self.assertNotIn(str(self.game_root), self.manager.path_label.text())
        self.assertIn(str(self.game_root), self.manager.path_label.toolTip())

        self.assertLess(
            self.manager.preview_label.geometry().bottom(),
            self.manager.path_label.geometry().top(),
        )
        self.assertLessEqual(
            self.manager.path_label.geometry().bottom(),
            self.manager.preview_host.contentsRect().bottom(),
        )
        self.assertLessEqual(
            self.manager.path_label.height(), Geometry.CONTROL * 3
        )

    def test_thumbnail_labels_are_single_line_and_middle_elided(self):
        self.assertFalse(self.manager.image_list.wordWrap())
        self.assertEqual(self.manager.image_list.textElideMode(), Qt.ElideMiddle)
        self.assertGreater(
            self.manager.image_list.gridSize().height(),
            self.manager.image_list.iconSize().height()
            + self.manager.image_list.fontMetrics().height(),
        )

    def test_engine_detection_shares_engine_row_above_filters(self):
        engine_top = self.manager.engine_combo.mapTo(
            self.manager, self.manager.engine_combo.rect().topLeft()
        ).y()
        engine_bottom = engine_top + self.manager.engine_combo.height()
        detection_top = self.manager.engine_detection_label.mapTo(
            self.manager, self.manager.engine_detection_label.rect().topLeft()
        ).y()
        detection_bottom = detection_top + self.manager.engine_detection_label.height()
        filter_top = self.manager.search_edit.mapTo(
            self.manager, self.manager.search_edit.rect().topLeft()
        ).y()

        self.assertLess(max(engine_top, detection_top), min(engine_bottom, detection_bottom))
        self.assertLess(max(engine_bottom, detection_bottom), filter_top)
        self.assertLessEqual(self.manager.folder_combo.maximumWidth(), 360)
        self.assertLessEqual(self.manager.state_combo.maximumWidth(), 220)

    def test_page_uses_outer_vertical_scroll_only_when_content_needs_it(self):
        scroll = self.manager.findChild(QScrollArea, "imageManagerScroll")
        self.assertIsNotNone(scroll)
        self.assertTrue(scroll.widgetResizable())
        self.manager._update_page_scroll_extent()
        self.app.processEvents()
        self.assertEqual(
            self.manager.page_content.minimumHeight(),
            self.manager.page_layout.sizeHint().height(),
        )
        if self.manager.page_content.minimumHeight() > scroll.viewport().height():
            self.assertGreater(scroll.verticalScrollBar().maximum(), 0)
        else:
            self.assertEqual(scroll.verticalScrollBar().maximum(), 0)

    def test_folder_popup_is_bounded_and_scrolls_long_lists(self):
        combo = self.manager.folder_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("All folders", "")
        for index in range(80):
            combo.addItem(f"img/pictures/group_{index:03d}/nested_folder", str(index))
        combo.setCurrentIndex(combo.count() - 1)
        combo.blockSignals(False)

        combo.showPopup()
        self.app.processEvents()
        try:
            view = combo.view()
            popup = view.window()
            screen = QApplication.screenAt(combo.mapToGlobal(combo.rect().center()))
            screen = screen or QApplication.primaryScreen()
            available = screen.availableGeometry()

            self.assertLessEqual(popup.height(), int(available.height() * 0.6))
            self.assertGreater(view.verticalScrollBar().maximum(), 0)
            self.assertTrue(view.verticalScrollBar().isVisible())
            self.assertGreaterEqual(popup.geometry().top(), available.top())
            self.assertLessEqual(popup.geometry().bottom(), available.bottom())
            current = combo.model().index(combo.currentIndex(), combo.modelColumn())
            current_rect = view.visualRect(current)
            self.assertLess(current_rect.top(), view.viewport().height())
            self.assertGreaterEqual(current_rect.bottom(), 0)
        finally:
            combo.hidePopup()

    def test_translation_skill_is_enabled_only_for_editable_images(self):
        self.assertFalse(self.manager.copy_translation_button.isEnabled())

        asset = self.manager.assets[0]
        asset.plain_path.parent.mkdir(parents=True, exist_ok=True)
        asset.plain_path.write_bytes(asset.runtime_plain_path.read_bytes())
        self.manager._start_scan()
        self.manager._scan_worker.wait(5000)
        self.app.processEvents()

        self.assertTrue(self.manager.copy_translation_button.isEnabled())

    def test_copy_skill_has_visible_beginner_instructions(self):
        text = self.manager.copy_skill_help_banner.text_label.text()
        self.assertIn("Copy skill", text)
        self.assertIn("AI helper", text)
        self.assertIn("paste", text.casefold())
        self.assertIn("review every edited image", text)

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
        self.assertIn(str(self.game_root / "vocab.txt"), prompt)
        self.assertIn("RPG Maker MV/MZ image profile", prompt)
        self.assertIn("This is an RPG Maker MV/MZ project", prompt)
        self.assertIn("`.rpgmvp` or `.png_`", prompt)
        self.assertIn("authoritative glossary for every translation", prompt)
        self.assertIn("deterministic raster backend", prompt)
        self.assertIn("runtime value locations as protected keepout regions", prompt)
        self.assertIn("inner and outer glow layers", prompt)
        self.assertIn("Do not add a backing rectangle", prompt)
        self.assertIn("same visual role and emphasis", prompt)
        self.assertIn("image_translation_log.md", prompt)
        self.assertIn("Coordinates `(x, y, width, height)`", prompt)
        self.assertIn("one table row per text region", prompt)
        self.assertNotIn("{{GAME_ROOT}}", prompt)
        self.assertNotIn("{{EDITABLE_IMAGES_FOLDER}}", prompt)
        self.assertNotIn("{{VOCAB_FILE}}", prompt)
        self.assertNotIn("{{ENGINE_NAME}}", prompt)
        self.assertNotIn("{{ENGINE_CONTEXT}}", prompt)
        self.assertIn(
            "Copied image translation skill for 1 editable PNG",
            self.manager.status_label.text(),
        )

    def test_workflow_readiness_detects_editable_and_misplaced_pngs(self):
        asset = self.manager.assets[0]
        asset.plain_path.parent.mkdir(parents=True, exist_ok=True)
        asset.plain_path.write_bytes(asset.runtime_plain_path.read_bytes())
        self.game_root.joinpath("vocab.txt").write_text("Menu (Menu)\n", encoding="utf-8")
        misplaced = self.game_root / ".dazedtl" / "images" / "img (2)" / "pictures"
        misplaced.mkdir(parents=True)
        misplaced.joinpath("menu.png").write_bytes(asset.runtime_plain_path.read_bytes())

        report = _inspect_image_workflow(self.game_root)

        self.assertTrue(report["ok"])
        self.assertEqual(report["runtime"], 4)
        self.assertEqual(report["editable"], 1)
        self.assertEqual(report["misplaced"], 1)
        self.assertTrue(report["vocab"].is_file())

    def test_open_folder_uses_highlighted_images_editable_parent(self):
        self._click(0)
        asset_id = self.manager.image_list.currentItem().data(Qt.UserRole + 1)
        expected = self.manager.assets_by_id[asset_id].plain_path.parent
        self.manager.image_list.setCurrentItem(None)

        with patch(
            "gui.rpgmaker_image_manager.QDesktopServices.openUrl",
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
            "gui.rpgmaker_image_manager.QDesktopServices.openUrl",
            return_value=True,
        ) as open_url:
            self.manager._open_editable_folder()

        opened_url = open_url.call_args.args[0]
        self.assertEqual(Path(opened_url.toLocalFile()), expected)
        self.assertTrue(expected.is_dir())

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
    def test_page_size_supports_large_image_sets(self):
        self.assertEqual(_PAGE_SIZE, 1000)

    def test_image_manager_is_a_dedicated_sidebar_page(self):
        root = Path(__file__).resolve().parents[1]
        main_source = (root / "gui" / "main.py").read_text(encoding="utf-8")
        workflow_source = (root / "gui" / "workflow_tab.py").read_text(encoding="utf-8")
        self.assertIn("PAGE_IMAGES = 2", main_source)
        self.assertIn("from gui.image_manager import ImageManager", main_source)
        self.assertIn("self.image_manager_tab = ImageManager", main_source)
        self.assertIn('create_nav_button("🖼", "Images")', main_source)
        self.assertIn('(\"7  Images\",       self._build_step6_images)', workflow_source)
        self.assertIn('self._open_images_btn = _make_btn("🖼  Open Image Manager"', workflow_source)


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
            manager = RPGMakerImageManager(game_root, settings=settings)
            manager.resize(1000, 700)
            manager.show()
            manager._scan_worker.wait(5000)
            self.app.processEvents()
            try:
                self.assertEqual(manager.engine_combo.currentData(), PROFILE_AUTO)
                self.assertEqual(manager.engine_id, PROFILE_GENERIC)
                self.assertTrue(manager.generic_root_host.isVisible())
                self.assertEqual(manager.decrypt_selected_button.text(), "Make")
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
                self.assertIn("manages loose PNG assets", prompt)
                self.assertIn("without assuming a particular game engine", prompt)
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
            game_root.joinpath("vocab.txt").write_text("Menu (Menu)\n", encoding="utf-8")

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
                workflow._data_path = str(game_data)
                workflow.folder_edit.setText(str(game_data.parent))
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
