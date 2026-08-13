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
    build_known_speakers_context,
    ctx,
    load_clipboard_skill,
    load_project_setup,
    load_rpgmaker_qa_skill,
    load_walkthrough_skill,
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
            ["release", "database", "risky-codes", "dialogue"],
        )
        expected_contract = {
            "app-owned-inventory",
            "immutable-review-bundles",
            "scene-affine-semantic-screen",
            "evidence-preserving-deep-handoff",
            "motif-family-receipts",
            "selective-risk-escalation",
            "validated-checkpoints",
            "honest-global-coverage",
            "grouped-finding-families",
            "motif-finding-attribution",
            "final-consistency-audit",
            "final-editorial-pass",
            "subjective-precision-gate",
            "ignored-receipt-workspace",
            "clean-release-auto-approval",
            "preserve-original",
            "atomic-apply",
            "post-fix-regression",
            "no-provider-api",
        }
        focus_signatures = {
            "dialogue": "Dialogue focus. Review each prepared scene",
            "database": "Database focus. The local manifest owns",
            "risky-codes": "Risky event-code focus. The local manifest owns",
            "release": "Coverage and release focus. The local manifest inventories",
        }
        for focus, _label in RPGMAKER_QA_FOCUSES:
            with self.subTest(focus=focus):
                prompt = load_rpgmaker_qa_skill(focus)
                lowered = prompt.casefold()
                contract = re.search(
                    r"<!-- qa-contract:rpgmaker-qa-local-v9\s+(.*?)-->",
                    prompt,
                    re.DOTALL,
                )
                self.assertIsNotNone(contract)
                self.assertEqual(set(contract.group(1).split()), expected_contract)
                self.assertIn("automatically create the all-findings correction map", lowered)
                self.assertIn("do not make the user approve", lowered)
                self.assertIn("targeted reruns still require approval", lowered)
                self.assertIn("never modify or remove", lowered)
                self.assertIn("`_original`", lowered)
                self.assertIn(".dazedtl/qa-receipts/", lowered)
                self.assertIn("never place `.qa-*.json`", lowered)
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
                    "{{QA_TOOL_ROOT}}",
                    "{{QA_FOCUS}}",
                ):
                    self.assertIn(placeholder, prompt)
                self.assertIn("scripts/rpgmaker_qa.py", prompt)
                self.assertIn("do not call a model-provider api", lowered)
                self.assertIn("do not create a replacement manifest", lowered)
                self.assertIn("the screen stage keeps every dialogue", lowered)
                self.assertIn("one worker only", lowered)
                self.assertIn("who performs each action", lowered)
                self.assertIn("pronouns and relationships", lowered)
                self.assertIn("third-person pronouns", lowered)
                self.assertIn("one representative scene per speaker", lowered)
                self.assertIn("ordinary safe repetition remains deduplicated", lowered)
                self.assertIn("actionable `fluency`, `voice`, and `wordplay`", lowered)
                self.assertIn("reviewer who did not author", lowered)
                self.assertIn("not merely preferred wording", lowered)
                self.assertIn("family receipt even when preserved", lowered)
                self.assertIn("unrelated defects", lowered)
                self.assertIn("deterministic consistency audit", lowered)
                self.assertIn("complete scene", lowered)
                self.assertIn("rebuild-deep", lowered)
                self.assertIn("themselves mandate deep review", lowered)
                self.assertIn("correction-map, dry-run, atomic-apply", lowered)
                if focus == "dialogue":
                    self.assertIn("related evidence supplied in the", lowered)
                if focus == "release":
                    self.assertIn("exhaustive screen and deep-review denominators", lowered)
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
        self.assertIn("optional reference translations", lowered)
        self.assertIn(".dazedtl/reference-overlaps.json", lowered)
        self.assertIn("advisory", lowered)
        self.assertIn("phase 1 — baseline setup", lowered)
        self.assertIn("phase 2 — global localization investigation", lowered)
        self.assertIn("localization investigation", lowered)
        self.assertIn("exactly three fresh subagents concurrently", lowered)
        self.assertIn("no forked conversation context", lowered)
        self.assertIn('`fork_turns="none"`', lowered)
        self.assertIn("never show a worker either of the other", lowered)
        self.assertIn("do not synthesize or begin coordinator verification", lowered)
        self.assertIn("only the coordinator may confirm families", lowered)
        self.assertIn("inspect every distinct resolved value", lowered)
        self.assertIn("do not force one english frame", lowered)
        self.assertIn("corpus minority", lowered)
        self.assertIn("starting guidance as hypotheses, not evidence", lowered)
        self.assertIn("audit anchored quirks", lowered)
        self.assertIn("player-visible and release-reachable", lowered)
        self.assertIn("ids alone are", lowered)
        self.assertIn("total family scope", lowered)
        self.assertIn("actionable target count", lowered)
        self.assertIn("confirmed actionable defects", lowered)
        self.assertIn("verified-clean families", lowered)
        self.assertIn("never count these as inconsistencies", lowered)
        self.assertIn("directly update these files without asking for approval", lowered)
        self.assertIn(".dazedtl/glossary.txt", lowered)
        self.assertIn(".dazedtl/skills/quirks.md", lowered)
        self.assertIn(".dazedtl/skills/game.md", lowered)
        self.assertIn("preserve the auto-appended base", lowered)
        self.assertIn("guidance files updated", lowered)
        self.assertIn("do not tell the user to copy or paste", lowered)
        self.assertNotIn("copy/paste into dazedtl", lowered)
        self.assertNotIn("{{localization_investigation_phase}}", lowered)
        self.assertNotIn("{{SUPPORTED_CODE408_MARKERS}}", prompt)
        for marker in SUPPORTED_CODE408_MARKERS:
            self.assertIn(marker, prompt)

        wolf_prompt = load_project_setup("wolf")
        wolf_lowered = wolf_prompt.casefold()
        self.assertNotIn("code408 : enable|skip", wolf_lowered)
        self.assertIn("recurring humor mode", wolf_lowered)
        self.assertIn("one-off jokes", wolf_lowered)
        self.assertIn("phase 2 — global localization investigation", wolf_lowered)
        self.assertNotIn("{{localization_investigation_phase}}", wolf_lowered)

        investigation = load_clipboard_skill("localization_investigation.md").casefold()
        self.assertIn("standalone skill reruns", investigation)
        self.assertIn("phase 2 — global localization investigation", investigation)
        self.assertEqual(investigation.count("<!-- investigation-phase -->"), 1)
        self.assertEqual(investigation.count("<!-- /investigation-phase -->"), 1)
        self.assertIn("do not edit runtime game data or translated text", investigation)
        self.assertIn("repeated scene structures", investigation)
        self.assertIn("exactly three fresh subagents concurrently", investigation)
        self.assertIn("no forked conversation context", investigation)
        self.assertIn('`fork_turns="none"`', investigation)
        self.assertIn("never show a worker either of the other", investigation)
        self.assertIn("do not synthesize or begin coordinator verification", investigation)
        self.assertIn("keep the guidance files unchanged", investigation)
        self.assertIn("only the coordinator may confirm families", investigation)
        self.assertIn("inspect every distinct resolved value", investigation)
        self.assertIn("do not force one english frame", investigation)
        self.assertIn("corpus minority", investigation)
        self.assertIn("starting guidance as hypotheses, not evidence", investigation)
        self.assertIn("audit anchored quirks", investigation)
        self.assertIn("player-visible and release-reachable", investigation)
        self.assertIn("ids alone are", investigation)
        self.assertIn("alone is not proof", investigation)
        self.assertIn("executive total sum actionable targets only", investigation)
        self.assertIn("discovery agreement", investigation)
        self.assertIn("translation quirks updates applied", investigation)
        self.assertIn("glossary updates applied", investigation)
        self.assertIn("directly apply confirmed", investigation)
        self.assertIn("do not wait for approval", investigation)
        self.assertIn("preserve the auto-appended base separator", investigation)
        self.assertNotIn("apply approved amendments manually", investigation)
        self.assertIn("correction families", investigation)
        self.assertIn("confirmed actionable defects", investigation)
        self.assertIn("verified-clean families", investigation)
        self.assertIn("never count a verified-clean family", investigation)
        self.assertIn("research backlog", investigation)
        self.assertIn("coverage", investigation)

        setup_source = load_clipboard_skill("project_setup.md")
        self.assertEqual(setup_source.count("{{LOCALIZATION_INVESTIGATION_PHASE}}"), 1)

        system_prompt = load_clipboard_skill("system.md").casefold()
        self.assertIn("preserve established lore facts", system_prompt)
        self.assertIn("natural english adaptation", system_prompt)

    def test_collected_speaker_targets_remain_provisional_until_setup(self):
        context = build_known_speakers_context(
            "rpgmaker", [("サン", "Sun"), ("サングイス", "Sanguis")]
        )
        prompt = load_project_setup("rpgmaker", prepend=context).casefold()

        self.assertIn("サン (sun)", prompt)
        self.assertIn("context-limited machine guesses", prompt)
        self.assertIn("provisional, not approved glossary spellings", prompt)
        self.assertIn("replace any unsupported guess", prompt)
        self.assertIn("longer related forms", prompt)
        self.assertIn("explicitly curated project glossary decisions", prompt)
        self.assertNotIn("prefer entries for these names", prompt)

        speaker_instruction = ctx("names.speaker", language="English").casefold()
        self.assertIn("for a proper name, transliterate it", speaker_instruction)
        self.assertIn("do not turn it into a common english word", speaker_instruction)

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

    def test_clipboard_skill_loaders_scope_paths_and_project_context(self):
        with self.assertRaises(ValueError):
            load_clipboard_skill("../system.md")

        with tempfile.TemporaryDirectory() as raw:
            game_root = Path(raw) / "Game With Spaces"
            game_root.mkdir()
            prompt = load_walkthrough_skill(game_root, "RPG Maker MZ")

        self.assertIn(str(game_root.resolve()), prompt)
        self.assertIn("RPG Maker MZ", prompt)
        self.assertNotIn("{{GAME_ROOT}}", prompt)
        self.assertNotIn("{{ENGINE}}", prompt)
        self.assertIn("<game>/WALKTHROUGH.html", prompt)
        self.assertIn("self-contained responsive HTML", prompt)
        self.assertIn("AI-generated guide", prompt)


if __name__ == "__main__":
    unittest.main()
