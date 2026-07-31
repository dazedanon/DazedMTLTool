#!/usr/bin/env python3
"""GUI-worker regression tests for deferred grouped speaker translation."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui.translation_tab import TranslationWorker
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

            def approve(names):
                events.append(("approve", list(names)))
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
            ):
                self.assertTrue(worker._prepare_mvmz_speakers(worker.selected_files))

            self.assertEqual(
                events,
                [
                    ("scan", "Map001.json", False),
                    ("scan", "Map002.json", False),
                    ("pending",),
                    ("approve", ["騎士", "秘書官"]),
                    ("translate",),
                ],
            )

    def test_cancel_sends_no_speaker_translation(self):
        with tempfile.TemporaryDirectory() as raw:
            worker = self._worker(Path(raw))
            worker.speaker_confirmation_signal.connect(
                lambda _names: worker.set_speaker_translation_response(False)
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
            ):
                self.assertFalse(worker._prepare_mvmz_speakers(worker.selected_files))
            finalize.assert_not_called()


if __name__ == "__main__":
    unittest.main()
