#!/usr/bin/env python3
"""Integration tests for _original source preservation in rpgmakermvmz searchCodes."""

from __future__ import annotations

import copy
import json
import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import modules.rpgmakermvmz as mvmz  # noqa: E402

LANGREGEX = mvmz.LANGREGEX


def _mock_translate(text, history, batch=False):
    def tr(s):
        if not isinstance(s, str):
            return s
        m = re.match(r"^(\[[^\]]+\]:\s?)", s)
        if m:
            return m.group(1) + "EN_TRANSLATED"
        return "EN_TRANSLATED"

    if isinstance(text, list):
        return [[tr(t) for t in text], [0, 0]]
    return [tr(text), [0, 0]]


def _mock_speaker(name):
    return [f"Speaker_{name}", [0, 0]]


FIXTURE_MAP = ROOT / "tests" / "fixtures" / "Map_original_fixture.json"
FIXTURE_MANIFEST = ROOT / "tests" / "fixtures" / "Map_original_fixture_manifest.json"
CASE_MARKER_RE = re.compile(r"# CASE:(\S+)")


def _load_fixture_page():
    data = json.loads(FIXTURE_MAP.read_text(encoding="utf-8-sig"))
    event = next(e for e in data["events"] if e and e.get("id") == 1)
    return {"list": copy.deepcopy(event["pages"][0]["list"])}


def _case_commands(page_list):
    """Map manifest case id -> command immediately following its 108 marker."""
    cases = {}
    pending = None
    for cmd in page_list:
        if not cmd:
            continue
        if cmd.get("code") == 108:
            m = CASE_MARKER_RE.search(str(cmd.get("parameters", [""])[0]))
            pending = m.group(1) if m else None
            continue
        if pending:
            cases[pending] = cmd
            pending = None
    return cases


def _load_fixture_manifest():
    return json.loads(FIXTURE_MANIFEST.read_text(encoding="utf-8"))


def _load_map_excerpt():
    """Hand-authored page mirroring a 101+401 dialogue block, a 102 choice, and
    synthetic 101/401/122 commands. Fully self-contained (no files/ dependency)."""
    # 101 message box (4 params, no speaker name) + 401 dialogue lines.
    real = [
        {"code": 101, "indent": 0, "parameters": ["", 0, 0, 2]},
        {"code": 401, "indent": 0, "parameters": ["これは本物のセリフです。"]},
        {"code": 401, "indent": 0, "parameters": ["二行目のテキストです。"]},
    ]

    # 102 choice command: parameters[0] is the list of Japanese choice strings.
    choice_cmd = {"code": 102, "indent": 0, "parameters": [["買う", "売る", "やめる"], -1, 0, 2, 0]}

    synthetic = [
        {"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, "\\C[2]アリス\\C[0]"]},
        {"code": 401, "indent": 0, "parameters": ["こんにちは、世界。"]},
        {
            "code": 122,
            "indent": 0,
            "parameters": [101, 101, 0, 0, "`変数テスト`"],
        },
    ]

    return {"list": real + [choice_cmd] + synthetic}


def _resolve_case_command(page_list, entry, marked_cases=None):
    """Find manifest case command by CASE marker or by code + expected _original."""
    marked_cases = marked_cases if marked_cases is not None else _case_commands(page_list)
    cid = entry["id"]
    cmd = marked_cases.get(cid)
    if cmd is not None and cmd.get("code") == entry.get("code"):
        return cmd
    exp = entry.get("expected_original")
    code = entry.get("code")
    if code is not None and exp is not None:
        for candidate in page_list:
            if candidate and candidate.get("code") == code and candidate.get("_original") == exp:
                return candidate
    return cmd


def _run_search_codes(
    page,
    *,
    preserve_original=True,
    speaker_fn=None,
    ignore_tl_text=False,
    translate_fn=None,
):
    """Full Pass 1 -> mock translate -> Pass 2 cycle."""
    captured = []

    def translate(text, history, batch=False):
        captured.append(copy.deepcopy(text))
        if translate_fn is not None:
            return translate_fn(text, history, batch)
        return _mock_translate(text, history, batch)

    def speaker(name):
        return speaker_fn(name) if speaker_fn is not None else _mock_speaker(name)

    orig_t = mvmz.translateAI
    orig_s = mvmz.getSpeaker
    orig_122 = mvmz.CODE122
    orig_408 = mvmz.CODE408
    orig_101 = mvmz.CODE101
    orig_401 = mvmz.CODE401
    orig_405 = mvmz.CODE405
    orig_102 = mvmz.CODE102
    orig_preserve = mvmz.PRESERVEORIGINAL
    orig_ignore = mvmz.IGNORETLTEXT
    missing_marker = object()
    orig_mismatch_marker = getattr(
        mvmz.THREAD_CTX,
        "last_translation_had_mismatch",
        missing_marker,
    )
    mvmz.translateAI = translate
    mvmz.getSpeaker = speaker
    mvmz.CODE122 = True
    mvmz.CODE408 = True
    mvmz.CODE101 = True
    mvmz.CODE401 = True
    mvmz.CODE405 = True
    mvmz.CODE102 = True
    mvmz.PRESERVEORIGINAL = preserve_original
    mvmz.IGNORETLTEXT = ignore_tl_text
    try:
        mvmz.THREAD_CTX.last_translation_had_mismatch = False
        page_copy = copy.deepcopy(page)
        mvmz.searchCodes(page_copy, None, [], "TestMap.json")
        return page_copy, captured
    finally:
        mvmz.translateAI = orig_t
        mvmz.getSpeaker = orig_s
        mvmz.CODE122 = orig_122
        mvmz.CODE408 = orig_408
        mvmz.CODE101 = orig_101
        mvmz.CODE401 = orig_401
        mvmz.CODE405 = orig_405
        mvmz.CODE102 = orig_102
        mvmz.PRESERVEORIGINAL = orig_preserve
        mvmz.IGNORETLTEXT = orig_ignore
        if orig_mismatch_marker is missing_marker:
            try:
                del mvmz.THREAD_CTX.last_translation_had_mismatch
            except AttributeError:
                pass
        else:
            mvmz.THREAD_CTX.last_translation_had_mismatch = orig_mismatch_marker


def _find_commands(page, code):
    return [cmd for cmd in page["list"] if cmd and cmd.get("code") == code]


def _has_japanese(s: str) -> bool:
    return bool(re.search(LANGREGEX, s or ""))


class TestMVMZSourceOriginal(unittest.TestCase):
    def test_code101_face_detection_supports_mv_and_mz_shapes(self):
        self.assertTrue(
            mvmz._101_has_face_graphic(
                {"parameters": ["Actor1", 0, 0, 2]}
            )
        )
        self.assertTrue(
            mvmz._101_has_face_graphic(
                {"parameters": ["Actor1", 0, 0, 2, "Alice"]}
            )
        )
        self.assertFalse(
            mvmz._101_has_face_graphic(
                {"parameters": ["", 0, 0, 2, "Alice"]}
            )
        )

    def test_code101_face_uses_configured_face_width_after_speaker_resolution(self):
        page = {
            "list": [
                {
                    "code": 101,
                    "indent": 0,
                    "parameters": ["___princess1", 0, 0, 2, ""],
                },
                {
                    "code": 401,
                    "indent": 0,
                    "parameters": ["これは顔付きの長い台詞です。"],
                },
            ]
        }
        widths = []

        def capture_wrap(text, width):
            widths.append(width)
            return text

        with (
            patch.object(mvmz, "WIDTH", 60),
            patch.object(mvmz, "FACEWIDTH", 50),
            patch.object(mvmz, "FACENAME101", True),
            patch.object(mvmz.dazedwrap, "wrapText", side_effect=capture_wrap),
        ):
            _run_search_codes(page)

        self.assertEqual(widths, [50])

    def test_code101_without_face_uses_full_dialogue_width(self):
        page = {
            "list": [
                {"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
                {
                    "code": 401,
                    "indent": 0,
                    "parameters": ["これは通常幅の台詞です。"],
                },
            ]
        }
        widths = []

        def capture_wrap(text, width):
            widths.append(width)
            return text

        with (
            patch.object(mvmz, "WIDTH", 60),
            patch.object(mvmz, "FACEWIDTH", 50),
            patch.object(mvmz.dazedwrap, "wrapText", side_effect=capture_wrap),
        ):
            _run_search_codes(page)

        self.assertEqual(widths, [60])

    def test_choice_condition_prefix_parser_handles_nested_calls(self):
        prefix, label = mvmz._split_choice_condition_prefix(
            "if($gameSwitches.value(1) && v[31]>=4)迷宮四階"
        )

        self.assertEqual(prefix, "if($gameSwitches.value(1) && v[31]>=4)")
        self.assertEqual(label, "迷宮四階")

    def test_choice_condition_prefix_parser_leaves_malformed_input_untouched(self):
        source = "if(v[31]>=4迷宮四階"
        self.assertEqual(mvmz._split_choice_condition_prefix(source), ("", source))

    def test_choice_condition_suffix_parser_handles_chained_nested_calls(self):
        source = "？？？ 必要な欠片：30 en(foo(v[88])>99) if(s[278]&!s[276])"

        label, suffix = mvmz._split_choice_condition_suffix(source)

        self.assertEqual(label, "？？？ 必要な欠片：30")
        self.assertEqual(suffix, " en(foo(v[88])>99) if(s[278]&!s[276])")

    def test_choice_condition_suffix_parser_leaves_malformed_input_untouched(self):
        source = "？？？ 必要な欠片：30 en(v[88]>99"
        self.assertEqual(mvmz._split_choice_condition_suffix(source), (source, ""))

    def test_choice_translation_restores_condition_prefix_byte_for_byte(self):
        source = "if(v[31]>=4)迷宮四階：図書館"
        page = {
            "list": [
                {"code": 102, "indent": 0, "parameters": [[source], -1, 0, 2, 0]},
            ]
        }

        def translate(text, _history, _batch=False):
            self.assertEqual(text, ["迷宮四階：図書館"])
            return [["labyrinth floor 4: library"], [0, 0]]

        translated, _ = _run_search_codes(page, translate_fn=translate)

        choice = _find_commands(translated, 102)[0]["parameters"][0][0]
        self.assertEqual(choice, "if(v[31]>=4)Labyrinth floor 4: library")

    def test_choice_translation_hides_and_restores_condition_suffix_byte_for_byte(self):
        source = "‣？？？ 必要な欠片：30 en(v[88]>99) if(s[278]&!s[276])"
        page = {
            "list": [
                {"code": 102, "indent": 0, "parameters": [[source], -1, 0, 2, 0]},
            ]
        }

        def translate(text, _history, _batch=False):
            self.assertEqual(text, ["‣？？？ 必要な欠片：30"])
            return [["‣??? fragments required: 30"], [0, 0]]

        translated, _ = _run_search_codes(page, translate_fn=translate)

        choice = _find_commands(translated, 102)[0]["parameters"][0][0]
        self.assertEqual(
            choice,
            "‣??? fragments required: 30 en(v[88]>99) if(s[278]&!s[276])",
        )

    def test_first_pass_writes_original(self):
        page, _ = _run_search_codes(_load_map_excerpt())

        cmds401 = _find_commands(page, 401)
        with_orig = [c for c in cmds401 if c.get("_original")]
        self.assertGreater(len(with_orig), 0, "401 dialogue should have _original")
        for c in with_orig:
            self.assertTrue(_has_japanese(c["_original"]))
            self.assertNotEqual(c["parameters"][0], c["_original"])

        c102 = _find_commands(page, 102)[0]
        self.assertIsInstance(c102.get("_original"), list)
        self.assertEqual(len(c102["_original"]), len(c102["parameters"][0]))
        for i, orig in enumerate(c102["_original"]):
            if orig:
                self.assertTrue(_has_japanese(orig), f"choice {i} _original should be Japanese")
                self.assertNotEqual(c102["parameters"][0][i], orig)

        c101 = next(c for c in _find_commands(page, 101) if len(c.get("parameters", [])) > 4)
        self.assertIn("_original", c101)
        self.assertIn("アリス", c101["_original"])
        self.assertIn("\\C[2]", c101["_original"])
        self.assertIn("Speaker_", c101["parameters"][4])

        c122 = _find_commands(page, 122)[0]
        self.assertEqual(c122["_original"], "変数テスト")
        self.assertIn("EN_TRANSLATED", c122["parameters"][4])

    def test_skip_translated_uses_current_commands_not_original(self):
        translated, _ = _run_search_codes(
            _load_map_excerpt(),
            speaker_fn=lambda _name: ["Alice", [0, 0]],
        )
        visible_before = copy.deepcopy(translated)
        speakers_seen = []

        def speaker(name):
            speakers_seen.append(name)
            return _mock_speaker(name)

        result, captured = _run_search_codes(
            translated,
            ignore_tl_text=True,
            speaker_fn=speaker,
        )

        self.assertEqual(captured, [])
        self.assertEqual(speakers_seen, [])
        self.assertEqual(result, visible_before)

    def test_101_display_brackets_do_not_leak_into_401_dialogue(self):
        speakers_seen = []

        def speaker(name):
            speakers_seen.append(name)
            return ["Game Description", [0, 0]]

        page = {
            "list": [
                {
                    "code": 101,
                    "indent": 0,
                    "parameters": ["", 0, 0, 2, "【[Game Description]】"],
                    "_original": "【ゲーム説明】",
                },
                {
                    "code": 401,
                    "indent": 0,
                    "parameters": ["ここから本編スタートとなります。"],
                },
            ]
        }

        translated, captured = _run_search_codes(page, speaker_fn=speaker)
        cmd101, cmd401 = translated["list"]

        self.assertTrue(speakers_seen)
        self.assertEqual(set(speakers_seen), {"ゲーム説明"})
        self.assertEqual(cmd101["parameters"][4], "【Game Description】")
        self.assertEqual(cmd401["parameters"][0], "EN_TRANSLATED")
        self.assertNotIn("Game Description", cmd401["parameters"][0])
        self.assertTrue(
            any(
                isinstance(item, str) and item.startswith("[Game Description]: ")
                for payload in captured
                for item in (payload if isinstance(payload, list) else [payload])
            )
        )

    def test_rerun_uses_original_not_display_text(self):
        page1, captured1 = _run_search_codes(_load_map_excerpt())
        originals_snapshot = json.dumps(
            {i: cmd.get("_original") for i, cmd in enumerate(page1["list"]) if cmd},
            ensure_ascii=False,
        )

        page2, captured2 = _run_search_codes(page1)
        originals_after = json.dumps(
            {i: cmd.get("_original") for i, cmd in enumerate(page2["list"]) if cmd},
            ensure_ascii=False,
        )
        self.assertEqual(originals_snapshot, originals_after, "_original must not change on re-run")

        # Every batch sent to translateAI on re-run should still contain Japanese
        for payload in captured2:
            items = payload if isinstance(payload, list) else [payload]
            for item in items:
                if not isinstance(item, str):
                    continue
                if item == "EN_TRANSLATED":
                    continue
                if _has_japanese(item):
                    continue
                if re.match(r"^\[.+?\]:\s*EN_TRANSLATED$", item):
                    continue
                self.fail(f"Re-run sent non-Japanese to translateAI: {item!r}")

    def test_micro_page_401_original(self):
        """Translate a tiny 3x401 dialogue slice and confirm _original capture."""
        micro = {
            "list": [
                {"code": 401, "indent": 0, "parameters": ["一行目のセリフ。"]},
                {"code": 401, "indent": 0, "parameters": ["二行目のセリフ。"]},
                {"code": 401, "indent": 0, "parameters": ["三行目のセリフ。"]},
            ]
        }

        page, _ = _run_search_codes(micro)
        c401 = _find_commands(page, 401)
        self.assertGreaterEqual(len(c401), 1)
        with_orig = [c for c in c401 if c.get("_original")]
        self.assertGreaterEqual(len(with_orig), 1)
        for c in with_orig:
            self.assertTrue(_has_japanese(c["_original"]))

    def test_leading_format_codes_not_duplicated(self):
        """Leading \\F/\\AA/\\M codes must be restored once, including on re-run."""
        src = "\\F4[2]\\AA[4]\\M4[yes]うなずいてみるよ"
        page = {
            "list": [
                {"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, "セラス"]},
                {"code": 401, "indent": 0, "parameters": [src]},
            ]
        }

        page1, captured1 = _run_search_codes(page)
        cmd = _find_commands(page1, 401)[0]
        self.assertEqual(cmd.get("_original"), src)
        out = cmd["parameters"][0]
        self.assertEqual(out.count("\\F4[2]"), 1, out)
        self.assertEqual(out.count("\\AA[4]"), 1, out)
        self.assertEqual(out.count("\\M4[yes]"), 1, out)
        self.assertTrue(out.startswith("\\F4[2]\\AA[4]\\M4[yes]"), out)
        for payload in captured1:
            items = payload if isinstance(payload, list) else [payload]
            for item in items:
                if isinstance(item, str):
                    self.assertNotIn("\\F4[2]", item, f"codes must be stripped before AI: {item!r}")

        # Simulate a previously-bugged double prefix still sitting in parameters.
        cmd["parameters"][0] = "\\F4[2]\\AA[4]\\M4[yes]" + out
        page2, _ = _run_search_codes(page1)
        cmd2 = _find_commands(page2, 401)[0]
        out2 = cmd2["parameters"][0]
        self.assertEqual(cmd2.get("_original"), src)
        self.assertEqual(out2.count("\\F4[2]"), 1, out2)
        self.assertEqual(out2.count("\\AA[4]"), 1, out2)
        self.assertEqual(out2.count("\\M4[yes]"), 1, out2)

    def test_speaker_color_line_full_original(self):
        """Standalone \\C[n]Name\\C[n] speaker 401 lines keep the full string in _original."""
        page = {
            "list": [
                {"code": 401, "indent": 0, "parameters": ["\\C[2]エルーシャ\\C[0]"]},
                {"code": 401, "indent": 0, "parameters": ["「テストセリフ」"]},
            ]
        }
        page, _ = _run_search_codes(page)
        speaker_cmd = page["list"][0]
        self.assertEqual(speaker_cmd.get("_original"), "\\C[2]エルーシャ\\C[0]")
        self.assertIn("\\C[2]", speaker_cmd["parameters"][0])
        self.assertIn("Speaker_エルーシャ", speaker_cmd["parameters"][0])

        # Re-run: _original unchanged, getSpeaker still receives Japanese name
        speakers_seen = []

        def speaker(name):
            speakers_seen.append(name)
            return _mock_speaker(name)

        orig_t, orig_s = mvmz.translateAI, mvmz.getSpeaker
        orig_401 = mvmz.CODE401
        mvmz.getSpeaker = speaker
        mvmz.CODE401 = True
        mvmz.translateAI = lambda text, history, batch=False: _mock_translate(text, history, batch)
        try:
            mvmz.searchCodes(page, None, [], "TestMap.json")
        finally:
            mvmz.getSpeaker = orig_s
            mvmz.translateAI = orig_t
            mvmz.CODE401 = orig_401
        self.assertEqual(speaker_cmd["_original"], "\\C[2]エルーシャ\\C[0]")
        self.assertIn("エルーシャ", speakers_seen)

    def test_firstline_speaker_batch_uses_glossary_nameplate(self):
        """Unresolved batch speakers stay Japanese; glossary hits become English nameplates."""
        page = {
            "list": [
                {"code": 401, "indent": 0, "parameters": ["ニーナ"]},
                {
                    "code": 401,
                    "indent": 0,
                    "parameters": ["「ギルドに貼ってあった野犬の討伐の依頼」"],
                },
            ]
        }
        orig_first = mvmz.FIRSTLINESPEAKERS
        orig_vocab = mvmz.VOCAB
        orig_names = list(mvmz.NAMESLIST)
        mvmz.FIRSTLINESPEAKERS = True
        mvmz.VOCAB = "# Game Characters\nニーナ (Nina)\n"
        mvmz._speakerVocabSource = None
        mvmz.NAMESLIST = []
        with mvmz._speakerCacheLock:
            mvmz._speakerCache.clear()
        try:
            with patch.dict(os.environ, {"BATCH_PHASE": "collect"}):
                # Use real getSpeaker so glossary / batch deferral is exercised.
                page_out, _ = _run_search_codes(page, speaker_fn=mvmz.getSpeaker)
        finally:
            mvmz.FIRSTLINESPEAKERS = orig_first
            mvmz.VOCAB = orig_vocab
            mvmz._speakerVocabSource = None
            mvmz.NAMESLIST = orig_names
            with mvmz._speakerCacheLock:
                mvmz._speakerCache.clear()
            os.environ.pop("BATCH_PHASE", None)

        speaker_cmd = page_out["list"][0]
        self.assertEqual(speaker_cmd.get("_original"), "ニーナ")
        self.assertEqual(speaker_cmd["parameters"][0], "Nina")
        self.assertNotEqual(page_out["list"][1]["parameters"][0], page_out["list"][1]["_original"])

    def test_405_split_rerun_uses_anchor_original_only(self):
        """English 405 siblings after a split must not pollute re-run source."""
        page = {
            "list": [
                {
                    "code": 405,
                    "indent": 0,
                    "parameters": ["EN_LINE_1"],
                    "_original": "第一行\n第二行",
                },
                {"code": 405, "indent": 0, "parameters": ["EN_LINE_2"]},
            ]
        }
        _, captured = _run_search_codes(page)
        self.assertGreater(len(captured), 0)
        payloads = captured if isinstance(captured[0], str) else captured
        for payload in payloads:
            if not isinstance(payload, str):
                continue
            self.assertIn("第一行", payload)
            self.assertNotIn("EN_LINE_1", payload)
            self.assertNotIn("EN_LINE_2", payload)


    def test_408_choice_help_original(self):
        page = {
            "list": [
                {"code": 108, "indent": 0, "parameters": ["選択肢ヘルプ"]},
                {"code": 408, "indent": 0, "parameters": ["これは選択肢のヘルプです。"]},
            ]
        }
        page, captured = _run_search_codes(page)
        cmd = _find_commands(page, 408)[0]
        self.assertEqual(cmd.get("_original"), "これは選択肢のヘルプです。")
        self.assertNotEqual(cmd["parameters"][0], cmd["_original"])
        self.assertGreater(len(captured), 0)

        page2, captured2 = _run_search_codes(page)
        self.assertEqual(cmd["_original"], _find_commands(page2, 408)[0]["_original"])
        for payload in captured2:
            items = payload if isinstance(payload, list) else [payload]
            for item in items:
                if not isinstance(item, str) or item == "EN_TRANSLATED":
                    continue
                self.assertTrue(_has_japanese(item), f"408 re-run sent non-Japanese: {item!r}")

    def test_first_408_after_empty_108_is_translated_and_preserved(self):
        page = {
            "list": [
                {"code": 108, "indent": 0, "parameters": [""]},
                {"code": 408, "indent": 0, "parameters": ["テレポート。"]},
                {"code": 408, "indent": 0, "parameters": ["条件スイッチ。"]},
            ]
        }

        page, _ = _run_search_codes(page)
        comments = _find_commands(page, 408)

        self.assertEqual(comments[0].get("_original"), "テレポート。")
        self.assertEqual(comments[1].get("_original"), "条件スイッチ。")
        self.assertEqual(comments[0]["parameters"][0], "EN_TRANSLATED")
        self.assertEqual(comments[1]["parameters"][0], "EN_TRANSLATED")

    def test_failed_408_fallback_does_not_write_originals(self):
        page = {
            "list": [
                {"code": 108, "indent": 0, "parameters": [""]},
                {"code": 408, "indent": 0, "parameters": ["第一行"]},
                {"code": 408, "indent": 0, "parameters": ["第二行"]},
            ]
        }

        def failed_translation(text, _history, _batch=False):
            if isinstance(text, list) and text == ["第一行", "第二行"]:
                if "TestMap.json" not in mvmz.MISMATCH:
                    mvmz.MISMATCH.append("TestMap.json")
                mvmz.THREAD_CTX.last_translation_had_mismatch = True
                # Simulate one successful internal chunk and one chunk that
                # exhausted retries and fell back to its source text.
                return [["First line", text[1]], [0, 0]]
            return _mock_translate(text, _history, _batch)

        original_mismatches = mvmz.MISMATCH[:]
        try:
            page, _ = _run_search_codes(page, translate_fn=failed_translation)
        finally:
            mvmz.MISMATCH[:] = original_mismatches

        comments = _find_commands(page, 408)
        self.assertEqual([cmd["parameters"][0] for cmd in comments], ["第一行", "第二行"])
        self.assertTrue(all("_original" not in cmd for cmd in comments))

    def test_short_408_batch_is_not_partially_applied(self):
        page = {
            "list": [
                {"code": 108, "indent": 0, "parameters": [""]},
                {"code": 408, "indent": 0, "parameters": ["第一行"]},
                {"code": 408, "indent": 0, "parameters": ["第二行"]},
            ]
        }

        def short_translation(text, _history, _batch=False):
            if isinstance(text, list) and text == ["第一行", "第二行"]:
                return [["First line"], [0, 0]]
            return _mock_translate(text, _history, _batch)

        original_mismatches = mvmz.MISMATCH[:]
        try:
            page, _ = _run_search_codes(page, translate_fn=short_translation)
        finally:
            mvmz.MISMATCH[:] = original_mismatches

        comments = _find_commands(page, 408)
        self.assertEqual([cmd["parameters"][0] for cmd in comments], ["第一行", "第二行"])
        self.assertTrue(all("_original" not in cmd for cmd in comments))


class TestFixtureMapOriginal(unittest.TestCase):
    """Full fixture map covering every _original preservation code path."""

    def test_fixture_all_cases_original(self):
        page, _ = _run_search_codes(_load_fixture_page())
        marked = _case_commands(page["list"])
        manifest = _load_fixture_manifest()

        for entry in manifest["cases"]:
            cid = entry["id"]
            cmd = _resolve_case_command(page["list"], entry, marked)
            expected = entry["expected_original"]
            with self.subTest(case=cid):
                self.assertIsNotNone(cmd, f"could not resolve fixture case {cid}")
                self.assertEqual(cmd.get("_original"), expected, entry.get("summary", cid))
                if isinstance(expected, str):
                    self.assertTrue(_has_japanese(expected))
                    if cmd.get("parameters"):
                        display = cmd["parameters"][0]
                        if isinstance(display, str):
                            self.assertNotEqual(display, expected)

    def test_fixture_rerun_preserves_original(self):
        page1, _ = _run_search_codes(_load_fixture_page())
        page2, captured2 = _run_search_codes(page1)
        manifest = _load_fixture_manifest()

        for entry in manifest["cases"]:
            cid = entry["id"]
            cmd1 = _resolve_case_command(page1["list"], entry)
            cmd2 = _resolve_case_command(page2["list"], entry)
            with self.subTest(case=cid):
                self.assertIsNotNone(cmd1)
                self.assertIsNotNone(cmd2)
                self.assertEqual(cmd1.get("_original"), cmd2.get("_original"))

        for payload in captured2:
            items = payload if isinstance(payload, list) else [payload]
            for item in items:
                if not isinstance(item, str) or item == "EN_TRANSLATED":
                    continue
                if _has_japanese(item):
                    continue
                if re.match(r"^\[.+?\]:\s*EN_TRANSLATED$", item):
                    continue
                self.fail(f"Fixture re-run sent non-Japanese to translateAI: {item!r}")

    def test_preserve_original_codes_disabled(self):
        """PRESERVEORIGINAL=False must not write _original on map commands."""
        page = {
            "list": [
                {"code": 401, "indent": 0, "parameters": ["こんにちは"]},
            ]
        }
        page, _ = _run_search_codes(page, preserve_original=False)
        self.assertNotIn("_original", page["list"][0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
