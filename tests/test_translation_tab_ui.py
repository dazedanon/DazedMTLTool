from __future__ import annotations

import io
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from gui.theme import Spacing
from gui.translation_tab import (
    BATCH_MODE_LABEL,
    TranslationTab,
    TranslationWorker,
    _format_estimated_cost,
)


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

    def test_worker_reports_partial_file_failure_as_aggregate_failure(self) -> None:
        worker = TranslationWorker(
            Path.cwd(), ("JSON", (".json",), None)
        )
        worker.run_module_in_process = lambda filename, *_args: (
            "Fail" if filename == "bad.json" else "TOTAL: success"
        )
        errors = []
        worker.file_error_signal.connect(
            lambda filename, message: errors.append((filename, message))
        )

        with mock.patch.dict(os.environ, {"fileThreads": "1"}):
            result = worker._run_files(
                ["bad.json", "good.json"], False, batch_phase="consume"
            )

        self.assertEqual(result, "Fail")
        self.assertEqual(errors, [("bad.json", "Translation failed")])

    def test_translation_waits_for_evaluation_corpus_capture(self) -> None:
        worker = mock.Mock()
        worker.isRunning.return_value = True
        self.tab.parent_window = SimpleNamespace(
            evaluation_tab=SimpleNamespace(
                _worker=worker,
                _worker_uses_translation_runtime=True,
            )
        )

        with mock.patch(
            "gui.translation_tab.QMessageBox.warning"
        ) as warning:
            self.tab.start_translation()

        warning.assert_called_once()
        self.assertIn("preparation", warning.call_args.args[1].lower())

    def test_worker_turns_validation_marker_into_file_failure(self) -> None:
        worker = TranslationWorker(
            Path(__file__).resolve().parents[1], ("JSON", (".json",), None)
        )
        process = SimpleNamespace(
            stdout=io.StringIO(
                "MISMATCH_EVENT:Map001.json\nRESULT:TOTAL: success\n"
            ),
            stderr=io.StringIO(""),
            returncode=0,
            wait=lambda: None,
        )

        with mock.patch("gui.translation_tab.subprocess.Popen", return_value=process):
            result = worker.run_module_in_process(
                "Map001.json", False, batch_phase="consume"
            )

        self.assertEqual(result[0], "SUBPROCESS_ERROR")
        self.assertIn("validation failed", result[1].lower())

    def test_finish_before_file_progress_unlocks_ui_immediately(self) -> None:
        self.tab.files_total = 2
        self.tab.files_completed = 0
        self.tab._file_progress_started = False

        with mock.patch.object(self.tab, "_apply_finish_ui") as apply_finish:
            self.tab.on_translation_finished(False, "Speaker translation canceled")

        apply_finish.assert_called_once_with(False, "Speaker translation canceled")
        self.assertIsNone(self.tab._finish_pending)

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

    def test_completed_speaker_collection_resets_next_run_to_translate(self) -> None:
        self.assertGreaterEqual(self.tab.mode_combo.findText("Parse Speakers"), 0)
        self.tab.mode_combo.setCurrentText("Parse Speakers")
        self.tab.translation_worker = SimpleNamespace(parse_speakers=True)

        self.tab._apply_finish_ui(True, "Success")

        self.assertEqual(self.tab.mode_combo.currentText(), "Translate")

    def test_batch_no_work_is_not_rendered_as_completed_or_queued(self) -> None:
        self.tab._batch_active = True
        self.tab._on_batch_phase("no_work", {"files": 1})
        self.tab._apply_finish_ui(True, "Success")

        self.assertEqual(self.tab._batch_ui_phase, "no_work")
        self.assertIn("No work found", self.tab.batch_phase_title.text())
        self.assertEqual(self.tab.batch_overall_bar.value(), 25)
        self.assertEqual(self.tab.batch_overall_bar.format(), "No batch submitted")
        self.assertEqual(self.tab.translate_button.text(), "Nothing to submit")

    def test_failed_batch_is_not_rendered_as_complete(self) -> None:
        self.tab._batch_active = True
        self.tab._on_batch_phase("submit", {"files": 1, "requests": 16})
        self.tab._apply_finish_ui(False, "Gemini rejected the batch")

        self.assertEqual(self.tab._batch_ui_phase, "failed")
        self.assertIn("Failed", self.tab.batch_phase_title.text())
        self.assertEqual(self.tab.batch_overall_bar.format(), "Failed")
        self.assertNotEqual(self.tab.batch_overall_bar.value(), 100)

    def test_gemini_submit_estimate_uses_precision_and_thinking_warning(self) -> None:
        self.tab._batch_active = True
        self.tab._on_batch_phase("submit", {
            "files": 1,
            "requests": 16,
            "model": "models/gemini-3.6-flash",
            "provider": "gemini",
            "input_tokens": 54866,
            "output_tokens": 6600,
            "batch_cached_cost": 0.0658995,
            "batch_nocache_cost": 0.0658995,
            "live_cost": 0.131799,
            "uses_prompt_cache": False,
            "unestimated_thinking_tokens": True,
        })

        self.assertTrue(self.tab.batch_cost_cached.isHidden())
        self.assertEqual(
            self.tab.batch_cost_nocache.text(),
            "Batch estimate\n$0.0659 + thinking",
        )
        self.assertEqual(
            self.tab.batch_cost_live.text(),
            "Live API\n$0.1318 + thinking",
        )
        self.assertIn("54,866 input", self.tab.batch_submit_summary.text())
        self.assertIn("exclude them", self.tab.batch_submit_summary.text())
        self.assertIn("Model: gemini-3.6-flash", self.tab.batch_submit_summary.text())

    def test_estimated_cost_format_preserves_sub_cent_values(self) -> None:
        self.assertEqual(_format_estimated_cost(0.0027433), "$0.0027")
        self.assertEqual(_format_estimated_cost(1.234), "$1.23")

    def test_openai_submit_estimate_labels_automatic_cache(self) -> None:
        self.tab._batch_active = True
        self.tab._on_batch_phase("submit", {
            "files": 1,
            "requests": 16,
            "model": "gpt-5.6-terra",
            "provider": "openai",
            "input_tokens": 54866,
            "output_tokens": 6600,
            "batch_cached_cost": 0.055,
            "batch_nocache_cost": 0.094466,
            "live_cost": 0.188932,
            "uses_prompt_cache": True,
            "cache_kind": "automatic",
        })

        self.assertFalse(self.tab.batch_cost_cached.isHidden())
        self.assertEqual(
            self.tab.batch_cost_cached.text(),
            "Batch + auto cache\n$0.0550",
        )
        self.assertEqual(
            self.tab.batch_cost_nocache.text(),
            "Batch worst-case\n$0.0945",
        )


if __name__ == "__main__":
    unittest.main()
