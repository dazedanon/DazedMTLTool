from __future__ import annotations

import io
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from gui.log_viewer import LogViewer, _parse_mismatch_log_line
from gui.translation_tab import (
    TranslationTab,
    TranslationWorker,
    _format_estimated_cost,
)




class TranslationLogFormattingTests(unittest.TestCase):
    def test_mismatch_blocks_count_once_instead_of_once_per_line(self) -> None:
        lines = (
            "[MISMATCH] Validation mismatch: Troops.json",
            "[MISMATCH] Original text kept after 5 attempts.",
            "[MISMATCH] Input:",
            '[MISMATCH] {"Line1": "Japanese"}',
            "[MISMATCH] Provider output:",
            '[MISMATCH] {"Line1": "English"}',
            "[MISMATCH] End mismatch",
            "[MISMATCH] Validation mismatch: Map001.json",
            "[MISMATCH] Original text kept after 5 attempts.",
            "[MISMATCH] End mismatch",
        )
        in_block = False
        mismatch_count = 0
        bodies = []

        for line in lines:
            body, starts_block, in_block = _parse_mismatch_log_line(
                line, in_block
            )
            bodies.append(body)
            mismatch_count += int(starts_block)

        self.assertEqual(mismatch_count, 2)
        self.assertEqual(LogViewer._plural(mismatch_count, "mismatch"), "mismatches")
        self.assertEqual(bodies[0], "Validation mismatch: Troops.json")
        self.assertNotIn("[MISMATCH]", "\n".join(bodies))


class TranslationCostFormattingTests(unittest.TestCase):
    def test_preserves_sub_cent_values(self) -> None:
        self.assertEqual(_format_estimated_cost(0.0027433), "$0.0027")
        self.assertEqual(_format_estimated_cost(1.234), "$1.23")


class TranslationTabUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        alert_env = mock.patch.dict(os.environ, {"translationCompletionAlert": "false"})
        alert_env.start()
        self.addCleanup(alert_env.stop)
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

    def test_finish_before_file_progress_unlocks_ui_immediately(self) -> None:
        self.tab.files_total = 2
        self.tab.files_completed = 0
        self.tab._file_progress_started = False

        with mock.patch.object(self.tab, "_apply_finish_ui") as apply_finish:
            self.tab.on_translation_finished(False, "Speaker translation canceled")

        apply_finish.assert_called_once_with(False, "Speaker translation canceled")
        self.assertIsNone(self.tab._finish_pending)

        # A completion alert belongs to the entire run, after the last file's
        # results arrive. Duplicate finish signals must never repeat the alert.
        with (
            mock.patch.dict(os.environ, {"translationCompletionAlert": "true"}),
            mock.patch.object(QApplication, "beep") as beep,
            mock.patch.object(QApplication, "alert") as alert,
            mock.patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=True) as available,
            mock.patch.object(QSystemTrayIcon, "supportsMessages", return_value=True) as supports,
            mock.patch.object(QSystemTrayIcon, "show"),
            mock.patch.object(QSystemTrayIcon, "showMessage") as message,
        ):
            self.tab._file_progress_started = True
            self.tab.on_translation_finished(True, "Success")
            self.assertIsNotNone(self.tab._finish_pending)
            beep.assert_not_called()
            self.tab.update_file_progress(1, 2, "Actors.json")
            beep.assert_not_called()
            self.tab.update_file_progress(2, 2, "Map001.json")
            beep.assert_called_once_with()
            alert.assert_called_once()
            message.assert_called_once()
            self.assertIsNone(self.tab._finish_pending)
            self.tab.on_translation_finished(True, "Success")
            beep.assert_called_once()
            message.assert_called_once()

            parent = SimpleNamespace(PAGE_TRANSLATION=3, switch_page=mock.Mock())
            self.tab.parent_window = parent
            self.tab._completion_tray.messageClicked.emit()
            parent.switch_page.assert_called_once_with(parent.PAGE_TRANSLATION)

            # Disabled alerts are silent. Machines without desktop-message
            # support still get the sound and taskbar attention when enabled.
            for enabled, has_tray, has_messages in (
                (False, True, True), (True, False, True), (True, True, False),
            ):
                with self.subTest(enabled=enabled, tray=has_tray, messages=has_messages):
                    os.environ["translationCompletionAlert"] = str(enabled).lower()
                    available.return_value = has_tray
                    supports.return_value = has_messages
                    self.tab._completion_notified = False
                    beep.reset_mock()
                    alert.reset_mock()
                    message.reset_mock()
                    self.tab.on_translation_finished(True, "Success")
                    self.assertEqual(beep.call_count, int(enabled))
                    self.assertEqual(alert.call_count, int(enabled))
                    message.assert_not_called()

    def test_estimate_choice_stays_safe_and_is_never_rendered_as_translation(
        self,
    ) -> None:
        """A deliberate estimate must survive refreshes and remain unmistakable."""
        self.tab.mode_combo.setCurrentText("Estimate")
        self.tab._mark_mode_user_selected(1)
        self.tab._last_default_translation_mode = "changed-provider"

        with mock.patch(
            "gui.translation_tab.default_translation_mode",
            return_value="Translate",
        ):
            self.tab.refresh_default_translation_mode()

        self.assertEqual(self.tab.mode_combo.currentText(), "Estimate")
        self.assertFalse(self.tab.estimate_mode_note.isHidden())
        self.assertIn("Batch and Live costs", self.tab.estimate_mode_note.text())
        self.assertIn(
            "No translations generated or written",
            self.tab.estimate_mode_note.text(),
        )

        self.tab.project_root = Path(self.temporary.name)
        self.tab.select_files_by_name(["Actors.json"])
        self.tab._completion_notified = True
        with (
            mock.patch(
                "gui.translation_tab._activate_configured_game_context",
                return_value=("", {}),
            ),
            mock.patch.object(TranslationWorker, "start") as start,
        ):
            self.tab.start_translation(skip_confirm=True)

        start.assert_called_once_with()
        self.assertTrue(self.tab.translation_worker.estimate_only)
        self.assertEqual(self.tab.file_card.title_label.text(), "Estimation progress")
        self.assertEqual(
            self.tab.progress_table.horizontalHeaderItem(4).text(), "Est. cost"
        )

        self.tab.update_item_progress("Actors.json", 1, 10)
        row = self.tab.file_progress_items["Actors.json"]["row"]
        self.assertEqual(
            self.tab.progress_table.item(row, 1).text(), "Estimating"
        )

        # Request-set estimation has no per-file billing line. Its definitive
        # file event must close the row, and a buffered tqdm event must not
        # paint that completed row back to Estimating.
        self.tab.update_file_progress(1, 1, "Actors.json")
        self.assertEqual(
            self.tab.progress_table.item(row, 1).text(), "Estimated"
        )
        self.tab.update_item_progress("Actors.json", 10, 10)
        self.assertEqual(
            self.tab.progress_table.item(row, 1).text(), "Estimated"
        )
        self.assertEqual(self.tab.progress_table.item(row, 2).text(), "✓")

        with mock.patch(
            "gui.translation_tab._estimate_cost_comparison",
            return_value={
                "batch_supported": True,
                "batch_cost": 0.25,
                "live_cost": 0.50,
                "unestimated_thinking_tokens": False,
            },
        ):
            self.tab._apply_file_result("Actors.json", 100, 200, 0.50, 1.0)
        self.assertEqual(
            self.tab.progress_table.item(row, 1).text(), "Estimated"
        )
        self.assertIn("Batch $0.2500", self.tab.totals_cost_label.text())
        self.assertIn("Live $0.5000", self.tab.totals_cost_label.text())

        self.tab._apply_estimate_summary({
            "basis": "request_queue",
            "input_tokens": 1000,
            "output_tokens": 200,
            "batch_supported": True,
            "batch_cost": 0.20,
            "batch_cached_cost": 0.15,
            "batch_nocache_cost": 0.20,
            "live_cost": 0.40,
            "uses_prompt_cache": True,
            "cache_kind": "automatic",
            "unestimated_thinking_tokens": False,
            "elapsed_seconds": 1.5,
        })
        self.assertIn("1000 in / 200 out", self.tab.totals_tokens_label.text())
        self.assertIn("Batch + auto cache $0.1500", self.tab.totals_cost_label.text())
        self.assertIn("Batch worst-case $0.2000", self.tab.totals_cost_label.text())
        self.assertIn("Live $0.4000", self.tab.totals_cost_label.text())
        self.assertEqual(self.tab.totals_time_label.text(), "Time: 1.5s")

        self.assertFalse(self.tab._completion_notified, "Starting a new run must rearm its alert.")
        with (
            mock.patch.dict(os.environ, {"translationCompletionAlert": "true"}),
            mock.patch.object(QApplication, "beep") as beep,
        ):
            self.tab._apply_finish_ui(True, "TOTAL: estimate")
        beep.assert_not_called()
        self.assertIn("Batch + auto cache $0.1500", self.tab.totals_cost_label.text())
        self.assertEqual(self.tab.file_card.title_label.text(), "Estimation results")
        self.assertEqual(self.tab.translate_button.text(), "Estimation complete")
        self.assertTrue(self.tab.open_translations_button.isHidden())
        self.assertTrue(self.tab.sync_export_button.isHidden())






    def test_finished_run_offers_the_contextual_next_action(self) -> None:
        self.assertGreaterEqual(self.tab.mode_combo.findText("Parse Speakers"), 0)
        self.tab.mode_combo.setCurrentText("Parse Speakers")
        self.tab.translation_worker = SimpleNamespace(parse_speakers=True)

        with (
            mock.patch.dict(os.environ, {"translationCompletionAlert": "true"}),
            mock.patch.object(QApplication, "beep") as beep,
        ):
            self.tab._apply_finish_ui(True, "Success")
        beep.assert_not_called()

        self.assertEqual(self.tab.mode_combo.currentText(), "Translate")
        self.assertFalse(self.tab.sync_export_button.isHidden())
        self.assertTrue(self.tab.return_to_workflow_button.isHidden())
        self.tab.translation_worker = None

        game_data = Path(self.temporary.name) / "game" / "data"
        game_data.mkdir(parents=True)
        self.tab.translated_dir.joinpath("Actors.json").write_text(
            '{"name": "translated"}', encoding="utf-8"
        )
        self.tab.translated_dir.joinpath("Map001.json").write_text(
            '{"name": "not in run"}', encoding="utf-8"
        )
        self.tab._last_run_files = ["Actors.json"]

        with (
            mock.patch(
                "gui.translation_tab.QFileDialog.getExistingDirectory",
                return_value=str(game_data),
            ),
            mock.patch.object(
                QMessageBox, "question", return_value=QMessageBox.Yes
            ) as question,
            mock.patch.object(QMessageBox, "information"),
        ):
            self.tab._sync_and_export_last_run_files()

        expected = '{"name": "translated"}'
        self.assertEqual(
            self.tab.files_dir.joinpath("Actors.json").read_text(), expected
        )
        self.assertEqual(game_data.joinpath("Actors.json").read_text(), expected)
        self.assertFalse(game_data.joinpath("Map001.json").exists())
        question.assert_called_once()

        workflow = SimpleNamespace(_goto_step=mock.Mock())
        parent = SimpleNamespace(
            PAGE_WORKFLOW=1,
            switch_page=mock.Mock(),
            workflow_stack=None,
            workflow_engine_combo=None,
        )
        self.tab.parent_window = parent
        self.tab._active_workflow_return = (workflow, 4)

        self.tab._apply_finish_ui(True, "Success")

        self.assertFalse(self.tab.return_to_workflow_button.isHidden())
        self.assertTrue(self.tab.reset_view_button.isHidden())
        self.assertTrue(self.tab.open_translations_button.isHidden())
        self.assertFalse(self.tab.sync_export_button.isHidden())
        self.assertTrue(self.tab.translate_button.isHidden())

        self.tab.return_to_workflow_button.click()

        workflow._goto_step.assert_called_once_with(4)
        parent.switch_page.assert_called_once_with(parent.PAGE_WORKFLOW)
        self.assertEqual(self.tab.file_stack.currentIndex(), 0)
        self.assertIsNone(self.tab._active_workflow_return)

    def test_generic_context_and_legacy_resume_preserve_safe_workflow(self) -> None:
        self.tab._batch_active = True
        self.tab._on_batch_phase("canceled", {"requests": 3})
        with (
            mock.patch.dict(os.environ, {"translationCompletionAlert": "true"}),
            mock.patch.object(QApplication, "beep") as beep,
        ):
            self.tab._apply_finish_ui(True, "Batch canceled")
        beep.assert_not_called()

        self.assertEqual(self.tab.file_stack.currentIndex(), 0)
        self.assertFalse(self.tab._batch_active)
        self.assertEqual(self.tab.file_card.title_label.text(), "Files to translate")

        context_root = Path(self.temporary.name) / "context-game"
        context_root.joinpath("data").mkdir(parents=True)
        context_root.joinpath("data", "System.json").write_text(
            "{}", encoding="utf-8"
        )
        context_root.joinpath(".dazedtl", "skills").mkdir(parents=True)
        context_root.joinpath(".dazedtl", "glossary.txt").write_text(
            "Hero (Hero)\n", encoding="utf-8"
        )
        context_root.joinpath(".dazedtl", "skills", "game.md").write_text(
            "# Translation Frame\n", encoding="utf-8"
        )
        context_root.joinpath(".dazedtl", "skills", "quirks.md").write_text(
            "- Keep the narrator terse.\n", encoding="utf-8"
        )
        context_root.joinpath(".dazedtl", "skills", "battle.md").write_text(
            "- Keep battle labels short.\n", encoding="utf-8"
        )
        self.assertFalse(self.tab.manual_context_host.isHidden())
        with mock.patch(
            "gui.translation_tab.QFileDialog.getExistingDirectory",
            return_value=str(context_root),
        ):
            self.tab._choose_manual_context_root()
        self.assertEqual(self.tab.manual_context_root_edit.text(), str(context_root))
        self.assertTrue(
            all(
                label.property("available")
                for label in self.tab.context_asset_labels.values()
            )
        )
        self.assertIn("4 context files", self.tab.context_status_label.text())

        QApplication.clipboard().clear()
        self.assertTrue(self.tab._copy_generic_project_setup())
        copied_setup = QApplication.clipboard().text()
        self.assertIn(str(context_root), copied_setup)
        self.assertNotIn("{{GAME_ROOT}}", copied_setup)

        self.tab._open_context_editor()
        self.app.processEvents()
        self.assertTrue(self.tab._context_dialog.isVisible())
        self.assertIn(
            "Hero (Hero)",
            self.tab._context_dialog.editors.vocab_editor.toPlainText(),
        )
        self.assertIn(
            "Translation Frame",
            self.tab._context_dialog.editors.game_skill_editor.toPlainText(),
        )
        self.tab._context_dialog.close()

        self.tab.mode_combo.setCurrentText("Batch Translate")
        self.tab.select_files_by_name(["Actors.json"])
        with (
            mock.patch("util.translation.batchRunState", return_value="queued"),
            mock.patch("util.translation.batchRunMetadata", return_value={}),
            mock.patch("util.translation.isBatchSupported", return_value=True),
            mock.patch(
                "gui.translation_tab.QMessageBox.question",
                return_value=QMessageBox.No,
            ) as question,
            mock.patch("gui.translation_tab.QMessageBox.warning") as warning,
            mock.patch(
                "gui.translation_tab._activate_configured_game_context",
                return_value=("", {}),
            ) as activate_game_context,
            mock.patch(
                "gui.translation_tab._activate_game_context_root",
                return_value=(str(context_root), {}),
            ) as activate_selected_context,
            mock.patch.object(TranslationWorker, "start") as start,
        ):
            self.tab.start_translation(skip_confirm=True)

        warning.assert_not_called()
        question.assert_called_once()
        self.assertLess(len(question.call_args.args[2]), 120)
        self.assertIsNone(self.tab.translation_worker.batch_resume_state)
        activate_game_context.assert_not_called()
        activate_selected_context.assert_called_once_with(
            str(context_root), "RPG Maker MV/MZ", validate_engine=False
        )
        start.assert_called_once_with()

        profile = {
            "engine": "rpgmakermvmz",
            "version": 1,
            "config": {
                "CODE101": True,
                "CODE401": True,
                "CODE405": True,
                "CODE102": True,
            },
            "enabled_plugins_357": [],
            "enabled_patterns_355655": [],
        }
        self.tab.select_files_by_name(["Map001.json"])
        metadata_without_profile = {
            "file_set": ["Map001.json"],
            "workflow_return": {
                "engine": "rpgmakermvmz",
                "step_index": 4,
            },
        }
        metadata_with_profile = {
            **metadata_without_profile,
            "runtime_profile": profile,
        }
        workflow = SimpleNamespace(
            _goto_step=mock.Mock(),
            _step_tabs=SimpleNamespace(currentIndex=lambda: 4),
        )
        parent = SimpleNamespace(
            workflow_tab=workflow,
            wolf_workflow_tab=None,
            evaluation_tab=None,
            workflow_stack=None,
            workflow_engine_combo=None,
            _ensure_workflow_container=mock.Mock(),
            PAGE_WORKFLOW=1,
            switch_page=mock.Mock(),
        )
        self.tab.parent_window = parent

        with (
            mock.patch("util.translation.isBatchSupported", return_value=True),
            mock.patch(
                "util.translation.batchRunMetadata",
                side_effect=[metadata_without_profile, metadata_with_profile],
            ),
            mock.patch(
                "util.runtime_profile.capture_batch_runtime_profile",
                return_value=profile,
            ),
            mock.patch("util.translation.saveBatchRuntimeProfile") as save_profile,
            mock.patch(
                "gui.translation_tab.QMessageBox.question",
                return_value=QMessageBox.Yes,
            ) as question,
            mock.patch(
                "gui.translation_tab._activate_configured_game_context",
                return_value=("", {}),
            ),
            mock.patch.object(TranslationWorker, "start") as start,
        ):
            self.tab.start_translation(forced_resume_state="fetched")

        save_profile.assert_called_once_with(profile)
        self.assertIn("legacy batch profile", question.call_args.args[1].lower())
        self.assertEqual(
            self.tab.translation_worker.batch_resume_state, "fetched"
        )
        self.assertEqual(
            self.tab.translation_worker.batch_workflow_return,
            {"engine": "rpgmakermvmz", "step_index": 4},
        )
        self.assertTrue(self.tab.manual_context_host.isHidden())
        start.assert_called_once_with()
        self.tab._apply_finish_ui(True, "Success")

        self.assertFalse(self.tab.return_to_workflow_button.isHidden())
        self.assertTrue(self.tab.reset_view_button.isHidden())
        self.tab.return_to_workflow_button.click()
        workflow._goto_step.assert_called_once_with(4)
        parent.switch_page.assert_called_once_with(parent.PAGE_WORKFLOW)

        self.tab.mode_combo.setCurrentText("Batch Translate")
        self.tab.select_files_by_name(["Actors.json"])
        with (
            mock.patch("gui.translation_tab.load_dotenv"),
            mock.patch("util.translation.batchRunState", return_value="fetched"),
            mock.patch("util.translation.isBatchSupported", return_value=True),
            mock.patch(
                "gui.translation_tab.QMessageBox.question",
                return_value=QMessageBox.No,
            ) as question,
            mock.patch(
                "gui.translation_tab._activate_configured_game_context",
                return_value=("", {}),
            ),
            mock.patch("gui.translation_tab._activate_game_context_root"),
            mock.patch.object(TranslationWorker, "start"),
        ):
            self.tab.start_translation(skip_confirm=True)

        prompt = question.call_args.args[2]
        self.assertIn("Downloaded results", prompt)
        self.assertIn("ready to write", prompt)
        self.assertNotIn("already in progress", prompt)

    @mock.patch.dict(os.environ, {"translationCompletionAlert": "true"})
    @mock.patch.object(QApplication, "beep")
    @mock.patch.object(QApplication, "alert")
    @mock.patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=False)
    def test_noncompletion_batch_outcomes_are_not_rendered_as_complete(self, _tray, _attention, beep) -> None:
        self.tab.create_progress_item("Classes.json")
        self.tab._batch_active = True
        self.tab._batch_ui_phase = "collect"
        self.tab.mark_file_queued("Classes.json")

        # A late monitor sample from a fast persistent-worker file must not
        # regress its definitive collect result back to Scanning 0/N.
        self.tab.update_item_progress("Classes.json", 0, 17)
        row = self.tab.file_progress_items["Classes.json"]["row"]
        self.assertEqual(self.tab.progress_table.item(row, 1).text(), "Collected")
        self.assertEqual(self.tab.progress_table.item(row, 2).text(), "queued")

        self.tab._batch_ui_phase = "consume"
        self.tab.update_item_progress("Classes.json", 1, 17)
        self.assertEqual(self.tab.progress_table.item(row, 1).text(), "Writing")
        self.assertEqual(self.tab.progress_table.item(row, 2).text(), "1/17")

        self.tab._batch_active = True
        self.tab._on_batch_phase("no_work", {"files": 1})
        self.tab._apply_finish_ui(True, "Success")

        self.assertEqual(self.tab._batch_ui_phase, "no_work")
        self.assertIn("No work found", self.tab.batch_phase_title.text())
        self.assertEqual(self.tab.batch_overall_bar.value(), 25)
        self.assertEqual(self.tab.batch_overall_bar.format(), "No batch submitted")
        self.assertEqual(self.tab.translate_button.text(), "Nothing to submit")
        beep.assert_not_called()

        self.tab._batch_active = True
        self.tab._completion_notified = False
        self.tab._on_batch_phase("submit", {"files": 1, "requests": 16})
        self.tab._apply_finish_ui(False, "Gemini rejected the batch")

        self.assertEqual(self.tab._batch_ui_phase, "failed")
        self.assertIn("Failed", self.tab.batch_phase_title.text())
        self.assertEqual(self.tab.batch_overall_bar.format(), "Failed")
        self.assertNotEqual(self.tab.batch_overall_bar.value(), 100)
        beep.assert_not_called()

        # Resume/poll must clear a stale Failed overall-bar label from a prior finish.
        self.tab._on_batch_phase("polling", None)
        self.assertEqual(self.tab.batch_overall_bar.format(), "%p%")
        self.assertIn("Processing", self.tab.batch_phase_title.text())

        self.tab._on_batch_phase("failed", {"message": "previous local run failed"})
        self.tab._on_batch_phase("poll_status", [{
            "id": "batch_x",
            "api_status": "in_progress",
            "request_count": 54,
            "counts": {
                "succeeded": 40,
                "processing": 14,
                "errored": 0,
                "canceled": 0,
                "expired": 0,
            },
        }])
        self.assertEqual(self.tab.batch_overall_bar.format(), "%p%")
        self.assertIn("Processing", self.tab.batch_phase_title.text())
        self.assertIn("in_progress", self.tab.batch_poll_status.text())
        beep.assert_not_called()

        self.tab._batch_active = True
        self.tab._completion_notified = False
        self.tab.translation_worker = SimpleNamespace(_run_mismatch_count=5)
        self.tab._on_batch_phase("consume", None)

        self.tab._apply_finish_ui(True, "TOTAL: success")

        self.assertEqual(self.tab._batch_ui_phase, "done")
        self.assertIn("Complete with warnings", self.tab.batch_phase_title.text())
        self.assertEqual(
            self.tab.batch_overall_bar.format(), "Completed with warnings"
        )
        self.assertIn("5 validation mismatches", self.tab.batch_consume_status.text())
        self.assertNotIn("Failed", self.tab.translating_label.text())
        beep.assert_called_once_with()
        self.tab._apply_finish_ui(True, "TOTAL: success")
        beep.assert_called_once_with()

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
