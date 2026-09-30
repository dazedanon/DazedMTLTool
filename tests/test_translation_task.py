"""Shared runner regressions without a Qt application or GUI imports."""
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

from util.translation_task import TranslationTask as TranslationWorker


class TranslationWorkerTests(unittest.TestCase):
    def setUp(self):
        environment = mock.patch.dict(os.environ, {"TRANSLATION_RUN_LOG": ""})
        environment.start()
        self.addCleanup(environment.stop)

    def test_estimate_uses_file_concurrency_and_returns_both_prices(self) -> None:
        """Estimate mode must stay accurate without forcing one file at a time."""
        worker = TranslationWorker(Path.cwd(), ("JSON", (".json",), None))
        barrier = threading.Barrier(3)
        lock = threading.Lock()
        active = {"count": 0, "max": 0}

        def estimate_one(_filename, *_args):
            with lock:
                active["count"] += 1
                active["max"] = max(active["max"], active["count"])
            barrier.wait(timeout=1.0)
            with lock:
                active["count"] -= 1
            return (
                "TOTAL: [Input: 100][Output: 20]"
                "[Cost: $0.0000][0.1s]"
            )

        worker.run_module_in_process = estimate_one
        with mock.patch.dict(os.environ, {
            "fileThreads": "3",
            "model": "gpt-5.6-terra",
            "api": "https://api.openai.com/v1",
            "API_PROVIDER": "openai",
        }):
            result = worker._run_files(
                ["a.json", "b.json", "c.json"], True
            )

        self.assertEqual(active["max"], 3)
        self.assertIn("[Input: 300]", result)
        self.assertIn("[Output: 60]", result)
        self.assertIn("[Batch:", result)
        self.assertIn("[Live:", result)
        self.assertAlmostEqual(
            worker.estimate_summary["batch_cost"],
            worker.estimate_summary["live_cost"] * 0.5,
        )

    def test_declining_batch_submission_discards_the_local_queue(self) -> None:
        # Cancel must release both approval waits, including a stop that arrives
        # before the prompt is opened. A late approval cannot undo cancellation.
        for action in ("decline", "stop", "stopped_before_prompt"):
            for prompt in ("batch", "linked_batch", "speakers"):
                with self.subTest(action=action, prompt=prompt):
                    worker = TranslationWorker(Path.cwd(), ("JSON", (".json",), None), preserve_batch_queue=prompt == "linked_batch")
                    def answer(*_args):
                        if action != "decline":
                            worker.stop()
                        worker.set_batch_submit_response(action != "decline")
                        worker.set_speaker_translation_response(action != "decline")
                    worker.batch_phase_signal.connect(answer)
                    worker.speaker_confirmation_signal.connect(answer)
                    if action == "stopped_before_prompt":
                        worker.stop()
                    results = []
                    wait = worker._wait_batch_submit if prompt != "speakers" else worker._wait_speaker_translation
                    with mock.patch("util.translation.clearBatchFiles") as clear_batch_files:
                        thread = threading.Thread(target=lambda: results.append(wait([])), daemon=True)
                        thread.start()
                        thread.join(timeout=1)
                        self.assertFalse(thread.is_alive(), "Stop left an approval prompt waiting")
                    self.assertEqual(results, [False])
                    self.assertEqual(clear_batch_files.call_count, int(prompt == "batch"))

    def test_failed_provider_batch_never_fetches_or_starts_consume(self) -> None:
        worker = TranslationWorker(Path.cwd(), ("JSON", (".json",), None))
        statuses = [{
            "id": "batch-failed",
            "provider": "openai",
            "api_status": "failed",
            "terminal_failure": True,
            "counts": {},
            "errors": [{
                "code": "invalid_request",
                "message": "Input file validation failed.",
                "param": "input_file_id",
            }],
        }]
        phases = []
        worker.batch_phase_signal.connect(
            lambda phase, payload: phases.append((phase, payload))
        )

        with (
            mock.patch(
                "util.translation._read_batch_file",
                return_value={"status": "partially_submitted", "sequential_token_limit": 100,
                              "batches": [{"id": "batch-failed"}]},
            ),
            mock.patch(
                "util.translation.checkTranslationBatchStatuses",
                return_value=(True, statuses),
            ),
            mock.patch("util.translation.fetchTranslationBatches") as fetch,
            mock.patch("util.translation.submitTranslationBatches") as submit,
            mock.patch("util.translation._batch_file_lock"),
        ):
            result = worker._run_batch_poll_fetch()

        self.assertIs(result, False)
        fetch.assert_not_called()
        submit.assert_not_called()
        self.assertEqual(phases[-1][0], "failed")
        self.assertIn("queue was preserved", phases[-1][1]["message"])

    def test_sequential_resume_polls_before_advancing_and_fetches_only_at_end(self):
        worker = TranslationWorker(Path.cwd(), ("JSON", (".json",), None))
        state = {"status": "partially_submitted", "sequential_token_limit": 100,
                 "batches": [{"id": "paid-first"}]}
        actions = []

        def poll(**_kwargs):
            actions.append("poll")
            return True, [{"id": state["batches"][-1]["id"], "terminal_failure": False}]

        def submit(**_kwargs):
            self.assertEqual(actions, ["poll"])
            actions.append("submit")
            state["status"] = "submitted"
            state["batches"].append({"id": "paid-last"})
            return ["paid-first", "paid-last"]

        def fetch():
            actions.append("fetch")
            return 3, 0

        with (
            mock.patch("util.translation._read_batch_file", side_effect=lambda *_: state),
            mock.patch("util.translation.checkTranslationBatchStatuses", side_effect=poll),
            mock.patch("util.translation.submitTranslationBatches", side_effect=submit),
            mock.patch("util.translation.fetchTranslationBatches", side_effect=fetch),
            mock.patch("util.translation._batch_file_lock"),
        ):
            self.assertEqual(worker._run_batch_poll_fetch(), (3, 0))
        self.assertEqual(actions, ["poll", "submit", "poll", "fetch"])

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
        """Unsupported plugin data cannot abort the shared RPG Maker worker."""
        worker = TranslationWorker(
            Path.cwd(), ("RPG Maker MV/MZ", (".json",), None)
        )
        calls = []
        errors = []
        progress = []
        worker.file_error_signal.connect(lambda *args: errors.append(args))
        worker.progress_signal.connect(lambda *args: progress.append(args))
        supported = ["Map001.json", "Map002.json", "Actors.json"]
        selected = ["TrpParticleGroups.json", *supported[:1],
                    "PluginData.json", *supported[1:]]

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
        for phase in ("collect", "estimate", "consume"):
            with self.subTest(phase=phase):
                progress.clear()
                result = worker._run_files(selected, phase == "estimate", phase)
                self.assertEqual(result, "TOTAL: success")
                self.assertEqual(calls[-1], (supported, phase == "estimate", phase))
                self.assertEqual([event[0] for event in progress], [1, 2, 3, 4, 5])
                self.assertTrue(all(event[1] == 5 for event in progress))
                self.assertEqual({event[2] for event in progress}, set(selected))
        self.assertEqual(len(calls), 3)
        # Collect/consume must not report the same skipped file twice.
        self.assertEqual([error[0] for error in errors],
                         ["TrpParticleGroups.json", "PluginData.json"])

        def fail_supported(filenames, *_args, file_result_callback):
            file_result_callback(filenames[0], ("SUBPROCESS_ERROR", "bad JSON"))
            return ("SUBPROCESS_ERROR", "bad JSON")

        worker.run_module_in_process = fail_supported
        self.assertEqual(worker._run_files(selected, True, "estimate"), "Fail")
        self.assertEqual([error[0] for error in errors[-3:]], supported)

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
            "util.translation_task.subprocess.Popen", return_value=process
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

        # Stop can race with Popen before the child is registered. The new
        # process must still be terminated, without reading its output.
        worker = TranslationWorker(Path.cwd(), ("JSON", (".json",), None))
        process = SimpleNamespace(terminate=mock.Mock(), wait=mock.Mock())
        def stop_during_spawn(*_args, **_kwargs):
            worker.stop()
            return process
        with mock.patch("util.translation_task.subprocess.Popen", side_effect=stop_during_spawn):
            self.assertEqual(worker.run_module_in_process("fixture.json", True), "Stopped")
        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=2)


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
            "util.translation_task.subprocess.Popen", return_value=process
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
                mock.patch("util.translation_task.load_dotenv"),
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
