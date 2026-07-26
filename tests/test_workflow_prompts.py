"""Regression tests for concise, interactive plugin translation prompts."""

import unittest
from pathlib import Path

from util.skills import load_clipboard_skill


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

    def test_static_clipboard_prompts_live_under_data_skills(self):
        expected = (
            "wrap_config.md",
            "plugin_translation.md",
            "ace_script_translation.md",
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

    def test_clipboard_skill_loader_rejects_paths(self):
        with self.assertRaises(ValueError):
            load_clipboard_skill("../system.md")


if __name__ == "__main__":
    unittest.main()
