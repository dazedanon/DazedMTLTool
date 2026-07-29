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
        self.assertEqual(result.safety_skipped, 1)
        self.assertEqual(
            result.safety_details,
            ["db type 1 row 0 field 0 — control-code mismatch"],
        )


class InjectPrecheckLocalTests(unittest.TestCase):
    def test_explain_issue_summarizes_extra_font_code(self):
        message = (
            "event 5 page 0 cmd 0 str 0: control-code mismatch - "
            'source has ["\\n\\n", "\\\\f[10]"], translation has '
            '["\\n\\n", "\\\\f[10]", "\\\\f[10]"]; edit the words'
        )

        problem, difference, guidance = pre.explain_issue(
            "code_mismatch",
            message,
            "Japanese\n\n\\f[10]note",
            "\\f[10]English\n\n\\f[10]note",
        )

        self.assertEqual(problem, "Font-size codes differ from the source")
        self.assertEqual(difference, "Missing: none\nExtra: `\\f[10]`")
        self.assertIn("intentionally changed", guidance)

    def test_explain_issue_calls_out_unclosed_source_code(self):
        source = "Japanese \\i[200\nrest of source"
        text = "English \\i[200\nrest of source"

        problem, difference, guidance = pre.explain_issue(
            "code_mismatch", "raw diagnostic", source, text
        )

        self.assertEqual(problem, "Source has an unclosed control code: `\\i[200`")
        self.assertIn("missing `]`", difference)
        self.assertIn("affected suffix", guidance)

    def test_explain_issue_calls_out_literal_newline(self):
        message = (
            "event 7 page 0 cmd 25 str 0: control-code mismatch - "
            'source has ["@1"], translation has '
            '["@1", "\\\\n", "\\\\nfreely"]; edit the words'
        )

        problem, difference, guidance = pre.explain_issue(
            "code_mismatch", message, "@1\nJapanese", r"@1\nEnglish\nfreely"
        )

        self.assertEqual(problem, "Translation contains literal `\\n` text")
        self.assertIn("`\\nfreely`", difference)
        self.assertIn("real line break", guidance)

    def test_explain_issue_lists_unencodable_characters(self):
        problem, difference, guidance = pre.explain_issue(
            "unrepresentable", "", "Japanese", "Heart 💖"
        )

        self.assertIn("cannot store", problem)
        self.assertIn("U+1F496", difference)
        self.assertIn("Replace", guidance)

    def test_issue_summary_omits_raw_diagnostic_and_translation_dump(self):
        issue = pre.InjectIssue(
            json_file="Map001.mps.json",
            kind="code_mismatch",
            locator="event 2 page 0 cmd 4 str 0",
            message="very long raw diagnostic",
            text="very long translated line",
            problem="Translation is missing control codes",
            difference="Missing: `\\^`\nExtra: none",
            guidance="Copy the missing code.",
        )

        self.assertEqual(
            issue.summary(),
            "Translation is missing control codes\n"
            "Map001.mps.json · event 2 page 0 cmd 4 str 0",
        )
        self.assertNotIn("diagnostic", issue.detail())
        self.assertIn("Missing: `\\^`", issue.detail())

    def test_ai_repair_manifest_includes_every_issue_and_marks_font_review(self):
        issues = [
            pre.InjectIssue(
                json_file="Map001.mps.json",
                kind="code_mismatch",
                locator="event 2 page 0 cmd 4 str 0",
                message="raw",
                problem="Translation is missing control codes",
                difference="Missing: `\\^`\nExtra: none",
                guidance="Copy the missing code.",
            ),
            pre.InjectIssue(
                json_file="SampleMapA.mps.json",
                kind="code_mismatch",
                locator="event 5 page 0 cmd 0 str 0",
                message="raw",
                problem="Font-size codes differ from the source",
                difference="Missing: none\nExtra: `\\f[10]`",
                guidance="Keep intentional wrapping.",
            ),
        ]

        manifest = pre.format_ai_repair_issues(issues)

        self.assertIn("1. [FIX] Map001.mps.json", manifest)
        self.assertIn("2. [REVIEW FONT-ONLY] SampleMapA.mps.json", manifest)
        self.assertIn("event 2 page 0 cmd 4 str 0", manifest)
        self.assertIn("event 5 page 0 cmd 0 str 0", manifest)
        self.assertIn("Missing: `\\^`", manifest)
        self.assertNotIn("raw", manifest)

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

    def test_repair_inject_json_allows_safe_unclosed_source_code_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Map001_1.mps.json"
            doc = {
                "kind": "map",
                "scenes": [
                    {
                        "event": 12,
                        "page": 2,
                        "lines": [
                            {
                                "cmd": 172,
                                "str": 0,
                                "source": "A\\i[200\nB\\i[31]",
                                "text": "English\\i[200]\nMore\\i[31]",
                            }
                        ],
                    }
                ],
            }
            original = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
            path.write_text(original, encoding="utf-8")

            repaired_path, safe_code_drift = wi.repair_inject_json(path)

            self.assertEqual(repaired_path, path)
            self.assertTrue(safe_code_drift)
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

if __name__ == "__main__":
    unittest.main()
