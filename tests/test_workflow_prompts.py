"""Regression tests for concise, interactive plugin translation prompts."""

import json
import re
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from scripts.score_rpgmaker_qa_benchmark import (
    load_oracle,
    main as score_benchmark_main,
    score_run,
    validate_fixture,
)

from util.skills import (
    RPGMAKER_QA_FOCUSES,
    load_clipboard_skill,
    load_project_setup,
    load_rpgmaker_qa_skill,
)
from util.rpgmaker_markers import SUPPORTED_CODE408_MARKERS


class WorkflowTranslationPromptTests(unittest.TestCase):
    def _assert_interactive_in_place_prompt(self, prompt: str):
        lowered = prompt.casefold()
        self.assertIn("do not edit anything yet", lowered)
        self.assertIn("ask one focused question", lowered)
        self.assertIn("offer to translate all safe items yourself", lowered)
        self.assertIn("edit approved", lowered)
        self.assertIn("never paste or repost an entire", lowered)
        self.assertIn("minimal unified diff", lowered)
        self.assertNotIn("complete replacement", lowered)
        self.assertNotIn("full translated file", lowered)

    def test_script_prompts_require_scoped_approval_before_editing(self):
        cases = (
            ("plugin_translation.md", "js/plugins.js"),
            ("ace_script_translation.md", "ace_json/scripts/*.rb"),
        )
        for name, project_scope in cases:
            with self.subTest(name=name):
                prompt = load_clipboard_skill(name)
                self._assert_interactive_in_place_prompt(prompt)
                self.assertIn(project_scope, prompt)

    def _assert_rpgmaker_qa_benchmark(self):
        fixture_root = (
            Path(__file__).parent / "fixtures" / "rpgmaker_qa_benchmark"
        )
        oracle = load_oracle(fixture_root / "oracle.json")
        validate_fixture(oracle, fixture_root)
        perfect_run = {
            "schema_version": 1,
            "benchmark_id": "rpgmaker-qa-v1",
            "oracle_sha256": oracle["oracle_sha256"],
            "artifact_sha256": oracle["artifact_sha256"],
            "reviewed_clusters_by_focus": {
                "dialogue": [
                    "cluster-bullet",
                    "cluster-control-argument",
                    "cluster-control-reset",
                    "cluster-polarity",
                    "cluster-referent",
                    "cluster-referent-linked",
                    "cluster-source-residue",
                    "cluster-threshold-only",
                    "cluster-visible-number",
                    "cluster-wordplay-adaptation",
                ],
                "database": [
                    "cluster-glossary-decoy",
                    "cluster-glossary-item",
                    "cluster-glossary-related-name",
                    "cluster-item-description",
                ],
            },
            "findings": [
                {
                    "locator": "Map001.json#/events/1/pages/0/list/0/parameters/0",
                    "focus": "dialogue",
                    "family_id": "F-REFERENT-001",
                    "severity": "High",
                    "correction": "That professor is him.",
                },
                {
                    "locator": "Map001.json#/events/1/pages/0/list/1/parameters/0",
                    "focus": "dialogue",
                    "family_id": "F-REFERENT-001",
                    "severity": "High",
                    "correction": "He is the professor.",
                },
                {
                    "locator": "Map001.json#/events/1/pages/0/list/2/parameters/0",
                    "focus": "dialogue",
                    "family_id": "F-POLARITY-001",
                    "severity": "High",
                    "correction": "The door won't open.",
                },
                {
                    "locator": "Map001.json#/events/1/pages/0/list/3/parameters/0",
                    "focus": "dialogue",
                    "family_id": "F-NUMBER-001",
                    "severity": "High",
                    "correction": "Use three herbs.",
                },
                {
                    "locator": "Map001.json#/events/1/pages/0/list/4/parameters/0",
                    "focus": "dialogue",
                    "family_id": "F-RESIDUE-001",
                    "severity": "High",
                    "correction": "Run!",
                },
                {
                    "locator": "Map001.json#/events/1/pages/0/list/5/parameters/0",
                    "focus": "dialogue",
                    "family_id": "F-CONTROL-001",
                    "severity": "High",
                    "correction": "\\C[2]Danger\\C[0]",
                },
                {
                    "locator": "Map001.json#/events/1/pages/0/list/6/parameters/0",
                    "focus": "dialogue",
                    "family_id": "F-BULLET-001",
                    "severity": "Medium",
                    "correction": "• Open the journal",
                },
                {
                    "locator": "Items.json#/1/name",
                    "focus": "database",
                    "family_id": "F-GLOSSARY-001",
                    "severity": "High",
                    "correction": "Astral Key",
                },
            ],
            "run_metadata": {
                "elapsed_seconds": 10,
                "input_tokens": 100,
                "output_tokens": 20,
            },
        }
        perfect_score = score_run(oracle, perfect_run)
        self.assertTrue(perfect_score["quality_pass"])
        self.assertEqual(perfect_score["locator_f1"], 1.0)
        self.assertEqual(perfect_score["propagation_completeness"], 1.0)
        self.assertEqual(perfect_score["coverage"], 1.0)
        self.assertEqual(perfect_score["expected_cluster_count"], 14)
        self.assertEqual(perfect_score["clusters_per_hour"], 5040.0)

        missed_run = {**perfect_run, "findings": perfect_run["findings"][1:]}
        missed_score = score_run(oracle, missed_run)
        self.assertFalse(missed_score["quality_pass"])
        self.assertLess(missed_score["locator_recall"], 1.0)
        self.assertLess(missed_score["propagation_completeness"], 1.0)

        threshold_case = next(
            case for case in oracle["cases"]
            if "threshold-only" in case.get("tags", [])
        )
        false_positive_run = {
            **perfect_run,
            "findings": [
                *perfect_run["findings"],
                {
                    "locator": threshold_case["locator"],
                    "focus": "dialogue",
                    "family_id": "F-SPURIOUS-OVERFLOW",
                    "severity": "Medium",
                    "correction": "Unnecessary rewrap.",
                },
            ],
        }
        false_positive_score = score_run(oracle, false_positive_run)
        self.assertFalse(false_positive_score["quality_pass"])
        self.assertLess(false_positive_score["locator_precision"], 1.0)
        self.assertEqual(
            false_positive_score["threshold_only_false_positive_count"], 1
        )

        wrong_family_run = {
            **perfect_run,
            "findings": [
                {**perfect_run["findings"][0], "family_id": "F-WRONG"},
                *perfect_run["findings"][1:],
            ],
        }
        wrong_family_score = score_run(oracle, wrong_family_run)
        self.assertFalse(wrong_family_score["quality_pass"])
        self.assertLess(wrong_family_score["family_precision"], 1.0)
        self.assertLess(
            wrong_family_score["locator_family_label_accuracy"], 1.0
        )

        wrong_correction_run = {
            **perfect_run,
            "findings": [
                {**perfect_run["findings"][0], "correction": "Wrong."},
                *perfect_run["findings"][1:],
            ],
        }
        wrong_correction_score = score_run(oracle, wrong_correction_run)
        self.assertFalse(wrong_correction_score["quality_pass"])
        self.assertLess(wrong_correction_score["correction_exactness"], 1.0)

        wrong_focus_run = {
            **perfect_run,
            "findings": [
                {**perfect_run["findings"][0], "focus": "database"},
                *perfect_run["findings"][1:],
            ],
        }
        self.assertFalse(score_run(oracle, wrong_focus_run)["quality_pass"])

        wrong_severity_run = {
            **perfect_run,
            "findings": [
                {**perfect_run["findings"][0], "severity": "Medium"},
                *perfect_run["findings"][1:],
            ],
        }
        self.assertFalse(score_run(oracle, wrong_severity_run)["quality_pass"])

        incomplete_run = {
            **perfect_run,
            "reviewed_clusters_by_focus": {
                **perfect_run["reviewed_clusters_by_focus"],
                "database": perfect_run["reviewed_clusters_by_focus"]["database"][:-1],
            },
        }
        incomplete_score = score_run(oracle, incomplete_run)
        self.assertFalse(incomplete_score["quality_pass"])
        self.assertLess(incomplete_score["coverage"], 1.0)

        invalid_metadata_run = {
            **perfect_run,
            "run_metadata": {"elapsed_seconds": float("nan")},
        }
        with self.assertRaises(ValueError):
            score_run(oracle, invalid_metadata_run)
        with self.assertRaises(ValueError):
            score_run(oracle, {**perfect_run, "schema_version": True})

        with tempfile.TemporaryDirectory() as raw:
            run_path = Path(raw) / "missed-run.json"
            run_path.write_text(json.dumps(missed_run), encoding="utf-8")
            with (
                patch("sys.argv", [
                    "score_rpgmaker_qa_benchmark.py",
                    str(fixture_root / "oracle.json"),
                    str(run_path),
                ]),
                redirect_stdout(StringIO()),
            ):
                self.assertEqual(score_benchmark_main(), 1)

    def test_rpgmaker_qa_prompt_and_benchmark_contract(self):
        self.assertEqual(
            [focus for focus, _label in RPGMAKER_QA_FOCUSES],
            ["database", "risky-codes", "dialogue", "release"],
        )
        expected_contract = {
            "focus-isolation",
            "exhaustive-coverage",
            "approval-before-edit",
            "preserve-original",
            "durable-artifacts",
            "fresh-shard-workers",
            "immutable-context-pack",
            "indexed-mechanical-preprocessing",
            "affected-identity-revalidation",
            "batched-registry-epochs",
            "parallel-component-propagation",
            "adversarial-closing-validation",
            "semantic-first-layout-last",
            "threshold-only-nonfinding",
            "family-consistency-validation",
            "offline-quality-benchmark",
            "throughput-evidence",
            "coordinator-only-apply",
            "post-fix-regression",
        }
        focus_signatures = {
            "dialogue": "Audit only event commands 101, 102, 401, and 405",
            "database": "Audit `_original` leaves in these canonical database files",
            "risky-codes": "Audit translated or translation-sensitive event commands",
            "release": "Inventory every `_original` leaf in every JSON file",
        }
        for focus, _label in RPGMAKER_QA_FOCUSES:
            with self.subTest(focus=focus):
                prompt = load_rpgmaker_qa_skill(focus)
                lowered = prompt.casefold()
                contract = re.search(
                    r"<!-- qa-contract:rpgmaker-qa-v3\s+(.*?)-->",
                    prompt,
                    re.DOTALL,
                )
                self.assertIsNotNone(contract)
                self.assertEqual(set(contract.group(1).split()), expected_contract)
                self.assertIn("do not edit until the user approves", lowered)
                self.assertIn("never modify or remove `_original`", lowered)
                self.assertIn(focus_signatures[focus], prompt)
                for other_focus, signature in focus_signatures.items():
                    if other_focus != focus:
                        self.assertNotIn(signature, prompt)
                for placeholder in (
                    "{{GAME_DATA_FOLDER}}",
                    "{{GAME_ROOT}}",
                    "{{VOCAB_FILE}}",
                    "{{QUIRKS_FILE}}",
                    "{{GAME_SKILL_FILE}}",
                    "{{GAME_SKILLS_FOLDER}}",
                ):
                    self.assertIn(placeholder, prompt)
                if focus == "dialogue":
                    self.assertIn("complete - exhaustive", lowered)
                    self.assertIn("dialogue-narrative-wordplay-v1", prompt)
                if focus == "database":
                    self.assertIn("zero unreviewed clusters", lowered)
                if focus == "release":
                    self.assertIn("dialogue-narrative-wordplay-v1", prompt)
                    self.assertIn("context fingerprint matching", lowered)
        with self.assertRaises(ValueError):
            load_rpgmaker_qa_skill("everything")
        self._assert_rpgmaker_qa_benchmark()

    def test_rpgmaker_project_setup_covers_optional_text_and_widths(self):
        prompt = load_project_setup("rpgmaker")
        lowered = prompt.casefold()

        self.assertIn("code408 : enable|skip", lowered)
        self.assertIn("dialogue : width=", lowered)
        self.assertIn("facewidth=<code-101 face width>", lowered)
        self.assertIn("list/help: listwidth=", lowered)
        self.assertIn("notes    : notewidth=", lowered)
        self.assertIn("only fills an empty code-101 param[4]", lowered)
        self.assertIn("include displayed comment text (code 408)", lowered)
        self.assertIn("recurring humor mode", lowered)
        self.assertIn("one-off jokes", lowered)
        self.assertNotIn("{{SUPPORTED_CODE408_MARKERS}}", prompt)
        for marker in SUPPORTED_CODE408_MARKERS:
            self.assertIn(marker, prompt)

        wolf_prompt = load_project_setup("wolf")
        wolf_lowered = wolf_prompt.casefold()
        self.assertNotIn("code408 : enable|skip", wolf_lowered)
        self.assertIn("recurring humor mode", wolf_lowered)
        self.assertIn("one-off jokes", wolf_lowered)

        system_prompt = load_clipboard_skill("system.md").casefold()
        self.assertIn("preserve established lore facts", system_prompt)
        self.assertIn("natural english adaptation", system_prompt)

    def test_wrap_prompt_accounts_for_code101_faces_and_font_changes(self):
        prompt = load_clipboard_skill("wrap_config.md").casefold()
        self.assertIn("facewidth", prompt)
        self.assertIn("non-empty parameter 0", prompt)
        self.assertIn("plugin portraits", prompt)
        self.assertIn("visible-row limit", prompt)

    def test_image_translation_prompt_ends_skips_with_recovery_options(self):
        prompt = load_clipboard_skill("image_translation.md")

        self.assertIn("### Skipped / review items", prompt)
        self.assertIn("literal final section of the user-facing response", prompt)
        self.assertIn("Try it anyway", prompt)
        self.assertIn("Use generative AI", prompt)
        self.assertIn("Manual artist review", prompt)

    def test_wolf_precheck_repair_skill_is_scoped_and_actionable(self):
        prompt = load_clipboard_skill("wolf_precheck_repair.md")

        for placeholder in ("{{TRANSLATED_DIR}}", "{{GAME_ROOT}}", "{{ISSUES}}"):
            self.assertIn(placeholder, prompt)
        self.assertIn("Edit only the affected `text` value", prompt)
        self.assertIn("Never edit `source`", prompt)

    def test_clipboard_skill_loader_rejects_paths(self):
        with self.assertRaises(ValueError):
            load_clipboard_skill("../system.md")


if __name__ == "__main__":
    unittest.main()
