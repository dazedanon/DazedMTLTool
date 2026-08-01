"""Regression coverage for every general option on the Config tab."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from dotenv import dotenv_values
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QPalette
    from PyQt5.QtWidgets import QApplication, QMainWindow

    from gui.config_tab import ConfigTab, ModelFetchThread
    from util import api_keys

    _HAS_QT = True
except Exception:  # pragma: no cover - PyQt5 is optional for non-GUI installs
    _HAS_QT = False


@unittest.skipUnless(_HAS_QT, "PyQt5 not available")
class ConfigTabRegressionTests(unittest.TestCase):
    CONFIG_KEYS = {
        "api",
        "key",
        "API_KEY_OPTIONAL",
        "model",
        "language",
        "timeout",
        "fileThreads",
        "threads",
        "batchsize",
        "frequency_penalty",
        "width",
        "faceWidth",
        "listWidth",
        "noteWidth",
        "convertQuotes",
        "useSfxReference",
        "input_cost",
        "output_cost",
        "font_scale",
        "gameUpdateForge",
        "gameUpdateHost",
        "gameUpdateUsername",
        "gameUpdateBranch",
    }

    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.env_path = self.base / ".env"
        self.vault_path = self.base / "api_keys.json"
        self._old_cwd = Path.cwd()
        self._tabs: list[ConfigTab] = []
        self._windows: list[QMainWindow] = []

        self._environment = patch.dict(os.environ, {}, clear=False)
        self._environment.start()
        self._vault = patch.object(api_keys, "API_KEYS_PATH", self.vault_path)
        self._vault.start()
        self._fetch = patch.object(
            ConfigTab,
            "fetch_models",
            autospec=True,
            return_value=None,
        )
        self._fetch.start()

        os.chdir(self.base)
        self.env_path.write_text(
            "\n".join([
                "api=https://api.initial.test/v1",
                "key=sk-regression",
                "API_KEY_OPTIONAL=false",
                "model=initial-model",
                "language=Japanese",
                "timeout=123",
                "fileThreads=4",
                "threads=7",
                "batchsize=42",
                "frequency_penalty=0.75",
                "width=88",
                "faceWidth=77",
                "listWidth=99",
                "noteWidth=111",
                "convertQuotes=false",
                "useSfxReference=false",
                "input_cost=3.25",
                "output_cost=14.75",
                "font_scale=1.4",
                "gameUpdateForge=github",
                "gameUpdateHost=github.example.test",
                "gameUpdateUsername=translation-team",
                "gameUpdateBranch=develop",
                "",
            ]),
            encoding="utf-8",
        )
        # Keep this key's endpoint empty so the API URL field exercises the
        # global endpoint round-trip rather than per-key endpoint precedence.
        api_keys.upsert_key(
            "Regression",
            "sk-regression",
            endpoint="",
            path=self.vault_path,
        )

    def tearDown(self) -> None:
        for window in self._windows:
            window.takeCentralWidget()
            window.close()
        for tab in self._tabs:
            tab.close()
            tab.deleteLater()
        self._app.processEvents()
        os.chdir(self._old_cwd)
        self._fetch.stop()
        self._vault.stop()
        self._environment.stop()
        self._tmp.cleanup()

    def make_tab(self) -> ConfigTab:
        tab = ConfigTab()
        self._tabs.append(tab)
        return tab

    def assert_initial_values(self, tab: ConfigTab) -> None:
        self.assertEqual(tab.api_url_edit.text(), "https://api.initial.test/v1")
        self.assertEqual(tab.api_key_combo.currentText(), "Regression")
        self.assertEqual(tab.model_combo.currentText(), "initial-model")
        self.assertEqual(tab.language_combo.currentText(), "Japanese")
        self.assertEqual(tab.timeout_spin.value(), 123)
        self.assertEqual(tab.file_threads_spin.value(), 4)
        self.assertEqual(tab.threads_spin.value(), 7)
        self.assertEqual(tab.batch_size_spin.value(), 42)
        self.assertAlmostEqual(tab.frequency_penalty_spin.value(), 0.75)
        self.assertEqual(tab.width_spin.value(), 88)
        self.assertEqual(tab.face_width_spin.value(), 77)
        self.assertEqual(tab.list_width_spin.value(), 99)
        self.assertEqual(tab.note_width_spin.value(), 111)
        self.assertFalse(tab.convert_quotes_cb.isChecked())
        self.assertFalse(tab.use_sfx_reference_cb.isChecked())
        self.assertAlmostEqual(tab.input_cost_spin.value(), 3.25)
        self.assertAlmostEqual(tab.output_cost_spin.value(), 14.75)
        self.assertAlmostEqual(tab.font_scale_spin.value(), 1.4)
        self.assertEqual(tab.gu_forge_combo.currentData(), "github")
        self.assertEqual(tab.gu_host_edit.text(), "github.example.test")
        self.assertEqual(tab.gu_username_edit.text(), "translation-team")
        self.assertEqual(tab.gu_branch_edit.text(), "develop")

    def test_loads_every_option_and_left_aligns_form_labels(self) -> None:
        tab = self.make_tab()

        self.assert_initial_values(tab)
        self.assertEqual(set(tab.get_config()), self.CONFIG_KEYS - {"API_KEY_OPTIONAL"})
        self.assertTrue(tab.validate())
        self.assertTrue(tab._general_form_labels)
        for label in tab._general_form_labels:
            self.assertTrue(label.alignment() & Qt.AlignLeft, label.text())

    def test_text_fields_and_dropdowns_share_alignment_and_size(self) -> None:
        tab = self.make_tab()
        window = QMainWindow()
        self._windows.append(window)
        window.setCentralWidget(tab)
        window.resize(2048, 884)
        window.show()
        for _ in range(4):
            self._app.processEvents()

        def x_position(widget) -> int:
            return widget.mapTo(tab, widget.rect().topLeft()).x()

        def x_within_card(widget, title: str) -> int:
            card = tab._general_cards_by_title[title]
            return widget.mapTo(card, widget.rect().topLeft()).x()

        api_controls = (
            tab.api_url_edit,
            tab.api_key_combo,
            tab.model_combo,
        )
        self.assertEqual(len({x_position(widget) for widget in api_controls}), 1)
        self.assertEqual(
            {widget.width() for widget in api_controls},
            {api_controls[0].width()},
        )
        api_buttons = (
            tab.api_url_preset_btn,
            tab.api_key_new_btn,
            tab.api_key_delete_btn,
            tab.model_refresh_btn,
        )
        self.assertEqual(
            {button.width() for button in api_buttons},
            {api_buttons[0].width()},
        )

        aligned_groups = (
            (
                tab.language_combo,
                tab.timeout_spin,
                tab.width_spin,
                tab.face_width_spin,
                tab.list_width_spin,
                tab.note_width_spin,
            ),
            (
                tab.file_threads_spin,
                tab.threads_spin,
                tab.batch_size_spin,
                tab.frequency_penalty_spin,
                tab.input_cost_spin,
                tab.output_cost_spin,
            ),
            (
                tab.gu_forge_combo,
                tab.gu_host_edit,
                tab.gu_username_edit,
                tab.gu_branch_edit,
                tab.font_scale_spin,
            ),
        )
        for group in aligned_groups:
            self.assertEqual(len({x_position(widget) for widget in group}), 1)
            self.assertEqual(len({widget.width() for widget in group}), 1)
            self.assertEqual(len({widget.height() for widget in group}), 1)

        standard_widths = [
            widget.width()
            for group in aligned_groups
            for widget in group
        ]
        self.assertLessEqual(max(standard_widths) - min(standard_widths), 1)

        representative_controls = (
            (tab.api_url_edit, "🔑 API Configuration"),
            (tab.font_scale_spin, "🖥️ Interface"),
            (tab.language_combo, "🌐 Translation & Text"),
            (tab.file_threads_spin, "⚡ Performance & Pricing"),
            (tab.gu_forge_combo, "📦 Game Update Defaults"),
        )
        self.assertEqual(
            len({
                x_within_card(widget, title)
                for widget, title in representative_controls
            }),
            1,
        )

    def test_dropdown_popup_is_opaque(self) -> None:
        tab = self.make_tab()
        window = QMainWindow()
        self._windows.append(window)
        window.setCentralWidget(tab)
        window.resize(1280, 760)
        window.show()
        for _ in range(3):
            self._app.processEvents()

        tab.model_combo.showPopup()
        for _ in range(3):
            self._app.processEvents()

        view = tab.model_combo.view()
        popup = view.window()
        self.assertTrue(view.autoFillBackground())
        self.assertTrue(view.viewport().autoFillBackground())
        self.assertEqual(view.palette().color(QPalette.Base).name(), "#353539")
        self.assertEqual(
            view.viewport().palette().color(QPalette.Base).name(),
            "#353539",
        )
        self.assertEqual(popup.windowOpacity(), 1.0)
        self.assertFalse(popup.testAttribute(Qt.WA_TranslucentBackground))
        tab.model_combo.hidePopup()

    def test_long_model_popup_is_bounded_and_scrollable(self) -> None:
        tab = self.make_tab()
        window = QMainWindow()
        self._windows.append(window)
        window.setCentralWidget(tab)
        window.resize(1280, 760)
        window.show()
        tab.model_combo.clear()
        tab.model_combo.addItems([f"provider-model-{index:03d}" for index in range(100)])
        for _ in range(3):
            self._app.processEvents()

        tab.model_combo.showPopup()
        for _ in range(3):
            self._app.processEvents()

        view = tab.model_combo.view()
        popup = view.window()
        screen = self._app.screenAt(tab.model_combo.mapToGlobal(tab.model_combo.rect().center()))
        self.assertLessEqual(view.height(), tab.model_combo._popup_height_limit())
        self.assertLessEqual(popup.height(), view.height() + 8)
        self.assertGreater(view.verticalScrollBar().maximum(), 0)
        self.assertLessEqual(popup.frameGeometry().bottom(), screen.availableGeometry().bottom())
        tab.model_combo.hidePopup()

    def test_selecting_saved_provider_refreshes_its_models(self) -> None:
        api_keys.upsert_key(
            "Gemini",
            "gemini-secret",
            endpoint="https://generativelanguage.googleapis.com/v1beta/openai/",
            make_active=False,
            path=self.vault_path,
        )
        tab = self.make_tab()
        ConfigTab.fetch_models.reset_mock()

        tab.api_key_combo.setCurrentText("Gemini")

        self.assertEqual(
            tab.api_url_edit.text(),
            "https://generativelanguage.googleapis.com/v1beta/openai/",
        )
        ConfigTab.fetch_models.assert_called_once_with(
            tab,
            silent=True,
            select_available=True,
        )

    def test_provider_refresh_selects_a_valid_model(self) -> None:
        tab = self.make_tab()
        tab.model_combo.setCurrentText("model-from-old-provider")

        with patch.object(tab, "auto_save") as auto_save:
            tab._on_models_fetched(
                ["gemini-3.1-pro", "gemini-3.6-flash"],
                select_available=True,
            )

        self.assertEqual(tab.model_combo.currentText(), "gemini-3.1-pro")
        auto_save.assert_called_once_with()

    def test_explicit_official_openai_url_filters_non_chat_models(self) -> None:
        worker = ModelFetchThread(
            "openai-secret", "https://api.openai.com/v1"
        )
        models = SimpleNamespace(list=lambda: [
            SimpleNamespace(id="text-embedding-3-large"),
            SimpleNamespace(id="gpt-5.6-terra"),
            SimpleNamespace(id="o4-mini"),
            SimpleNamespace(id="dall-e-3"),
        ])
        with patch(
            "openai.OpenAI",
            return_value=SimpleNamespace(models=models),
        ):
            fetched = worker._fetch_openai()

        self.assertEqual(fetched, ["gpt-5.6-terra", "o4-mini"])

    def test_custom_openai_compatible_url_keeps_provider_models(self) -> None:
        worker = ModelFetchThread(
            "custom-secret", "https://provider.example/v1"
        )
        models = SimpleNamespace(list=lambda: [
            SimpleNamespace(id="provider-chat"),
            SimpleNamespace(id="provider-reasoner"),
        ])
        with patch(
            "openai.OpenAI",
            return_value=SimpleNamespace(models=models),
        ):
            fetched = worker._fetch_openai()

        self.assertEqual(fetched, ["provider-chat", "provider-reasoner"])

    def test_manual_model_refresh_preserves_custom_model(self) -> None:
        tab = self.make_tab()
        tab.model_combo.setCurrentText("custom-provider-model")

        tab._on_models_fetched(["listed-model"], select_available=False)

        self.assertEqual(tab.model_combo.currentText(), "custom-provider-model")

    def test_presets_menu_is_opaque(self) -> None:
        tab = self.make_tab()
        window = QMainWindow()
        self._windows.append(window)
        window.setCentralWidget(tab)
        window.resize(1280, 760)
        window.show()
        for _ in range(3):
            self._app.processEvents()

        menu = tab.api_url_preset_btn.menu()
        menu.popup(
            tab.api_url_preset_btn.mapToGlobal(
                tab.api_url_preset_btn.rect().bottomLeft()
            )
        )
        for _ in range(3):
            self._app.processEvents()

        self.assertTrue(menu.autoFillBackground())
        self.assertEqual(menu.palette().color(QPalette.Window).name(), "#353539")
        self.assertEqual(menu.palette().color(QPalette.Base).name(), "#353539")
        self.assertEqual(menu.windowOpacity(), 1.0)
        self.assertFalse(menu.testAttribute(Qt.WA_TranslucentBackground))
        self.assertTrue(menu.testAttribute(Qt.WA_OpaquePaintEvent))
        menu.hide()

    def test_save_and_reload_round_trip_for_every_option(self) -> None:
        tab = self.make_tab()
        tab.disconnect_auto_save()

        tab.api_url_edit.setText("https://api.saved.test/v2")
        tab.model_combo.setCurrentText("saved-model")
        tab.language_combo.setCurrentText("Korean")
        tab.timeout_spin.setValue(234)
        tab.file_threads_spin.setValue(6)
        tab.threads_spin.setValue(9)
        tab.batch_size_spin.setValue(64)
        tab.frequency_penalty_spin.setValue(1.25)
        tab.width_spin.setValue(72)
        tab.face_width_spin.setValue(62)
        tab.list_width_spin.setValue(84)
        tab.note_width_spin.setValue(96)
        tab.convert_quotes_cb.setChecked(True)
        tab.use_sfx_reference_cb.setChecked(True)
        tab.input_cost_spin.setValue(4.5)
        tab.output_cost_spin.setValue(18.25)
        tab.font_scale_spin.setValue(1.8)
        tab.gu_forge_combo.setCurrentIndex(
            tab.gu_forge_combo.findData("forgejo")
        )
        tab.gu_host_edit.setText("forge.example.test")
        tab.gu_username_edit.setText("saved-team")
        tab.gu_branch_edit.setText("release")

        changes: list[bool] = []
        tab.config_changed.connect(lambda: changes.append(True))
        tab.save_to_env(show_message=False)
        self.assertEqual(len(changes), 1)

        saved = dotenv_values(self.env_path)
        expected = {
            "api": "https://api.saved.test/v2",
            "key": "sk-regression",
            "API_KEY_OPTIONAL": "false",
            "model": "saved-model",
            "language": "Korean",
            "timeout": "234",
            "fileThreads": "6",
            "threads": "9",
            "batchsize": "64",
            "frequency_penalty": "1.25",
            "width": "72",
            "faceWidth": "62",
            "listWidth": "84",
            "noteWidth": "96",
            "convertQuotes": "true",
            "useSfxReference": "true",
            "input_cost": "4.5",
            "output_cost": "18.25",
            "font_scale": "1.8",
            "gameUpdateForge": "forgejo",
            "gameUpdateHost": "forge.example.test",
            "gameUpdateUsername": "saved-team",
            "gameUpdateBranch": "release",
        }
        self.assertEqual({key: saved.get(key) for key in expected}, expected)

        reloaded = self.make_tab()
        self.assertEqual(reloaded.api_url_edit.text(), expected["api"])
        self.assertEqual(reloaded.api_key_combo.currentText(), "Regression")
        self.assertEqual(reloaded.model_combo.currentText(), expected["model"])
        self.assertEqual(reloaded.language_combo.currentText(), expected["language"])
        self.assertEqual(reloaded.timeout_spin.value(), 234)
        self.assertEqual(reloaded.file_threads_spin.value(), 6)
        self.assertEqual(reloaded.threads_spin.value(), 9)
        self.assertEqual(reloaded.batch_size_spin.value(), 64)
        self.assertAlmostEqual(reloaded.frequency_penalty_spin.value(), 1.25)
        self.assertEqual(reloaded.width_spin.value(), 72)
        self.assertEqual(reloaded.face_width_spin.value(), 62)
        self.assertEqual(reloaded.list_width_spin.value(), 84)
        self.assertEqual(reloaded.note_width_spin.value(), 96)
        self.assertTrue(reloaded.convert_quotes_cb.isChecked())
        self.assertTrue(reloaded.use_sfx_reference_cb.isChecked())
        self.assertAlmostEqual(reloaded.input_cost_spin.value(), 4.5)
        self.assertAlmostEqual(reloaded.output_cost_spin.value(), 18.25)
        self.assertAlmostEqual(reloaded.font_scale_spin.value(), 1.8)
        self.assertEqual(reloaded.gu_forge_combo.currentData(), "forgejo")
        self.assertEqual(reloaded.gu_host_edit.text(), "forge.example.test")
        self.assertEqual(reloaded.gu_username_edit.text(), "saved-team")
        self.assertEqual(reloaded.gu_branch_edit.text(), "release")

    def test_reset_restores_and_persists_every_default(self) -> None:
        tab = self.make_tab()
        with (
            patch.object(tab.mvmz_tab, "reset_to_defaults") as reset_mvmz,
            patch.object(tab.wolf_tab, "reset_to_defaults") as reset_wolf,
            patch.object(tab.csv_tab, "reset_to_defaults") as reset_csv,
            patch.object(tab.srpg_tab, "reset_to_defaults") as reset_srpg,
        ):
            tab.reset_to_defaults_with_save()

        reset_mvmz.assert_called_once_with()
        reset_wolf.assert_called_once_with()
        reset_csv.assert_called_once_with()
        reset_srpg.assert_called_once_with()

        self.assertEqual(tab.api_url_edit.text(), "")
        self.assertEqual(tab.model_combo.currentText(), "gpt-4.1")
        self.assertEqual(tab.language_combo.currentText(), "English")
        self.assertEqual(tab.timeout_spin.value(), 90)
        self.assertEqual(tab.file_threads_spin.value(), 1)
        self.assertEqual(tab.threads_spin.value(), 1)
        self.assertEqual(tab.batch_size_spin.value(), 30)
        self.assertAlmostEqual(tab.frequency_penalty_spin.value(), 0.05)
        self.assertEqual(tab.width_spin.value(), 60)
        self.assertEqual(tab.face_width_spin.value(), 50)
        self.assertEqual(tab.list_width_spin.value(), 100)
        self.assertEqual(tab.note_width_spin.value(), 75)
        self.assertTrue(tab.convert_quotes_cb.isChecked())
        self.assertTrue(tab.use_sfx_reference_cb.isChecked())
        self.assertAlmostEqual(tab.input_cost_spin.value(), 2.0)
        self.assertAlmostEqual(tab.output_cost_spin.value(), 8.0)
        self.assertAlmostEqual(tab.font_scale_spin.value(), 1.0)
        self.assertEqual(tab.gu_forge_combo.currentData(), "gitlab")
        self.assertEqual(tab.gu_host_edit.text(), "gitgud.io")
        self.assertEqual(tab.gu_username_edit.text(), "")
        self.assertEqual(tab.gu_branch_edit.text(), "main")

        saved = dotenv_values(self.env_path)
        expected_defaults = {
            "api": "",
            "model": "gpt-4.1",
            "language": "English",
            "timeout": "90",
            "fileThreads": "1",
            "threads": "1",
            "batchsize": "30",
            "frequency_penalty": "0.05",
            "width": "60",
            "faceWidth": "50",
            "listWidth": "100",
            "noteWidth": "75",
            "convertQuotes": "true",
            "useSfxReference": "true",
            "input_cost": "2.0",
            "output_cost": "8.0",
            "font_scale": "1.0",
            "gameUpdateForge": "gitlab",
            "gameUpdateHost": "gitgud.io",
            "gameUpdateUsername": "",
            "gameUpdateBranch": "main",
        }
        self.assertEqual(
            {key: saved.get(key) for key in expected_defaults},
            expected_defaults,
        )


if __name__ == "__main__":
    unittest.main()
