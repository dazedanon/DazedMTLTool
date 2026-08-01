"""Regression tests for concise, interactive plugin translation prompts."""

import unittest
from pathlib import Path

from util.skills import load_clipboard_skill, load_project_setup


ROOT = Path(__file__).resolve().parents[1]


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

    def test_mvmz_prompt_audits_enabled_plugins_before_editing(self):
        prompt = load_clipboard_skill("plugin_translation.md")
        self._assert_interactive_in_place_prompt(prompt)
        self.assertIn("js/plugins.js", prompt)
        self.assertIn("js/plugins/<PluginName>.js", prompt)
        self.assertIn("which listed plugins should you translate", prompt)

    def test_ace_prompt_audits_scripts_before_editing(self):
        prompt = load_clipboard_skill("ace_script_translation.md")
        self._assert_interactive_in_place_prompt(prompt)
        self.assertIn("ace_json/scripts/*.rb", prompt)
        self.assertIn("which listed scripts should you translate", prompt)
        self.assertIn("Ruby interpolation (#{...})", prompt)

    def test_rpgmaker_qa_prompt_scales_and_requires_approval(self):
        prompt = load_clipboard_skill("rpgmaker_translation_qa.md")
        lowered = prompt.casefold()
        self.assertIn("mechanically check 100%", lowered)
        self.assertIn("deterministic stratified semantic-review waves", lowered)
        self.assertIn("control-code scope and placement", lowered)
        self.assertIn("enabled plugin code consumes a 108/408 comment block", lowered)
        self.assertIn("do not edit during discovery", lowered)
        self.assertIn("stop and wait for approval", lowered)
        self.assertIn("never modify or remove `_original`", lowered)
        self.assertIn("500 unique pairs per wave", lowered)
        self.assertIn("`relative file + json path + source hash`", lowered)
        self.assertIn("two consecutive waves", lowered)
        self.assertIn("corpus-wide issue propagation", lowered)
        self.assertIn("continuous remediation", lowered)
        self.assertIn("non-overlapping discovery wave after fixes", lowered)
        self.assertIn("never claim readiness without", lowered)
        for placeholder in (
            "{{GAME_DATA_FOLDER}}",
            "{{GAME_ROOT}}",
            "{{VOCAB_FILE}}",
        ):
            self.assertIn(placeholder, prompt)

    def test_rpgmaker_project_setup_recommends_408_and_layout_geometry(self):
        prompt = load_project_setup("rpgmaker")
        lowered = prompt.casefold()

        self.assertIn("code408 : enable|skip", lowered)
        self.assertIn("translate code 408 plugin/comment text", lowered)
        self.assertIn("dialogue : width=", lowered)
        self.assertIn("facewidth=<code-101 face width>", lowered)
        self.assertIn("list/help: listwidth=", lowered)
        self.assertIn("notes    : notewidth=", lowered)
        self.assertIn("face/portrait reservation", lowered)
        self.assertIn("applicable line height", lowered)
        self.assertIn("pagination/manual reflow", lowered)
        self.assertIn("filename alone", lowered)
        self.assertIn("the tool does not use", lowered)
        self.assertIn("shared sheet", lowered)
        self.assertIn("one-to-one `filename -> speaker`", lowered)
        self.assertIn("deterministic speaker micro-repairs", lowered)
        self.assertIn("at most three entries", lowered)
        self.assertIn("without asking for confirmation", lowered)
        self.assertIn("only fills an empty code-101 param[4]", lowered)
        self.assertIn("facename101 is not needed after rescan", lowered)
        self.assertIn("global extraction decision", lowered)
        self.assertIn("tiny relative to the inventory", lowered)
        self.assertIn("translating those few values manually", lowered)

        wolf_prompt = load_project_setup("wolf")
        self.assertNotIn("code408 : enable|skip", wolf_prompt.casefold())

    def test_phase1_code408_is_user_controlled(self):
        from gui.workflow_tab import PHASE1_CONFIG

        self.assertFalse(PHASE1_CONFIG["CODE408"])
        workflow_source = (ROOT / "gui/workflow_tab.py").read_text(encoding="utf-8")
        self.assertIn("Include displayed comment text (code 408)", workflow_source)
        self.assertIn('config["CODE408"] = bool(', workflow_source)

    def test_rpgmaker_step_help_is_complete_and_beginner_focused(self):
        from gui.workflow_tab import _STEP_HELP

        self.assertEqual(set(_STEP_HELP), set(range(9)))
        required_actions = {
            0: ("Choose game folder", "Import selected files"),
            1: ("Run available tasks",),
            2: ("Collect names", "Copy setup instructions"),
            3: ("Translate database", "Translate dialogue", "Build variable cache"),
            4: ("Copy advanced-text audit", "Translate selected text"),
            5: ("glossary.txt", "Export selected files"),
            6: ("Preview rewrap", "Apply rewrap", "Copy final QA skill"),
            7: ("Open Image Manager", "Copy skill", "Patch selected"),
            8: ("Save defaults", "Build public release ZIP"),
        }
        for step, actions in required_actions.items():
            with self.subTest(step=step):
                help_text = _STEP_HELP[step]
                self.assertIn("What to do", help_text)
                for action in actions:
                    self.assertIn(action, help_text)

        combined = " ".join(_STEP_HELP.values())
        for internal_jargon in (
            "phase profile",
            "prompt cache",
            "RV2JSON -u",
            "code-101",
            "code-401",
            "VCS metadata",
        ):
            self.assertNotIn(internal_jargon, combined)
        self.assertIn("directly inside the game folder", _STEP_HELP[5])
        self.assertIn("final workflow action", _STEP_HELP[8])

    def test_static_clipboard_prompts_live_under_data_skills(self):
        expected = (
            "wrap_config.md",
            "plugin_translation.md",
            "ace_script_translation.md",
            "rpgmaker_translation_qa.md",
            "evaluation_csv_review.md",
            "image_translation.md",
            "risky_codes.md",
            "wolf_speakers.md",
            "wolf_precheck_repair.md",
        )
        for name in expected:
            with self.subTest(name=name):
                self.assertTrue(load_clipboard_skill(name).strip())

        workflow_source = (ROOT / "gui/workflow_tab.py").read_text(encoding="utf-8")
        wolf_source = (ROOT / "gui/wolf_workflow_tab.py").read_text(encoding="utf-8")
        for constant in (
            "_WRAP_PROMPT",
            "_PLUGINS_JS_TRANSLATE_PROMPT",
            "_ACE_SCRIPTS_TRANSLATE_PROMPT",
            "_PLUGIN_PROMPT",
        ):
            self.assertNotIn(constant, workflow_source)
        self.assertNotIn("_WOLF_SPEAKER_PROMPT", wolf_source)
        self.assertIn("Copy AI repair skill", wolf_source)
        self.assertIn('load_clipboard_skill("wolf_precheck_repair.md")', wolf_source)
        self.assertIn("Copy final QA skill", workflow_source)
        self.assertIn('load_clipboard_skill("rpgmaker_translation_qa.md")', workflow_source)

    def test_wrap_prompt_accounts_for_code101_faces_and_font_changes(self):
        prompt = load_clipboard_skill("wrap_config.md").casefold()
        self.assertIn("facewidth", prompt)
        self.assertIn("non-empty parameter 0", prompt)
        self.assertIn("plugin portraits", prompt)
        self.assertIn("pagination/manual reflow", prompt)
        self.assertIn("rendered line count", prompt)
        self.assertIn("visible-row limit", prompt)
        self.assertIn("simultaneous constraints", prompt)
        self.assertIn("narrower wrapping usually creates more lines", prompt)

    def test_rpgmaker_workflow_has_selective_rewrap_step(self):
        workflow_source = (ROOT / "gui/workflow_tab.py").read_text(encoding="utf-8")
        self.assertIn('("6  Rewrap",       self._build_step5_rewrap)', workflow_source)
        self.assertIn("Dialogue with faces", workflow_source)
        self.assertIn("Maps & events", workflow_source)
        self.assertIn("Event codes:", workflow_source)
        self.assertIn("Preview rewrap", workflow_source)
        self.assertIn("Apply rewrap", workflow_source)
        self.assertIn("never edits _original", workflow_source)
        self.assertIn("self.directory", workflow_source)
        self.assertIn("_rewrap_data_directory", workflow_source)

    def test_image_translation_prompt_ends_skips_with_recovery_options(self):
        prompt = load_clipboard_skill("image_translation.md")

        self.assertIn("### Skipped / review items", prompt)
        self.assertIn("literal final section of the user-facing response", prompt)
        self.assertIn("Try it anyway", prompt)
        self.assertIn("Use generative AI", prompt)
        self.assertIn("Provide clean source art or layers", prompt)
        self.assertIn("Manual artist review", prompt)
        self.assertIn("If nothing was skipped or marked for review, omit", prompt)

    def test_wolf_precheck_repair_skill_is_scoped_and_actionable(self):
        prompt = load_clipboard_skill("wolf_precheck_repair.md")
        normalized = " ".join(prompt.split())

        for placeholder in ("{{TRANSLATED_DIR}}", "{{GAME_ROOT}}", "{{ISSUES}}"):
            self.assertIn(placeholder, prompt)
        self.assertIn("Edit only the affected `text` value", prompt)
        self.assertIn("Never edit `source`", prompt)
        self.assertIn("Never convert literal `\\n` globally", prompt)
        self.assertIn("Continue until every listed `FIX` item", normalized)
        self.assertIn("edit those JSON files in place", prompt)
        self.assertIn("does not need it pasted back", prompt)

    def test_clipboard_skill_loader_rejects_paths(self):
        with self.assertRaises(ValueError):
            load_clipboard_skill("../system.md")


if __name__ == "__main__":
    unittest.main()
