"""Structural regression tests for the RPG Maker workflow visual system."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt5.QtCore import QSettings, Qt
from PyQt5.QtGui import QPalette
from PyQt5.QtWidgets import QApplication, QPushButton, QWidget

from gui.theme import COLORS, contrast_ratio, dark_palette
from gui.workflow_components import (
    DisclosureSection,
    WorkflowActivityPanel,
    WorkflowPageHeader,
    WorkflowStageCard,
)
from util.game_settings import (
    GameSettingsError,
    load_game_wrap_widths,
    save_game_wrap_widths,
)
from util.paths import GLOSSARY_BASE_SEPARATOR


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
        self.saved_game.joinpath("data").mkdir()
        self.saved_game.joinpath("data", "System.json").write_text(
            "{}", encoding="utf-8"
        )
        glossary = self.saved_game / ".dazedtl" / "glossary.txt"
        glossary.parent.mkdir()
        glossary.write_text(
            "# Game Characters\nユウ (Yuu)\n\n"
            + GLOSSARY_BASE_SEPARATOR
            + "base\n",
            encoding="utf-8",
        )
        self.settings = QSettings(
            str(Path(self.temp.name) / "workflow.ini"), QSettings.IniFormat
        )
        self.settings.setValue("workflow/last_game_folder", str(self.saved_game))
        with (
            patch("gui.workflow_tab.QSettings", return_value=self.settings),
            patch("gui.workflow_tab.QTimer.singleShot"),
        ):
            from gui.workflow_tab import WorkflowTab

            self.workflow = WorkflowTab()
        self.assertTrue(self.workflow.setup_editors.reload_all())
        self.workflow._prepared_game_root = str(self.saved_game)
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
        glossary = self.saved_game / ".dazedtl" / "glossary.txt"
        self.assertTrue(glossary.exists())
        self.assertIn("ユウ (Yuu)", self.workflow.setup_editors.vocab_editor.toPlainText())

        self.workflow.setup_editors._save_vocab()
        self.assertTrue(glossary.is_file())

        self.assertEqual(self.workflow._step_tabs.count(), 10)
        self.assertEqual(len(self.workflow._step_rail.buttons), 10)
        self.assertEqual(
            [button.accessibleName() for button in self.workflow._step_rail.buttons[7:10]],
            ["Step 8: QA", "Step 9: Images", "Step 10: Playtest"],
        )
        prepare_page = self.workflow._step_tabs.widget(1)
        self.assertEqual(len(prepare_page.findChildren(WorkflowStageCard)), 4)
        self.assertFalse(
            any(
                "optional" in button.text().casefold()
                for button in prepare_page.findChildren(QPushButton)
            )
        )
        qa_help = self.workflow._qa_ai_help_banner.text_label.text()
        self.assertIn("full-game release gate once", qa_help)
        self.assertIn("Targeted modes are optional", qa_help)
        self.assertIn("DazedTL owns coverage", qa_help)
        investigation_help = self.workflow._investigation_help_banner.text_label.text()
        self.assertIn("compare English against", investigation_help)
        self.assertIn("directly maintaining confirmed", investigation_help)
        self.workflow._refresh_reference_games()
        self.assertIsNotNone(self.workflow.reference_games_list)
        self.assertIn("optional", self.workflow.reference_games_status.text().casefold())
        self.assertIn("Reload the existing Setup editors", investigation_help)
        self.assertEqual(
            self.workflow._investigation_copy_btn.text(), "Copy investigation skill"
        )
        self.assertEqual(
            self.workflow._investigation_review_guidance_btn.text(),
            "Reload and review guidance",
        )
        self.assertEqual(
            self.workflow._qa_prepare_btn.text(), "Prepare / resume QA"
        )
        self.assertEqual(
            self.workflow._qa_rebuild_btn.text(), "Copy final rebuild handoff"
        )

        self.workflow._goto_step(7)
        existing_glossary = glossary.read_text(encoding="utf-8")
        glossary.write_text(
            existing_glossary.replace("ユウ (Yuu)", "ユウ (Yu)"),
            encoding="utf-8",
        )
        quirks = self.saved_game / ".dazedtl" / "skills" / "quirks.md"
        quirks.parent.mkdir(parents=True, exist_ok=True)
        quirks.write_text("- Preserve the confirmed running joke.\n", encoding="utf-8")
        self.workflow.setup_editors.quirks_editor.setPlainText("stale editor content")
        self.workflow._reload_investigation_guidance()
        self.app.processEvents()
        self.assertEqual(self.workflow._step_tabs.currentIndex(), 2)
        self.assertEqual(self.workflow.setup_editors._editors.currentIndex(), 1)
        self.assertEqual(
            self.workflow.setup_editors.quirks_editor.toPlainText(),
            "- Preserve the confirmed running joke.\n",
        )
        self.assertIn("ユウ (Yu)", self.workflow.setup_editors.vocab_editor.toPlainText())

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

        conflict_game = Path(self.temp.name) / "Migration Conflict"
        conflict_game.joinpath("data").mkdir(parents=True)
        conflict_game.joinpath("data", "System.json").write_text(
            "{}", encoding="utf-8"
        )
        conflict_game.joinpath("skills").mkdir(parents=True)
        conflict_game.joinpath(".dazedtl", "skills").mkdir(parents=True)
        legacy_glossary = conflict_game / "glossary.txt"
        legacy_glossary.write_text("Legacy (Legacy)\n", encoding="utf-8")
        self.workflow.file_list.addItem("OldGameMap.json")
        self.workflow._data_path = "/old/game/data"
        self.workflow._prepared_game_root = str(self.saved_game)
        stale_generation = self.workflow._project_generation
        self.workflow.git_prepare.set_game_root(self.saved_game)
        self.workflow.rewrap_file_list.addItem("OldGameMap.json")
        self.workflow.rewrap_scan_btn.setEnabled(True)
        self.workflow.rewrap_apply_btn.setEnabled(True)
        for button in self.workflow._import_buttons:
            button.setEnabled(True)
        self.workflow.folder_edit.setText(str(conflict_game))
        self.assertEqual(self.workflow.file_list.count(), 0)
        self.assertIsNone(self.workflow._data_path)
        self.assertTrue(
            all(not button.isEnabled() for button in self.workflow._import_buttons)
        )

        startup_game = Path(self.temp.name) / "Invalid Saved Game"
        startup_game.joinpath("skills").mkdir(parents=True)
        startup_game.joinpath("glossary.txt").write_text(
            "startup legacy\n", encoding="utf-8"
        )
        startup_game.joinpath("skills", "guide.md").write_text(
            "startup skill\n", encoding="utf-8"
        )
        startup_settings = QSettings(
            str(Path(self.temp.name) / "startup.ini"), QSettings.IniFormat
        )
        startup_settings.setValue("workflow/last_game_folder", str(startup_game))
        with (
            patch("gui.workflow_tab.QSettings", return_value=startup_settings),
            patch("gui.workflow_tab.QTimer.singleShot"),
        ):
            from gui.workflow_tab import WorkflowTab

            startup_workflow = WorkflowTab()
        try:
            self.assertFalse(startup_game.joinpath(".dazedtl").exists())
            self.assertFalse(startup_game.joinpath(".gitignore").exists())
            self.assertEqual(
                startup_workflow.setup_editors.vocab_editor.toPlainText(), ""
            )
            self.assertFalse(startup_workflow._detect_folder())
            self.assertEqual(
                startup_settings.value("workflow/last_game_folder", ""), ""
            )
        finally:
            startup_workflow.close()
            startup_workflow.deleteLater()
        self.assertEqual(self.workflow.git_prepare._game_root, "")
        self.assertEqual(self.workflow.rewrap_file_list.count(), 0)
        self.assertFalse(self.workflow.rewrap_scan_btn.isEnabled())
        self.assertFalse(self.workflow.rewrap_apply_btn.isEnabled())
        self.workflow._on_scan_done(
            [
                {
                    "name": "LateMap.json",
                    "path": "/old/LateMap.json",
                    "size_kb": 1,
                    "category": "map",
                    "default": True,
                }
            ],
            stale_generation,
            str(self.saved_game),
        )
        self.assertEqual(self.workflow.file_list.count(), 0)
        self.assertEqual(self.settings.value("workflow/last_game_folder", ""), "")

        self.assertFalse(self.workflow.setup_editors.reload_all())
        self.assertTrue(legacy_glossary.is_file())
        self.assertFalse(
            conflict_game.joinpath(".dazedtl", "glossary.txt").exists()
        )
        self.assertIn(
            "Could not prepare portable game guidance",
            self.workflow.log_area.toPlainText(),
        )
        self.assertEqual(self.workflow.setup_editors.vocab_editor.toPlainText(), "")
        self.assertEqual(self.workflow.setup_editors.quirks_editor.toPlainText(), "")
        self.assertEqual(self.workflow.setup_editors.game_skill_editor.toPlainText(), "")

        self.workflow.setup_editors.vocab_editor.setPlainText("wrong game content")
        self.workflow.setup_editors._save_vocab()
        self.assertFalse(
            conflict_game.joinpath(".dazedtl", "glossary.txt").exists()
        )

        self.workflow.file_list.addItem("OldGameMap.json")
        self.workflow._data_path = "/old/game/data"
        for button in self.workflow._import_buttons:
            button.setEnabled(True)
        self.workflow._detect_folder()
        self.assertEqual(
            self.workflow.detected_label.text(),
            "Portable guidance needs attention",
        )
        self.assertEqual(self.workflow.file_list.count(), 0)
        self.assertIsNone(self.workflow._data_path)
        self.assertTrue(
            all(not button.isEnabled() for button in self.workflow._import_buttons)
        )

        self.workflow._apply_wrap_config()
        self.assertFalse(
            conflict_game.joinpath(".dazedtl", "settings.json").exists()
        )

        reload_only_game = Path(self.temp.name) / "Reload Only"
        reload_only_game.joinpath("skills").mkdir(parents=True)
        reload_only_game.joinpath("skills", "quirks.md").write_text(
            "legacy quirks\n", encoding="utf-8"
        )
        reload_only_game.joinpath("glossary.txt").write_text(
            "legacy glossary\n", encoding="utf-8"
        )
        self.workflow.folder_edit.setText(str(reload_only_game))
        self.workflow.setup_editors._reload_quirks()
        self.assertTrue(reload_only_game.joinpath("skills", "quirks.md").is_file())
        self.assertFalse(reload_only_game.joinpath(".dazedtl", "skills").exists())
        self.assertEqual(self.workflow.setup_editors.quirks_editor.toPlainText(), "")
        self.workflow._detect_folder()
        self.assertTrue(reload_only_game.joinpath("glossary.txt").is_file())
        self.assertTrue(reload_only_game.joinpath("skills", "quirks.md").is_file())
        self.assertFalse(reload_only_game.joinpath(".dazedtl").exists())
        self.assertFalse(reload_only_game.joinpath(".gitignore").exists())
        self.assertEqual(self.settings.value("workflow/last_game_folder", ""), "")

        for label, marker_path in (
            ("WOLF", reload_only_game / "Data.wolf"),
            ("unknown JSON", reload_only_game / "config" / "settings.json"),
        ):
            with self.subTest(label):
                marker_path.parent.mkdir(parents=True, exist_ok=True)
                marker_path.write_bytes(
                    b"" if marker_path.suffix == ".wolf" else b"{}"
                )
                self.workflow._detect_folder()
                self.assertTrue(reload_only_game.joinpath("glossary.txt").is_file())
                self.assertTrue(
                    reload_only_game.joinpath("skills", "quirks.md").is_file()
                )
                self.assertFalse(reload_only_game.joinpath(".dazedtl").exists())
                self.assertEqual(
                    self.settings.value("workflow/last_game_folder", ""), ""
                )
                marker_path.unlink()

        self.workflow.file_list.addItem("StillOld.json")
        self.workflow._data_path = "/still/old/data"
        for button in self.workflow._import_buttons:
            button.setEnabled(True)
        self.workflow.folder_edit.setText("")
        self.workflow._detect_folder()
        self.assertEqual(self.workflow.file_list.count(), 0)
        self.assertIsNone(self.workflow._data_path)
        self.assertTrue(
            all(not button.isEnabled() for button in self.workflow._import_buttons)
        )

    def test_activity_console_is_pinned_below_the_workflow(self):
        self.assertTrue(self.workflow._activity_panel.isVisible())
        self.assertEqual(self.workflow._workflow_splitter.orientation(), Qt.Vertical)
        self.assertFalse(self.workflow._workflow_splitter.isCollapsible(1))
        first = self.workflow._step_tabs.widget(0).findChild(WorkflowPageHeader)
        middle = self.workflow._step_tabs.widget(1).findChild(WorkflowPageHeader)
        last = self.workflow._step_tabs.widget(9).findChild(WorkflowPageHeader)

        self.assertIsNone(first.back_button)
        self.assertIsNotNone(first.continue_button)
        self.assertIsNotNone(middle.back_button)
        self.assertIsNotNone(middle.continue_button)
        self.assertIsNotNone(last.back_button)
        self.assertIsNone(last.continue_button)
        self.assertIsNone(self.workflow.findChild(QWidget, "workflowFooter"))

    def test_activity_log_uses_shared_semantic_colors_and_plain_text(self):
        panel = self.workflow._activity_panel
        panel.append_message("\x1b[31m❌ Injection failed\x1b[0m")
        panel.append_message("⚠ Translation mismatch")
        panel.append_message("✅ Injection completed")
        panel.append_message("Neutral status")
        panel.append_message("")
        panel.append_message("────────────────")
        panel.append_message("Neutral status")

        self.assertEqual(
            panel.log.toPlainText().splitlines(),
            [
                "❌ Injection failed",
                "⚠ Translation mismatch",
                "✅ Injection completed",
                "Neutral status",
            ],
        )
        html = panel.log.toHtml().casefold()
        self.assertIn(COLORS.danger.casefold(), html)
        self.assertIn(COLORS.warning.casefold(), html)
        self.assertIn(COLORS.success.casefold(), html)
        self.assertIn(COLORS.text_primary.casefold(), html)
        self.assertEqual(panel.message_kind("0 failed"), "info")
        self.assertEqual(panel.message_kind("No errors found"), "info")
        self.assertEqual(panel.message_kind("Could not save file"), "error")

        panel.clear_activity()
        self.assertFalse(panel.log.toPlainText())
        self.assertEqual(panel.summary_label.text(), "Activity Console · Idle")

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



    def test_phase_one_widths_follow_the_selected_game(self):
        game_b = Path(self.temp.name) / "Game B"
        game_b.mkdir()
        cases = (
            (self.saved_game, (82, 68, 104, 91)),
            (game_b, (54, 44, 76, 65)),
        )

        with patch.dict(os.environ, {}, clear=False):
            for game, widths in cases:
                self.workflow.folder_edit.setText(str(game))
                self.assertTrue(self.workflow.setup_editors.reload_all())
                for spin, value in zip(
                    (
                        self.workflow.wrap_width_spin,
                        self.workflow.wrap_face_spin,
                        self.workflow.wrap_list_spin,
                        self.workflow.wrap_note_spin,
                    ),
                    widths,
                ):
                    spin.setValue(value)
                self.workflow._apply_wrap_config()

            for game, widths in cases:
                self.workflow.folder_edit.setText(str(game))
                self.workflow.refresh_wrap_widths_for_game()
                self.workflow._load_rewrap_widths()
                self.assertEqual(
                    (
                        self.workflow.wrap_width_spin.value(),
                        self.workflow.wrap_face_spin.value(),
                        self.workflow.wrap_list_spin.value(),
                        self.workflow.wrap_note_spin.value(),
                    ),
                    widths,
                )
                self.assertEqual(
                    (
                        self.workflow.rewrap_dialogue_width.value(),
                        self.workflow.rewrap_face_width.value(),
                        self.workflow.rewrap_list_width.value(),
                        self.workflow.rewrap_note_width.value(),
                    ),
                    widths,
                )
                self.assertEqual(
                    tuple(
                        int(os.environ[key])
                        for key in ("width", "faceWidth", "listWidth", "noteWidth")
                    ),
                    widths,
                )
                saved = json.loads(
                    game.joinpath(".dazedtl", "settings.json").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(
                    tuple(saved["rpgmaker"]["wrapWidths"].values()), widths
                )

            rewrap_widths = (63, 57, 88, 77)
            self.assertTrue(self.workflow.setup_editors.reload_all())
            for spin, value in zip(
                (
                    self.workflow.rewrap_dialogue_width,
                    self.workflow.rewrap_face_width,
                    self.workflow.rewrap_list_width,
                    self.workflow.rewrap_note_width,
                ),
                rewrap_widths,
            ):
                spin.setValue(value)
            self.workflow._save_rewrap_widths()
            self.assertEqual(
                (
                    self.workflow.wrap_width_spin.value(),
                    self.workflow.wrap_face_spin.value(),
                    self.workflow.wrap_list_spin.value(),
                    self.workflow.wrap_note_spin.value(),
                ),
                rewrap_widths,
            )
            self.assertEqual(
                tuple(load_game_wrap_widths(game_b).values()), rewrap_widths
            )

            linked_game = Path(self.temp.name) / "Linked Settings"
            linked_game.joinpath(".dazedtl").mkdir(parents=True)
            external = Path(self.temp.name) / "external-settings.json"
            external.write_text(
                json.dumps({"rpgmaker": {"wrapWidths": {"width": 99}}}),
                encoding="utf-8",
            )
            linked_game.joinpath(".dazedtl", "settings.json").symlink_to(external)
            with self.assertRaisesRegex(GameSettingsError, "not a regular file"):
                load_game_wrap_widths(linked_game)

            linked_metadata_game = Path(self.temp.name) / "Linked Metadata"
            linked_metadata_game.mkdir()
            external_metadata = Path(self.temp.name) / "external-metadata"
            external_metadata.mkdir()
            linked_metadata_game.joinpath(".dazedtl").symlink_to(
                external_metadata,
                target_is_directory=True,
            )
            with self.assertRaisesRegex(GameSettingsError, "not a normal folder"):
                save_game_wrap_widths(linked_metadata_game, {"width": 80})
            self.assertFalse(linked_metadata_game.joinpath(".gitignore").exists())

    def test_unsaved_game_widths_fall_back_to_env_and_clamp_face(self):
        with patch(
            "gui.workflow_tab.dotenv_values",
            return_value={"width": "48", "faceWidth": "70"},
        ):
            self.workflow.refresh_wrap_widths_for_game()

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
        self.assertTrue(panel.isVisible())
        self.assertEqual(self.workflow._workflow_splitter.orientation(), Qt.Vertical)
        self.assertFalse(self.workflow._workflow_splitter.isCollapsible(1))
        first = self.workflow._step_tabs.widget(0).findChild(WorkflowPageHeader)
        self.assertIsNotNone(first.continue_button)
        self.assertIsNone(self.workflow.findChild(QWidget, "workflowFooter"))
        prepare_page = self.workflow._step_tabs.widget(1)
        self.assertEqual(len(prepare_page.findChildren(WorkflowStageCard)), 3)
        self.assertFalse(
            any(
                "optional" in button.text().casefold()
                for button in prepare_page.findChildren(QPushButton)
            )
        )

        walkthrough_game = Path(self.temp.name) / "Walkthrough Game"
        walkthrough_game.mkdir()
        walkthrough_button = next(
            button
            for button in self.workflow._step_tabs.widget(8).findChildren(QPushButton)
            if button.text() == "Copy walkthrough skill"
        )
        QApplication.clipboard().clear()
        with patch.object(
            self.workflow,
            "_prepared_project_or_warn",
            return_value=str(walkthrough_game),
        ):
            walkthrough_button.click()
        walkthrough_prompt = QApplication.clipboard().text()
        self.assertIn(str(walkthrough_game.resolve()), walkthrough_prompt)
        self.assertIn("WOLF RPG", walkthrough_prompt)
        panel.clear_requested.emit()

        self.workflow._log("❌ Injection failed")
        self.assertEqual(panel.log.toPlainText(), "❌ Injection failed")

        panel.clear_requested.emit()
        self.assertFalse(panel.log.toPlainText())
        self.assertEqual(panel.summary_label.text(), "Activity Console · Idle")

        unrelated = Path(self.temp.name) / "Not A Wolf Game"
        unrelated.joinpath("skills").mkdir(parents=True)
        unrelated.joinpath("glossary.txt").write_text("legacy\n", encoding="utf-8")
        unrelated.joinpath("skills", "guide.md").write_text(
            "legacy skill\n", encoding="utf-8"
        )
        class RunningWorker:
            @staticmethod
            def isRunning():
                return True

        self.workflow._worker = RunningWorker()
        generation = self.workflow._project_generation
        self.assertFalse(self.workflow._detect_folder())
        self.assertEqual(self.workflow._project_generation, generation)
        self.workflow._worker = None
        with (
            patch(
                "gui.wolf_workflow_tab.QFileDialog.getExistingDirectory",
                return_value=str(unrelated),
            ),
            patch.object(self.workflow, "_ask_clear_old_files") as clear_old,
        ):
            self.workflow._browse_folder()
        clear_old.assert_not_called()
        self.assertTrue(unrelated.joinpath("glossary.txt").is_file())
        self.assertTrue(unrelated.joinpath("skills", "guide.md").is_file())
        self.assertFalse(unrelated.joinpath(".dazedtl").exists())
        self.assertFalse(unrelated.joinpath(".gitignore").exists())
        self.assertEqual(
            self.settings.value("wolf_workflow/last_game_folder", ""), ""
        )

        conflict = Path(self.temp.name) / "Conflict"
        conflict.joinpath("skills").mkdir(parents=True)
        conflict.joinpath("Data.wolf").write_bytes(b"")
        conflict.joinpath(".dazedtl", "skills").mkdir(parents=True)
        self.workflow.file_list.addItem("OldWolfMap.json")
        self.workflow._layout = {"engine": "WOLF", "data_dir": "/old/data"}
        for button in self.workflow._import_buttons:
            button.setEnabled(True)
        self.workflow.folder_edit.setText(str(conflict))
        self.assertEqual(self.workflow.file_list.count(), 0)
        self.assertEqual(self.workflow._layout, {})
        self.assertTrue(
            all(not button.isEnabled() for button in self.workflow._import_buttons)
        )
        self.assertEqual(
            self.settings.value("wolf_workflow/last_game_folder", ""), ""
        )
        self.workflow.file_list.addItem("OldWolfMap.json")
        self.workflow._layout = {"engine": "WOLF", "data_dir": "/old/data"}
        for button in self.workflow._import_buttons:
            button.setEnabled(True)
        self.workflow._detect_folder()
        self.assertEqual(
            self.workflow.detected_label.text(),
            "Portable guidance needs attention",
        )
        self.assertEqual(self.workflow.file_list.count(), 0)
        self.assertEqual(self.workflow._layout, {})
        self.assertTrue(
            all(not button.isEnabled() for button in self.workflow._import_buttons)
        )

        nested_game = Path(self.temp.name) / "Nested Data Game"
        nested_basic = nested_game / "Data" / "Data" / "BasicData"
        nested_basic.mkdir(parents=True)
        (nested_basic / "CommonEvent.dat").write_bytes(b"keep")
        nested_game.joinpath("Data.wolf").write_bytes(b"archive")
        self.workflow.folder_edit.setText(str(nested_game))

        def validate_guidance_before_repair():
            self.assertTrue((nested_basic / "CommonEvent.dat").is_file())
            return True

        with (
            patch.object(
                self.workflow.setup_editors,
                "reload_all",
                side_effect=validate_guidance_before_repair,
            ),
            patch("gui.wolf_workflow_tab.QTimer.singleShot"),
        ):
            self.assertTrue(self.workflow._detect_folder())
        repaired_basic = nested_game / "Data" / "BasicData" / "CommonEvent.dat"
        self.assertEqual(repaired_basic.read_bytes(), b"keep")
        self.assertFalse((nested_game / "Data" / "Data").exists())
        self.assertTrue(self.workflow._layout["unpacked"])
        self.assertEqual(self.workflow._layout["unpack_gaps"], [])
        with (
            patch.object(self.workflow, "_unpack") as unpack,
            patch.object(self.workflow, "_extract_to_work_dir") as extract,
        ):
            self.workflow._ensure_wolf_json()
        unpack.assert_not_called()
        extract.assert_called_once()

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
