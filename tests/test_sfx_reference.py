"""Tests for local, dynamically matched Japanese SFX context."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from util.sfx_reference import (
    SfxReference,
    build_sfx_reference_text,
    load_sfx_reference,
    source_strings,
)


class SfxReferenceTests(unittest.TestCase):
    def test_bundled_snapshot_loads_and_has_pinned_identity(self):
        reference = load_sfx_reference()
        self.assertEqual(len(reference.entries), 660)
        self.assertEqual(
            reference.identity["revision"],
            "673f9f51651122e89948f5ef25794c78efe29f50",
        )
        self.assertEqual(
            reference.identity["sha256"],
            "d8f10a6399c39c64a92a0427975b00e3210e9c2d779711818493d3b02db95b84",
        )
        asset_root = Path(__file__).resolve().parents[1] / "data" / "sfx_reference"
        self.assertTrue((asset_root / "LICENSE.md").is_file())
        self.assertTrue((asset_root / "SOURCE.md").is_file())
        self.assertNotIn(
            '"example"', (asset_root / "j_ono.json").read_text(encoding="utf-8")
        )
        self.assertFalse(any(
            meaning == "s"
            for entry in reference.entries
            for sense in entry["senses"]
            for meaning in sense["meanings"]
        ))

    def test_extracts_only_json_string_values(self):
        payload = json.dumps({"Line1": "ドキドキ", "meta": 30}, ensure_ascii=False)
        self.assertEqual(source_strings(payload), ["ドキドキ"])

    def test_matches_supported_kana_variants(self):
        cases = (
            ("katakana", '{"Line1":"胸がドキドキする"}', "ドキドキ"),
            ("hiragana", '{"Line1":"どきどき……"}', "どきどき"),
            ("half-width katakana", '{"Line1":"胸がﾄﾞｷﾄﾞｷする"}', "ドキドキ"),
        )
        for label, payload, expected in cases:
            with self.subTest(label):
                self.assertIn(expected, build_sfx_reference_text(payload))

    def test_ordinary_hiragana_verb_does_not_create_false_sfx_match(self):
        self.assertEqual(build_sfx_reference_text('{"Line1":"勉強する"}'), "")
        context = build_sfx_reference_text('{"Line1":"胸がドキドキする"}')
        self.assertIn("ドキドキ", context)
        self.assertNotIn("\n- する /", context)

    def test_non_matches_and_disabled_reference_return_no_context(self):
        cases = (
            ("longer hiragana run", '{"Line1":"どきどきしている"}', {}),
            ("single kana", '{"Line1":"あ！"}', {}),
            ("disabled", '{"Line1":"ドキドキ"}', {"enabled": False}),
        )
        for label, payload, kwargs in cases:
            with self.subTest(label):
                self.assertEqual(build_sfx_reference_text(payload, **kwargs), "")

    def test_context_is_non_authoritative_and_preserves_ambiguity(self):
        context = build_sfx_reference_text('{"Line1":"ガーン……そんな"}')
        self.assertIn("contextual suggestions", context)
        self.assertIn("not approved fixed translations", context)
        self.assertNotIn("Romaji:", context)
        self.assertGreaterEqual(context.count("  - equivalents:"), 2)

    def test_longest_match_wins_and_cap_is_deterministic(self):
        document = {
            "schema_version": 1,
            "source": {"revision": "test"},
            "entries": [
                {"id": "short", "variants": ["ドキ"], "romaji": [], "senses": [{"equivalents": ["short"], "meanings": [], "type": "o"}]},
                {"id": "long", "variants": ["ドキドキ"], "romaji": [], "senses": [{"equivalents": ["long"], "meanings": [], "type": "o"}]},
                {"id": "bang", "variants": ["バタン"], "romaji": [], "senses": [{"equivalents": ["slam"], "meanings": [], "type": "o"}]},
            ],
        }
        reference = SfxReference(document)
        matches = reference.match("ドキドキ。バタン。", limit=1)
        self.assertEqual([match.entry["id"] for match in matches], ["long"])

    def test_malformed_snapshot_fails_closed(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "bad.json"
            path.write_text("{}", encoding="utf-8")
            self.assertEqual(build_sfx_reference_text("ドキドキ", path=path), "")


if __name__ == "__main__":
    unittest.main()
