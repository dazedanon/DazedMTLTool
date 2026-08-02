"""Behavioral checks for shared GUI accessibility and semantic contracts."""

import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QObject, Qt
from PyQt5.QtWidgets import QApplication, QLabel, QWidget

from gui.guide_tab import GuideTab
from gui.theme import COLORS, contrast_ratio
from gui.ui_components import PageHeader, SectionCard, make_action_button, set_status_text
from gui.workflow_components import DisclosureSection, WorkflowStageCard


class _TopLevelShowFilter(QObject):
    def __init__(self):
        super().__init__()
        self.shown = []

    def eventFilter(self, watched, event):
        if (
            event.type() == QEvent.Show
            and isinstance(watched, QWidget)
            and watched.isWindow()
        ):
            self.shown.append(watched)
        return False


class GUIUXContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_core_text_and_actions_meet_normal_text_contrast(self):
        pairs = (
            (COLORS.text_primary, COLORS.canvas),
            (COLORS.text_secondary, COLORS.surface_1),
            (COLORS.on_accent, COLORS.accent),
        )
        for foreground, background in pairs:
            with self.subTest(foreground=foreground, background=background):
                self.assertGreaterEqual(contrast_ratio(foreground, background), 4.5)

    def test_shared_components_expose_roles_without_transient_windows(self):
        show_filter = _TopLevelShowFilter()
        self.app.installEventFilter(show_filter)
        try:
            header = PageHeader("Title", "Purpose")
            card = SectionCard("Task", "Description")
            primary = make_action_button("Apply changes", variant="primary")
            stage = WorkflowStageCard(1, "Choose a game", "Select its folder.")
            disclosure = DisclosureSection(
                "Advanced", QWidget(), expanded=True
            )
        finally:
            self.app.removeEventFilter(show_filter)

        self.assertEqual(header.objectName(), "appPageHeader")
        self.assertEqual(header.title_label.objectName(), "appPageTitle")
        self.assertEqual(card.objectName(), "appSectionCard")
        self.assertEqual(primary.objectName(), "appActionButton")
        self.assertEqual(primary.property("variant"), "primary")
        self.assertEqual(stage.objectName(), "workflowStageCard")
        self.assertTrue(disclosure.content.isVisibleTo(disclosure))
        self.assertEqual(show_filter.shown, [])

    def test_status_updates_text_and_semantic_state_together(self):
        status = QLabel()

        set_status_text(status, "Could not load files", "error")

        self.assertEqual(status.text(), "Could not load files")
        self.assertEqual(status.objectName(), "appStatusText")
        self.assertEqual(status.property("state"), "error")

    def test_guide_group_headings_are_not_selectable_pages(self):
        with tempfile.TemporaryDirectory() as raw:
            help_dir = Path(raw)
            (help_dir / "index.json").write_text(
                json.dumps([
                    {"type": "group", "title": "Definitely Read These"},
                    {"id": "start", "title": "Start Here", "file": "start.md"},
                    {"type": "group", "title": "Extra Information"},
                    {"id": "extra", "title": "Extra", "file": "extra.md"},
                ]),
                encoding="utf-8",
            )
            (help_dir / "start.md").write_text("# Start\n", encoding="utf-8")
            (help_dir / "extra.md").write_text("# Extra\n", encoding="utf-8")

            guide = GuideTab(help_dir=help_dir)

            for row in (0, 2):
                heading = guide.section_list.item(row)
                self.assertTrue(heading.flags() & Qt.ItemIsEnabled)
                self.assertFalse(heading.flags() & Qt.ItemIsSelectable)
            self.assertEqual(guide.section_list.currentRow(), 1)
            self.assertTrue(guide.show_section("extra"))
            self.assertEqual(guide.section_list.currentRow(), 3)


if __name__ == "__main__":
    unittest.main()
