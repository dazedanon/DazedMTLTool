"""Action-level regression harness for the RPG Maker workflow.

These tests complement screenshot/geometry coverage.  They click the production
controls, verify their signal routing, and exercise mutation boundaries with
disposable projects and fake workers.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QWidget,
)

from gui.workflow_tab import (
    PHASE0_CONFIG,
    PHASE1B_CONFIG,
    PHASE1_CONFIG,
    PHASE2_CONFIG,
)
from tests.workflow_action_harness import FakeWorker, WorkflowHarness


class WorkflowActionWiringTests(unittest.TestCase):
    """Every visible action must still reach its intended endpoint."""

    def setUp(self) -> None:
        self.harness = WorkflowHarness(probe=True)
        self.workflow = self.harness.workflow

    def tearDown(self) -> None:
        self.harness.close()

    def assert_routes(self, step: int, expected: str, **locator) -> None:
        self.harness.clear_actions()
        self.harness.click(step, **locator)
        names = [call.name for call in self.workflow.actions]
        self.assertIn(expected, names, (step, locator, names))

    def test_all_step_action_buttons_route_to_their_contract_endpoints(self):
        cases = (
            (0, "browse_folder", {"tooltip": "Choose an RPG Maker game folder"}),
            (0, "select_all_files", {"text": "Select all"}),
            (0, "deselect_all_files", {"text": "Clear selection"}),
            (0, "select_core_only", {"text": "Database only"}),
            (0, "import_files", {"text": "Import selected files"}),
            (1, "run_dazedformat", {"text": "Format game data"}),
            (1, "browse_plugins_js", {"tooltip": "Choose the plugins.js file"}),
            (1, "run_prettier", {"text": "Format plugins.js"}),
            (1, "browse_gameupdate", {"tooltip": "Choose the GameUpdate source folder"}),
            (1, "run_gameupdate", {"text": "Install GameUpdate"}),
            (1, "run_all_preprocess", {"text": "Run available tasks"}),
            (2, "import_files", {"text": "Import files"}),
            (2, "clear_translated", {"text": "Clear translated"}),
            (2, "run_parse_speakers", {"text": "Collect names"}),
            (2, "copy_project_setup_prompt", {"text": "Copy setup skill"}),
            (3, "apply_wrap_config", {"text": "Save line widths"}),
            (3, "run_phase", {"text": "Translate database"}),
            (3, "run_phase", {"text": "Translate dialogue"}),
            (3, "run_phase", {"text": "Build variable cache"}),
            (4, "copy_plugin_prompt", {"text": "Copy advanced-text audit"}),
            (4, "apply_var_range", {"text": "Save range"}),
            (4, "run_phase", {"text": "Translate selected text"}),
            (5, "copy_vocab_to_game", {"text": "Copy glossary to game"}),
            (5, "copy_plugins_js_translate_prompt", {"text": "Copy plugin skill"}),
            (5, "export_active_files", {"text": "Export selected files"}),
            (5, "export_to_game", {"text": "Export all translated files"}),
            (6, "select_rewrap_files", {"text": "Select all"}),
            (6, "select_rewrap_files", {"text": "Maps & events"}),
            (6, "select_rewrap_files", {"text": "Database only"}),
            (6, "select_rewrap_files", {"text": "Clear selection"}),
            (6, "refresh_rewrap_files", {"text": "Refresh files"}),
            (6, "load_rewrap_widths", {"text": "Load saved line widths"}),
            (6, "run_rewrap", {"text": "Preview rewrap"}),
            (6, "run_rewrap", {"text": "Apply rewrap"}),
            (6, "copy_translation_qa_prompt", {"text": "Copy final QA skill"}),
            (6, "create_public_release", {"text": "Build public release ZIP"}),
            (7, "refresh_image_workflow_status", {"text": "Refresh readiness"}),
            (7, "copy_vocab_to_game", {"text": "Copy glossary to game"}),
            (7, "open_image_manager", {"text": "Open Image Manager"}),
            (8, "detect_tli_editors", {"text": "Find editors"}),
            (8, "browse_tli_editor", {"text": "Choose…"}),
            (8, "save_playtest_settings", {"text": "Save defaults"}),
            (8, "apply_playtest_settings", {"text": "Apply settings to game"}),
            (8, "install_tl_inspector", {"text": "Install TL Inspector"}),
            (8, "uninstall_tl_inspector", {"text": "Remove TL Inspector"}),
            (8, "install_forge", {"text": "Install Forge"}),
            (8, "uninstall_forge", {"text": "Remove Forge"}),
            (8, "install_both_playtest", {"text": "Install both plugins"}),
            (8, "refresh_playtest_status", {"text": "Refresh plugin status"}),
        )
        self.assertEqual(len(cases), 49)
        for step, endpoint, locator in cases:
            with self.subTest(step=step, endpoint=endpoint, locator=locator):
                self.assert_routes(step, endpoint, **locator)

    def test_line_edit_checkbox_and_editor_actions_are_wired(self):
        self.workflow.folder_edit.returnPressed.emit()
        self.assertEqual(self.workflow.actions[-1].name, "detect_folder")

        for checkbox in (
            self.workflow.spk_inline_cb,
            self.workflow.spk_firstline_cb,
            self.workflow.spk_face_cb,
        ):
            self.harness.clear_actions()
            checkbox.click()
            self.assertIn(
                "apply_speaker_flags",
                [call.name for call in self.workflow.actions],
            )

        editors = self.workflow.setup_editors
        expected = (
            ({"tooltip": "Save guidance changes"}, "save_game_skill"),
            ({"tooltip": "Reload guidance from disk"}, "reload_game_skill"),
            ({"tooltip": "Save rules changes"}, "save_quirks"),
            ({"tooltip": "Reload rules from disk"}, "reload_quirks"),
            ({"tooltip": "Save glossary changes"}, "save_vocab"),
            ({"tooltip": "Reload glossary from disk"}, "reload_vocab"),
            ({"text": "+ Add custom guidance"}, "add_custom_skill"),
        )
        for locator, endpoint in expected:
            editors.actions.clear()
            self.harness.click(2, **locator)
            self.assertIn(endpoint, [call.name for call in editors.actions])

    def test_local_disclosures_and_rewrap_presets_change_only_ui_state(self):
        self.workflow._goto_step(1)
        self.harness.app.processEvents()
        toggle = self.harness.button(1, text="Hide optional")
        self.assertTrue(self.workflow._pp_dazedformat_box.isVisible())
        toggle.click()
        self.assertFalse(self.workflow._pp_dazedformat_box.isVisible())
        self.assertEqual(toggle.text(), "Show optional")

        self.harness.click(6, text="Messages only")
        self.assertEqual(self.workflow.rewrap_codes_edit.text(), "401,405")
        self.harness.click(6, text="All supported fields")
        self.assertEqual(self.workflow.rewrap_codes_edit.text(), "")

    def test_help_and_navigation_controls_remain_connected(self):
        with patch("gui.workflow_tab._show_step_help") as show_help:
            for step in range(9):
                self.harness.click(step, text="?  Help")
            self.assertEqual(show_help.call_count, 9)

        self.workflow._goto_step(3)
        self.harness.click(3, text="Continue  →")
        self.assertEqual(self.workflow._step_tabs.currentIndex(), 4)
        self.assertIn(3, self.workflow._step_done)
        self.harness.click(4, text="←  Back")
        self.assertEqual(self.workflow._step_tabs.currentIndex(), 3)


class WorkflowHandlerContractTests(unittest.TestCase):
    """Real handlers run against disposable paths and substituted boundaries."""

    def setUp(self) -> None:
        FakeWorker.reset()
        self.harness = WorkflowHarness()
        self.workflow = self.harness.workflow

    def tearDown(self) -> None:
        self.harness.close()
        FakeWorker.reset()

    def test_project_selection_and_auto_import_preserve_exact_scope(self):
        items = [
            {"name": "Actors.json", "path": "/fixture/Actors.json", "size_kb": 1, "category": "core", "default": True},
            {"name": "Map001.json", "path": "/fixture/Map001.json", "size_kb": 1, "category": "map", "default": False},
        ]
        self.workflow._on_scan_done(items)
        self.workflow._select_core_only()
        self.assertEqual(
            [item["name"] for item in self.workflow._selected_import_items()],
            ["Actors.json"],
        )
        self.workflow._select_all_files()
        with patch("gui.workflow_tab._ImportWorker", FakeWorker):
            self.workflow._auto_import_if_needed()

        self.assertEqual(len(FakeWorker.instances), 1)
        worker = FakeWorker.instances[0]
        self.assertTrue(worker.started)
        self.assertEqual(worker.args[1], "files")
        self.assertEqual(
            [item["name"] for item in worker.args[0]],
            ["Actors.json", "Map001.json"],
        )
        self.assertEqual(
            self.workflow._pending_import_signature,
            ("Actors.json", "Map001.json"),
        )

    def test_import_and_clear_require_explicit_confirmation(self):
        selected = [{"name": "Actors.json", "path": "/fixture/Actors.json"}]
        existing = self.harness.root / "files" / "old.json"
        existing.write_text("{}", encoding="utf-8")
        with (
            patch("gui.workflow_tab._ImportWorker", FakeWorker),
            patch.object(QMessageBox, "warning", return_value=QMessageBox.Cancel) as warning,
        ):
            self.workflow._import_files(selected=selected)
        self.assertFalse(FakeWorker.instances)
        self.assertTrue(existing.exists())
        self.assertEqual(warning.call_args.args[-1], QMessageBox.Cancel)

        translated = self.harness.root / "translated" / "old.json"
        translated.write_text("{}", encoding="utf-8")
        with patch.object(QMessageBox, "warning", return_value=QMessageBox.Cancel):
            self.workflow._clear_translated()
        self.assertTrue(translated.exists())
        with patch.object(QMessageBox, "warning", return_value=QMessageBox.Yes):
            self.workflow._clear_translated()
        self.assertFalse(translated.exists())

    def test_mz_mv_and_ace_detection_use_disposable_project_roots(self):
        for engine in ("MZ", "MV"):
            game, data = self.harness.make_mvmz_project(engine)
            FakeWorker.reset()
            self.workflow.folder_edit.setText(str(game))
            with patch("gui.workflow_tab._ScanWorker", FakeWorker):
                self.workflow._detect_folder()
            self.assertEqual(Path(self.workflow._data_path), data)
            self.assertEqual(self.workflow._engine, "MVMZ")
            self.assertEqual(FakeWorker.instances[-1].args, (str(data), "MVMZ"))
            self.assertTrue(self.workflow._step_buttons[7].isVisible())
            self.assertTrue(self.workflow._step_buttons[8].isVisible())

        game, _data, ace_json = self.harness.make_ace_project()
        FakeWorker.reset()
        self.workflow.folder_edit.setText(str(game))
        with patch("gui.workflow_tab._ScanWorker", FakeWorker):
            self.workflow._detect_folder()
        self.assertEqual(Path(self.workflow._data_path), ace_json)
        self.assertEqual(FakeWorker.instances[-1].args, (str(ace_json), "MVMZ"))
        self.assertFalse(self.workflow._step_buttons[7].isVisible())
        self.assertFalse(self.workflow._step_buttons[8].isVisible())

    def test_prepare_actions_construct_the_expected_workers(self):
        game, data = self.harness.make_mvmz_project("MZ")
        plugins = game / "js" / "plugins.js"
        gameupdate = self.harness.root / "gameupdate"
        gameupdate.mkdir()
        self.workflow.folder_edit.setText(str(game))
        self.workflow._data_path = str(data)
        self.workflow.pp_plugins_edit.setText(str(plugins))
        self.workflow.pp_gameupdate_edit.setText(str(gameupdate))

        worker_specs = (
            ("_JsonFormatWorker", self.workflow._run_dazedformat, (str(data),)),
            ("_JsFormatWorker", self.workflow._run_prettier, (str(plugins),)),
            ("_FileCopyWorker", self.workflow._run_gameupdate, (str(gameupdate), str(game))),
        )
        for worker_name, action, expected_args in worker_specs:
            FakeWorker.reset()
            with patch(f"gui.workflow_tab.{worker_name}", FakeWorker):
                action()
            self.assertEqual(FakeWorker.instances[-1].args, expected_args)
            self.assertTrue(FakeWorker.instances[-1].started)

    def test_phase_actions_apply_exact_profiles_and_translation_presets(self):
        config = MagicMock()
        navigation = MagicMock()
        self.workflow._phase1_code408_cb.setChecked(True)
        first_p2_key, first_p2_check = next(iter(self.workflow._p2_code_checks.items()))
        first_p2_check.setChecked(not PHASE2_CONFIG.get(first_p2_key, False))

        expected = {
            0: (dict(PHASE0_CONFIG), "db"),
            1: (dict(PHASE1_CONFIG) | {"CODE408": True}, "events"),
            "1b": (dict(PHASE1B_CONFIG), "events"),
            2: (
                dict(PHASE2_CONFIG)
                | {key: check.isChecked() for key, check in self.workflow._p2_code_checks.items()},
                "events",
            ),
        }
        with (
            patch("gui.config_integration.ConfigIntegration", return_value=config),
            patch.object(self.workflow, "_navigate_to_translation", navigation),
            patch("gui.workflow_tab.QTimer.singleShot"),
        ):
            for phase, (profile, preset) in expected.items():
                config.reset_mock()
                navigation.reset_mock()
                self.workflow._run_phase(phase)
                config.update_rpgmaker_config.assert_called_once_with(profile)
                navigation.assert_called_once_with(
                    preset,
                    auto_start=True,
                    mode_text="Translate",
                )

    def test_phase_two_auto_save_preserves_code_plugin_and_pattern_keys(self):
        config = MagicMock()
        code_key, code_check = next(iter(self.workflow._p2_code_checks.items()))
        plugin_key, plugin_check = next(iter(self.workflow._p2_plugin_checks.items()))
        pattern_key, pattern_check = next(iter(self.workflow._p2_pattern_checks.items()))
        code_check.setChecked(True)
        plugin_check.setChecked(True)
        pattern_check.setChecked(True)
        self.workflow._p2_var_min.setText("12")
        self.workflow._p2_var_max.setText("345")
        with patch("gui.config_integration.ConfigIntegration", return_value=config):
            self.workflow._apply_p2_config()

        saved_codes = config.update_rpgmaker_config.call_args.args[0]
        self.assertTrue(saved_codes[code_key])
        self.assertEqual(saved_codes["CODE122_VAR_MIN"], 12)
        self.assertEqual(saved_codes["CODE122_VAR_MAX"], 345)
        enabled_plugins, enabled_patterns = config.update_plugin_config.call_args.args
        self.assertIn(plugin_key, enabled_plugins)
        self.assertIn(pattern_key, enabled_patterns)

    def test_speaker_flags_and_setup_editors_preserve_config_and_file_routes(self):
        config = MagicMock()
        states = (
            (self.workflow.spk_inline_cb, True),
            (self.workflow.spk_firstline_cb, False),
            (self.workflow.spk_face_cb, True),
        )
        for checkbox, checked in states:
            checkbox.blockSignals(True)
            checkbox.setChecked(checked)
            checkbox.blockSignals(False)
        with patch("gui.config_integration.ConfigIntegration", return_value=config):
            self.workflow._apply_speaker_flags()
        config.update_rpgmaker_config.assert_called_once_with(
            {
                "INLINE401SPEAKERS": True,
                "FIRSTLINESPEAKERS": False,
                "FACENAME101": True,
            }
        )

        editors = self.workflow.setup_editors
        write_vocab = MagicMock()
        editors.vocab_editor.setPlainText("term")
        with patch("gui.setup_skills_editors.write_game_vocab", write_vocab):
            editors._save_vocab()
        write_vocab.assert_called_once_with("term")
        with patch("gui.setup_skills_editors.read_game_vocab", return_value="loaded"):
            editors._reload_vocab()
        self.assertEqual(editors.vocab_editor.toPlainText(), "loaded")

        game = self.harness.root / "SetupGame"
        game.mkdir()
        self.workflow.folder_edit.setText(str(game))
        quirks = game / "skills" / "quirks.md"
        game_skill = game / "skills" / "game.md"
        with (
            patch("gui.setup_skills_editors.quirks_path_for_game", return_value=quirks),
            patch("gui.setup_skills_editors.game_skill_path_for_game", return_value=game_skill),
        ):
            editors.quirks_editor.setPlainText("quirk")
            editors._save_quirks()
            editors.quirks_editor.clear()
            editors._reload_quirks()
            self.assertEqual(editors.quirks_editor.toPlainText(), "quirk\n")

            editors.game_skill_editor.setPlainText("frame")
            editors._save_game_skill()
            editors.game_skill_editor.clear()
            editors._reload_game_skill()
            self.assertEqual(editors.game_skill_editor.toPlainText(), "frame\n")

    def test_parse_speakers_selects_event_files_and_starts_translation(self):
        class Host(QMainWindow):
            PAGE_TRANSLATION = 4

            def __init__(self):
                super().__init__()
                self.translation_tab = QWidget(self)
                tt = self.translation_tab
                tt.module_combo = QComboBox(tt)
                tt.module_combo.addItems(("Generic", "RPG Maker MV/MZ"))
                tt.mode_combo = QComboBox(tt)
                tt.mode_combo.addItems(("Translate", "Parse Speakers"))
                tt.file_list = QListWidget(tt)
                for name in ("Actors.json", "CommonEvents.json", "Map001.json"):
                    item = QListWidgetItem(name)
                    item.setCheckState(Qt.Unchecked)
                    tt.file_list.addItem(item)
                tt.refresh_file_lists = MagicMock()
                tt.start_translation = MagicMock()
                self.switched_to = None

            def switch_page(self, index):
                self.switched_to = index

        host = Host()
        nested = WorkflowHarness(parent=host)
        try:
            with patch("gui.workflow_tab.QTimer.singleShot", side_effect=lambda _ms, cb: cb()):
                nested.workflow._run_parse_speakers()
            tt = host.translation_tab
            self.assertEqual(tt.module_combo.currentText(), "RPG Maker MV/MZ")
            self.assertEqual(tt.mode_combo.currentText(), "Parse Speakers")
            checks = {
                tt.file_list.item(i).text(): tt.file_list.item(i).checkState()
                for i in range(tt.file_list.count())
            }
            self.assertEqual(checks["Actors.json"], Qt.Unchecked)
            self.assertEqual(checks["CommonEvents.json"], Qt.Checked)
            self.assertEqual(checks["Map001.json"], Qt.Checked)
            self.assertEqual(host.switched_to, host.PAGE_TRANSLATION)
            tt.start_translation.assert_called_once_with(skip_confirm=True)
        finally:
            nested.close()
            host.close()

    def test_export_active_and_all_route_filters_and_keep_safe_default(self):
        data = self.harness.root / "Game" / "data"
        data.mkdir(parents=True)
        self.workflow._data_path = str(data)
        for name in ("Actors.json", "Map001.json"):
            (self.harness.root / "files" / name).write_text("{}", encoding="utf-8")
            (self.harness.root / "translated" / name).write_text("{}", encoding="utf-8")

        with (
            patch("gui.workflow_tab._ExportWorker", FakeWorker),
            patch.object(QMessageBox, "question", return_value=QMessageBox.Yes) as question,
        ):
            self.workflow._export_active_files()
            active_worker = FakeWorker.instances[-1]
            self.assertEqual(active_worker.args, (str(data),))
            self.assertEqual(
                active_worker.kwargs["filter_names"],
                ["Actors.json", "Map001.json"],
            )
            self.assertEqual(question.call_args.args[-1], QMessageBox.No)

            self.workflow._export_to_game()
            all_worker = FakeWorker.instances[-1]
            self.assertEqual(all_worker.args, (str(data),))
            self.assertNotIn("filter_names", all_worker.kwargs)
            self.assertEqual(question.call_args.args[-1], QMessageBox.No)

    def test_rewrap_scan_and_apply_share_options_but_apply_requires_yes(self):
        data = self.harness.root / "Game" / "data"
        data.mkdir(parents=True)
        (data / "Actors.json").write_text("[]", encoding="utf-8")
        self.workflow._data_path = str(data)
        self.workflow.folder_edit.setText(str(data.parent))
        self.workflow._refresh_rewrap_files()

        with patch("gui.workflow_tab._RpgMakerRewrapWorker", FakeWorker):
            self.workflow._run_rewrap(False)
        scan = FakeWorker.instances[-1]
        self.assertEqual(scan.args[0], str(data))
        self.assertEqual(scan.args[2], ["Actors.json"])
        self.assertFalse(scan.kwargs["apply"])

        self.workflow._rewrap_worker = None
        FakeWorker.reset()
        with (
            patch("gui.workflow_tab._RpgMakerRewrapWorker", FakeWorker),
            patch.object(QMessageBox, "question", return_value=QMessageBox.No) as question,
        ):
            self.workflow._run_rewrap(True)
        self.assertFalse(FakeWorker.instances)
        self.assertEqual(question.call_args.args[-1], QMessageBox.No)

        with (
            patch("gui.workflow_tab._RpgMakerRewrapWorker", FakeWorker),
            patch.object(QMessageBox, "question", return_value=QMessageBox.Yes),
        ):
            self.workflow._run_rewrap(True)
        apply_worker = FakeWorker.instances[-1]
        self.assertEqual(apply_worker.args[0], scan.args[0])
        self.assertEqual(apply_worker.args[1], scan.args[1])
        self.assertEqual(apply_worker.args[2], scan.args[2])
        self.assertTrue(apply_worker.kwargs["apply"])

    def test_public_release_owns_worker_until_finish(self):
        game, _data = self.harness.make_mvmz_project("MZ")
        output = self.harness.root / "release.zip"
        self.workflow.folder_edit.setText(str(game))
        with (
            patch("gui.workflow_tab._ReleaseZipWorker", FakeWorker),
            patch(
                "gui.workflow_tab.QFileDialog.getSaveFileName",
                return_value=(str(output), "ZIP archives (*.zip)"),
            ),
        ):
            self.workflow._create_public_release()
        worker = FakeWorker.instances[-1]
        self.assertEqual(worker.args, (str(game), str(output)))
        self.assertTrue(worker.started)
        self.assertIs(self.workflow._worker, worker)
        self.assertFalse(self.workflow._release_zip_btn.isEnabled())
        worker.finished.emit()
        self.assertIsNone(self.workflow._worker)
        self.assertTrue(self.workflow._release_zip_btn.isEnabled())
        self.assertTrue(worker.deleted)

    def test_playtest_installers_route_config_and_uninstalls_are_default_safe(self):
        game, _data = self.harness.make_mvmz_project("MZ")
        self.workflow.folder_edit.setText(str(game))
        save_config = MagicMock()
        install_tli = MagicMock(return_value=(True, "TLI installed"))
        install_forge = MagicMock(return_value=(True, "Forge installed"))
        uninstall_tli = MagicMock(return_value=(True, "TLI removed"))
        uninstall_forge = MagicMock(return_value=(True, "Forge removed"))
        refresh = MagicMock()
        with (
            patch("util.playtest.config.save_config", save_config),
            patch("util.tl_inspector.installer.install", install_tli),
            patch("util.forge.installer.install", install_forge),
            patch("util.forge.installer.detect_engine", return_value="MZ"),
            patch("util.tl_inspector.installer.uninstall", uninstall_tli),
            patch("util.forge.installer.uninstall", uninstall_forge),
            patch.object(self.workflow, "_refresh_playtest_status", refresh),
        ):
            self.workflow._install_tl_inspector()
            self.workflow._install_forge()
            self.workflow._install_both_playtest()

            with patch.object(QMessageBox, "question", return_value=QMessageBox.No) as question:
                self.workflow._uninstall_tl_inspector()
                self.workflow._uninstall_forge()
                self.assertEqual(question.call_args.args[-1], QMessageBox.No)
            self.assertFalse(uninstall_tli.called)
            self.assertFalse(uninstall_forge.called)

            with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
                self.workflow._uninstall_tl_inspector()
                self.workflow._uninstall_forge()

        self.assertEqual(install_tli.call_count, 2)
        self.assertEqual(install_forge.call_count, 2)
        self.assertEqual(uninstall_tli.call_count, 1)
        self.assertEqual(uninstall_forge.call_count, 1)
        self.assertEqual(save_config.call_count, 3)
        self.assertGreaterEqual(refresh.call_count, 5)


if __name__ == "__main__":
    unittest.main()
