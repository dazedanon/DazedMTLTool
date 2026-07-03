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

    def run(self, data, filename="doc.json", estimate=False):
        def translate(text, history, history_ctx=None):
            self.captured.append(copy.deepcopy(text))
            return _mock_translate(text, history, history_ctx)

        orig_t = wd.translateAI
        orig_estimate = wd.ESTIMATE
        wd.translateAI = translate
        wd.ESTIMATE = estimate
        try:
            data_copy = copy.deepcopy(data)
            result = wd.parseDocument(data_copy, filename)
            return result, self.captured
        finally:
            wd.translateAI = orig_t
            wd.ESTIMATE = orig_estimate


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
    "count": 1,
    "names": [{"source": "剣", "text": "剣", "occurrences": 2, "note": "Item"}],
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
        self.assertEqual(len(wd.collectEntries(MAP_DOC)), 2)
        self.assertEqual(len(wd.collectEntries(DB_DOC)), 1)
        self.assertEqual(len(wd.collectEntries(GAMEDAT_DOC)), 1)
        self.assertEqual(len(wd.collectEntries(NAMES_DOC)), 1)
        self.assertEqual(len(wd.collectEntries(TXTDIR_DOC)), 1)


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

    def test_names_translates(self):
        (data, _t, err), _c = _WolfTranslateHarness().run(NAMES_DOC, "names.json")
        self.assertIsNone(err)
        self.assertEqual(data["names"][0]["text"], "EN_剣")
        self.assertEqual(data["names"][0]["source"], "剣")

    def test_txtdir_translates(self):
        (data, _t, err), _c = _WolfTranslateHarness().run(TXTDIR_DOC, "Evtext.json")
        self.assertIsNone(err)
        self.assertEqual(data["files"][0]["lines"][0]["text"], "EN_せりふ")

    def test_estimate_mode_does_not_write(self):
        (data, _t, err), _c = _WolfTranslateHarness().run(MAP_DOC, "Map001.mps.json", estimate=True)
        self.assertIsNone(err)
        # In estimate mode text stays equal to source.
        self.assertEqual(data["scenes"][0]["lines"][0]["text"], "こんにちは")


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
