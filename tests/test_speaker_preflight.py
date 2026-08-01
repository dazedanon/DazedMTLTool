#!/usr/bin/env python3
"""GUI-worker regression tests for deferred grouped speaker translation."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QMessageBox

from gui.translation_tab import (
    TranslationTab,
    TranslationWorker,
    _configured_game_root,
    _should_prepare_speakers_automatically,
)
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

    def test_confirmation_shows_estimate_before_approval(self):
        responses = []
        dummy = SimpleNamespace(
            translation_worker=SimpleNamespace(
                set_speaker_translation_response=responses.append
            )
        )
        payload = {
            "speakers": ["騎士", "秘書官"],
            "model": "test-model",
            "request_count": 1,
            "input_tokens": 1234,
            "output_tokens": 56,
            "estimated_cost": 0.012345,
            "cold_cache": False,
        }
        with patch.object(
            QMessageBox, "question", return_value=QMessageBox.Yes
        ) as question:
            TranslationTab._on_speaker_confirmation(dummy, payload)

        message = question.call_args.args[2]
        self.assertIn("Model: test-model", message)
        self.assertIn("Grouped requests: 1", message)
        self.assertIn("1,234 input / 56 output", message)
        self.assertIn("$0.012345", message)
        self.assertIn("No speaker translation requests have been sent yet", message)
        self.assertEqual(responses, [True])

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
                patch.object(wolfdawn, "pendingSpeakerNames") as pending,
                patch.object(wolfdawn, "translateSpeakerNames") as translate,
            ):
                self.assertFalse(worker._prepare_wolf_speakers(["broken.json"]))

            pending.assert_not_called()
            translate.assert_not_called()

    def test_game_root_uses_workflow_settings_key(self):
        class Settings:
            def value(self, key, default=""):
                return {
                    "workflow/last_game_folder": "/current/game",
                    "last_game_folder": "/legacy/game",
                }.get(key, default)

        self.assertEqual(_configured_game_root(Settings()), "/current/game")

    def test_rpgmaker_translation_does_not_repeat_workflow_speaker_collection(self):
        self.assertFalse(
            _should_prepare_speakers_automatically("RPG Maker MV/MZ")
        )

    def test_wolfdawn_keeps_automatic_speaker_preflight(self):
        self.assertTrue(
            _should_prepare_speakers_automatically("Wolf RPG (WolfDawn)")
        )
        self.assertFalse(
            _should_prepare_speakers_automatically(
                "Wolf RPG (WolfDawn)",
                batch_mode=True,
                batch_resume_state="fetched",
            )
        )


if __name__ == "__main__":
    unittest.main()
