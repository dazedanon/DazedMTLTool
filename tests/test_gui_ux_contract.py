"""Behavioral checks for shared GUI accessibility and semantic contracts."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QObject, QSettings, QUrl, Qt
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
        status = QLabel()

        set_status_text(status, "Could not load files", "error")

        self.assertEqual(status.text(), "Could not load files")
        self.assertEqual(status.objectName(), "appStatusText")
        self.assertEqual(status.property("state"), "error")

    def test_len_handoff_tracks_selected_game_and_scope(self):
        from gui.len_translation_tab import LenTranslationTab
        from util.len_translation import load_project, request_context
        from util.reference_games import load_registry
        from util.vocab import read_game_vocab
        from tests.test_len_translation import guidance_fixture, make_skill

        with tempfile.TemporaryDirectory() as raw, guidance_fixture(Path(raw)):
            root = Path(raw)
            game = root / "game"
            game.mkdir()
            second_game = root / "second-game"
            second_game.mkdir()
            settings = QSettings(str(root / "settings.ini"), QSettings.IniFormat)
            tab = LenTranslationTab(settings=settings, skill_root=make_skill(root / "skill"))
            try:
                tab.game_edit.setText(str(game))
                tab._load_game()
                tab.images_check.setChecked(False)
                self.assertFalse((game / ".dazedtl/len-method").exists())
                self.assertFalse(tab.guidance_section.toggle.isChecked())
                self.assertTrue(tab.copy_button.isEnabled(), tab.status.text())
                tab.copy_button.click()
                self.assertEqual(self.app.clipboard().text(), tab.preview.toPlainText())
                saved = load_project(game)
                self.assertFalse(saved.include_images)
                self.assertEqual(self.app.clipboard().text(), (saved.workspace / "handoff.md").read_text())
                self.assertTrue((saved.workspace / "setup.md").is_file())
                tab.guidance_section.toggle.click()
                tab.review_button.click()
                self.assertTrue(tab._context_dialog.copy_setup_button.isHidden())
                editors = tab._context_dialog.editors
                editors.vocab_editor.setPlainText("# Game Terms\n鍵 (Key)\n")
                editors._save_vocab()
                editors.quirks_editor.setPlainText("Keep pauses.")
                editors._save_quirks()
                self.assertIn("鍵 (Key)", read_game_vocab(game))
                self.assertIn("Keep pauses.", request_context(saved, ["鍵"])["system"])
                tab._context_dialog.close()
                tab.references_button.click()
                references = tab._references_dialog
                jp, en = root / "jp", root / "en"
                jp.mkdir()
                en.mkdir()
                (jp / "Text.json").write_text(json.dumps({"line": "鍵"}))
                (en / "Text.json").write_text(json.dumps({"line": "Old Key"}))
                with (
                    patch("gui.reference_games_dialog.QFileDialog.getExistingDirectory", side_effect=[str(jp), str(en)]),
                    patch("gui.reference_games_dialog.QInputDialog.getText", return_value=("Earlier Game", True)),
                ):
                    references._add_pair()
                self.assertEqual(references.references.count(), 1, references.status.text())
                self.assertEqual(len(load_registry(game)["references"]), 1)
                self.assertIn("鍵", request_context(saved, ["鍵"])["reference_translations"]["matches"])
                references.close()
                (saved.workspace / "status.md").write_text("Needs in-game verification.")
                tab._refresh_progress()
                self.assertEqual(tab.progress_text.toPlainText(), "Needs in-game verification.")
                tab.stage_combo.setCurrentIndex(tab.stage_combo.findData("qa"))
                self.assertTrue(tab.copy_button.isEnabled())
                self.assertEqual(tab.preview.toPlainText(), "")
                tab.copy_button.click()
                self.assertEqual(load_project(game).stage, "qa")
                current = json.loads((saved.workspace / "context.json").read_text())
                self.assertIn("Keep pauses.", current["system"])
                self.assertEqual(len(current["references"]["references"]), 1)
                copied = self.app.clipboard().text()
                with patch("gui.len_translation_tab.prepare_project", side_effect=ValueError("Invalid guidance")):
                    tab.copy_button.click()
                self.assertEqual(self.app.clipboard().text(), copied)
                self.assertEqual(tab.preview.toPlainText(), "")
                tab.game_edit.setText(str(second_game))
                self.assertFalse(tab.copy_button.isEnabled())
                tab._load_game()
                editors.vocab_editor.setPlainText("stale edit")
                editors._save_vocab()
                self.assertFalse((second_game / ".dazedtl/glossary.txt").exists())
                self.assertEqual(references.references.count(), 0)
                self.assertTrue(tab.copy_button.isEnabled())
                self.assertEqual(tab.preview.toPlainText(), "")
                self.assertEqual(tab.progress_text.toPlainText(), "")
                self.assertTrue(tab.images_check.isChecked())
                tab.game_edit.setText(str(game))
                tab._load_game()
                self.assertFalse(tab.images_check.isChecked())
                self.assertEqual(tab.stage_combo.currentData(), "qa")
                tab.references_button.click()
                references.references.setCurrentRow(0)
                references._remove()
                self.assertEqual(load_registry(game)["references"], [])
            finally:
                tab.close()

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
