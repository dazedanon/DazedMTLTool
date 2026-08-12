"""Tests for deterministic RPG Maker rewrapping of existing translations."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from util.rpgmaker_rewrap import (
    DIALOGUE,
    FACE_DIALOGUE,
    LIST_HELP,
    NOTES,
    RewrapOptions,
    parse_event_codes,
    rewrap_directory,
)


def _write(path: Path, document) -> None:
    path.write_text(json.dumps(document, ensure_ascii=False, indent=4), encoding="utf-8")


def _map_with(commands: list[dict]) -> dict:
    return {
        "events": {
            "1": {
                "id": 1,
                "pages": [{"list": commands}],
            }
        }
    }


class RpgMakerRewrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _options(self, **overrides) -> RewrapOptions:
        values = {
            "dialogue_width": 24,
            "face_dialogue_width": 14,
            "list_width": 28,
            "note_width": 20,
            "categories": frozenset({DIALOGUE, FACE_DIALOGUE, LIST_HELP, NOTES}),
            "event_codes": frozenset({122, 324, 325, 357, 401, 405}),
            "max_protected_rows": 20,
            "skip_protected_overflow": True,
        }
        values.update(overrides)
        return RewrapOptions(**values)

    def test_dialogue_and_face_dialogue_use_separate_widths(self):
        face_original = "顔付きの原文"
        normal_original = "通常の原文"
        path = self.root / "Map001.json"
        _write(
            path,
            _map_with(
                [
                    {"code": 101, "indent": 0, "parameters": ["Actor1", 0, 0, 2]},
                    {
                        "code": 401,
                        "indent": 0,
                        "parameters": ["Face dialogue needs a distinctly narrower line width."],
                        "_original": face_original,
                    },
                    {"code": 0, "indent": 0, "parameters": []},
                    {"code": 101, "indent": 0, "parameters": ["", 0, 0, 2]},
                    {
                        "code": 401,
                        "indent": 0,
                        "parameters": ["Normal dialogue can use the wider message window width."],
                        "_original": normal_original,
                    },
                    {"code": 0, "indent": 0, "parameters": []},
                ]
            ),
        )

        preview = rewrap_directory(self.root, self._options(), apply=False)
        self.assertEqual(preview.by_category[FACE_DIALOGUE], 1)
        self.assertEqual(preview.by_category[DIALOGUE], 1)

        result = rewrap_directory(self.root, self._options(), apply=True)
        self.assertEqual(result.changes_applied, 2)
        data = json.loads(path.read_text(encoding="utf-8"))
        commands = data["events"]["1"]["pages"][0]["list"]
        face_lines = commands[1]["parameters"][0].splitlines()
        self.assertGreater(len(face_lines), 1)
        self.assertTrue(all(len(line) <= 14 for line in face_lines))
        self.assertEqual(commands[1]["_original"], face_original)
        normal_anchor = next(c for c in commands if c.get("_original") == normal_original)
        self.assertEqual(normal_anchor["_original"], normal_original)

    def test_code_401_is_never_blocked_by_row_protection(self):
        path = self.root / "Map002.json"
        original_text = "One two three four five six seven eight nine ten eleven twelve."
        _write(
            path,
            _map_with(
                [
                    {"code": 101, "indent": 0, "parameters": ["", 0, 0, 2]},
                    {"code": 401, "indent": 0, "parameters": [original_text]},
                ]
            ),
        )
        result = rewrap_directory(
            self.root,
            self._options(
                categories=frozenset({DIALOGUE}),
                event_codes=frozenset({401}),
                dialogue_width=8,
                max_protected_rows=2,
            ),
            apply=True,
        )
        self.assertEqual(result.overflow_skipped, 0)
        self.assertEqual(result.changes_applied, 1)
        data = json.loads(path.read_text(encoding="utf-8"))
        wrapped = data["events"]["1"]["pages"][0]["list"][1]["parameters"][0]
        self.assertIn("\n", wrapped)

    def test_code_401_bypasses_default_row_protection(self):
        path = self.root / "MapDefaultRows.json"
        original_text = "One two three four five six seven eight nine ten eleven twelve."
        _write(
            path,
            _map_with(
                [
                    {"code": 101, "indent": 0, "parameters": ["", 0, 0, 2]},
                    {"code": 401, "indent": 0, "parameters": [original_text]},
                ]
            ),
        )
        options = RewrapOptions(
            dialogue_width=8,
            face_dialogue_width=8,
            list_width=20,
            note_width=20,
            categories=frozenset({DIALOGUE}),
            event_codes=frozenset({401}),
        )

        result = rewrap_directory(self.root, options, apply=True)

        self.assertEqual(result.overflow_skipped, 0)
        self.assertEqual(result.changes_applied, 1)
        data = json.loads(path.read_text(encoding="utf-8"))
        commands = data["events"]["1"]["pages"][0]["list"]
        rows = commands[1]["parameters"][0].splitlines()
        self.assertEqual([command.get("code") for command in commands], [101, 401])
        self.assertGreater(len(rows), 4)

    def test_dialogue_wrap_preserves_every_code_401_command(self):
        path = self.root / "MapPreserve401.json"
        first = "The first existing command needs several wrapped lines of dialogue."
        second = "The second existing command must remain separate and intact too."
        _write(
            path,
            _map_with(
                [
                    {"code": 101, "indent": 0, "parameters": ["Actor1", 0, 0, 2]},
                    {
                        "code": 401,
                        "indent": 0,
                        "parameters": [first],
                        "_original": "一",
                    },
                    {
                        "code": 401,
                        "indent": 0,
                        "parameters": [second],
                        "_original": "二",
                    },
                    {"code": 0, "indent": 0, "parameters": []},
                ]
            ),
        )

        result = rewrap_directory(
            self.root,
            self._options(
                categories=frozenset({FACE_DIALOGUE}),
                event_codes=frozenset({401}),
                face_dialogue_width=12,
            ),
            apply=True,
        )

        self.assertEqual(result.changes_applied, 1)
        commands = json.loads(path.read_text(encoding="utf-8"))["events"]["1"]["pages"][0]["list"]
        self.assertEqual(len(commands), 4)
        self.assertEqual([command.get("code") for command in commands], [101, 401, 401, 0])
        self.assertEqual(commands[1]["_original"], "一")
        self.assertEqual(commands[2]["_original"], "二")
        self.assertIn("\n", commands[1]["parameters"][0])
        self.assertIn("\n", commands[2]["parameters"][0])
        self.assertEqual(commands[1]["parameters"][0].replace("\n", " "), first)
        self.assertEqual(commands[2]["parameters"][0].replace("\n", " "), second)

    def test_row_protection_applies_to_scrolling_text(self):
        path = self.root / "MapScrollingRows.json"
        _write(
            path,
            _map_with(
                [
                    {"code": 105, "indent": 0, "parameters": [2, False]},
                    {
                        "code": 405,
                        "indent": 0,
                        "parameters": ["Scrolling text can use as many wrapped rows as needed."],
                    },
                ]
            ),
        )
        result = rewrap_directory(
            self.root,
            self._options(
                categories=frozenset({DIALOGUE}),
                event_codes=frozenset({405}),
                dialogue_width=8,
                max_protected_rows=1,
                skip_protected_overflow=True,
            ),
            apply=True,
        )

        self.assertEqual(result.overflow_skipped, 1)
        self.assertEqual(result.changes_applied, 0)

    def test_row_protection_applies_to_list_help_and_notes(self):
        path = self.root / "Items.json"
        description = "A long help description that wraps onto several visible rows."
        note_body = "A long player-facing note body that also wraps onto several rows."
        _write(
            path,
            [
                None,
                {
                    "id": 1,
                    "description": description,
                    "note": f"<infowindow:{note_body}>",
                },
            ],
        )
        result = rewrap_directory(
            self.root,
            self._options(
                categories=frozenset({LIST_HELP, NOTES}),
                list_width=8,
                note_width=8,
                max_protected_rows=1,
                skip_protected_overflow=True,
            ),
            apply=True,
        )

        self.assertEqual(result.overflow_skipped, 2)
        self.assertEqual(result.changes_applied, 0)
        data = json.loads(path.read_text(encoding="utf-8"))[1]
        self.assertEqual(data["description"], description)
        self.assertEqual(data["note"], f"<infowindow:{note_body}>")

    def test_face_code_401_is_never_blocked_by_row_protection(self):
        path = self.root / "MapSpeaker.json"
        text = "[Alice]\nOne two three four five six seven eight."
        _write(
            path,
            _map_with(
                [
                    {"code": 101, "indent": 0, "parameters": ["Actor1", 0, 0, 2]},
                    {"code": 401, "indent": 0, "parameters": [text]},
                ]
            ),
        )
        result = rewrap_directory(
            self.root,
            self._options(
                categories=frozenset({FACE_DIALOGUE}),
                event_codes=frozenset({401}),
                face_dialogue_width=14,
                max_protected_rows=3,
            ),
            apply=True,
        )
        self.assertEqual(result.overflow_skipped, 0)
        self.assertEqual(result.changes_applied, 1)

    def test_existing_translation_can_be_rewrapped_repeatedly(self):
        path = self.root / "Map003.json"
        text = "This existing English translation can be narrowed and widened repeatedly."
        _write(
            path,
            _map_with(
                [
                    {"code": 101, "indent": 0, "parameters": ["", 0, 0, 2]},
                    {
                        "code": 401,
                        "indent": 0,
                        "parameters": [text],
                        "_original": "繰り返し折り返せる原文",
                    },
                    {"code": 0, "indent": 0, "parameters": []},
                ]
            ),
        )
        narrow = self._options(
            categories=frozenset({DIALOGUE}),
            event_codes=frozenset({401}),
            dialogue_width=12,
        )
        wide = self._options(
            categories=frozenset({DIALOGUE}),
            event_codes=frozenset({401}),
            dialogue_width=40,
        )
        rewrap_directory(self.root, narrow, apply=True)
        narrowed = json.loads(path.read_text(encoding="utf-8"))
        narrow_commands = narrowed["events"]["1"]["pages"][0]["list"]
        narrow_rows = narrow_commands[1]["parameters"][0].splitlines()
        rewrap_directory(self.root, wide, apply=True)
        widened = json.loads(path.read_text(encoding="utf-8"))
        wide_commands = widened["events"]["1"]["pages"][0]["list"]
        wide_rows = wide_commands[1]["parameters"][0].splitlines()
        self.assertLess(len(wide_rows), len(narrow_rows))
        self.assertEqual(" ".join(wide_rows), text)
        self.assertEqual([command.get("code") for command in wide_commands], [101, 401, 0])
        self.assertEqual(wide_commands[1]["_original"], "繰り返し折り返せる原文")

    def test_over_limit_mode_leaves_text_that_already_fits_unchanged(self):
        path = self.root / "MapOverLimitOnly.json"
        fitting = r"\c[1]Already fits\c[0]\non two manual rows."
        overflowing = "Face dialogue currently runs beyond its narrower configured limit."
        _write(
            path,
            _map_with(
                [
                    {"code": 101, "indent": 0, "parameters": ["", 0, 0, 2]},
                    {"code": 401, "indent": 0, "parameters": [fitting]},
                    {"code": 0, "indent": 0, "parameters": []},
                    {"code": 101, "indent": 0, "parameters": ["Actor1", 0, 0, 2]},
                    {"code": 401, "indent": 0, "parameters": [overflowing]},
                ]
            ),
        )

        result = rewrap_directory(
            self.root,
            self._options(
                categories=frozenset({DIALOGUE, FACE_DIALOGUE}),
                event_codes=frozenset({401}),
                dialogue_width=30,
                face_dialogue_width=14,
                only_over_limit=True,
            ),
            apply=True,
        )

        self.assertEqual(result.changes_found, 1)
        self.assertEqual(result.changes_applied, 1)
        self.assertEqual(result.by_category, {FACE_DIALOGUE: 1})
        commands = json.loads(path.read_text(encoding="utf-8"))["events"]["1"]["pages"][0]["list"]
        self.assertEqual(commands[1]["parameters"][0], fitting)
        self.assertIn("\n", commands[4]["parameters"][0])

    def test_database_list_and_note_bodies_rewrap_without_touching_original(self):
        path = self.root / "Items.json"
        source = {
            "description": "説明",
            "note": "<infowindow:長い説明>",
        }
        document = [
            None,
            {
                "id": 1,
                "description": "A long item description that needs a narrower help window.",
                "note": (
                    "<infowindow:This note body is player facing and needs its own narrower wrap.>\n"
                    "<dPlnText:This second player-facing note also needs narrower wrapping.>"
                ),
                "_original": source,
            },
        ]
        _write(path, document)
        result = rewrap_directory(
            self.root,
            self._options(categories=frozenset({LIST_HELP, NOTES})),
            apply=True,
        )
        self.assertEqual(result.by_category[LIST_HELP], 1)
        self.assertEqual(result.by_category[NOTES], 2)
        updated = json.loads(path.read_text(encoding="utf-8"))[1]
        self.assertIn("\n", updated["description"])
        self.assertIn("\n", updated["note"])
        self.assertEqual(updated["_original"], source)
        self.assertTrue(updated["note"].startswith("<infowindow:"))
        self.assertTrue(updated["note"].endswith(">"))
        self.assertIn("<dPlnText:", updated["note"])

    def test_file_and_event_code_filters_limit_scope(self):
        map1 = self.root / "Map001.json"
        map2 = self.root / "Map002.json"
        command_list = [
            {"code": 101, "indent": 0, "parameters": ["", 0, 0, 2]},
            {
                "code": 401,
                "indent": 0,
                "parameters": ["A standard message that would wrap at this configured width."],
            },
            {
                "code": 357,
                "indent": 0,
                "parameters": ["Plugin", "command", "", {"text": "Plugin text that would also wrap."}],
            },
        ]
        _write(map1, _map_with(command_list))
        _write(map2, _map_with(command_list))

        result = rewrap_directory(
            self.root,
            self._options(
                categories=frozenset({DIALOGUE}),
                event_codes=frozenset({357}),
            ),
            file_names=["Map002.json"],
            apply=True,
        )
        self.assertEqual(result.files_scanned, 1)
        self.assertEqual(result.by_code[357], 1)
        untouched = json.loads(map1.read_text(encoding="utf-8"))
        changed = json.loads(map2.read_text(encoding="utf-8"))
        self.assertNotIn(
            "\n",
            untouched["events"]["1"]["pages"][0]["list"][2]["parameters"][3]["text"],
        )
        self.assertIn(
            "\n",
            changed["events"]["1"]["pages"][0]["list"][2]["parameters"][3]["text"],
        )
        self.assertNotIn(
            "\n",
            changed["events"]["1"]["pages"][0]["list"][1]["parameters"][0],
        )

    def test_dtextpicture_rewrap_preserves_centering_on_every_line(self):
        path = self.root / "MapDTextPicture.json"
        original = "\\ac This centered picture text was already\n\\ac wrapped at another width."
        command = {
            "code": 357,
            "indent": 0,
            "parameters": [
                "DTextPicture",
                "dText",
                "String Picture Preparation",
                {"text": original, "fontSize": "0"},
            ],
            "_original": "中央揃えの原文",
        }
        _write(path, _map_with([command]))

        result = rewrap_directory(
            self.root,
            self._options(
                categories=frozenset({DIALOGUE}),
                event_codes=frozenset({357}),
                dialogue_width=16,
            ),
            apply=True,
        )

        self.assertEqual(result.by_code[357], 1)
        self.assertEqual(result.changes_applied, 1)
        updated = json.loads(path.read_text(encoding="utf-8"))["events"]["1"]["pages"][0]["list"][0]
        wrapped = updated["parameters"][3]["text"]
        self.assertGreater(len(wrapped.splitlines()), 1)
        self.assertTrue(all(line.startswith(r"\ac ") for line in wrapped.splitlines()))
        self.assertEqual(
            " ".join(line.removeprefix(r"\ac ") for line in wrapped.splitlines()),
            "This centered picture text was already wrapped at another width.",
        )
        self.assertEqual(updated["parameters"][3]["fontSize"], "0")
        self.assertEqual(updated["_original"], "中央揃えの原文")

    def test_dtextpicture_ignores_non_text_plugin_commands(self):
        path = self.root / "MapDTextSetting.json"
        text = "This field is not a dText display argument and must stay unchanged."
        command = {
            "code": 357,
            "indent": 0,
            "parameters": [
                "DTextPicture",
                "dTextSetting",
                "String Picture Settings",
                {"text": text},
            ],
        }
        _write(path, _map_with([command]))

        result = rewrap_directory(
            self.root,
            self._options(
                categories=frozenset({DIALOGUE}),
                event_codes=frozenset({357}),
                dialogue_width=12,
            ),
            apply=True,
        )

        self.assertEqual(result.changes_found, 0)
        updated = json.loads(path.read_text(encoding="utf-8"))["events"]["1"]["pages"][0]["list"][0]
        self.assertEqual(updated["parameters"][3]["text"], text)

    def test_code122_rewraps_only_the_backtick_string(self):
        path = self.root / "CommonEvents.json"
        expression = "`A stored help string that should be rewrapped without changing syntax.`;"
        _write(
            path,
            [
                None,
                {
                    "id": 1,
                    "list": [
                        {"code": 122, "indent": 0, "parameters": [1, 1, 0, 4, expression]}
                    ],
                },
            ],
        )
        result = rewrap_directory(
            self.root,
            self._options(
                categories=frozenset({LIST_HELP}),
                event_codes=frozenset({122}),
                list_width=18,
            ),
            apply=True,
        )
        self.assertEqual(result.by_code[122], 1)
        value = json.loads(path.read_text(encoding="utf-8"))[1]["list"][0]["parameters"][4]
        self.assertTrue(value.startswith("`"))
        self.assertTrue(value.endswith("`;"))
        self.assertIn(r"\n", value)

    def test_parse_event_codes(self):
        self.assertIsNone(parse_event_codes("  "))
        self.assertEqual(parse_event_codes("401, 405 357"), frozenset({401, 405, 357}))
        with self.assertRaises(ValueError):
            parse_event_codes("401, dialogue")
        with self.assertRaisesRegex(ValueError, "Unsupported event code"):
            parse_event_codes("102")


if __name__ == "__main__":
    unittest.main()
