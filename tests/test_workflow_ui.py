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
from PyQt5.QtWidgets import (
    QApplication,
    QBoxLayout,
    QCheckBox,
    QPushButton,
    QWidget,
)

from gui.theme import COLORS, Geometry, Spacing, contrast_ratio, dark_palette
from gui.workflow_components import (
    DisclosureSection,
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

    def test_phase_two_advanced_controls_preserve_state_when_collapsed(self):
        disclosure = self.workflow._phase2_advanced
        self.assertIsInstance(disclosure, DisclosureSection)
        checkbox = next(iter(self.workflow._p2_plugin_checks.values()))
        self.workflow._p2_loading_config = True
        checkbox.setChecked(True)
        self.workflow._p2_loading_config = False
        disclosure.toggle.setChecked(True)
        disclosure.toggle.setChecked(False)
        self.assertTrue(checkbox.isChecked())

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
                "Run final QA and build the release",
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
                "Edit glossary and project guidance",
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
                "Run final QA and build the release",
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
            ],
        }
        for page_index, titles in expected.items():
            page = self.workflow._step_tabs.widget(page_index)
            stages = page.findChildren(WorkflowStageCard)
            self.assertEqual([stage.title_label.text() for stage in stages], titles)

    def test_related_action_groups_share_width_and_control_height(self):
        groups = {
            0: (("Select all", "Clear selection", "Database only"),),
            1: (("Install GameUpdate", "Run available tasks"),),
            2: (
                ("Import files", "Clear translated"),
                ("Collect names", "Copy setup skill"),
            ),
            5: (
                ("Copy glossary to game", "Copy plugin skill"),
                ("Export selected files", "Export all translated files"),
            ),
            6: (
                ("Select all", "Maps & events", "Database only", "Clear selection"),
                ("Preview rewrap", "Apply rewrap"),
                ("Copy final QA skill", "Build public release ZIP"),
            ),
            8: (
                ("Save defaults", "Apply settings to game"),
                ("Install TL Inspector", "Remove TL Inspector"),
                ("Install Forge", "Remove Forge"),
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

    def test_setup_checkbox_and_phase_one_width_grids_are_aligned(self):
        self.workflow._goto_step(2)
        self.app.processEvents()
        setup_checks = (
            self.workflow.spk_inline_cb,
            self.workflow.spk_firstline_cb,
            self.workflow.spk_face_cb,
        )
        self.assertEqual(len({checkbox.y() for checkbox in setup_checks}), 1)
        self.assertEqual(
            [checkbox.x() for checkbox in setup_checks],
            sorted(checkbox.x() for checkbox in setup_checks),
        )

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
