"""Behavioral checks for shared GUI accessibility and semantic contracts."""

import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QObject, QUrl, Qt
from PyQt5.QtGui import QImage, QPixmap
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

    def test_guide_navigation_and_bundled_images(self):
        with tempfile.TemporaryDirectory() as raw:
            help_dir = Path(raw)
            image_dir = help_dir / "images"
            image_dir.mkdir()
            image_path = image_dir / "choose-project.png"
            image = QImage(1600, 1200, QImage.Format_RGB32)
            image.fill(Qt.cyan)
            self.assertTrue(image.save(str(image_path), "PNG"))
            (help_dir / "index.json").write_text(
                json.dumps([
                    {"type": "group", "title": "Definitely Read These"},
                    {"id": "start", "title": "Start Here", "file": "start.md"},
                    {"type": "group", "title": "Extra Information"},
                    {"id": "extra", "title": "Extra", "file": "extra.md"},
                ]),
                encoding="utf-8",
            )
            (help_dir / "start.md").write_text(
                "# Start\n\n![Choose a project](images/choose-project.png)\n",
                encoding="utf-8",
            )
            (help_dir / "extra.md").write_text(
                "# Extra\n\n![Choose a project](images/choose-project.png)\n\n"
                + "\n\n".join(["Scrollable guide content."] * 30),
                encoding="utf-8",
            )

            guide = GuideTab(help_dir=help_dir)
            guide.resize(800, 600)
            guide.show()
            for _ in range(3):
                self.app.processEvents()

            for row in (0, 2):
                heading = guide.section_list.item(row)
                self.assertTrue(heading.flags() & Qt.ItemIsEnabled)
                self.assertFalse(heading.flags() & Qt.ItemIsSelectable)
            self.assertEqual(guide.section_list.currentRow(), 1)
            resolved = QUrl.fromLocalFile(str(image_path.resolve()))
            loaded = guide.browser.document().resource(
                guide.browser.document().ImageResource,
                resolved,
            )
            self.assertIsInstance(loaded, (QImage, QPixmap))
            self.assertFalse(loaded.isNull())
            self.assertEqual(guide.browser.horizontalScrollBar().maximum(), 0)
            self.assertEqual(guide.browser.verticalScrollBar().maximum(), 0)

            # Scrolling used to make the viewport alternate between widths as
            # its vertical scrollbar appeared, rebuilding the document forever
            # and preventing a stable bottom position.
            self.assertTrue(guide.show_section("extra"))
            for _ in range(3):
                self.app.processEvents()
            self.assertEqual(guide.section_list.currentRow(), 3)
            content_changes = []
            guide.browser.document().contentsChanged.connect(
                lambda: content_changes.append(True)
            )
            scrollbar = guide.browser.verticalScrollBar()
            self.assertGreater(scrollbar.maximum(), 0)
            scrollbar.setValue(scrollbar.maximum())
            for _ in range(8):
                self.app.processEvents()
            self.assertEqual(scrollbar.value(), scrollbar.maximum())
            self.assertEqual(content_changes, [])
            guide.close()


if __name__ == "__main__":
    unittest.main()
