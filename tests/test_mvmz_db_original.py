#!/usr/bin/env python3
"""Integration tests for _original source preservation in database parsers."""

from __future__ import annotations

import copy
import json
import os
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import modules.rpgmakermvmz as mvmz  # noqa: E402

LANGREGEX = mvmz.LANGREGEX
FIXTURES = ROOT / "tests" / "fixtures"
MANIFEST = json.loads((FIXTURES / "db_original_manifest.json").read_text(encoding="utf-8"))


def _mock_translate(text, history, batch=False):
    def tr(s):
        if not isinstance(s, str):
            return s
        return "EN_TRANSLATED"

    if isinstance(text, list):
        return [[tr(t) for t in text], [0, 0]]
    return [tr(text), [0, 0]]


def _has_japanese(s: str) -> bool:
    return bool(re.search(LANGREGEX, s or ""))


def _run_search_names(data, context, filename, *, preserve_original=True):
    captured = []

    def translate(text, history, batch=False):
        captured.append(copy.deepcopy(text))
        return _mock_translate(text, history, batch)

    orig_t = mvmz.translateAI
    orig_vocab = mvmz.update_vocab_section
    orig_preserve = mvmz.PRESERVEORIGINAL
    mvmz.translateAI = translate
    mvmz.update_vocab_section = lambda *args, **kwargs: None
    mvmz.PRESERVEORIGINAL = preserve_original
    try:
        data_copy = copy.deepcopy(data)
        mvmz.searchNames(data_copy, None, context, filename)
        return data_copy, captured
    finally:
        mvmz.translateAI = orig_t
        mvmz.update_vocab_section = orig_vocab
        mvmz.PRESERVEORIGINAL = orig_preserve


def _run_search_ss(state):
    captured = []

    def translate(text, history, batch=False):
        captured.append(copy.deepcopy(text))
        return _mock_translate(text, history, batch)

    orig_t = mvmz.translateAI
    orig_preserve = mvmz.PRESERVEORIGINAL
    mvmz.translateAI = translate
    mvmz.PRESERVEORIGINAL = True
    try:
        state_copy = copy.deepcopy(state)
        mvmz.searchSS(state_copy, None)
        return state_copy, captured
    finally:
        mvmz.translateAI = orig_t
        mvmz.PRESERVEORIGINAL = orig_preserve


def _run_search_system(data):
    captured = []

    def translate(text, history, batch=False):
        captured.append(copy.deepcopy(text))
        return _mock_translate(text, history, batch)

    orig_t = mvmz.translateAI
    orig_preserve = mvmz.PRESERVEORIGINAL
    mvmz.translateAI = translate
    mvmz.PRESERVEORIGINAL = True
    try:
        data_copy = copy.deepcopy(data)
        mvmz.searchSystem(data_copy, None)
        return data_copy, captured
    finally:
        mvmz.translateAI = orig_t
        mvmz.PRESERVEORIGINAL = orig_preserve


def _assert_batches_japanese(captured):
    for payload in captured:
        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            if not isinstance(item, str) or item == "EN_TRANSLATED":
                continue
            if item.startswith("Taro"):
                item = item[4:]
            self_fail = not _has_japanese(item)
            if self_fail:
                raise AssertionError(f"Re-run sent non-Japanese to translateAI: {item!r}")


class TestActorsOriginal(unittest.TestCase):
    def test_first_pass_writes_original(self):
        data = json.loads((FIXTURES / "Actors_original_fixture.json").read_text(encoding="utf-8"))
        result, _ = _run_search_names(data, "Actors", "Actors.json")
        entry = result[MANIFEST["actors"]["entry_index"]]
        expected = MANIFEST["actors"]["expected_original"]
        self.assertEqual(entry.get("_original"), expected)
        self.assertNotEqual(entry["name"], expected["name"])
        self.assertNotEqual(entry["nickname"], expected["nickname"])
        self.assertNotEqual(entry["profile"], expected["profile"])

    def test_rerun_preserves_original(self):
        data = json.loads((FIXTURES / "Actors_original_fixture.json").read_text(encoding="utf-8"))
        result1, _ = _run_search_names(data, "Actors", "Actors.json")
        orig_snapshot = copy.deepcopy(result1[1]["_original"])
        result2, captured2 = _run_search_names(result1, "Actors", "Actors.json")
        self.assertEqual(result2[1]["_original"], orig_snapshot)
        _assert_batches_japanese(captured2)


class TestItemsOriginal(unittest.TestCase):
    def test_first_pass_writes_original(self):
        data = json.loads((FIXTURES / "Items_original_fixture.json").read_text(encoding="utf-8"))
        result, _ = _run_search_names(data, "Items", "Items.json")
        entry = result[MANIFEST["items"]["entry_index"]]
        expected = MANIFEST["items"]["expected_original"]
        self.assertEqual(entry.get("_original"), expected)
        self.assertNotEqual(entry["name"], expected["name"])
        self.assertNotEqual(entry["description"], expected["description"])

    def test_rerun_preserves_original(self):
        data = json.loads((FIXTURES / "Items_original_fixture.json").read_text(encoding="utf-8"))
        result1, _ = _run_search_names(data, "Items", "Items.json")
        orig_snapshot = copy.deepcopy(result1[1]["_original"])
        result2, captured2 = _run_search_names(result1, "Items", "Items.json")
        self.assertEqual(result2[1]["_original"], orig_snapshot)
        _assert_batches_japanese(captured2)


class TestSkillsOriginal(unittest.TestCase):
    def test_first_pass_writes_original(self):
        data = json.loads((FIXTURES / "Skills_original_fixture.json").read_text(encoding="utf-8"))
        result, _ = _run_search_names(data, "Skills", "Skills.json")
        entry = result[MANIFEST["skills"]["entry_index"]]
        expected = MANIFEST["skills"]["expected_original"]
        self.assertEqual(entry.get("_original"), expected)
        for field, jp in expected.items():
            self.assertNotEqual(entry[field], jp)

    def test_rerun_preserves_original(self):
        data = json.loads((FIXTURES / "Skills_original_fixture.json").read_text(encoding="utf-8"))
        result1, _ = _run_search_names(data, "Skills", "Skills.json")
        orig_snapshot = copy.deepcopy(result1[1]["_original"])
        result2, captured2 = _run_search_names(result1, "Skills", "Items.json")
        self.assertEqual(result2[1]["_original"], orig_snapshot)
        _assert_batches_japanese(captured2)


class TestStatesOriginal(unittest.TestCase):
    def test_first_pass_writes_original(self):
        data = json.loads((FIXTURES / "States_original_fixture.json").read_text(encoding="utf-8"))
        state = data[MANIFEST["states"]["entry_index"]]
        result, _ = _run_search_ss(state)
        expected = MANIFEST["states"]["expected_original"]
        self.assertEqual(result.get("_original"), expected)
        for field, jp in expected.items():
            self.assertNotEqual(result[field], jp)

    def test_rerun_preserves_original(self):
        data = json.loads((FIXTURES / "States_original_fixture.json").read_text(encoding="utf-8"))
        state = data[MANIFEST["states"]["entry_index"]]
        result1, _ = _run_search_ss(state)
        orig_snapshot = copy.deepcopy(result1["_original"])
        result2, captured2 = _run_search_ss(result1)
        self.assertEqual(result2["_original"], orig_snapshot)
        _assert_batches_japanese(captured2)


class TestSystemOriginal(unittest.TestCase):
    def test_first_pass_writes_original(self):
        data = json.loads((FIXTURES / "System_original_fixture.json").read_text(encoding="utf-8"))
        result, _ = _run_search_system(data)
        expected = MANIFEST["system"]["expected_original"]
        self.assertEqual(result.get("_original"), expected)
        self.assertNotEqual(result["gameTitle"], expected["gameTitle"])
        self.assertNotEqual(result["terms"]["basic"][1], expected["terms"]["basic"]["1"])
        self.assertNotEqual(result["armorTypes"][1], expected["armorTypes"]["1"])

    def test_rerun_preserves_original(self):
        data = json.loads((FIXTURES / "System_original_fixture.json").read_text(encoding="utf-8"))
        result1, _ = _run_search_system(data)
        orig_snapshot = copy.deepcopy(result1["_original"])
        result2, captured2 = _run_search_system(result1)
        self.assertEqual(result2["_original"], orig_snapshot)
        _assert_batches_japanese(captured2)


class TestPreserveOriginalDisabled(unittest.TestCase):
    def test_db_preserve_disabled_skips_original(self):
        data = json.loads((FIXTURES / "Items_original_fixture.json").read_text(encoding="utf-8"))
        result, _ = _run_search_names(data, "Items", "Items.json", preserve_original=False)
        entry = result[MANIFEST["items"]["entry_index"]]
        self.assertNotIn("_original", entry)


if __name__ == "__main__":
    unittest.main(verbosity=2)
