"""Structural regression tests for the RPG Maker workflow visual system."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt5.QtCore import QSettings, Qt
from PyQt5.QtGui import QPalette
from PyQt5.QtWidgets import (
    QApplication,
    QBoxLayout,
    QCheckBox,
    QLabel,
    QPushButton,
    QTabWidget,
    QWidget,
)

from gui.theme import COLORS, Geometry, Spacing, contrast_ratio, dark_palette
from gui.workflow_components import (
    DisclosureSection,
    WorkflowActivityPanel,
    WorkflowPageHeader,
    WorkflowStageCard,
)


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
        self.settings = QSettings(
            str(Path(self.temp.name) / "workflow.ini"), QSettings.IniFormat
        )
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
        self.assertEqual(self.workflow._step_tabs.count(), 9)
        self.assertEqual(len(self.workflow._step_rail.buttons), 9)
        self.assertEqual(self.workflow._step_rail.width(), 176)

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

    def test_activity_utility_is_flush_with_the_navigation_footer(self):
        page = self.workflow._step_tabs.currentWidget()
        footer = page.findChild(QWidget, "workflowFooter")
        activity = self.workflow._step_rail.activity_button
        self.assertEqual(activity.height(), footer.height())
        self.assertEqual(
            activity.mapTo(self.workflow, activity.rect().bottomLeft()).y(),
            footer.mapTo(self.workflow, footer.rect().bottomLeft()).y(),
        )

    def test_step_rail_compacts_at_constrained_width(self):
        self.workflow.resize(1000, 600)
        self.app.processEvents()
        self.assertEqual(
            self.workflow._step_rail.width(), Geometry.STEP_RAIL_COMPACT_WIDTH
        )
        self.workflow.resize(1400, 760)
        self.app.processEvents()
        self.assertEqual(self.workflow._step_rail.width(), 176)

    def test_step_rail_uses_aligned_number_and_label_columns(self):
        rail = self.workflow._step_rail
        self.assertFalse(rail._compact)
        self.assertEqual(
            {label.geometry().x() for label in rail._number_labels},
            {rail._number_labels[0].geometry().x()},
        )
        self.assertEqual(
            {label.geometry().x() for label in rail._text_labels},
            {rail._text_labels[0].geometry().x()},
        )
        self.assertEqual(
            [label.text() for label in rail._text_labels],
            [
                "Project",
                "Prepare",
                "Setup",
                "Phase 1",
                "Phase 2",
                "Export",
                "Rewrap",
                "Images",
                "Playtest",
            ],
        )
        self.assertEqual(
            [label.text() for label in rail._number_labels],
            [str(index) for index in range(1, 10)],
        )
        for display_step, button in enumerate(rail.buttons, start=1):
            self.assertTrue(button.toolTip().startswith(f"Step {display_step}:"))
            self.assertTrue(button.accessibleName().startswith(f"Step {display_step}:"))

    def test_every_page_has_standard_header_and_tokenized_page_margins(self):
        allowed = {0, Spacing.XS, Spacing.SM, Spacing.MD, Spacing.LG, Spacing.XL, Spacing.XXL}
        for index in range(self.workflow._step_tabs.count()):
            page = self.workflow._step_tabs.widget(index)
            headers = page.findChildren(WorkflowPageHeader)
            self.assertEqual(len(headers), 1, index)
            self.assertTrue(headers[0].title_label.text().strip(), index)
            self.assertTrue(headers[0].purpose_label.text().strip(), index)
            content = page.findChild(QWidget, "workflowPageContent")
            self.assertIsNotNone(content, index)
            layout = content.layout()
            margins = layout.contentsMargins()
            self.assertTrue(
                all(
                    value in allowed
                    for value in (
                        margins.left(), margins.top(), margins.right(), margins.bottom()
                    )
                ),
                index,
            )
            self.assertIn(layout.spacing(), allowed, index)

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

    def test_phase_two_advanced_area_uses_plain_labels_and_neutral_surfaces(self):
        page = self.workflow._step_tabs.widget(4)
        labels = {label.text() for label in page.findChildren(QLabel)}
        self.assertIn("MZ plugin command filters", labels)
        self.assertIn("Script text filters", labels)
        self.assertNotIn("MZ plugin handlers (code 357)", labels)
        self.assertNotIn("Script patterns (codes 355/655)", labels)
        self.assertNotIn("Available now:", self.workflow._p2_advanced_hint.text())
        for widget in (
            page.findChild(QWidget, "phase2AdvancedLists"),
            self.workflow._p2_plugin_filter_group,
            self.workflow._p2_pattern_filter_group,
        ):
            self.assertIsNotNone(widget)
            self.assertIn("background:transparent", widget.styleSheet())

    def test_ai_copy_actions_explain_the_next_step_on_the_page(self):
        banners = (
            self.workflow.speaker_setup_hint,
            self.workflow._p2_ai_help_banner,
            self.workflow._plugin_ai_help_banner,
            self.workflow._qa_ai_help_banner,
        )
        for banner in banners:
            text = banner.text_label.text()
            self.assertIn("AI helper", text)
        for banner in banners[1:]:
            self.assertIn("paste", banner.text_label.text().casefold())

    def test_glossary_is_copied_once_and_release_is_the_last_mvmz_stage(self):
        glossary_buttons = [
            button
            for button in self.workflow.findChildren(QPushButton)
            if "Copy glossary to game" in button.text()
        ]
        self.assertEqual(len(glossary_buttons), 1)
        self.assertTrue(
            self.workflow._step_tabs.widget(5).isAncestorOf(glossary_buttons[0])
        )

        playtest_stages = self.workflow._step_tabs.widget(8).findChildren(
            WorkflowStageCard
        )
        self.assertEqual(playtest_stages[-1].title_label.text(), "Build the public release")
        self.assertTrue(playtest_stages[-1].isAncestorOf(self.workflow._release_zip_btn))

    def test_rewrap_is_a_four_stage_progressive_workflow(self):
        page = self.workflow._step_tabs.widget(6)
        stages = page.findChildren(WorkflowStageCard)
        self.assertEqual([stage.number_label.text() for stage in stages], ["1", "2", "3", "4"])
        self.assertEqual(
            [stage.title_label.text() for stage in stages],
            [
                "Select game-data files",
                "Set line-wrapping rules",
                "Preview and apply rewrap",
                "Run final QA",
            ],
        )
        self.assertFalse(self.workflow._rewrap_advanced.toggle.isChecked())
        self.assertFalse(self.workflow._rewrap_results_disclosure.toggle.isChecked())

    def test_rewrap_workspace_reflows_instead_of_compressing_columns(self):
        self.workflow.resize(1400, 760)
        self.app.processEvents()
        self.assertEqual(
            self.workflow._rewrap_workspace_layout.direction(), QBoxLayout.TopToBottom
        )
        self.workflow.resize(1600, 900)
        self.app.processEvents()
        self.assertEqual(
            self.workflow._rewrap_workspace_layout.direction(), QBoxLayout.LeftToRight
        )

    def test_speaker_setup_tells_beginners_what_to_enable_and_in_what_order(self):
        hint = self.workflow.speaker_setup_hint.text_label.text()
        self.assertIn("Always start with “1  Collect names”", hint)
        self.assertIn("option ENABLE", hint)
        self.assertIn("collect names again", hint)
        self.assertIn("Many games need none", hint)

        expected_labels = (
            (self.workflow.spk_inline_cb, "attached to the dialogue", "INLINE401SPEAKERS"),
            (self.workflow.spk_firstline_cb, "alone on the first dialogue line", "FIRSTLINESPEAKERS"),
            (self.workflow.spk_face_cb, "face image's filename", "FACENAME101"),
        )
        for checkbox, explanation, flag in expected_labels:
            self.assertIn(explanation, checkbox.text())
            self.assertIn("only when the setup helper says", checkbox.toolTip())
            self.assertIn(flag, checkbox.toolTip())

        self.assertIn("1  Collect names", self.workflow.speaker_collect_names_btn.text())
        self.assertIn("2  Copy setup instructions", self.workflow.speaker_copy_setup_btn.text())

    def test_setup_editor_tabs_match_project_setup_block_names(self):
        editors = self.workflow.setup_editors.findChild(QTabWidget, "setupEditors")
        self.assertIsNotNone(editors)
        self.assertEqual(
            [editors.tabText(i) for i in range(editors.count())],
            ["Glossary", "Translation quirks", "Game skill"],
        )
        tab_bar = editors.tabBar()
        self.assertGreaterEqual(tab_bar.minimumHeight(), 44)
        self.assertEqual(tab_bar.elideMode(), Qt.ElideNone)
        self.assertTrue(tab_bar.usesScrollButtons())

    def test_every_page_uses_a_numbered_task_sequence(self):
        expected = {
            0: [
                "Select the RPG Maker project",
                "Select files to translate",
                "Import selected files",
            ],
            1: [
                "Format game data",
                "Format plugin configuration",
                "Install the GameUpdate helper",
            ],
            2: [
                "Prepare the translation workspace",
                "Configure speakers and generate project context",
                "Edit glossary, translation quirks, and game skill",
            ],
            3: [
                "Set run mode and line widths",
                "Translate database text",
                "Translate dialogue and choices",
                "Build the variable translation cache",
            ],
            4: [
                "Audit advanced text sources",
                "Select audited text sources",
                "Start advanced translation",
            ],
            5: [
                "Prepare plugin or script translations",
                "Export reviewed translations",
            ],
            6: [
                "Select game-data files",
                "Set line-wrapping rules",
                "Preview and apply rewrap",
                "Run final QA",
            ],
            7: [
                "Check image readiness",
                "Prepare images for translation",
                "Review and patch translated images",
            ],
            8: [
                "Configure playtest tools",
                "Install playtest plugins",
                "Verify plugins in game",
                "Build the public release",
            ],
        }
        for page_index, titles in expected.items():
            page = self.workflow._step_tabs.widget(page_index)
            stages = page.findChildren(WorkflowStageCard)
            self.assertEqual([stage.title_label.text() for stage in stages], titles)

    def test_related_action_groups_share_width_and_control_height(self):
        groups = {
            0: (("Select all", "Clear selection", "Database only"),),
            1: ((
                "Format game data",
                "Format plugins.js",
                "Install GameUpdate",
                "Run available tasks",
            ),),
            2: (
                ("Import files", "Clear translated"),
                ("Copy setup instructions", "Collect names"),
            ),
            3: ((
                "Save line widths",
                "Translate database",
                "Translate dialogue",
                "Build variable cache",
            ),),
            4: (("Copy advanced-text audit", "Translate selected text"),),
            5: (
                ("Copy glossary to game", "Copy plugin skill"),
                ("Export selected files", "Export all translated files"),
            ),
            6: (
                ("Select all", "Maps & events", "Database only", "Clear selection"),
                ("Preview rewrap", "Apply rewrap"),
                ("Copy final QA skill",),
            ),
            7: (("Refresh readiness", "Open Image Manager"),),
            8: (
                ("Find editors", "Choose…"),
                ("Save defaults", "Apply settings to game"),
                (
                    "Install TL Inspector",
                    "Remove TL Inspector",
                    "Install Forge",
                    "Remove Forge",
                    "Install both plugins",
                ),
                ("Build public release ZIP",),
            ),
        }

        for page_index, page_groups in groups.items():
            self.workflow._goto_step(page_index)
            self.app.processEvents()
            page = self.workflow._step_tabs.widget(page_index)
            buttons = page.findChildren(QPushButton)
            for labels in page_groups:
                matched = []
                for label in labels:
                    button = next(
                        candidate
                        for candidate in buttons
                        if label.casefold() in candidate.text().casefold()
                    )
                    matched.append(button)
                with self.subTest(page=page_index, labels=labels):
                    self.assertEqual(len({button.width() for button in matched}), 1)
                    self.assertEqual(len({button.height() for button in matched}), 1)

        for button in self.workflow.findChildren(QPushButton, "workflowButton"):
            self.assertGreaterEqual(button.minimumHeight(), Geometry.CONTROL)

    def test_prepare_run_all_is_a_separate_bottom_action(self):
        self.workflow._goto_step(1)
        self.app.processEvents()

        buttons = self.workflow.pp_preprocess_action_buttons
        self.assertEqual(len({button.width() for button in buttons}), 1)
        self.assertEqual(buttons[0].width(), Geometry.ACTION_WIDE)
        self.assertGreater(
            buttons[-1].mapTo(self.workflow, buttons[-1].rect().topLeft()).y(),
            buttons[-2].mapTo(self.workflow, buttons[-2].rect().topLeft()).y(),
        )
        self.assertIs(buttons[-1].parentWidget(), self.workflow.pp_run_all_bar)

    def test_setup_speaker_rows_and_phase_one_width_grid_are_aligned(self):
        self.workflow._goto_step(2)
        self.app.processEvents()
        setup_checks = (
            self.workflow.spk_inline_cb,
            self.workflow.spk_firstline_cb,
            self.workflow.spk_face_cb,
        )
        self.assertEqual(len({checkbox.x() for checkbox in setup_checks}), 1)
        self.assertEqual(
            [checkbox.y() for checkbox in setup_checks],
            sorted(checkbox.y() for checkbox in setup_checks),
        )
        self.assertEqual(len({checkbox.y() for checkbox in setup_checks}), 3)

        self.workflow._goto_step(3)
        self.app.processEvents()
        width_fields = (
            self.workflow.wrap_width_spin,
            self.workflow.wrap_face_spin,
            self.workflow.wrap_list_spin,
            self.workflow.wrap_note_spin,
        )
        self.assertEqual(len({field.y() for field in width_fields}), 1)
        self.assertEqual(len({field.height() for field in width_fields}), 1)

    def test_setup_workspace_reflows_with_available_width(self):
        self.workflow.resize(1400, 760)
        self.app.processEvents()
        self.assertEqual(
            self.workflow._setup_workspace_layout.direction(), QBoxLayout.TopToBottom
        )
        self.workflow.resize(1600, 900)
        self.app.processEvents()
        self.assertEqual(
            self.workflow._setup_workspace_layout.direction(), QBoxLayout.LeftToRight
        )


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

    def test_wolf_worker_reports_one_concise_exception(self):
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

    def test_wolf_check_has_two_aligned_full_workflow_actions(self):
        self.workflow._goto_step(6)
        self.app.processEvents()

        page = self.workflow._step_tabs.widget(6)
        buttons = page.findChildren(QPushButton)
        labels = [button.text() for button in buttons]
        self.assertIn("Preview all files", labels)
        self.assertIn("Copy AI repair skill", labels)
        self.assertNotIn("Preview selected files", labels)
        self.assertNotIn("Refresh files", labels)
        self.assertNotIn("Select all", labels)
        self.assertNotIn("Clear selection", labels)

        preview = next(button for button in buttons if button.text() == "Preview all files")
        repair = next(
            button for button in buttons if button.text() == "Copy AI repair skill"
        )
        self.assertEqual(preview.width(), Geometry.ACTION_WIDE)
        self.assertEqual(repair.width(), Geometry.ACTION_WIDE)
        self.assertEqual(preview.height(), repair.height())
        self.assertEqual(
            preview.mapTo(page, preview.rect().topLeft()).x(),
            repair.mapTo(page, repair.rect().topLeft()).x(),
        )

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
