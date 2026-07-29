#!/usr/bin/env python3
"""Unit tests for inject precheck and safety-guard parsers."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from util import wolfdawn  # noqa: E402
from util.wolfdawn import inject as wi  # noqa: E402
from util.wolfdawn import inject_precheck as pre  # noqa: E402


class InjectSafetyParserTests(unittest.TestCase):
    def test_identity_count_is_not_safety(self):
        stderr = (
            "db type 49 row 18 field 21: control-code mismatch - source has "
            '["\\\\c[19]"], translation has []; edit the words\n'
            "would apply 2178 translation(s) (4 untranslated, 0 drifted); "
            "dry run - did NOT write out.project\n"
            "WARNING: 1 line(s) left UNTRANSLATED by a safety guard - "
            "1 control-code mismatch, 0 not encodable\n"
        )
        self.assertEqual(wolfdawn.parse_strings_inject_counts("", stderr), (2178, 0))
        self.assertEqual(wolfdawn.parse_strings_inject_untranslated("", stderr), 4)
        self.assertEqual(wolfdawn.parse_strings_inject_safety_count("", stderr), 1)
        lines = wolfdawn.parse_strings_inject_safety_lines("", stderr)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0][1], "code_mismatch")

    def test_interpret_ignores_identity_in_summary(self):
        res = mock.Mock(
            ok=True,
            returncode=0,
            stdout="",
            stderr=(
                "applied 2178 translation(s) (4 untranslated, 0 drifted); "
                "wrote DataBase.project\n"
            ),
        )
        result = wi._interpret_strings_result("DataBase.project.json", res)
        self.assertTrue(result.success)
        self.assertEqual(result.summary, "applied 2178 line(s)")
        self.assertNotIn("unchanged", result.summary)
        self.assertNotIn("safety", result.summary)

    def test_interpret_labels_real_safety_warning(self):
        res = mock.Mock(
            ok=True,
            returncode=0,
            stdout="",
            stderr=(
                "db type 1 row 0 field 0: control-code mismatch - source has "
                '["\\\\^"], translation has []\n'
                "applied 10 translation(s) (0 untranslated, 0 drifted); wrote x\n"
                "WARNING: 1 line(s) left UNTRANSLATED by a safety guard - "
                "1 control-code mismatch, 0 not encodable\n"
            ),
        )
        result = wi._interpret_strings_result("x.json", res)
        self.assertTrue(result.success)
        self.assertIn("skipped by safety guard", result.summary)


class InjectPrecheckLocalTests(unittest.TestCase):
    def test_repair_inject_json_does_not_rewrite_valid_moved_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "CommonEvent.dat.json"
            doc = {
                "kind": "common",
                "scenes": [
                    {
                        "event": 24,
                        "lines": [
                            {
                                "cmd": 101,
                                "str": 0,
                                "source": r"\v[24]Day        ",
                                "text": "Day \\v[24]\n        ",
                            }
                        ],
                    }
                ],
            }
            original = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
            path.write_text(original, encoding="utf-8")

            repaired_path, font_drift = wi.repair_inject_json(path)

            self.assertEqual(repaired_path, path)
            self.assertFalse(font_drift)
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_repair_inject_json_does_not_hide_non_font_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "DataBase.project.json"
            doc = {
                "kind": "db",
                "groups": [
                    {
                        "typeName": "mixed",
                        "lines": [
                            {
                                "source": r"\f[18]文字",
                                "text": r"\f[14]Text",
                            },
                            {
                                "source": r"\c[1]赤\c[0]",
                                "text": r"Red \c[1]",
                            },
                        ],
                    }
                ],
            }
            original = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
            path.write_text(original, encoding="utf-8")

            _repaired_path, safe_font_only_drift = wi.repair_inject_json(path)

            self.assertFalse(safe_font_only_drift)
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_resolve_db_locator(self):
        doc = {
            "kind": "db",
            "groups": [
                {
                    "type": 23,
                    "typeName": "Sheet",
                    "lines": [
                        {
                            "row": 2,
                            "field": 65,
                            "fieldName": "comment",
                            "source": "txtblank",
                            "text": "txtblank",
                        },
                    ],
                }
            ],
        }
        line, hit = pre.resolve_locator_line(doc, "db type 23 row 2 field 65")
        self.assertIsNotNone(line)
        self.assertEqual(line["text"], "txtblank")
        self.assertEqual(hit["sheet_name"], "Sheet")

    def test_apply_issue_text_updates_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "DataBase.project.json"
            doc = {
                "kind": "db",
                "groups": [
                    {
                        "type": 1,
                        "typeName": "T",
                        "lines": [
                            {
                                "row": 0,
                                "field": 2,
                                "fieldName": "f",
                                "source": "あ\\^",
                                "text": "A",
                            }
                        ],
                    }
                ],
            }
            path.write_text(json.dumps(doc), encoding="utf-8")
            issue = pre.InjectIssue(
                json_file="DataBase.project.json",
                kind="code_mismatch",
                locator="db type 1 row 0 field 2",
                message="mismatch",
                source="あ\\^",
                text="A",
            )
            ok, err = pre.apply_issue_text(Path(tmp), issue, "A\\^")
            self.assertTrue(ok, err)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["groups"][0]["lines"][0]["text"], "A\\^")


if __name__ == "__main__":
    unittest.main()
