#!/usr/bin/env python3
"""Shared-worker regression tests for deferred grouped speaker translation."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from util.translation_task import TranslationTask as TranslationWorker, _should_prepare_speakers_automatically
import modules.rpgmakermvmz as mvmz


class SpeakerPreflightWorkerTests(unittest.TestCase):
    def _worker(self, root: Path) -> TranslationWorker:
        return TranslationWorker(
            root,
            ["RPG Maker MV/MZ", ["json"], None],
            selected_files=["Map001.json", "Map002.json"],
        )

    def test_scan_finishes_before_approval_and_grouped_translation(self):
        with tempfile.TemporaryDirectory() as raw:
            worker = self._worker(Path(raw))
            events = []
            tokens = [0, 0]

            def handle(filename, estimate):
                events.append(("scan", filename, estimate))

            def pending():
                events.append(("pending",))
                return ["騎士", "秘書官"]

            def finalize():
                events.append(("translate",))
                tokens[:] = [10, 2]

            estimate = {
                "model": "test-model",
                "request_count": 1,
                "input_tokens": 100,
                "output_tokens": 10,
                "estimated_cost": 0.001,
            }

            def approve(payload):
                events.append(("approve", payload))
                worker.set_speaker_translation_response(True)

            worker.speaker_confirmation_signal.connect(approve)
            with (
                patch.object(mvmz, "refreshRuntimeConfig") as refresh,
                patch.object(mvmz, "TOKENS", tokens),
                patch.object(mvmz, "resetSpeakerState"),
                patch.object(mvmz, "setSpeakerParseMode"),
                patch.object(mvmz, "handleMVMZ", side_effect=handle),
                patch.object(mvmz, "pendingSpeakerNames", side_effect=pending),
                patch.object(mvmz, "finalizeSpeakerParse", side_effect=finalize),
                patch.object(mvmz, "calculateCost", return_value=0.01),
                patch.object(
                    worker,
                    "_estimate_grouped_speakers",
                    return_value=estimate,
                ),
            ):
                self.assertTrue(worker._prepare_mvmz_speakers(worker.selected_files))

            self.assertEqual(
                events,
                [
                    ("scan", "Map001.json", False),
                    ("scan", "Map002.json", False),
                    ("pending",),
                    ("approve", {**estimate, "speakers": ["騎士", "秘書官"]}),
                    ("translate",),
                ],
            )
            refresh.assert_called_once_with()

    def test_grouped_estimate_reports_requests_tokens_and_cost_without_translation(self):
        config = SimpleNamespace(batchSize=2, maxHistory=10, model="test-model")
        with (
            patch("util.translation.createContext", return_value=("system", "", "user")),
            patch("util.translation.countTokens", return_value=[100, 20]),
            patch(
                "util.translation.getPricingConfig",
                return_value={"inputAPICost": 2.0, "outputAPICost": 8.0},
            ),
            patch("util.translation.isClaudeNative", return_value=False),
        ):
            estimate = TranslationWorker._estimate_grouped_speakers(
                ["騎士", "秘書官", "王"], "npc history", config, "test-model"
            )

        self.assertEqual(estimate["request_count"], 2)
        self.assertEqual(estimate["input_tokens"], 200)
        self.assertEqual(estimate["output_tokens"], 40)
        self.assertAlmostEqual(estimate["estimated_cost"], 0.00072)
        self.assertFalse(estimate["cold_cache"])


    def test_cancel_sends_no_speaker_translation(self):
        with tempfile.TemporaryDirectory() as raw:
            worker = self._worker(Path(raw))
            worker.speaker_confirmation_signal.connect(
                lambda _payload: worker.set_speaker_translation_response(False)
            )
            with (
                patch.object(mvmz, "resetSpeakerState"),
                patch.object(mvmz, "setSpeakerParseMode"),
                patch.object(mvmz, "handleMVMZ"),
                patch.object(
                    mvmz,
                    "pendingSpeakerNames",
                    return_value=["騎士", "秘書官"],
                ),
                patch.object(mvmz, "finalizeSpeakerParse") as finalize,
                patch.object(
                    worker,
                    "_estimate_grouped_speakers",
                    return_value={
                        "request_count": 1,
                        "input_tokens": 100,
                        "output_tokens": 10,
                        "estimated_cost": 0.001,
                    },
                ),
            ):
                self.assertFalse(worker._prepare_mvmz_speakers(worker.selected_files))
            finalize.assert_not_called()

    def test_mvmz_scan_failure_fails_preflight_before_translation(self):
        with tempfile.TemporaryDirectory() as raw:
            worker = self._worker(Path(raw))
            with (
                patch.object(mvmz, "resetSpeakerState"),
                patch.object(mvmz, "setSpeakerParseMode"),
                patch.object(mvmz, "handleMVMZ", side_effect=ValueError("bad JSON")),
                patch.object(mvmz, "pendingSpeakerNames") as pending,
                patch.object(mvmz, "finalizeSpeakerParse") as finalize,
            ):
                self.assertFalse(
                    worker._prepare_mvmz_speakers(worker.selected_files)
                )

            pending.assert_not_called()
            finalize.assert_not_called()

    def test_known_nontranslatable_mvmz_files_do_not_block_speaker_scan(self):
        """Engine and plugin data without parsers must not abort speaker scans."""
        with tempfile.TemporaryDirectory() as raw:
            worker = TranslationWorker(
                Path(raw),
                ["RPG Maker MV/MZ", ["json"], None],
                selected_files=[
                    "Animations.json",
                    "Map001.json",
                    "Tilesets.json",
                    "TrpParticleGroups.json",
                ],
                parse_speakers=True,
            )
            logs = []
            errors = []
            progress = []
            worker.log_signal.connect(logs.append)
            worker.file_error_signal.connect(lambda *args: errors.append(args))
            worker.progress_signal.connect(lambda *args: progress.append(args))

            with (
                patch.object(mvmz, "resetSpeakerState"),
                patch.object(mvmz, "setSpeakerParseMode"),
                patch.object(mvmz, "handleMVMZ") as handle,
                patch.object(mvmz, "pendingSpeakerNames", return_value=[]),
                patch.object(mvmz, "finalizeSpeakerParse") as finalize,
            ):
                self.assertTrue(
                    worker._prepare_mvmz_speakers(
                        worker.selected_files, emit_progress=True
                    )
                )

            handle.assert_called_once_with("Map001.json", False)
            finalize.assert_not_called()
            self.assertEqual(
                [error[0] for error in errors],
                ["Animations.json", "Tilesets.json", "TrpParticleGroups.json"],
            )
            self.assertEqual(
                progress,
                [
                    (1, 4, "Animations.json"),
                    (2, 4, "Map001.json"),
                    (3, 4, "Tilesets.json"),
                    (4, 4, "TrpParticleGroups.json"),
                ],
            )
            self.assertTrue(any("3 unsupported skipped" in line for line in logs))
            self.assertFalse(any("Speaker scan failed" in line for line in logs))

    def test_known_nontranslatable_mvmz_files_do_not_fail_translation_run(self):
        unsupported = ["Animations.json", "TrpParticleGroups.json"]
        for estimate, supported in (
            (False, ["Map001.json"]), (True, ["Map001.json"]),
            (False, []), (True, []),
        ):
            with self.subTest(estimate=estimate, supported=supported):
                self._check_unsupported_run(unsupported, supported, estimate)

    def _check_unsupported_run(self, unsupported, supported, estimate):
        with tempfile.TemporaryDirectory() as raw:
            selected = unsupported + supported
            worker = TranslationWorker(
                Path(raw),
                ["RPG Maker MV/MZ", ["json"], None],
                selected_files=selected,
            )
            errors = []
            progress = []
            worker.file_error_signal.connect(lambda *args: errors.append(args))
            worker.progress_signal.connect(lambda *args: progress.append(args))

            with (
                patch.dict(os.environ, {
                    "fileThreads": "1", "model": "gpt-5.6-terra",
                    "api": "https://api.openai.com/v1", "API_PROVIDER": "openai",
                }),
                patch.object(
                    worker, "run_module_in_process", return_value="Success"
                ) as run_file,
            ):
                result = worker._run_files(selected, estimate)

            if estimate:
                self.assertIn("TOTAL estimate:", result)
            else:
                self.assertEqual(result, "Success")
            if supported:
                run_file.assert_called_once_with("Map001.json", estimate, None)
            else:
                run_file.assert_not_called()
            self.assertEqual([error[0] for error in errors], unsupported)
            self.assertEqual(
                progress,
                [(index, len(selected), filename)
                 for index, filename in enumerate(selected, 1)],
            )

    def test_wolf_scan_failure_fails_preflight_before_translation(self):
        import modules.wolfdawn as wolfdawn

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "files").mkdir()
            (root / "files" / "broken.json").write_text("{bad", encoding="utf-8")
            worker = TranslationWorker(
                root,
                ["Wolf RPG (WolfDawn)", ["json"], None],
                selected_files=["broken.json"],
            )
            with (
                patch.object(wolfdawn, "refreshRuntimeConfig") as refresh,
                patch.object(wolfdawn, "pendingSpeakerNames") as pending,
                patch.object(wolfdawn, "translateSpeakerNames") as translate,
            ):
                self.assertFalse(worker._prepare_wolf_speakers(["broken.json"]))

            pending.assert_not_called()
            translate.assert_not_called()
            refresh.assert_called_once_with()


    def test_automatic_speaker_preflight_cases(self):
        cases = (
            ("RPG Maker workflow already collected", "RPG Maker MV/MZ", {}, False),
            ("Plugin files are not RPG Maker event JSON", "RPG Maker Plugin", {"batch_mode": True}, False),
            ("RPG Maker fresh batch", "RPG Maker MV/MZ", {"batch_mode": True}, True),
            (
                "RPG Maker batch resume",
                "RPG Maker MV/MZ",
                {"batch_mode": True, "batch_resume_state": "fetched"},
                False,
            ),
            ("WolfDawn normal translation", "Wolf RPG (WolfDawn)", {}, True),
            (
                "WolfDawn fetched batch",
                "Wolf RPG (WolfDawn)",
                {"batch_mode": True, "batch_resume_state": "fetched"},
                False,
            ),
        )
        for label, module_name, kwargs, expected in cases:
            with self.subTest(label):
                self.assertEqual(
                    _should_prepare_speakers_automatically(module_name, **kwargs),
                    expected,
                )


if __name__ == "__main__":
    unittest.main()
