"""Exact-match reference translation behavior for Setup and QA."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from util import rpgmaker_qa
from util.reference_games import (
    OVERLAP_RELATIVE,
    add_embedded_reference,
    add_game_pair_reference,
    add_paired_reference,
    build_index,
    prepare_overlaps,
    setup_reference_note,
)


def _write(path: Path, value, *, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding=encoding)


class ReferenceGameTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.game = self.root / "current"
        self.data = self.game / "data"
        self.data.mkdir(parents=True)
        _write(
            self.data / "Items.json",
            [None, {"id": 1, "name": "薬", "description": "体力を回復する。"}],
        )

    def _embedded_reference(self) -> Path:
        data = self.root / "old-game" / "data"
        _write(
            data / "Items.json",
            [
                None,
                {
                    "id": 1,
                    "name": "Tonic",
                    "description": "Restores health.",
                    "_original": {"name": "薬", "description": "体力を回復する。"},
                },
            ],
        )
        return data

    def test_embedded_reference_builds_local_exact_overlap_artifact(self):
        add_embedded_reference(self.game, "Earlier Game", self._embedded_reference())

        index = build_index(self.game)
        self.assertEqual(index["games"][0]["pair_count"], 2)
        self.assertEqual(index["matches"]["薬"][0]["translation"], "Tonic")

        overlaps = prepare_overlaps(self.game, self.data)
        self.assertEqual(overlaps["status"], "ready")
        self.assertEqual(overlaps["source_count"], 2)
        self.assertTrue((self.game / OVERLAP_RELATIVE).is_file())
        note = setup_reference_note(self.game, self.data)
        self.assertIn("Earlier Game", note)
        self.assertIn(str(self.game / OVERLAP_RELATIVE), note)
        self.assertIn("advisory evidence", note)

    def test_paired_reference_groups_reflowed_message_lines(self):
        japanese = self.root / "paired" / "ja"
        english = self.root / "paired" / "en"
        _write(
            japanese / "Map001.json",
            {
                "events": [
                    None,
                    {
                        "pages": [
                            {
                                "list": [
                                    {"code": 101, "parameters": ["", 0, 0, 2, ""]},
                                    {"code": 401, "parameters": ["おはよう。"]},
                                    {"code": 401, "parameters": ["元気か？"]},
                                    {"code": 0, "parameters": []},
                                ]
                            }
                        ]
                    },
                ]
            },
        )
        _write(
            english / "Map001.json",
            {
                "events": [
                    None,
                    {
                        "pages": [
                            {
                                "list": [
                                    {"code": 101, "parameters": ["", 0, 0, 2, ""]},
                                    {"code": 401, "parameters": ["Morning. How are you?"]},
                                    {"code": 0, "parameters": []},
                                ]
                            }
                        ]
                    },
                ]
            },
        )
        add_paired_reference(self.game, "Paired Game", japanese, english)

        index = build_index(self.game)
        source = "おはよう。\n元気か？"
        self.assertEqual(index["matches"][source][0]["translation"], "Morning. How are you?")

    def test_game_roots_cache_normalized_pair_and_accept_utf8_bom(self):
        japanese_game = self.root / "japanese-install"
        english_game = self.root / "english-install"
        _write(
            japanese_game / "data" / "Items.json",
            [None, {"id": 1, "name": "薬"}],
        )
        _write(
            english_game / "www" / "data" / "Items.json",
            [None, {"id": 1, "name": "Tonic"}],
            encoding="utf-8-sig",
        )

        registry = add_game_pair_reference(
            self.game,
            "Detected Pair",
            japanese_game,
            english_game,
        )

        entry = registry["references"][0]
        source_data = Path(entry["source_data"])
        translated_data = Path(entry["translated_data"])
        cache_root = self.game / ".dazedtl" / "reference-data"
        self.assertIn(cache_root, source_data.parents)
        self.assertIn(cache_root, translated_data.parents)
        self.assertTrue((source_data / "Items.json").is_file())
        self.assertTrue((translated_data / "Items.json").is_file())
        self.assertEqual(
            build_index(self.game)["matches"]["薬"][0]["translation"],
            "Tonic",
        )

    def test_ace_game_roots_run_the_bundled_json_conversion_path(self):
        japanese_game = self.root / "ace-ja"
        english_game = self.root / "ace-en"
        (japanese_game / "Data").mkdir(parents=True)
        (english_game / "Data").mkdir(parents=True)
        (japanese_game / "Data" / "Items.rvdata2").write_bytes(b"ja")
        (english_game / "Data" / "Items.rvdata2").write_bytes(b"en")
        converted = iter(("薬", "Tonic"))

        def fake_convert(_command, cwd, _label, _log_fn):
            _write(
                Path(cwd) / "ace_json" / "Items.json",
                [None, {"id": 1, "name": next(converted)}],
            )

        with (
            patch("util.ace.update_tools.ensure_ace_tools", return_value=True),
            patch(
                "util.ace.update_tools.ace_tool_path",
                return_value=Path("RV2JSON.exe"),
            ),
            patch("util.reference_games._run_checked", side_effect=fake_convert),
        ):
            add_game_pair_reference(
                self.game,
                "Ace Pair",
                japanese_game,
                english_game,
            )

        self.assertEqual(
            build_index(self.game)["matches"]["薬"][0]["translation"],
            "Tonic",
        )

    def test_wolf_game_roots_run_wolfdawn_extraction(self):
        japanese_game = self.root / "wolf-ja"
        english_game = self.root / "wolf-en"
        for root in (japanese_game, english_game):
            source = root / "Data" / "BasicData" / "CommonEvent.dat"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"fixture")

        def fake_strings(_source, output, **_kwargs):
            value = "薬" if "source" in Path(output).parts else "Tonic"
            _write(Path(output), {"entries": [{"text": value}]})
            return SimpleNamespace(ok=True)

        def fake_names(_source, output, **_kwargs):
            _write(Path(output), {"entries": []})
            return SimpleNamespace(ok=True)

        with (
            patch("util.wolfdawn.strings_extract", side_effect=fake_strings),
            patch("util.wolfdawn.names_extract", side_effect=fake_names),
        ):
            add_game_pair_reference(
                self.game,
                "WOLF Pair",
                japanese_game,
                english_game,
            )

        self.assertEqual(
            build_index(self.game)["matches"]["薬"][0]["translation"],
            "Tonic",
        )

    def test_qa_bundle_carries_reference_evidence_without_forcing_deep_review(self):
        translated = self.game / "translated"
        _write(
            translated / "Items.json",
            [
                None,
                {
                    "id": 1,
                    "name": "Potion",
                    "description": "Restores health.",
                    "_original": {"name": "薬", "description": "体力を回復する。"},
                },
            ],
        )
        add_embedded_reference(self.game, "Earlier Game", self._embedded_reference())
        task, _state = rpgmaker_qa.prepare_task(
            self.game,
            translated,
            "database",
            self.root / "tasks",
        )
        context = json.loads((task / "context.json").read_text(encoding="utf-8"))
        self.assertEqual(context["reference_translations"]["status"], "ready")
        bundle_paths = sorted((task / "bundles" / "screen").glob("*.json"))
        bundles = [json.loads(path.read_text(encoding="utf-8")) for path in bundle_paths]
        items = [item for bundle in bundles for item in bundle["items"]]
        potion = next(item for item in items if item.get("source") == "薬")
        self.assertEqual(potion["reference_translations"][0]["translation"], "Tonic")
        self.assertIn("reference-difference", potion["risk"])
        self.assertNotIn("reference-difference", rpgmaker_qa._forced_deep_reasons(potion))


if __name__ == "__main__":
    unittest.main()
