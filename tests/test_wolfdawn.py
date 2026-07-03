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
        orig_wrap = wd.WRAP
        wd.translateAI = translate
        wd.ESTIMATE = estimate
        wd.WRAP = False  # keep write-back byte-faithful; wrapping tested separately
        try:
            data_copy = copy.deepcopy(data)
            result = wd.parseDocument(data_copy, filename)
            return result, self.captured
        finally:
            wd.translateAI = orig_t
            wd.ESTIMATE = orig_estimate
            wd.WRAP = orig_wrap


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

    def __init__(self, config, wrap=False, width=0):
        self.config = config
        self.wrap = wrap
        self.width = width
        self.captured = []

    def run(self, data, filename="OP.mps.json"):
        def translate(text, history=None, history_ctx=None):
            self.captured.append(copy.deepcopy(text))
            return _mock_translate_speaker(text, history, history_ctx)

        orig = (wd.translateAI, wd.ESTIMATE, wd.SPEAKER_CONFIG, wd.WRAP, wd.WRAPWIDTH)
        wd.translateAI = translate
        wd.ESTIMATE = False
        wd.SPEAKER_CONFIG = self.config
        wd.WRAP = self.wrap
        wd.WRAPWIDTH = self.width
        try:
            result = wd.parseDocument(copy.deepcopy(data), filename)
            return result, self.captured
        finally:
            (wd.translateAI, wd.ESTIMATE, wd.SPEAKER_CONFIG, wd.WRAP, wd.WRAPWIDTH) = orig


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


class TestWrapping(unittest.TestCase):
    """dazedwrap-style re-wrapping, with the speaker name kept on its own line."""

    def setUp(self):
        self._orig = (wd.WRAP, wd.WRAPWIDTH)

    def tearDown(self):
        wd.WRAP, wd.WRAPWIDTH = self._orig

    def _set(self, enabled, width):
        wd.WRAP, wd.WRAPWIDTH = enabled, width

    def test_wrap_body_respects_width_and_keeps_words(self):
        self._set(True, 10)
        out = wd._wrap_body("alpha beta gamma delta")
        self.assertGreater(out.count("\n"), 0)  # actually wrapped
        for line in out.split("\n"):
            self.assertLessEqual(len(line), 10)
        self.assertEqual(out.replace("\n", " "), "alpha beta gamma delta")

    def test_wrap_disabled_is_noop(self):
        self._set(False, 10)
        self.assertEqual(wd._wrap_body("alpha beta gamma delta"), "alpha beta gamma delta")

    def test_zero_width_is_noop(self):
        self._set(True, 0)
        self.assertEqual(wd._wrap_body("alpha beta gamma delta"), "alpha beta gamma delta")

    def test_wrap_plain_preserves_nameplate_line(self):
        self._set(True, 12)
        out = wd._wrap_plain("Name\nalpha beta gamma delta epsilon", is_firstline=True)
        self.assertEqual(out.split("\n", 1)[0], "Name")  # name never merged into body
        for line in out.split("\n")[1:]:
            self.assertLessEqual(len(line), 12)

    def test_wrap_plain_preserves_window_prefix(self):
        self._set(True, 12)
        out = wd._wrap_plain("@1\nName\nalpha beta gamma delta", is_firstline=True)
        self.assertTrue(out.startswith("@1\nName\n"))

    def test_speaker_body_wrapped_but_name_kept(self):
        # Integration: even at a tiny width the (translated) name stays on line 1.
        cfg = {"literal_line1": True, "literal_line1_lowconf": True}
        (data, _t, err), _c = _SpeakerHarness(cfg, wrap=True, width=6).run(SPEAKER_MAP_DOC)
        self.assertIsNone(err)
        line0 = data["scenes"][0]["lines"][0]["text"]
        self.assertEqual(line0.split("\n", 1)[0], "EN_市民")


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
