"""Regression tests for concise, interactive plugin translation prompts."""

import unittest

from util.skills import load_clipboard_skill, load_project_setup
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

    def test_rpgmaker_qa_prompt_scales_and_requires_approval(self):
        prompt = load_clipboard_skill("rpgmaker_translation_qa.md")
        lowered = prompt.casefold()
        self.assertIn("control-code scope and placement", lowered)
        self.assertIn("do not edit during discovery", lowered)
        self.assertIn("stop and wait for approval", lowered)
        self.assertIn("never modify or remove `_original`", lowered)
        self.assertIn("`relative file + json path + source hash`", lowered)
        self.assertIn("never claim readiness without", lowered)
        for placeholder in (
            "{{GAME_DATA_FOLDER}}",
            "{{GAME_ROOT}}",
            "{{VOCAB_FILE}}",
        ):
            self.assertIn(placeholder, prompt)

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
        self.assertNotIn("{{SUPPORTED_CODE408_MARKERS}}", prompt)
        for marker in SUPPORTED_CODE408_MARKERS:
            self.assertIn(marker, prompt)

        wolf_prompt = load_project_setup("wolf")
        self.assertNotIn("code408 : enable|skip", wolf_prompt.casefold())

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
