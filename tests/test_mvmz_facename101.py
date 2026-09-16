#!/usr/bin/env python3
"""Regression tests for code-101 face filename speaker mappings."""

import copy
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import modules.rpgmakermvmz as mvmz
from util import translation as tr
from util.rpgmaker_autonamepopup import parse_name_keys


class FaceName101Tests(unittest.TestCase):
    def test_recurring_character_faces_resolve_to_speakers(self):
        expected = {
            "__HA": "Count Bampton",
            "___Nimurda": "Nimurda",
            "___Ren": "Ren",
            "___prince": "Prince Elliot",
            "___princess1": "Lilifa",
            "___princess2": "Lilifa",
            "___princess2_2": "Lilifa",
            "___princess3": "Lilifa",
            "___princess4": "Lilifa",
            "___princess5": "Lilifa",
            "__opHA": "Count Bampton",
            "__opRen": "Ren",
            "__opλ": "Lambda",
            "__λ": "Lambda",
            "___princess2_2_smile": "Lilifa",
            "_guard_M10_talk": "Guard 2",
            "_guard_M1_talk": "Guard 1",
        }

        for face_name, speaker in expected.items():
            with self.subTest(face_name=face_name):
                command = {"parameters": [face_name, 0, 0, 2, ""]}
                self.assertEqual(mvmz._facename101_speaker(command), speaker)

        command = {"parameters": ["___prince", 1, 0, 2, "リリファ"]}
        self.assertIsNone(mvmz._facename101_speaker(command))


class AutoNamePopupTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        original_cwd = Path.cwd()
        self.addCleanup(os.chdir, original_cwd)
        os.chdir(self.root)
        self.game = self.root / "game"
        (self.game / "js").mkdir(parents=True)
        Path("files").mkdir()
        Path("translated").mkdir()
        actors = [None,
                  {"id": 1, "name": "Riri", "_original": {"name": "リリ"}},
                  {"id": 3, "name": "先生"}]
        Path("files/Actors.json").write_text(json.dumps(actors), encoding="utf-8")
        Path("translated/Actors.json").write_text(
            json.dumps([None, {"id": 1, "name": "Wrong Name"}]), encoding="utf-8"
        )
        self.plugin = {"name": "AutoNamePopup", "status": True, "parameters": {
            "characterFacialExpressions": "1", "actorFacialExpressions": "2",
            "nameKeys": json.dumps([
                json.dumps({"faceName": "Actor1", "faceIndex": "0", "name": r"\N[1]", "facialExpressions": "-1"}),
                json.dumps({"faceName": "Actor1", "faceIndex": "2", "name": r"\N[3]", "facialExpressions": "0"}),
            ]),
        }}
        self.registry = self.game / "js/plugins.js"
        self.registry.write_text(self._registry(self.plugin), encoding="utf-8")
        patches = (
            mock.patch.dict(os.environ, {"DAZED_GAME_ROOT": str(self.game), "BATCH_PHASE": ""}),
            mock.patch.multiple(mvmz, AUTONAMEPOPUP101=True, FACENAME101=True,
                                CODE101=False, CODE320=False, CODE401=True,
                                FIRSTLINESPEAKERS=False, INLINE401SPEAKERS=False,
                                PRESERVEORIGINAL=True, IGNORETLTEXT=False,
                                FIXTEXTWRAP=False, SPEAKER_PARSE_MODE=False,
                                PREFLIGHT_COUNT_MODE=False, ESTIMATE=False,
                                VOCAB="# Game Characters\nリリ (Riri)\n先生 (Sensei)\n",
                                NAMESLIST=[], SPEAKER_COLLECTED=[], MISMATCH=[], PBAR=None),
        )
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        mvmz.resetSpeakerState()
        self.addCleanup(mvmz.resetSpeakerState)

    @staticmethod
    def _registry(*plugins):
        return "var $plugins = " + json.dumps(list(plugins)) + ";"

    def test_enabled_nested_mapping_uses_exact_indexes_and_plugin_precedence(self):
        expected = {("Actor1", 0): r"\N[1]", ("Actor1", 1): r"\N[1]", ("Actor1", 2): r"\N[3]"}
        self.assertEqual(parse_name_keys(self.registry.read_text()), expected)
        disabled = dict(self.plugin, status=False)
        self.assertEqual(parse_name_keys(self._registry(disabled)), {})
        override = copy.deepcopy(self.plugin)
        override["parameters"]["nameKeys"] = json.dumps([
            json.dumps({"faceName": "Actor1", "faceIndex": "1", "name": "別名"})
        ])
        combined = parse_name_keys(self._registry(self.plugin, override, disabled))
        self.assertEqual(combined[("Actor1", 1)], "別名")
        for params in (["Actor1", 3, 0, 2, ""], ["Actor1_extra", 0, 0, 2, ""],
                       ["Actor1", 0, 0, 2, r"\N[3]"]):
            with self.subTest(params=params):
                self.assertIsNone(mvmz._autonamepopup101_speaker({"parameters": params}))
        self.assertEqual(mvmz._autonamepopup101_speaker({"parameters": ["Actor1", 0, 0, 2, ""]}), "リリ")
        self.assertEqual(mvmz._autonamepopup_actor_ids(), {1, 3})
        # Switching active projects must not reuse a previous plugin declaration.
        with mock.patch.dict(os.environ, {"DAZED_GAME_ROOT": str(self.root / "other")}):
            self.assertEqual(mvmz._get_autonamepopup_map(), {})

    def test_shared_faces_and_linked_defaults_preserve_event_identity(self):
        commands = []
        for index in (0, 2, 3):
            commands.extend([
                {"code": 101, "indent": 0, "parameters": ["Actor1", index, 0, 2, ""]},
                {"code": 401, "indent": 0, "parameters": ["こんにちは。"]},
            ])
        commands.extend([
            {"code": 320, "indent": 0, "parameters": [1, "リリ"]},
            {"code": 320, "indent": 0, "parameters": [3, "仮名"], "_original": "先生"},
            {"code": 320, "indent": 0, "parameters": [9, "無関係"]},
            {"code": 303, "indent": 0, "parameters": [1, 8]},
            {"code": 0, "indent": 0, "parameters": []},
        ])
        before = copy.deepcopy(commands)
        registry_before = self.registry.read_bytes()
        captured = []

        def translate(text, *_args):
            captured.extend(text if isinstance(text, list) else [text])
            if isinstance(text, list):
                return [[line.replace("こんにちは。", "Hello.") for line in text], [0, 0]]
            return [text.replace("こんにちは。", "Hello."), [0, 0]]

        with (
            mock.patch.object(mvmz, "translateAI", side_effect=translate),
            mock.patch.object(mvmz, "_facename101_speaker") as generic,
        ):
            mvmz.searchCodes({"list": commands}, None, [], "Map001.json")
        generic.assert_not_called()
        self.assertEqual(captured, ["[Riri]: こんにちは。", "[Sensei]: こんにちは。", "こんにちは。"])
        self.assertEqual([cmd for cmd in commands if cmd["code"] == 101],
                         [cmd for cmd in before if cmd["code"] == 101])
        names = [cmd for cmd in commands if cmd["code"] == 320]
        self.assertEqual(names[0]["parameters"], [1, "Riri"])
        self.assertEqual(names[0]["_original"], "リリ")
        self.assertEqual(names[1]["parameters"], [3, "Sensei"])
        self.assertEqual(names[1]["_original"], "先生")
        self.assertEqual(names[2], before[-3])
        self.assertEqual(next(cmd for cmd in commands if cmd["code"] == 303), before[-2])
        self.assertEqual(self.registry.read_bytes(), registry_before)

    def test_runtime_controls_survive_batch_roundtrip_and_bad_markers_keep_source(self):
        source = r"名前は――\N[3]先生。 \n[003]と\V[007]。\F1[portrait]\F2[other]\AA[F]"
        config = tr.TranslationConfig(
            model="gpt-4", language="English", prompt="Translate Japanese to English.",
            vocab="", batchSize=30, useSfxReference=False,
            logFilePath=str(self.root / "translation.log"),
            mismatchLogPath=str(self.root / "mismatch.log"),
        )
        with (
            mock.patch.object(mvmz, "TRANSLATION_CONFIG", config),
            mock.patch.object(mvmz, "getPricingConfig", return_value={"batchSize": 30}),
            mock.patch.multiple(tr,
                                BATCH_QUEUE_FILE=self.root / "queue.json",
                                BATCH_STATE_FILE=self.root / "state.json",
                                BATCH_RESULTS_FILE=self.root / "results.json",
                                BATCH_LOCK_FILE=self.root / "batch.lock",
                                _batch_queue_pending={}, _batch_results=None, _batch_phase=None),
            mock.patch.object(tr, "getBatchProvider", return_value="openai"),
            mock.patch.object(tr, "get_cached_translation", return_value=None),
            mock.patch.object(tr, "cache_translation"),
            mock.patch.object(tr, "translateText") as live_provider,
            mock.patch.dict(os.environ, {"BATCH_PHASE": "collect", "API_PROVIDER": "openai"}),
            mock.patch("builtins.print"),
        ):
            result = mvmz.translateAI([source], [])
            self.assertEqual(result[0], [source])
            tr.flush_batch_queue()
            queue = tr._read_batch_queue(strict=True)
            self.assertEqual(len(queue), 1)
            key, entry = next(iter(queue.items()))
            payload = json.loads(entry["payload"])
            protected, replacements = tr.protect_script_codes(source)
            self.assertEqual(payload["Line1"], protected)
            translated = protected.replace("名前は――", "Her name is―").replace("先生。", "-sensei.").replace("と", " and ").replace("。", ".")
            os.environ["BATCH_PHASE"] = "consume"
            # Exercise the real durable lookup with a simulated provider JSON result.
            for damaged_marker in (None, *replacements):
                with self.subTest(damaged_marker=damaged_marker):
                    output = translated
                    if damaged_marker:
                        output = output.replace(damaged_marker, "__PROTECTED_BROKEN__")
                    tr._write_batch_file(tr.BATCH_RESULTS_FILE, {
                        key: {"text": json.dumps({"Line1": output}), "input_tokens": 10, "output_tokens": 10}
                    })
                    tr._batch_results = None
                    result = mvmz.translateAI([source], [])
                    if damaged_marker:
                        self.assertEqual(result[0], [source])
                        self.assertTrue(mvmz.THREAD_CTX.last_translation_had_mismatch)
                    else:
                        restored = tr.restore_script_codes(translated, replacements)
                        self.assertEqual(result[0], [restored])
                        self.assertTrue(mvmz.saveProgress(
                            {"list": [{"code": 401, "parameters": result[0]}]}, "Map001.json", force=True
                        ))
                        saved = json.loads(Path("translated/Map001.json").read_text())
                        self.assertEqual(saved["list"][0]["parameters"], [restored])
                        self.assertEqual(tr.extract_control_codes(restored), tr.extract_control_codes(source))
            live_provider.assert_not_called()
        mvmz.THREAD_CTX.last_translation_had_mismatch = False


if __name__ == "__main__":
    unittest.main()
