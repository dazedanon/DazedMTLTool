from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from gui.theme import Spacing
from gui.translation_tab import BATCH_MODE_LABEL, TranslationTab


class TranslationTabUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.previous_cwd = Path.cwd()
        os.chdir(self.temporary.name)
        files = Path("files")
        files.mkdir()
        files.joinpath("Actors.json").write_text("{}", encoding="utf-8")
        files.joinpath("Map001.json").write_text("{}", encoding="utf-8")
        self.tab = TranslationTab()
        self.tab.files_dir = files.resolve()
        self.tab.translated_dir = Path("translated").resolve()
        self.tab.translated_dir.mkdir()
        self.tab.refresh_file_lists()
        self.tab.resize(1400, 900)
        self.tab.show()
        self.app.processEvents()

    def tearDown(self) -> None:
        self.tab.close()
        self.app.processEvents()
        os.chdir(self.previous_cwd)
        self.temporary.cleanup()

    def test_idle_workspace_prioritizes_scope_and_keeps_log_visible(self) -> None:
        self.assertEqual(self.tab.file_stack.currentIndex(), 0)
        self.assertTrue(self.tab.translation_log_viewer.isVisible())
        self.assertFalse(self.tab.translate_button.isEnabled())
        self.assertEqual(self.tab.selection_summary_label.text(), "0 of 2 selected")
        self.assertEqual(self.tab.select_all_button.text(), "All")
        self.assertEqual(self.tab.clear_selection_button.text(), "Clear")
        self.assertEqual(self.tab.add_files_button.text(), "Add")
        self.assertEqual(self.tab.remove_files_button.text(), "Remove")
        self.assertEqual(self.tab.more_file_actions_button.text(), "More")
        self.assertEqual(self.tab.setup_card.title_label.text(), "Translation settings")
        self.assertEqual(self.tab.workspace_splitter.handleWidth(), Spacing.MD)
        self.assertEqual(
            [action.text() for action in self.tab.more_file_actions_button.menu().actions()],
            [
                "Open workspace folder",
                "Refresh file list",
                "Export selected translations to game",
                "Check model pricing",
            ],
        )

        self.tab.file_list.item(0).setCheckState(Qt.Checked)
        self.app.processEvents()
        self.assertTrue(self.tab.translate_button.isEnabled())
        self.assertEqual(self.tab.selection_summary_label.text(), "1 of 2 selected")

    def test_wide_setup_places_run_choices_side_by_side(self) -> None:
        self.tab.resize(1900, 900)
        self.app.processEvents()
        self.tab._arrange_translation_workspace()
        module_position = self.tab.settings_grid.getItemPosition(
            self.tab.settings_grid.indexOf(self.tab.module_combo)
        )
        mode_position = self.tab.settings_grid.getItemPosition(
            self.tab.settings_grid.indexOf(self.tab.mode_combo)
        )
        self.assertEqual(module_position[:2], (1, 0))
        self.assertEqual(mode_position[:2], (1, 1))
        button_rows = {
            button.parentWidget()
            for button in (
                self.tab.add_files_button,
                self.tab.remove_files_button,
                self.tab.more_file_actions_button,
                self.tab.select_all_button,
                self.tab.clear_selection_button,
            )
        }
        self.assertEqual(len(button_rows), 1)

    def test_narrow_file_toolbar_uses_two_aligned_equal_width_rows(self) -> None:
        self.tab.file_card.resize(620, self.tab.file_card.height())
        self.tab._arrange_translation_file_controls()
        self.assertEqual(self.tab.add_files_button.text(), "Add")
        self.assertEqual(self.tab.remove_files_button.text(), "Remove")
        buttons = (
            self.tab.add_files_button,
            self.tab.remove_files_button,
            self.tab.more_file_actions_button,
            self.tab.select_all_button,
            self.tab.clear_selection_button,
        )
        self.assertEqual(len({button.width() for button in buttons}), 1)
        self.assertIs(
            self.tab.selection_summary_label.parentWidget(),
            self.tab.file_controls_top_host,
        )
        self.assertIs(
            self.tab.select_all_button.parentWidget(), self.tab.file_controls_top_host
        )
        self.assertIs(
            self.tab.clear_selection_button.parentWidget(), self.tab.file_controls_top_host
        )
        for button in (
            self.tab.add_files_button,
            self.tab.remove_files_button,
            self.tab.more_file_actions_button,
        ):
            self.assertIs(button.parentWidget(), self.tab.file_controls_bottom_host)

    def test_log_remains_visible_beside_active_progress(self) -> None:
        self.assertEqual(self.tab.workspace_splitter.orientation(), Qt.Horizontal)
        self.assertTrue(self.tab.translation_log_viewer.isVisible())
        left_width, log_width = self.tab.workspace_splitter.sizes()
        self.assertLessEqual(abs(left_width - log_width), Spacing.XL)

        self.tab.file_stack.setCurrentIndex(1)
        self.tab._set_progress_view_mode(True, 2)
        self.tab._set_run_controls_enabled(False)
        self.assertTrue(self.tab.progress_tab_row.isVisible())
        self.assertTrue(self.tab.batch_tab_btn.isChecked())
        self.assertFalse(self.tab.files_tab_btn.isChecked())
        self.assertFalse(self.tab.module_combo.isEnabled())
        self.assertFalse(self.tab.mode_combo.isEnabled())
        self.tab._set_activity_visible(False)
        self.assertTrue(self.tab.translation_log_viewer.isVisible())

    def test_run_result_actions_use_explicit_labels(self) -> None:
        self.assertIs(
            self.tab.run_footer.layout().itemAt(0).widget(), self.tab.totals_widget
        )
        self.assertIs(
            self.tab.run_footer.layout().itemAt(1).widget(), self.tab.run_actions_host
        )
        self.assertEqual(self.tab.stop_button.text(), "Stop run")
        self.assertEqual(self.tab.reset_view_button.text(), "Back to files")
        self.assertEqual(
            self.tab.open_translations_button.text(), "Open output folder"
        )
        self.assertEqual(self.tab.sync_translated_button.text(), "Sync to workspace")
        self.assertEqual(self.tab.export_active_button.text(), "Export run to game")

    def test_modes_explain_batch_cost_and_name_the_primary_action(self) -> None:
        self.tab.mode_combo.setCurrentText("Translate")
        self.assertEqual(self.tab.translate_button.text(), "Start Translation")
        self.assertTrue(self.tab.batch_mode_note.isHidden())

        self.tab.mode_combo.setCurrentText(BATCH_MODE_LABEL)
        self.assertEqual(self.tab.translate_button.text(), "Start Batch Translation")
        self.assertFalse(self.tab.batch_mode_note.isHidden())
        self.assertIn("50%", self.tab.batch_mode_note.text())


if __name__ == "__main__":
    unittest.main()
