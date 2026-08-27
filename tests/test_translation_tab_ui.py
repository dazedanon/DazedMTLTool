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

from gui.log_viewer import LogViewer, _parse_mismatch_log_line
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

    def test_mvmz_batch_phase_reuses_one_process_for_all_files(self) -> None:
        """RPG Maker batch I/O must not pay one interpreter import per file."""
        worker = TranslationWorker(
            Path.cwd(), ("RPG Maker MV/MZ", (".json",), None)
        )
        calls = []

        def run_many(
            filenames,
            estimate_only,
            batch_phase,
            file_result_callback=None,
        ):
            calls.append((filenames, estimate_only, batch_phase))
            for filename in filenames:
                file_result_callback(filename, "TOTAL: success")
            return "Success"

        worker.run_module_in_process = run_many
        result = worker._run_files(
            ["Map001.json", "Map002.json", "Actors.json"],
            False,
            batch_phase="consume",
        )

        self.assertEqual(result, "TOTAL: success")
        self.assertEqual(
            calls,
            [(
                ["Map001.json", "Map002.json", "Actors.json"],
                False,
                "consume",
            )],
        )

    def test_multi_file_runner_streams_input_and_per_file_results(self) -> None:
        """The persistent protocol retains per-file mismatch reporting."""
        worker = TranslationWorker(
            Path.cwd(), ("RPG Maker MV/MZ", (".json",), None)
        )

        class CapturingInput(io.StringIO):
            def close(self):
                self.was_closed = True

        stdin = CapturingInput()
        process = SimpleNamespace(
            stdin=stdin,
            stdout=io.StringIO(
                'FILE_RESULT:{"filename":"Map001.json","result":"TOTAL: one",'
                '"mismatch_count":0}\n'
                'FILE_RESULT:{"filename":"Map002.json","result":"TOTAL: two",'
                '"mismatch_count":2}\n'
                "RESULT:Success\n"
            ),
            stderr=io.StringIO(""),
            returncode=0,
            wait=lambda: None,
        )
        results = []

        with mock.patch(
            "gui.translation_tab.subprocess.Popen", return_value=process
        ):
            overall = worker.run_module_in_process(
                ["Map001.json", "Map002.json"],
                False,
                batch_phase="consume",
                file_result_callback=lambda filename, result: results.append(
                    (filename, result)
                ),
            )

        self.assertEqual(
            json.loads(stdin.getvalue()),
            ["Map001.json", "Map002.json"],
        )
        self.assertEqual(overall, "Success")
        self.assertEqual(results[0], ("Map001.json", "TOTAL: one"))
        self.assertEqual(results[1][0], "Map002.json")
        self.assertEqual(results[1][1][0], "VALIDATION_MISMATCH")
        self.assertEqual(results[1][1][3], 2)

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
        self.assertEqual(worker._run_mismatch_count, 1)
        self.assertEqual(len(mismatches), 1)
        self.assertEqual(mismatches[0][0], "bad.json")
        self.assertEqual(errors, [])

    def test_completed_batch_with_mismatches_clears_active_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project_root = Path(temporary)
            project_root.joinpath("files").mkdir()
            project_root.joinpath("files", "Map001.json").write_text(
                "{}", encoding="utf-8"
            )
            worker = TranslationWorker(
                project_root,
                ("JSON", (".json",), None),
                selected_files=["Map001.json"],
                batch_mode=True,
                batch_resume_state="fetched",
            )
            phases = []
            finished = []
            worker.batch_phase_signal.connect(
                lambda phase, payload: phases.append((phase, payload))
            )
            worker.finished_signal.connect(
                lambda success, message: finished.append((success, message))
            )

            def finish_files(*_args, **_kwargs):
                worker._run_had_mismatch = True
                worker._run_mismatch_count = 5
                return "TOTAL: success"

            worker._run_files = finish_files
            required_env = {
                "api": "OpenAI",
                "key": "test-key",
                "model": "test-model",
                "language": "English",
                "timeout": "30",
                "fileThreads": "1",
                "threads": "1",
                "width": "40",
                "listWidth": "40",
                "TRANSLATION_RUN_LOG": "",
            }
            with (
                mock.patch.dict(os.environ, required_env, clear=False),
                mock.patch("gui.translation_tab.load_dotenv"),
                mock.patch("util.translation.clear_cache"),
                mock.patch("util.translation.batchRunMetadata", return_value={}),
                mock.patch("util.translation.clearBatchFiles") as clear_batch_files,
                mock.patch("util.batch_history.missing_result_count", return_value=(1, 1)),
                mock.patch(
                    "util.vocab.restore_batch_glossary_freeze_from_state",
                    return_value=False,
                ),
            ):
                worker.run()

        clear_batch_files.assert_called_once_with(strict=True)
        self.assertEqual(finished, [(True, "TOTAL: success")])
        self.assertIn(("done", {"mismatches": 5}), phases)


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

    def test_generic_context_and_legacy_resume_preserve_safe_workflow(self) -> None:
        self.tab._batch_active = True
        self.tab._on_batch_phase("canceled", {"requests": 3})
        self.tab._apply_finish_ui(True, "Batch canceled")

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
        self.assertIn("has finished", prompt)
        self.assertNotIn("already in progress", prompt)

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

        self.tab._batch_active = True
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
