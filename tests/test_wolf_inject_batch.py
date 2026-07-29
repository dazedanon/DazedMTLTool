#!/usr/bin/env python3
"""Unit tests for util/wolfdawn/inject.py orchestration."""

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

from util.wolfdawn import inject as wi  # noqa: E402


class ListInjectableTests(unittest.TestCase):
    def test_lists_translated_files_with_manifest_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            translated = root / "translated"
            translated.mkdir()
            (translated / "names.json").write_text("{}", encoding="utf-8")
            (translated / "Map001.mps.json").write_text("{}", encoding="utf-8")
            (translated / "orphan.json").write_text("{}", encoding="utf-8")
            entries = [
                {"json": "names.json", "kind": "names", "base": "/data"},
                {"json": "Map001.mps.json", "kind": "map", "base": "/data/Map001.mps"},
            ]
            self.assertEqual(
                wi.list_injectable(translated, entries),
                ["Map001.mps.json", "names.json"],
            )


class InjectOrderTests(unittest.TestCase):
    def test_names_runs_before_strings(self):
        calls: list[str] = []
        string_bases: list[str] = []

        def fake_names(*_a, **_k):
            calls.append("names")
            return mock.Mock(
                ok=True,
                returncode=0,
                stdout="applied 2 name change(s) (0 drifted/unmatched)",
                stderr="",
            )

        def fake_strings(edited_json, base, output, **_k):
            if not _k.get("dry_run"):
                calls.append("strings")
                string_bases.append(str(base))
            return mock.Mock(
                ok=True,
                returncode=0,
                stdout="applied 1 translation(s) (0 drifted)",
                stderr="",
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            translated = root / "translated"
            originals = root / "originals"
            data = root / "data"
            translated.mkdir()
            originals.mkdir()
            data.mkdir()
            (translated / "names.json").write_text("{}", encoding="utf-8")
            (translated / "Map001.mps.json").write_text(
                '{"kind":"map","scenes":[]}', encoding="utf-8"
            )
            map_live = data / "Map001.mps"
            map_orig = originals / "Map001.mps"
            map_live.write_bytes(b"live")
            map_orig.write_bytes(b"orig")

            entries = [
                {"json": "names.json", "kind": "names", "base": str(data)},
                {"json": "Map001.mps.json", "kind": "map", "base": str(map_live)},
            ]

            def would_apply_counts():
                yield 1  # prepare: after restore
                yield 1  # _inject_names: preflight
                yield 0  # _inject_names: post-check

            counts = would_apply_counts()

            def next_would_apply(*_a, **_k):
                return next(counts, 0)

            with mock.patch.object(wi.wolf_originals, "names_inject_would_apply", side_effect=next_would_apply), \
                 mock.patch.object(wi.wolfdawn, "names_inject", side_effect=fake_names), \
                 mock.patch.object(wi.wolfdawn, "strings_inject", side_effect=fake_strings):
                report = wi.inject_selected(
                    ["Map001.mps.json", wi.NAMES_JSON],
                    manifest_entries=entries,
                    data_dir=data,
                    originals_dir=originals,
                    translated_dir=translated,
                    game_root=data.parent,
                )

            self.assertEqual(calls, ["names", "strings"])
            self.assertTrue(report.ok)
            self.assertEqual(len(report.succeeded), 2)
            # After names-inject, strings must use live Data/ as --base so
            # name-only fields are not rebuilt from pristine Japanese originals.
            self.assertEqual(string_bases, [str(map_live)])

    def test_strings_alone_use_pristine_original_base(self):
        string_bases: list[str] = []
        string_drift: list[bool] = []

        def fake_strings(edited_json, base, output, **kwargs):
            if not kwargs.get("dry_run"):
                string_bases.append(str(base))
                string_drift.append(bool(kwargs.get("allow_code_drift")))
            return mock.Mock(
                ok=True,
                returncode=0,
                stdout="applied 1 translation(s) (0 drifted)",
                stderr="",
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            translated = root / "translated"
            originals = root / "originals"
            data = root / "data"
            translated.mkdir()
            originals.mkdir()
            data.mkdir()
            (translated / "Map001.mps.json").write_text(
                '{"kind":"map","scenes":[]}', encoding="utf-8"
            )
            map_live = data / "Map001.mps"
            map_orig = originals / "Map001.mps"
            map_live.write_bytes(b"live")
            map_orig.write_bytes(b"orig")
            entries = [
                {"json": "Map001.mps.json", "kind": "map", "base": str(map_live)},
            ]
            with mock.patch.object(wi.wolfdawn, "strings_inject", side_effect=fake_strings):
                report = wi.inject_selected(
                    ["Map001.mps.json"],
                    manifest_entries=entries,
                    data_dir=data,
                    originals_dir=originals,
                    translated_dir=translated,
                    game_root=data.parent,
                )
            self.assertTrue(report.ok)
            self.assertEqual(string_bases, [str(map_orig)])
            self.assertEqual(string_drift, [False])

    def test_strings_auto_allow_code_drift_for_font_size(self):
        string_drift: list[bool] = []

        def fake_strings(edited_json, base, output, **kwargs):
            if not kwargs.get("dry_run"):
                string_drift.append(bool(kwargs.get("allow_code_drift")))
            return mock.Mock(
                ok=True,
                returncode=0,
                stdout="applied 1 translation(s) (0 drifted)",
                stderr="",
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            translated = root / "translated"
            originals = root / "originals"
            data = root / "data"
            translated.mkdir()
            originals.mkdir()
            data.mkdir()
            doc = {
                "kind": "db",
                "groups": [
                    {
                        "typeName": "噂",
                        "lines": [
                            {
                                "source": r"\c[21]\f[20]娼館\c[19]\f[18]",
                                "text": r"\f[14]\c[21]\f[16]Brothel\c[19]\f[14]",
                            }
                        ],
                    }
                ],
            }
            (translated / "DataBase.project.json").write_text(
                json.dumps(doc, ensure_ascii=False), encoding="utf-8"
            )
            proj_live = data / "DataBase.project"
            proj_orig = originals / "DataBase.project"
            proj_live.write_bytes(b"live")
            proj_orig.write_bytes(b"orig")
            (data / "DataBase.dat").write_bytes(b"live-dat")
            (originals / "DataBase.dat").write_bytes(b"orig-dat")
            entries = [
                {
                    "json": "DataBase.project.json",
                    "kind": "db",
                    "base": str(proj_live),
                },
            ]
            with mock.patch.object(wi.wolfdawn, "strings_inject", side_effect=fake_strings):
                report = wi.inject_selected(
                    ["DataBase.project.json"],
                    manifest_entries=entries,
                    data_dir=data,
                    originals_dir=originals,
                    translated_dir=translated,
                    game_root=data.parent,
                    allow_code_drift=False,
                )
            self.assertTrue(report.ok)
            self.assertEqual(string_drift, [True])

    def test_unedited_names_are_a_successful_no_op(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            translated = root / "translated"
            data = root / "Data"
            originals = root / "originals"
            translated.mkdir()
            data.mkdir()
            (translated / "names.json").write_text(
                json.dumps(
                    {
                        "kind": "names",
                        "names": [{"source": "Day", "text": "Day"}],
                    }
                ),
                encoding="utf-8",
            )
            entries = [
                {"json": "names.json", "kind": "names", "base": str(data)}
            ]
            logs: list[str] = []

            with mock.patch.object(
                wi.wolf_originals,
                "names_inject_would_apply",
                side_effect=AssertionError("no-op names must not run WolfDawn"),
            ):
                report = wi.inject_selected(
                    ["names.json"],
                    manifest_entries=entries,
                    data_dir=data,
                    originals_dir=originals,
                    translated_dir=translated,
                    game_root=root,
                    log_fn=logs.append,
                )

            self.assertTrue(report.ok)
            self.assertEqual(report.files[0].summary, "no changes needed")
            self.assertEqual(logs, ["  ✓ names.json: no changes needed"])

    def test_stale_string_sources_are_rebased_before_injection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            translated = root / "translated"
            data = root / "Data"
            originals = root / "originals"
            translated.mkdir()
            data.mkdir()
            originals.mkdir()
            edited_path = translated / "CommonEvent.dat.json"
            edited_path.write_text(
                json.dumps(
                    {
                        "kind": "common",
                        "events": [
                            {"lines": [{"source": "Day", "text": "Moved Day"}]}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            live = data / "CommonEvent.dat"
            pristine = originals / "CommonEvent.dat"
            live.write_bytes(b"live")
            pristine.write_bytes(b"pristine")
            entries = [
                {
                    "json": edited_path.name,
                    "kind": "common",
                    "base": str(live),
                }
            ]
            calls: list[tuple[bool, str]] = []

            def fake_inject(edited_json, _base, _output, **kwargs):
                source = json.loads(Path(edited_json).read_text(encoding="utf-8"))[
                    "events"
                ][0]["lines"][0]["source"]
                dry_run = bool(kwargs.get("dry_run"))
                calls.append((dry_run, source))
                if source == "Day":
                    output = "would apply 0 translation(s) (1 drifted)"
                elif dry_run:
                    output = "would apply 1 translation(s) (0 drifted)"
                else:
                    output = "applied 1 translation(s) (0 drifted)"
                return mock.Mock(ok=True, returncode=0, stdout=output, stderr="")

            def fake_extract(_base, output, **_kwargs):
                Path(output).write_text(
                    json.dumps(
                        {
                            "kind": "common",
                            "events": [
                                {
                                    "lines": [
                                        {"source": "日目", "text": "日目"}
                                    ]
                                }
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
                return mock.Mock(ok=True, returncode=0, stdout="", stderr="")

            logs: list[str] = []
            with (
                mock.patch.object(
                    wi.wolfdawn, "strings_inject", side_effect=fake_inject
                ),
                mock.patch.object(
                    wi.wolfdawn, "strings_extract", side_effect=fake_extract
                ),
            ):
                report = wi.inject_selected(
                    [edited_path.name],
                    manifest_entries=entries,
                    data_dir=data,
                    originals_dir=originals,
                    translated_dir=translated,
                    game_root=root,
                    log_fn=logs.append,
                )

            self.assertTrue(report.ok)
            self.assertEqual(
                calls,
                [(True, "Day"), (True, "日目"), (False, "日目")],
            )
            repaired = json.loads(edited_path.read_text(encoding="utf-8"))
            line = repaired["events"][0]["lines"][0]
            self.assertEqual(line, {"source": "日目", "text": "Moved Day"})
            self.assertTrue(any("refreshed 1 stale source" in log for log in logs))

    def test_names_result_mentions_safety_skips(self):
        res = mock.Mock(
            ok=True,
            returncode=0,
            stdout=(
                "would apply 10 name change(s) (0 drifted/unmatched)\n"
                "WARNING: 46 line(s) left UNTRANSLATED by a safety guard - "
                "46 control-code mismatch, 0 not encodable\n"
            ),
            stderr="",
        )
        # parse_names_inject_counts needs "applied N name change"
        res.stdout = (
            "applied 10 name change(s) (0 drifted/unmatched)\n"
            "WARNING: 46 line(s) left UNTRANSLATED by a safety guard - "
            "46 control-code mismatch, 0 not encodable\n"
        )
        result = wi._interpret_names_result("names.json", res)
        self.assertTrue(result.success)
        self.assertIn("46 skipped by safety guard", result.summary)
        self.assertEqual(result.safety_skipped, 46)


class ReportDialogTests(unittest.TestCase):
    def test_success_has_no_dialog(self):
        report = wi.InjectReport(
            files=[
                wi.FileInjectResult("a.json", True, "applied 3 line(s)"),
                wi.FileInjectResult("b.json", True, "no changes needed"),
            ],
        )
        self.assertIsNone(wi.format_report_dialog(report))
        self.assertEqual(wi.format_report_status(report), "Inject complete: 2 file(s).")

    def test_failure_dialog_lists_only_problems(self):
        report = wi.InjectReport(
            files=[
                wi.FileInjectResult("a.json", True, "applied 3 line(s)"),
                wi.FileInjectResult("b.json", False, "0 applied, 2 drifted", detail="stderr"),
            ],
            sync_failures=[("c.json", "permission denied")],
        )
        dialog = wi.format_report_dialog(report)
        self.assertIsNotNone(dialog)
        title, body = dialog
        self.assertIn("errors", title)
        self.assertIn("✗ b.json", body)
        self.assertIn("✗ sync c.json", body)
        self.assertNotIn("✓ a.json", body)
        self.assertIn("1 file(s) succeeded", body)
        self.assertEqual(
            wi.format_report_status(report),
            "Inject: 1 ok, 2 failed (see dialog).",
        )

    def test_partial_safety_success_gets_warning_dialog_and_status(self):
        report = wi.InjectReport(
            files=[
                wi.FileInjectResult(
                    "CommonEvent.dat.json",
                    True,
                    "applied 1063 line(s) (2 skipped by safety guard)",
                    applied=1063,
                    safety_skipped=2,
                    safety_details=[
                        "event 74 cmd 200 str 0 — control-code mismatch",
                        "event 245 cmd 31 str 0 — control-code mismatch",
                    ],
                )
            ]
        )

        dialog = wi.format_report_dialog(report)

        self.assertIsNotNone(dialog)
        title, body = dialog
        self.assertEqual(title, "Inject completed with warnings")
        self.assertIn("event 74 cmd 200 str 0", body)
        self.assertIn("event 245 cmd 31 str 0", body)
        self.assertIn("Step 7 Check", body)
        self.assertEqual(
            wi.format_report_status(report),
            (
                "⚠ Inject completed with warnings: 1 file(s), "
                "2 line(s) skipped (see dialog)."
            ),
        )


if __name__ == "__main__":
    unittest.main()
