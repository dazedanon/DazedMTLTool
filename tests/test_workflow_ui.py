"""Structural regression tests for the RPG Maker workflow visual system."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt5.QtCore import QSettings
from PyQt5.QtGui import QPalette
from PyQt5.QtWidgets import QApplication

from gui.theme import COLORS, contrast_ratio, dark_palette
from gui.workflow_components import (
    DisclosureSection,
    WorkflowActivityPanel,
)
from util.paths import LEGACY_GLOSSARY_BASE_SEPARATOR


class ThemeContractTests(unittest.TestCase):
    def test_required_text_and_button_pairs_meet_normal_text_contrast(self):
        pairs = (
            (COLORS.text_primary, COLORS.canvas),
            (COLORS.text_secondary, COLORS.canvas),
            (COLORS.text_muted, COLORS.canvas),
            (COLORS.accent_text, COLORS.canvas),
            (COLORS.success, COLORS.canvas),
            (COLORS.warning, COLORS.canvas),
            (COLORS.danger, COLORS.canvas),
            (COLORS.on_accent, COLORS.accent),
            (COLORS.on_accent, COLORS.danger_fill),
            (COLORS.danger_hover, COLORS.danger_surface),
        )
        for foreground, background in pairs:
            with self.subTest(foreground=foreground, background=background):
                self.assertGreaterEqual(contrast_ratio(foreground, background), 4.5)

    def test_qpalette_has_explicit_dark_roles(self):
        palette = dark_palette()
        self.assertEqual(palette.color(QPalette.Window).name().upper(), COLORS.canvas)
        self.assertEqual(palette.color(QPalette.Base).name().upper(), COLORS.surface_2)
        self.assertEqual(
            palette.color(QPalette.ToolTipBase).name().upper(), COLORS.surface_2
        )
        self.assertEqual(
            palette.color(QPalette.Highlight).name().upper(), COLORS.selection
        )


class WorkflowShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.saved_game = Path(self.temp.name) / "Saved Game"
        self.saved_game.mkdir()
        self.saved_game.joinpath("vocab.txt").write_text(
            "# Game Characters\nユウ (Yuu)\n\n"
            + LEGACY_GLOSSARY_BASE_SEPARATOR
            + "old base\n",
            encoding="utf-8",
        )
        self.settings = QSettings(
            str(Path(self.temp.name) / "workflow.ini"), QSettings.IniFormat
        )
        self.settings.setValue("workflow/last_game_folder", str(self.saved_game))
        with patch("gui.workflow_tab.QSettings", return_value=self.settings):
            from gui.workflow_tab import WorkflowTab

            self.workflow = WorkflowTab()
        self.workflow._detected_on_show = True
        self.workflow.resize(1400, 760)
        self.workflow.show()
        self.app.processEvents()

    def tearDown(self):
        self.workflow.close()
        self.workflow.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def test_vertical_step_rail_drives_existing_page_stack(self):
        glossary = self.saved_game / "glossary.txt"
        self.assertFalse(glossary.exists())
        self.assertIn("ユウ (Yuu)", self.workflow.setup_editors.vocab_editor.toPlainText())

        self.workflow.setup_editors._save_vocab()
        self.assertTrue(glossary.is_file())

        self.assertEqual(self.workflow._step_tabs.count(), 9)
        self.assertEqual(len(self.workflow._step_rail.buttons), 9)

        self.workflow._goto_step(3)
        self.app.processEvents()
        self.assertEqual(self.workflow._step_tabs.currentIndex(), 3)
        self.assertTrue(self.workflow._step_rail.buttons[3].isChecked())

        self.workflow._advance_step(3)
        self.app.processEvents()
        self.assertIn(3, self.workflow._step_done)
        self.assertEqual(self.workflow._step_tabs.currentIndex(), 4)
        self.assertEqual(
            self.workflow._step_rail.buttons[3].property("stepState"), "complete"
        )

    def test_activity_panel_is_collapsible_and_persisted(self):
        self.assertFalse(self.workflow._activity_panel.isVisible())
        self.workflow._set_activity_visible(True)
        self.app.processEvents()
        self.assertTrue(self.workflow._activity_panel.isVisible())
        self.assertEqual(self.settings.value("workflow/activity_panel_visible"), "true")
        self.workflow._set_activity_visible(False)
        self.assertEqual(self.settings.value("workflow/activity_panel_visible"), "false")

    def test_activity_log_uses_shared_semantic_colors_and_plain_text(self):
        panel = self.workflow._activity_panel
        panel.append_message("\x1b[31m❌ Injection failed\x1b[0m")
        panel.append_message("⚠ Translation mismatch")
        panel.append_message("✅ Injection completed")

        self.assertEqual(
            panel.log.toPlainText().splitlines(),
            [
                "❌ Injection failed",
                "⚠ Translation mismatch",
                "✅ Injection completed",
            ],
        )
        html = panel.log.toHtml().casefold()
        self.assertIn(COLORS.danger.casefold(), html)
        self.assertIn(COLORS.warning.casefold(), html)
        self.assertIn(COLORS.success.casefold(), html)
        self.assertEqual(panel.message_kind("0 failed"), "info")
        self.assertEqual(panel.message_kind("No errors found"), "info")

        panel.clear_activity()
        self.assertFalse(panel.log.toPlainText())
        self.assertEqual(panel.summary_label.text(), "Activity · Idle")

    def test_phase_two_child_controls_require_their_parent_code(self):
        checks = self.workflow._p2_code_checks
        self.workflow._p2_loading_config = True
        for checkbox in checks.values():
            checkbox.setChecked(False)
        self.workflow._p2_loading_config = False
        self.workflow._refresh_p2_control_dependencies()

        self.assertFalse(self.workflow._p2_var_range_box.isEnabled())
        self.assertFalse(self.workflow._p2_plugin_filter_group.isEnabled())
        self.assertFalse(self.workflow._p2_pattern_filter_group.isEnabled())
        self.assertFalse(self.workflow._phase2_advanced.toggle.isEnabled())
        self.assertFalse(self.workflow._run_p2_btn.isEnabled())

        self.workflow._p2_loading_config = True
        checks["CODE122"].setChecked(True)
        checks["CODE357"].setChecked(True)
        self.workflow._p2_loading_config = False
        self.workflow._refresh_p2_control_dependencies()

        self.assertTrue(self.workflow._p2_var_range_box.isEnabled())
        self.assertTrue(self.workflow._p2_plugin_filter_group.isEnabled())
        self.assertFalse(self.workflow._p2_pattern_filter_group.isEnabled())
        self.assertTrue(self.workflow._phase2_advanced.toggle.isEnabled())
        self.assertTrue(self.workflow._run_p2_btn.isEnabled())

        self.workflow._p2_loading_config = True
        checks["CODE355655"].setChecked(True)
        self.workflow._p2_loading_config = False
        self.workflow._refresh_p2_control_dependencies()
        self.assertTrue(self.workflow._p2_pattern_filter_group.isEnabled())

    def test_phase_two_advanced_controls_preserve_state_when_collapsed(self):
        disclosure = self.workflow._phase2_advanced
        self.assertIsInstance(disclosure, DisclosureSection)
        self.workflow._p2_loading_config = True
        self.workflow._p2_code_checks["CODE357"].setChecked(True)
        self.workflow._p2_loading_config = False
        self.workflow._refresh_p2_control_dependencies()
        checkbox = next(iter(self.workflow._p2_plugin_checks.values()))
        self.workflow._p2_loading_config = True
        checkbox.setChecked(True)
        self.workflow._p2_loading_config = False
        disclosure.toggle.setChecked(True)
        disclosure.toggle.setChecked(False)
        self.assertTrue(checkbox.isChecked())



    def test_phase_one_widths_reload_live_values_from_env(self):
        live_values = {
            "width": "82",
            "faceWidth": "68",
            "listWidth": "104",
            "noteWidth": "91",
        }
        with (
            patch("gui.workflow_tab.Path.is_file", return_value=True),
            patch("gui.workflow_tab.dotenv_values", return_value=live_values),
        ):
            self.workflow._goto_step(3)
            self.app.processEvents()

        self.assertEqual(self.workflow.wrap_width_spin.value(), 82)
        self.assertEqual(self.workflow.wrap_face_spin.value(), 68)
        self.assertEqual(self.workflow.wrap_list_spin.value(), 104)
        self.assertEqual(self.workflow.wrap_note_spin.value(), 91)

    def test_phase_one_face_width_is_clamped_to_live_dialogue_width(self):
        with (
            patch("gui.workflow_tab.Path.is_file", return_value=True),
            patch(
                "gui.workflow_tab.dotenv_values",
                return_value={"width": "48", "faceWidth": "70"},
            ),
        ):
            self.workflow.refresh_wrap_widths_from_env()

        self.assertEqual(self.workflow.wrap_width_spin.value(), 48)
        self.assertEqual(self.workflow.wrap_face_spin.value(), 48)

class WolfTaskWorkerTests(unittest.TestCase):
    def test_reports_one_concise_exception(self):
        from gui.wolf_workflow_tab import _WolfTaskWorker

        def fail(_log, _progress):
            raise RuntimeError("broken archive")

        log_messages = []
        completions = []
        worker = _WolfTaskWorker(fail)
        worker.log.connect(log_messages.append)
        worker.done.connect(lambda ok, message: completions.append((ok, message)))

        worker.run()

        self.assertEqual(log_messages, [])
        self.assertEqual(completions, [(False, "RuntimeError: broken archive")])


class WolfWorkflowShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = QSettings(
            str(Path(self.temp.name) / "wolf-workflow.ini"), QSettings.IniFormat
        )
        with patch("gui.wolf_workflow_tab.QSettings", return_value=self.settings):
            from gui.wolf_workflow_tab import WolfWorkflowTab

            self.workflow = WolfWorkflowTab()
        self.workflow._detected_on_show = True
        self.workflow.resize(1400, 760)
        self.workflow.show()
        self.app.processEvents()

    def tearDown(self):
        self.workflow.close()
        self.workflow.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def test_wolf_uses_the_shared_activity_shell_and_state(self):
        panel = self.workflow._activity_panel
        self.assertIsInstance(panel, WorkflowActivityPanel)
        self.assertIs(self.workflow.log_area, panel.log)
        self.assertEqual(self.workflow._workflow_splitter.indexOf(panel), 1)
        self.assertFalse(panel.isVisible())

        self.workflow._log("❌ Injection failed")
        self.assertEqual(self.workflow._activity_unread, 1)
        self.assertEqual(self.workflow._activity_errors, 1)
        self.assertIn("1 error", self.workflow._step_rail.activity_button.toolTip())

        self.workflow._set_activity_visible(True)
        self.app.processEvents()
        self.assertTrue(panel.isVisible())
        self.assertEqual(self.workflow._activity_unread, 0)
        self.assertEqual(self.workflow._activity_errors, 0)
        self.assertEqual(
            self.settings.value("wolf_workflow/activity_panel_visible"), "true"
        )

        panel.clear_requested.emit()
        self.assertFalse(panel.log.toPlainText())
        self.assertEqual(panel.summary_label.text(), "Activity · Idle")

    def test_wolf_check_copies_scoped_ai_repair_skill(self):
        from util.wolfdawn.inject_precheck import InjectIssue

        self.workflow._game_root = self.temp.name
        self.workflow._inject_precheck_issues = [
            InjectIssue(
                json_file="SampleMapA.mps.json",
                kind="code_mismatch",
                locator="event 7 page 0 cmd 55 str 0",
                message="raw diagnostic",
                problem="Translation changed one or more control codes",
                difference="Missing: `\\.` ×5\nExtra: `\\\\` ×5",
                guidance="Restore the missing codes.",
            )
        ]
        QApplication.clipboard().clear()

        self.workflow._copy_inject_precheck_repair_skill()

        prompt = QApplication.clipboard().text()
        self.assertIn(str((Path.cwd() / "translated").resolve()), prompt)
        self.assertIn(str(Path(self.temp.name).resolve()), prompt)
        self.assertIn("SampleMapA.mps.json", prompt)
        self.assertIn("event 7 page 0 cmd 55 str 0", prompt)
        self.assertIn("Missing: `\\.` ×5", prompt)
        self.assertNotIn("raw diagnostic", prompt)


class CaptureDiffTests(unittest.TestCase):
    def test_capture_diff_reports_changed_pixels(self):
        from scripts.capture_workflow_ui import compare_captures

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            current = root / "current-run" / "current" / "100x100-1"
            baseline = root / "baseline" / "current" / "100x100-1"
            current.mkdir(parents=True)
            baseline.mkdir(parents=True)
            name = "step-00-project.png"
            Image.new("RGB", (20, 20), "#1E1E1E").save(current / name)
            Image.new("RGB", (20, 20), "#252526").save(baseline / name)

            result = compare_captures(root / "current-run", root / "baseline")

            self.assertEqual(result["compared"], 1)
            self.assertEqual(result["changed"], 1)
            self.assertEqual(result["images"][0]["changed_pixels"], 400)


if __name__ == "__main__":
    unittest.main()
