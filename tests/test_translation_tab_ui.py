from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QMessageBox

from gui.translation_tab import (
    TranslationTab,
    TranslationWorker,
    _format_estimated_cost,
)


class TranslationWorkerTests(unittest.TestCase):
    def test_declining_batch_submission_discards_the_local_queue(self) -> None:
        worker = TranslationWorker(Path.cwd(), ("JSON", (".json",), None))
        worker.batch_phase_signal.connect(
            lambda _phase, _estimate: worker.set_batch_submit_response(False)
        )

        with mock.patch("util.translation.clearBatchFiles") as clear_batch_files:
            approved = worker._wait_batch_submit({"requests": 3})

        self.assertFalse(approved)
        clear_batch_files.assert_called_once_with(strict=True)

    def test_partial_file_failure_is_an_aggregate_failure(self) -> None:
        worker = TranslationWorker(Path.cwd(), ("JSON", (".json",), None))
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

    def test_batch_consume_runs_files_sequentially(self) -> None:
        """Pass 2 must finish one file before starting the next."""
        worker = TranslationWorker(Path.cwd(), ("JSON", (".json",), None))
        started = []
        active = {"count": 0, "max": 0}

        def run_one(filename, *_args):
            started.append(filename)
            active["count"] += 1
            active["max"] = max(active["max"], active["count"])
            active["count"] -= 1
            return "TOTAL: success"

        worker.run_module_in_process = run_one
        with mock.patch.dict(os.environ, {"fileThreads": "4"}):
            result = worker._run_files(
                ["a.json", "b.json", "c.json"], False, batch_phase="consume"
            )

        self.assertEqual(result, "TOTAL: success")
        self.assertEqual(started, ["a.json", "b.json", "c.json"])
        self.assertEqual(active["max"], 1)

    def test_validation_marker_is_a_soft_mismatch(self) -> None:
        """Paid/validated chunks stay written; mismatch does not hard-fail the file."""
        worker = TranslationWorker(
            Path(__file__).resolve().parents[1],
            ("RPG Maker MV/MZ", (".json",), None),
        )
        process = SimpleNamespace(
            stdout=io.StringIO(
                "MISMATCH_EVENT:Map001.json\nRESULT:TOTAL: success\n"
            ),
            stderr=io.StringIO(""),
            returncode=0,
            wait=lambda: None,
        )
        worker.batch_runtime_profile = {
            "engine": "rpgmakermvmz",
            "version": 1,
            "config": {"CODE401": True},
            "enabled_plugins_357": [],
            "enabled_patterns_355655": [],
        }

        with mock.patch(
            "gui.translation_tab.subprocess.Popen", return_value=process
        ) as popen:
            result = worker.run_module_in_process(
                "Map001.json", False, batch_phase="consume"
            )

        self.assertEqual(result[0], "VALIDATION_MISMATCH")
        self.assertIn("validation failed", result[1].lower())
        self.assertEqual(result[2], "TOTAL: success")
        pinned_profile = json.loads(
            popen.call_args.kwargs["env"]["DAZED_BATCH_RUNTIME_PROFILE"]
        )
        self.assertTrue(pinned_profile["config"]["CODE401"])

    def test_batch_consume_continues_after_soft_mismatch(self) -> None:
        worker = TranslationWorker(Path.cwd(), ("JSON", (".json",), None))
        mismatches = []
        worker.file_mismatch_signal.connect(
            lambda filename, message: mismatches.append((filename, message))
        )
        errors = []
        worker.file_error_signal.connect(
            lambda filename, message: errors.append((filename, message))
        )

        def run_one(filename, *_args):
            if filename == "bad.json":
                return (
                    "VALIDATION_MISMATCH",
                    "original text was preserved for failed chunks",
                    "TOTAL: partial",
                )
            return "TOTAL: success"

        worker.run_module_in_process = run_one
        with mock.patch.dict(os.environ, {"fileThreads": "1"}):
            result = worker._run_files(
                ["bad.json", "good.json"], False, batch_phase="consume"
            )

        self.assertEqual(result, "TOTAL: success")
        self.assertTrue(worker._run_had_mismatch)
        self.assertEqual(len(mismatches), 1)
        self.assertEqual(mismatches[0][0], "bad.json")
        self.assertEqual(errors, [])


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






    def test_finished_run_offers_the_contextual_next_action(self) -> None:
        self.assertGreaterEqual(self.tab.mode_combo.findText("Parse Speakers"), 0)
        self.tab.mode_combo.setCurrentText("Parse Speakers")
        self.tab.translation_worker = SimpleNamespace(parse_speakers=True)

        self.tab._apply_finish_ui(True, "Success")

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

    def test_cancel_and_legacy_resume_preserve_safe_workflow(self) -> None:
        self.tab._batch_active = True
        self.tab._on_batch_phase("canceled", {"requests": 3})
        self.tab._apply_finish_ui(True, "Batch canceled")

        self.assertEqual(self.tab.file_stack.currentIndex(), 0)
        self.assertFalse(self.tab._batch_active)
        self.assertEqual(self.tab.file_card.title_label.text(), "Files to translate")

        manual_glossary = Path(self.temporary.name) / "manual-glossary.txt"
        manual_glossary.write_text("Manual (Selected)\n", encoding="utf-8")
        self.assertFalse(self.tab.manual_glossary_host.isHidden())
        self.assertTrue(self.tab.manual_glossary_base_checkbox.isChecked())
        with mock.patch(
            "gui.translation_tab.QFileDialog.getOpenFileName",
            return_value=(str(manual_glossary), "Glossary files (*.txt)"),
        ):
            self.tab._choose_manual_glossary()
        self.assertEqual(
            self.tab.manual_glossary_edit.text(), str(manual_glossary.resolve())
        )

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
                "gui.translation_tab._activate_manual_glossary"
            ) as activate_manual_glossary,
            mock.patch.object(TranslationWorker, "start") as start,
        ):
            self.tab.start_translation(skip_confirm=True)

        warning.assert_not_called()
        question.assert_called_once()
        self.assertLess(len(question.call_args.args[2]), 120)
        self.assertIsNone(self.tab.translation_worker.batch_resume_state)
        activate_game_context.assert_called_once_with(
            self.tab.settings, "RPG Maker MV/MZ"
        )
        activate_manual_glossary.assert_called_once_with(
            str(manual_glossary.resolve()), include_base=True
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
        metadata_without_profile = {"file_set": ["Map001.json"]}
        metadata_with_profile = {
            **metadata_without_profile,
            "runtime_profile": profile,
        }
        workflow = SimpleNamespace(
            _step_tabs=SimpleNamespace(currentIndex=lambda: 4)
        )
        self.tab.set_workflow_return_target(workflow)
        self.assertTrue(self.tab.manual_glossary_host.isHidden())

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
            mock.patch(
                "gui.translation_tab._activate_manual_glossary"
            ) as activate_manual_glossary,
            mock.patch.object(TranslationWorker, "start") as start,
        ):
            self.tab.start_translation(forced_resume_state="fetched")

        save_profile.assert_called_once_with(profile)
        self.assertIn("legacy batch profile", question.call_args.args[1].lower())
        self.assertEqual(
            self.tab.translation_worker.batch_resume_state, "fetched"
        )
        activate_manual_glossary.assert_not_called()
        start.assert_called_once_with()

    def test_noncompletion_batch_outcomes_are_not_rendered_as_complete(self) -> None:
        self.tab._batch_active = True
        self.tab._on_batch_phase("no_work", {"files": 1})
        self.tab._apply_finish_ui(True, "Success")

        self.assertEqual(self.tab._batch_ui_phase, "no_work")
        self.assertIn("No work found", self.tab.batch_phase_title.text())
        self.assertEqual(self.tab.batch_overall_bar.value(), 25)
        self.assertEqual(self.tab.batch_overall_bar.format(), "No batch submitted")
        self.assertEqual(self.tab.translate_button.text(), "Nothing to submit")

        self.tab._batch_active = True
        self.tab._on_batch_phase("submit", {"files": 1, "requests": 16})
        self.tab._apply_finish_ui(False, "Gemini rejected the batch")

        self.assertEqual(self.tab._batch_ui_phase, "failed")
        self.assertIn("Failed", self.tab.batch_phase_title.text())
        self.assertEqual(self.tab.batch_overall_bar.format(), "Failed")
        self.assertNotEqual(self.tab.batch_overall_bar.value(), 100)

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
