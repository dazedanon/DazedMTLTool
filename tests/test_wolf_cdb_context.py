#!/usr/bin/env python3
"""Tests for WOLF ``\\cdb`` translation-context lookup generation."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from util.wolfdawn import cdb_context  # noqa: E402


FULL_CDB = {
    "kind": "CDB",
    "types": [
        {
            "id": 0,
            "fields": [
                {"id": 0, "name": "キャラ名", "kind": "string"},
                {"id": 1, "name": "レベル", "kind": "int"},
            ],
            "rows": [
                {
                    "id": 12,
                    "name": "ウルファール",
                    "values": {"キャラ名": "ウルファール", "レベル": 5},
                }
            ],
        }
    ],
}


class WolfCdbContextTests(unittest.TestCase):
    def test_builds_lookup_by_numeric_type_row_and_field(self):
        self.assertEqual(
            cdb_context.lookup_from_db_json(FULL_CDB),
            {"0:12:0": "ウルファール"},
        )

    def test_strings_extract_is_available_as_a_partial_fallback(self):
        extracted = {
            "kind": "db",
            "groups": [
                {
                    "type": 20,
                    "lines": [
                        {"row": 3, "field": 2, "source": "表示テキスト"},
                        {"row": 3, "field": 4, "source": 99},
                    ],
                }
            ],
        }
        self.assertEqual(
            cdb_context.lookup_from_strings_extract(extracted),
            {"20:3:2": "表示テキスト"},
        )

    def test_write_sidecar_reduces_full_db_json(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project = root / "CDataBase.project"
            project.write_bytes(b"test")
            sidecar = root / cdb_context.SIDECAR_NAME

            def fake_db_json(_project, output, log_fn=None):
                Path(output).write_text(
                    json.dumps(FULL_CDB, ensure_ascii=False), encoding="utf-8"
                )
                return type("Result", (), {"ok": True})()

            with patch.object(cdb_context.wolfdawn, "db_json", side_effect=fake_db_json):
                self.assertTrue(cdb_context.write_sidecar(project, sidecar))

            self.assertEqual(
                cdb_context.read_sidecar(sidecar),
                {"0:12:0": "ウルファール"},
            )


if __name__ == "__main__":
    unittest.main()
