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
        self.assertIn("deterministic stratified sample", lowered)
        self.assertIn("control-code scope and placement", lowered)
        self.assertIn("enabled plugin code consumes a 108/408 comment block", lowered)
        self.assertIn("do not edit during the first pass", lowered)
        self.assertIn("stop and wait for approval", lowered)
        self.assertIn("never modify or remove `_original`", lowered)
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

        wolf_prompt = load_project_setup("wolf")
        self.assertNotIn("code408 : enable|skip", wolf_prompt.casefold())

    def test_phase1_code408_is_user_controlled(self):
        from gui.workflow_tab import PHASE1_CONFIG

        self.assertFalse(PHASE1_CONFIG["CODE408"])
        workflow_source = (ROOT / "gui/workflow_tab.py").read_text(encoding="utf-8")
        self.assertIn("Translate code 408 plugin/comment text", workflow_source)
        self.assertIn('config["CODE408"] = bool(', workflow_source)

    def test_static_clipboard_prompts_live_under_data_skills(self):
        expected = (
            "wrap_config.md",
            "plugin_translation.md",
            "ace_script_translation.md",
            "rpgmaker_translation_qa.md",
            "image_translation.md",
            "risky_codes.md",
            "wolf_speakers.md",
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
        self.assertIn("QA Game Data Skill", workflow_source)
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
        self.assertIn("Dialogue + Face", workflow_source)
        self.assertIn("Maps / Events", workflow_source)
        self.assertIn("Event codes:", workflow_source)
        self.assertIn("Scan selected", workflow_source)
        self.assertIn("Rewrap selected", workflow_source)
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

    def test_clipboard_skill_loader_rejects_paths(self):
        with self.assertRaises(ValueError):
            load_clipboard_skill("../system.md")


if __name__ == "__main__":
    unittest.main()
