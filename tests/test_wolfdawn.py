#!/usr/bin/env python3
"""Unit tests for the WolfDawn translation module (modules/wolfdawn.py).

Covers each WolfDawn document ``kind``: translatable (Japanese) leaves get their
``text`` filled in while ``source`` is preserved, and non-translatable leaves are
left untouched so WolfDawn injection treats them as no-ops.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env", override=True)

import modules.wolfdawn as wd  # noqa: E402


def _mock_translate(text, history, history_ctx=None):
    """Return an EN_ prefixed translation for each item, preserving list length."""
    if isinstance(text, list):
        return [[f"EN_{t}" for t in text], [1, 1]]
    return [f"EN_{text}", [1, 1]]


class _WolfTranslateHarness:
    """Run parseDocument with translateAI mocked and captured payloads recorded."""

    def __init__(self):
        self.captured = []
        self.vocab_writes = []
        self.vocab_remove_writes = []

    def run(self, data, filename="doc.json", estimate=False, ignore_tl_text=True):
        def translate(text, history, history_ctx=None):
            self.captured.append(copy.deepcopy(text))
            return _mock_translate(text, history, history_ctx)

        def capture_vocab(category, pairs, merge=False):
            self.vocab_writes.append((category, list(pairs), merge))

        orig_t = wd.translateAI
        orig_estimate = wd.ESTIMATE
        orig_ignore = wd.IGNORETLTEXT
        orig_update = wd.wolf_vocab.update_vocab_section
        orig_labels = wd.wolf_names.derive_db_labels
        orig_db_filter = wd.wolf_db.load_db_filter_config
        wd.translateAI = translate
        wd.ESTIMATE = estimate
        wd.IGNORETLTEXT = ignore_tl_text
        # Never touch the real glossary / DB files during tests.
        wd.wolf_vocab.update_vocab_section = capture_vocab
        wd.wolf_names.derive_db_labels = lambda _p: {}
        wd.wolf_db.load_db_filter_config = lambda: (frozenset(), frozenset())
        try:
            data_copy = copy.deepcopy(data)
            result = wd.parseDocument(data_copy, filename)
            return result, self.captured
        finally:
            wd.translateAI = orig_t
            wd.ESTIMATE = orig_estimate
            wd.IGNORETLTEXT = orig_ignore
            wd.wolf_vocab.update_vocab_section = orig_update
            wd.wolf_names.derive_db_labels = orig_labels
            wd.wolf_db.load_db_filter_config = orig_db_filter


MAP_DOC = {
    "file": "Map001.mps",
    "kind": "map",
    "scenes": [
        {
            "event": 1,
            "name": "ev",
            "lines": [
                {"cmd": 0, "str": 0, "speaker": "NPC", "speaker_src": "x", "source": "こんにちは", "text": "こんにちは"},
                {"cmd": 1, "str": 0, "speaker": "", "speaker_src": "", "source": "OK", "text": "OK"},
            ],
        }
    ],
}

DB_DOC = {
    "file": "DataBase.project",
    "kind": "db",
    "groups": [
        {"type": 0, "typeName": "Item", "lines": [
            {"row": 0, "field": 2, "rowName": "ポーション", "fieldName": "説明", "source": "HPを回復", "text": "HPを回復"},
        ]}
    ],
}

GAMEDAT_DOC = {
    "file": "Game.dat",
    "kind": "gamedat",
    "lines": [{"key": "Title", "source": "ゲームタイトル", "text": "ゲームタイトル"}],
}

NAMES_DOC = {
    "kind": "names",
    "count": 3,
    "names": [
        {"source": "剣", "text": "剣", "occurrences": 2, "note": "武器", "safety": "safe"},
        {"source": "槍", "text": "槍", "occurrences": 1, "note": "武器", "safety": "refs"},
        {
            "source": "スイッチ状態",
            "text": "スイッチ状態",
            "occurrences": 1,
            "note": "通常変数名",
            "safety": "verify",
        },
    ],
}

LEGACY_NAMES_DOC = {
    "kind": "names",
    "count": 1,
    "names": [
        {"source": "剣", "text": "剣", "occurrences": 1, "note": "武器"},
    ],
}

TXTDIR_DOC = {
    "kind": "txt-dir",
    "files": [
        {"file": "a.txt", "kind": "txt", "encoding": "sjis", "eol": "crlf",
         "lines": [{"i": 0, "source": "せりふ", "text": "せりふ"}]},
    ],
}


class TestCollectEntries(unittest.TestCase):
    def test_counts_per_kind(self):
        # Live .env may still have a DB sheet filter from the last GUI run.
        orig_filter = wd.wolf_db.load_db_filter_config
        wd.wolf_db.load_db_filter_config = lambda: (frozenset(), frozenset())
        try:
            self.assertEqual(len(wd.collectEntries(MAP_DOC)), 2)
            self.assertEqual(len(wd.collectEntries(DB_DOC)), 1)
            self.assertEqual(len(wd.collectEntries(GAMEDAT_DOC)), 1)
            # All name leaves, including verify - safety filtering is in parseDocument.
            self.assertEqual(len(wd.collectEntries(NAMES_DOC)), 3)
            self.assertEqual(len(wd.collectEntries(TXTDIR_DOC)), 1)
        finally:
            wd.wolf_db.load_db_filter_config = orig_filter


class TestTranslationWriteback(unittest.TestCase):
    def test_map_translates_japanese_only(self):
        (data, _tokens, err), captured = _WolfTranslateHarness().run(MAP_DOC, "Map001.mps.json")
        self.assertIsNone(err)
        lines = data["scenes"][0]["lines"]
        # Japanese line got translated; source preserved.
        self.assertEqual(lines[0]["text"], "EN_こんにちは")
        self.assertEqual(lines[0]["source"], "こんにちは")
        # Non-Japanese line left as-is (text == source), never sent to the model.
        self.assertEqual(lines[1]["text"], "OK")
        self.assertEqual(captured, [["こんにちは"]])

    def test_db_translates(self):
        (data, _t, err), _c = _WolfTranslateHarness().run(DB_DOC, "DataBase.project.json")
        self.assertIsNone(err)
        line = data["groups"][0]["lines"][0]
        self.assertEqual(line["text"], "EN_HPを回復")
        self.assertEqual(line["source"], "HPを回復")

    def test_gamedat_translates(self):
        (data, _t, err), _c = _WolfTranslateHarness().run(GAMEDAT_DOC, "Game.dat.json")
        self.assertIsNone(err)
        self.assertEqual(data["lines"][0]["text"], "EN_ゲームタイトル")

    def test_names_translate_only_safe(self):
        (data, _t, err), captured = _WolfTranslateHarness().run(
            NAMES_DOC, "names.json"
        )
        self.assertIsNone(err)
        self.assertEqual(data["names"][0]["text"], "EN_剣")
        self.assertEqual(data["names"][1]["text"], "槍")
        self.assertEqual(data["names"][2]["text"], "スイッチ状態")
        self.assertEqual(captured, [["剣"]])

    def test_names_without_safety_badges_translate_nothing(self):
        (data, _t, err), captured = _WolfTranslateHarness().run(
            LEGACY_NAMES_DOC, "names.json"
        )
        self.assertIsNone(err)
        self.assertEqual(captured, [])
        self.assertEqual(data["names"][0]["text"], "剣")

    def test_names_harvest_to_vocab(self):
        harness = _WolfTranslateHarness()
        (_data, _t, err), _c = harness.run(NAMES_DOC, "names.json")
        self.assertIsNone(err)
        self.assertEqual(
            harness.vocab_writes,
            [
                ("Weapon · 武器", [("剣", "EN_剣")], False),
            ],
        )

    def test_names_harvest_skipped_in_estimate(self):
        harness = _WolfTranslateHarness()
        harness.run(NAMES_DOC, "names.json", estimate=True)
        self.assertEqual(harness.vocab_writes, [])

    def test_names_harvest_skips_profile_blurbs(self):
        doc = {
            "kind": "names",
            "names": [
                {"source": "ダガー", "text": "EN_ダガー", "note": "武器", "safety": "safe"},
                {
                    "source": "セルリアと申します。\nよろしくお願いいたします。",
                    "text": "EN_profile",
                    "note": "├■プロフィール",
                    "safety": "safe",
                },
            ],
        }
        harness = _WolfTranslateHarness()
        harness.vocab_remove_writes = []
        orig_remove = wd.wolf_vocab.remove_vocab_section

        def capture_remove(category):
            harness.vocab_remove_writes.append(category)

        wd.wolf_vocab.remove_vocab_section = capture_remove
        try:
            (_data, _t, err), _c = harness.run(doc, "names.json")
        finally:
            wd.wolf_vocab.remove_vocab_section = orig_remove
        self.assertIsNone(err)
        self.assertEqual(harness.vocab_writes, [("Weapon · 武器", [("ダガー", "EN_ダガー")], False)])
        self.assertEqual(harness.vocab_remove_writes, ["├■プロフィール"])

    def test_txtdir_translates(self):
        (data, _t, err), _c = _WolfTranslateHarness().run(TXTDIR_DOC, "Evtext.json")
        self.assertIsNone(err)
        self.assertEqual(data["files"][0]["lines"][0]["text"], "EN_せりふ")

    def test_estimate_mode_does_not_write(self):
        (data, _t, err), _c = _WolfTranslateHarness().run(MAP_DOC, "Map001.mps.json", estimate=True)
        self.assertIsNone(err)
        # In estimate mode text stays equal to source.
        self.assertEqual(data["scenes"][0]["lines"][0]["text"], "こんにちは")

    def test_collect_pass_does_not_mutate_or_write(self):
        """Batch collect must not overwrite translated/ with Japanese source."""
        orig_phase = os.environ.get("BATCH_PHASE")
        os.environ["BATCH_PHASE"] = "collect"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "files").mkdir()
                (root / "translated").mkdir()
                doc = copy.deepcopy(MAP_DOC)
                doc["scenes"][0]["lines"][0]["source"] = "あ" * 40
                doc["scenes"][0]["lines"][0]["text"] = "あ" * 40
                src_path = root / "files" / "Map001.mps.json"
                src_path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
                out_path = root / "translated" / "Map001.mps.json"
                out_path.write_text('{"kind":"map","marker":"keep-me"}', encoding="utf-8")

                old_cwd = os.getcwd()
                os.chdir(root)
                try:
                    # Echo sources (what collect's queue path effectively returns).
                    def echo(text, history, history_ctx=None):
                        return [text if isinstance(text, list) else text, [0, 0]]

                    orig_t = wd.translateAI
                    wd.translateAI = echo
                    try:
                        result = wd.handleWolfDawn("Map001.mps.json", estimate=False)
                    finally:
                        wd.translateAI = orig_t
                finally:
                    os.chdir(old_cwd)

                self.assertNotEqual(result, "Fail")
                # Prior translated/ content must be left alone.
                self.assertEqual(
                    out_path.read_text(encoding="utf-8"),
                    '{"kind":"map","marker":"keep-me"}',
                )
        finally:
            if orig_phase is None:
                os.environ.pop("BATCH_PHASE", None)
            else:
                os.environ["BATCH_PHASE"] = orig_phase

    def test_layout_restore_runs_after_write(self):
        """After writing translated/, wolf layout-restore restores pad skeletons."""
        pad = "                                  \n"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "files").mkdir()
            (root / "translated").mkdir()
            # Use map kind so DB sheet filters from .env cannot skip the line.
            doc = {
                "kind": "map",
                "file": "Map001.mps",
                "scenes": [
                    {
                        "event": 1,
                        "name": "ev",
                        "lines": [
                            {
                                "cmd": 0,
                                "str": 0,
                                "source": pad + "なし",
                                "text": pad + "なし",
                            }
                        ],
                    }
                ],
            }
            (root / "files" / "Map001.mps.json").write_text(
                json.dumps(doc, ensure_ascii=False), encoding="utf-8"
            )

            def translate(text, history, history_ctx=None):
                # Model drops the leading pad / newline - the bug layout-restore fixes.
                if isinstance(text, list):
                    return [["None" for _ in text], [1, 1]]
                return ["None", [1, 1]]

            old_cwd = os.getcwd()
            os.chdir(root)
            orig_t = wd.translateAI
            wd.translateAI = translate
            try:
                result = wd.handleWolfDawn("Map001.mps.json", estimate=False)
            finally:
                wd.translateAI = orig_t
                os.chdir(old_cwd)

            self.assertNotEqual(result, "Fail")
            out = json.loads((root / "translated" / "Map001.mps.json").read_text(encoding="utf-8"))
            self.assertEqual(out["scenes"][0]["lines"][0]["text"], pad + "None")

    def test_echoed_source_does_not_overwrite_text(self):
        """If the model/collect echoes JP source, leave text alone."""
        doc = {
            "kind": "map",
            "scenes": [
                {
                    "event": 1,
                    "name": "ev",
                    "lines": [
                        {
                            "cmd": 0,
                            "str": 0,
                            "source": "あいうえおかきくけこさしすせそ",
                            "text": "あいうえおかきくけこさしすせそ",
                        },
                    ],
                }
            ],
        }

        def echo(text, history, history_ctx=None):
            return [text if isinstance(text, list) else text, [1, 1]]

        orig_t = wd.translateAI
        wd.translateAI = echo
        try:
            data, _tok, err = wd.parseDocument(copy.deepcopy(doc), "echo.mps.json")
        finally:
            wd.translateAI = orig_t
        self.assertIsNone(err)
        self.assertEqual(
            data["scenes"][0]["lines"][0]["text"],
            "あいうえおかきくけこさしすせそ",
        )

    def test_skips_already_translated_text(self):
        doc = {
            "kind": "map",
            "scenes": [
                {
                    "event": 1,
                    "name": "ev",
                    "lines": [
                        {
                            "cmd": 0,
                            "str": 0,
                            "source": "こんにちは",
                            "text": "Hello",
                        },
                        {
                            "cmd": 1,
                            "str": 0,
                            "source": "さようなら",
                            "text": "さようなら",
                        },
                        {
                            "cmd": 2,
                            "str": 0,
                            "source": "まだ日本語",
                            "text": "Partial 日本語 left",
                        },
                    ],
                }
            ],
        }
        (data, _t, err), captured = _WolfTranslateHarness().run(doc, "partial.mps.json")
        self.assertIsNone(err)
        lines = data["scenes"][0]["lines"]
        self.assertEqual(lines[0]["text"], "Hello")
        self.assertEqual(lines[1]["text"], "EN_さようなら")
        # Still-Japanese body is not skipped; the model still gets ``source``.
        self.assertEqual(lines[2]["text"], "EN_まだ日本語")
        self.assertEqual(captured, [["さようなら", "まだ日本語"]])

    def test_skips_english_body_with_japanese_nameplate(self):
        doc = {
            "kind": "map",
            "scenes": [
                {
                    "event": 1,
                    "name": "ev",
                    "lines": [
                        {
                            "cmd": 0,
                            "str": 0,
                            "speaker": "司祭",
                            "speaker_src": "literal_line1_lowconf",
                            "source": "司祭\n皆さんお待たせしました……。",
                            "text": "司祭\nSorry to keep you all waiting......",
                        },
                        {
                            "cmd": 1,
                            "str": 0,
                            "speaker": "UI",
                            "speaker_src": "ui",
                            "source": "まだだ",
                            "text": "まだだ",
                        },
                    ],
                }
            ],
        }
        (data, _t, err), captured = _WolfTranslateHarness().run(doc, "nameplate.mps.json")
        self.assertIsNone(err)
        lines = data["scenes"][0]["lines"]
        self.assertEqual(lines[0]["text"], "司祭\nSorry to keep you all waiting......")
        self.assertEqual(lines[1]["text"], "EN_まだだ")
        self.assertEqual(captured, [["まだだ"]])

    def test_ignore_tl_text_false_retranslates(self):
        doc = {
            "kind": "map",
            "scenes": [
                {
                    "event": 1,
                    "name": "ev",
                    "lines": [
                        {"cmd": 0, "str": 0, "source": "こんにちは", "text": "Hello"},
                    ],
                }
            ],
        }
        (data, _t, err), captured = _WolfTranslateHarness().run(
            doc, "force.mps.json", ignore_tl_text=False
        )
        self.assertIsNone(err)
        self.assertEqual(data["scenes"][0]["lines"][0]["text"], "EN_こんにちは")
        self.assertEqual(captured, [["こんにちは"]])

    def test_names_already_translated_still_harvest(self):
        doc = {
            "kind": "names",
            "names": [
                {"source": "剣", "text": "Sword", "note": "武器", "safety": "safe"},
                {"source": "槍", "text": "Spear", "note": "武器", "safety": "refs"},
            ],
        }
        harness = _WolfTranslateHarness()
        (_data, _t, err), captured = harness.run(doc, "names.json")
        self.assertIsNone(err)
        self.assertEqual(captured, [])
        self.assertEqual(
            harness.vocab_writes,
            [("Weapon · 武器", [("剣", "Sword")], False)],
        )

    def test_db_foundation_labels_harvest_to_vocab(self):
        doc = {
            "file": "SysDatabase.project",
            "kind": "db",
            "groups": [
                {
                    "type": 0,
                    "typeName": "Map Setting · マップ設定",
                    "lines": [
                        {
                            "row": 0,
                            "field": 0,
                            "fieldName": "マップ名",
                            "source": "礼拝堂",
                            "text": "礼拝堂",
                        },
                        {
                            "row": 1,
                            "field": 0,
                            "fieldName": "マップ名",
                            "source": "大通り",
                            "text": "大通り",
                        },
                        {
                            "row": 0,
                            "field": 1,
                            "fieldName": "Description · 説明",
                            "source": "静かな礼拝堂",
                            "text": "静かな礼拝堂",
                        },
                    ],
                },
                {
                    "type": 1,
                    "typeName": "■イベント(セルリア)",
                    "lines": [
                        {
                            "row": 0,
                            "field": 0,
                            "fieldName": "現在の行動",
                            "source": "礼拝堂で黙とう中",
                            "text": "礼拝堂で黙とう中",
                        },
                    ],
                },
            ],
        }
        harness = _WolfTranslateHarness()
        (_data, _t, err), _c = harness.run(doc, "SysDatabase.project.json")
        self.assertIsNone(err)
        self.assertEqual(
            harness.vocab_writes,
            [
                (
                    "Map Setting · マップ設定",
                    [("礼拝堂", "EN_礼拝堂"), ("大通り", "EN_大通り")],
                    True,
                ),
            ],
        )

    def test_db_harvest_skipped_in_estimate(self):
        doc = {
            "file": "SysDatabase.project",
            "kind": "db",
            "groups": [
                {
                    "type": 0,
                    "typeName": "Map Setting · マップ設定",
                    "lines": [
                        {
                            "row": 0,
                            "field": 0,
                            "fieldName": "マップ名",
                            "source": "礼拝堂",
                            "text": "礼拝堂",
                        },
                    ],
                },
            ],
        }
        harness = _WolfTranslateHarness()
        harness.run(doc, "SysDatabase.project.json", estimate=True)
        self.assertEqual(harness.vocab_writes, [])


import re  # noqa: E402


def _mock_translate_speaker(text, history=None, history_ctx=None):
    """Emulate a model that keeps the [Speaker]: format when present."""
    def one(t):
        m = re.match(r"^\[([^\]]*)\]:\s*(.*)$", t, re.DOTALL)
        if m:
            return f"[EN_{m.group(1)}]: EN_{m.group(2)}"
        return f"EN_{t}"

    if isinstance(text, list):
        return [[one(t) for t in text], [1, 1]]
    return [one(text), [1, 1]]


SPEAKER_MAP_DOC = {
    "file": "OP.mps",
    "kind": "map",
    "scenes": [
        {
            "event": 0, "name": "ev",
            "lines": [
                {"cmd": 26, "str": 0, "speaker": "市民", "speaker_src": "literal_line1_lowconf",
                 "source": "市民\nおはよう\n元気？", "text": "市民\nおはよう\n元気？"},
                {"cmd": 27, "str": 0, "speaker": "セルリア", "speaker_src": "literal_line1",
                 "source": "セルリア\nふふふ", "text": "セルリア\nふふふ"},
                {"cmd": 28, "str": 0, "speaker": "Narration", "speaker_src": "narration",
                 "source": "むかしむかし", "text": "むかしむかし"},
            ],
        }
    ],
}


class _SpeakerHarness:
    """Run parseDocument with the speaker-aware mock and a chosen speaker config."""

    def __init__(self, config):
        self.config = config
        self.captured = []

    def run(self, data, filename="OP.mps.json"):
        def translate(text, history=None, history_ctx=None):
            self.captured.append(copy.deepcopy(text))
            return _mock_translate_speaker(text, history, history_ctx)

        orig = (wd.translateAI, wd.ESTIMATE, wd.SPEAKER_CONFIG)
        wd.translateAI = translate
        wd.ESTIMATE = False
        wd.SPEAKER_CONFIG = self.config
        try:
            result = wd.parseDocument(copy.deepcopy(data), filename)
            return result, self.captured
        finally:
            (wd.translateAI, wd.ESTIMATE, wd.SPEAKER_CONFIG) = orig


class TestSpeakerReshaping(unittest.TestCase):
    def test_firstline_speakers_reshaped_and_restored(self):
        cfg = {"literal_line1": True, "literal_line1_lowconf": True}
        (data, _t, err), captured = _SpeakerHarness(cfg).run(SPEAKER_MAP_DOC)
        self.assertIsNone(err)
        # Model saw the [Speaker]: transport for the two nameplate lines.
        self.assertEqual(
            captured[0],
            ["[市民]: おはよう\n元気？", "[セルリア]: ふふふ", "むかしむかし"],
        )
        lines = data["scenes"][0]["lines"]
        # Restored to WOLF's native Speaker\nbody layout.
        self.assertEqual(lines[0]["text"], "EN_市民\nEN_おはよう\n元気？")
        self.assertEqual(lines[1]["text"], "EN_セルリア\nEN_ふふふ")
        # Narration was translated as a plain blob.
        self.assertEqual(lines[2]["text"], "EN_むかしむかし")
        # Sources are preserved for the inject drift guard.
        self.assertEqual(lines[0]["source"], "市民\nおはよう\n元気？")
        # Original layout (newline count) preserved on the reshaped lines.
        self.assertEqual(lines[0]["source"].count("\n"), lines[0]["text"].count("\n"))

    def test_disabled_format_sends_raw_blob(self):
        cfg = {"literal_line1": True, "literal_line1_lowconf": False}
        (data, _t, err), captured = _SpeakerHarness(cfg).run(SPEAKER_MAP_DOC)
        self.assertIsNone(err)
        # Low-confidence line is sent as the raw source (no reshaping).
        self.assertIn("市民\nおはよう\n元気？", captured[0])
        self.assertIn("[セルリア]: ふふふ", captured[0])
        lines = data["scenes"][0]["lines"]
        self.assertEqual(lines[0]["text"], "EN_市民\nおはよう\n元気？")


class TestOpenFiles(unittest.TestCase):
    def test_rejects_unknown_kind(self):
        with tempfile.TemporaryDirectory() as td:
            files_dir = Path(td) / "files"
            files_dir.mkdir()
            bad = files_dir / "bad.json"
            bad.write_text(json.dumps({"kind": "nope"}), encoding="utf-8")
            cwd = os.getcwd()
            os.chdir(td)
            try:
                with self.assertRaises(NameError):
                    wd.openFiles("bad.json")
            finally:
                os.chdir(cwd)


if __name__ == "__main__":
    unittest.main(verbosity=2)
